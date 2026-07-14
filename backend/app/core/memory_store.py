"""
#3 跨会话记忆系统

基于文本相似度的轻量记忆层，存储跨会话的生产经验：
  - 错误案例（某阶段某 Agent 的常见问题与修复方案）
  - 最佳实践（验收通过的高质量产出特征）
  - 规则优化（连续失败触发的规则升级记录）

检索策略：使用 TF-IDF + 余弦相似度（纯 Python 实现，无需额外依赖），
避免引入 numpy/sklearn/faiss 等重量级依赖。
对于小规模记忆库（<1000 条），性能完全够用。

存储格式：JSON 文件持久化到 data/memory_store/
"""
import os
import json
import time
import math
import re
import logging
from typing import Any, Dict, List, Optional
from collections import Counter

from app.core.config import settings

logger = logging.getLogger(__name__)

_STORE_DIR = settings.MEMORY_STORE_PATH
_ENTRIES_FILE = os.path.join(_STORE_DIR, "entries.json")
_INDEX_FILE = os.path.join(_STORE_DIR, "index.json")

# 内存缓存
_entries: List[Dict[str, Any]] = []
_tfidf_index: Dict[str, Dict[str, float]] = {}  # entry_id -> {term: tfidf}
_idf_cache: Dict[str, float] = {}
_loaded = False


def _ensure_loaded() -> None:
    """懒加载记忆库。"""
    global _loaded, _entries, _tfidf_index, _idf_cache
    if _loaded:
        return

    try:
        os.makedirs(_STORE_DIR, exist_ok=True)
        if os.path.isfile(_ENTRIES_FILE):
            with open(_ENTRIES_FILE, "r", encoding="utf-8") as f:
                _entries = json.load(f)
        if os.path.isfile(_INDEX_FILE):
            with open(_INDEX_FILE, "r", encoding="utf-8") as f:
                idx_data = json.load(f)
                _tfidf_index = idx_data.get("tfidf", {})
                _idf_cache = idx_data.get("idf", {})
    except Exception as exc:
        logger.warning("[MemoryStore] 加载记忆库失败: %s", exc)
        _entries = []

    _loaded = True
    logger.info("[MemoryStore] 记忆库已加载: %d 条记忆", len(_entries))


def _tokenize(text: str) -> List[str]:
    """简单分词：中文按字，英文按词。"""
    if not text:
        return []
    # 英文单词
    tokens = re.findall(r"[a-zA-Z]{2,}", text.lower())
    # 中文字符（按 2-gram）
    cn_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(cn_chars) - 1):
        tokens.append(cn_chars[i] + cn_chars[i + 1])
    return tokens


def _compute_tfidf(text: str, idf: Dict[str, float]) -> Dict[str, float]:
    """计算文本的 TF-IDF 向量。"""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    tf = Counter(tokens)
    total = len(tokens)
    return {term: (count / total) * idf.get(term, 1.0) for term, count in tf.items()}


def _cosine_similarity(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    """计算两个 TF-IDF 向量的余弦相似度。"""
    if not v1 or not v2:
        return 0.0
    # 取交集
    common = set(v1.keys()) & set(v2.keys())
    if not common:
        return 0.0
    dot = sum(v1[t] * v2[t] for t in common)
    norm1 = math.sqrt(sum(v * v for v in v1.values()))
    norm2 = math.sqrt(sum(v * v for v in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def _rebuild_index() -> None:
    """重建 TF-IDF 索引。"""
    global _tfidf_index, _idf_cache

    # 计算 IDF
    doc_count = len(_entries)
    if doc_count == 0:
        _tfidf_index = {}
        _idf_cache = {}
        return

    df: Dict[str, int] = {}
    for entry in _entries:
        tokens = set(_tokenize(entry.get("content", "")))
        for t in tokens:
            df[t] = df.get(t, 0) + 1

    _idf_cache = {
        t: math.log((doc_count + 1) / (d + 1)) + 1
        for t, d in df.items()
    }

    # 计算每条记忆的 TF-IDF
    _tfidf_index = {}
    for entry in _entries:
        eid = entry.get("id", "")
        _tfidf_index[eid] = _compute_tfidf(entry.get("content", ""), _idf_cache)


def _save() -> None:
    """持久化记忆库。"""
    try:
        os.makedirs(_STORE_DIR, exist_ok=True)
        with open(_ENTRIES_FILE, "w", encoding="utf-8") as f:
            json.dump(_entries, f, ensure_ascii=False, indent=2)
        with open(_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump({"tfidf": _tfidf_index, "idf": _idf_cache}, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("[MemoryStore] 保存记忆库失败: %s", exc)


def add_memory(
    memory_type: str,
    stage: str,
    agent: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """添加一条记忆。

    Args:
        memory_type: "error_case" | "best_practice" | "rule_update"
        stage: 所属阶段 (planning/asset/production)
        agent: 相关 Agent 名称
        content: 记忆文本内容
        metadata: 附加元数据

    Returns:
        记忆 ID
    """
    _ensure_loaded()
    import uuid
    entry_id = str(uuid.uuid4())[:8]
    entry = {
        "id": entry_id,
        "type": memory_type,
        "stage": stage,
        "agent": agent,
        "content": content,
        "metadata": metadata or {},
        "ts": time.time(),
    }
    _entries.append(entry)
    _rebuild_index()
    _save()
    logger.info("[MemoryStore] 添加记忆: type=%s stage=%s agent=%s id=%s", memory_type, stage, agent, entry_id)
    return entry_id


def retrieve_memories(
    query: str,
    top_k: Optional[int] = None,
    memory_type: Optional[str] = None,
    stage: Optional[str] = None,
    agent: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """检索相关记忆。

    Args:
        query: 查询文本
        top_k: 返回前 K 条（默认从 settings 读取）
        memory_type: 筛选记忆类型
        stage: 筛选阶段
        agent: 筛选 Agent

    Returns:
        按相似度降序排列的记忆列表
    """
    _ensure_loaded()
    k = top_k or settings.MEMORY_RETRIEVE_TOP_K

    if not _entries:
        return []

    # 筛选
    candidates = _entries
    if memory_type:
        candidates = [e for e in candidates if e.get("type") == memory_type]
    if stage:
        candidates = [e for e in candidates if e.get("stage") == stage]
    if agent:
        candidates = [e for e in candidates if e.get("agent") == agent]

    if not candidates:
        return []

    # 计算相似度
    query_vec = _compute_tfidf(query, _idf_cache)
    scored = []
    for entry in candidates:
        eid = entry.get("id", "")
        entry_vec = _tfidf_index.get(eid, {})
        score = _cosine_similarity(query_vec, entry_vec)
        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"score": round(s, 4), **e} for s, e in scored[:k] if s > 0]


def get_error_cases(stage: Optional[str] = None, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取错误案例。"""
    _ensure_loaded()
    result = [e for e in _entries if e.get("type") == "error_case"]
    if stage:
        result = [e for e in result if e.get("stage") == stage]
    if agent:
        result = [e for e in result if e.get("agent") == agent]
    return result


def get_best_practices(stage: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取最佳实践。"""
    _ensure_loaded()
    result = [e for e in _entries if e.get("type") == "best_practice"]
    if stage:
        result = [e for e in result if e.get("stage") == stage]
    return result


def get_stats() -> Dict[str, int]:
    """获取记忆库统计信息。"""
    _ensure_loaded()
    stats: Dict[str, int] = {"total": len(_entries)}
    for e in _entries:
        t = e.get("type", "unknown")
        stats[t] = stats.get(t, 0) + 1
    return stats


def clear_all() -> None:
    """清空记忆库。"""
    global _entries, _tfidf_index, _idf_cache
    _entries = []
    _tfidf_index = {}
    _idf_cache = {}
    _save()
    logger.info("[MemoryStore] 记忆库已清空")
