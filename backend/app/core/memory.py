import time
from typing import Dict, Any, Optional, List
from collections import OrderedDict

from app.core.config import settings


class MemoryCache:
    """进程内 LRU + TTL 缓存。

    性能优化：
    - set 时做过期清理 + 容量裁剪（写入路径频率远低于 get）。
    - get 时仅惰性清理被访问 key 的过期项，不做全量扫描，避免高频 get 的 O(n) 开销。
    - 定期（每 _evict_interval 秒）在 set 时触发一次全量清理，兼顾长期未访问的过期 key。

    多 worker 注意：本缓存为进程内内存态，Uvicorn 多 worker 部署时各 worker 各持一份，
    节点上下文不跨进程共享。生产部署如需共享，请使用单 worker + asyncio 并发，
    或将 node context / chat history 迁移到 Redis 等共享存储（session_store 已走 SQLite 共享）。
    """

    def __init__(self, max_size: int = None, ttl: int = None):
        self._cache: OrderedDict = OrderedDict()
        self._ttl = ttl if ttl is not None else settings.MEMORY_CACHE_TTL
        self._max_size = max_size if max_size is not None else settings.MEMORY_CACHE_MAX_SIZE
        self._last_full_evict_ts: float = time.time()
        # 全量清理间隔：取 ttl 的 1/4，至少 60s，避免写入路径频繁扫描
        self._evict_interval = max(60, self._ttl // 4)

    def _full_evict_expired(self):
        """全量扫描并清理所有过期 key + 超容量 LRU 裁剪。仅在 set 路径定期触发。"""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if now - v["_ts"] > v["_ttl"]]
        for k in expired_keys:
            del self._cache[k]
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        self._last_full_evict_ts = now

    def _lazy_evict_key(self, key: str) -> bool:
        """惰性清理单个 key：若已过期则删除并返回 True（表示未命中）。"""
        item = self._cache.get(key)
        if not item:
            return True
        if time.time() - item["_ts"] > item["_ttl"]:
            del self._cache[key]
            return True
        return False

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        # 若 key 已存在，先删除再写入，保证 OrderedDict 末尾为最新（LRU 语义）
        if key in self._cache:
            del self._cache[key]
        self._cache[key] = {"data": value, "_ts": time.time(), "_ttl": ttl or self._ttl}
        # 定期全量清理 + 容量裁剪，控制在 _evict_interval 一次
        if time.time() - self._last_full_evict_ts > self._evict_interval:
            self._full_evict_expired()
        else:
            # 廉价的容量裁剪，不扫过期
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def get(self, key: str) -> Optional[Any]:
        # 惰性清理：只检查被访问 key 是否过期，不做全量扫描
        if self._lazy_evict_key(key):
            return None
        # LRU：命中时移到末尾
        self._cache.move_to_end(key)
        return self._cache[key]["data"]

    def delete(self, key: str):
        self._cache.pop(key, None)

    def get_node_context(self, node_id: str) -> Dict[str, Any]:
        return self.get(f"ctx:{node_id}") or {}

    def set_node_context(self, node_id: str, context: Dict[str, Any]):
        self.set(f"ctx:{node_id}", context)

    def get_chat_history(self, node_id: str) -> List[Dict[str, str]]:
        return self.get(f"chat:{node_id}") or []

    def append_chat(self, node_id: str, role: str, content: str):
        history = self.get_chat_history(node_id)
        history.append({"role": role, "content": content, "ts": time.time()})
        self.set(f"chat:{node_id}", history)
        return history

    def clear_node(self, node_id: str):
        self.delete(f"ctx:{node_id}")
        self.delete(f"chat:{node_id}")


memory_cache = MemoryCache()
