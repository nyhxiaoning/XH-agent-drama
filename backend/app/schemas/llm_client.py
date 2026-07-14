"""
统一 LLM JSON 客户端：缓存 + 指数退避重试 + Token 计量。

H3 实现：
1. 基于 (system_prompt + user_content + model) 的 hash 内存缓存（LRU，可替换为 Redis）。
2. 对 LLM 调用做指数退避重试，区分可重试错误（429/5xx/超时）与不可重试错误（4xx 内容错误除外 429）。
3. 记录 prompt_tokens + completion_tokens 到调用方传入的 token_tracker。
4. 提供预算检查 helper，超阈值时打日志/返回警告。
"""
import hashlib
import json
import logging
import asyncio
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Callable

from app.services.ai_service import AIService

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_CACHE_SIZE = 200
DEFAULT_TOKEN_BUDGET = 50_000

# 进程内 LRU 缓存；未来可替换为 Redis / memcached。
_llm_cache: OrderedDict[str, Any] = OrderedDict()


def _extract_json(text: str) -> Optional[str]:
    """从 LLM 返回文本中提取 JSON 代码块或 JSON 对象。"""
    if not text:
        return None
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _sanitize_control_chars(text: str) -> str:
    """移除 JSON 字符串中不允许的控制字符（保留 \t, \n, \r）。"""
    if not text:
        return text
    # JSON 字符串中允许的控制字符：\u0009, \u000A, \u000D
    # 其余 0x00-0x1F 都需要转义或移除
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 0x20)


def _make_cache_key(system_prompt: str, user_content: str, model: Optional[str]) -> str:
    key = f"{model or 'default'}::{system_prompt}::{user_content}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _set_cache(cache_key: str, value: Any) -> None:
    _llm_cache[cache_key] = value
    _llm_cache.move_to_end(cache_key)
    while len(_llm_cache) > DEFAULT_CACHE_SIZE:
        _llm_cache.popitem(last=False)


def _is_retryable_error(exc: Exception) -> bool:
    """判断异常是否值得重试。"""
    msg = str(exc).lower()
    # 显式可重试信号
    retryable_signals = [
        "429", "rate limit", "too many requests",
        "503", "502", "500", "504", "gateway",
        "timeout", "timed out", "connection", "network",
    ]
    if any(s in msg for s in retryable_signals):
        return True
    # aiohttp / httpx 连接类异常
    if "connection" in msg or "network" in msg:
        return True
    return False


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（用于 LLM 未返回 usage 时兜底）。"""
    if not text:
        return 0
    # 中文字符按 1 token，英文按词按 0.75 token 粗略估计
    import re
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[a-zA-Z0-9]+", text))
    return int(cn_chars + words * 0.75 + len(text) * 0.1)


async def llm_json(
    system_prompt: str,
    user_content: str,
    model: Optional[str] = None,
    fallback: Optional[Dict[str, Any]] = None,
    enable_cache: bool = True,
    max_retries: int = DEFAULT_MAX_RETRIES,
    token_tracker: Optional[Dict[str, Any]] = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    cache_key_suffix: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.3,
) -> Dict[str, Any]:
    """
    调用 LLM 并解析 JSON；内置缓存、重试、token 计量。

    token_tracker: 调用方传入的可变 dict，会累计 token_used。
    """
    cache_key = _make_cache_key(system_prompt, user_content, model)
    if cache_key_suffix:
        cache_key = f"{cache_key}::{cache_key_suffix}"

    if enable_cache:
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            logger.info("[LLMClient] cache hit %s...", cache_key[:8])
            return cached

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            response = await AIService.chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            content = response["choices"][0]["message"]["content"]
            json_str = _sanitize_control_chars(_extract_json(content) or content.strip())
            if not json_str:
                raise ValueError("LLM 返回为空")
            parsed = json.loads(json_str)
            if not isinstance(parsed, dict):
                raise ValueError("LLM 返回不是 JSON 对象")

            # Token 计量
            usage = response.get("usage", {}) or {}
            prompt_tokens = usage.get("prompt_tokens") or _estimate_tokens(system_prompt + user_content)
            completion_tokens = usage.get("completion_tokens") or _estimate_tokens(content)
            total_tokens = prompt_tokens + completion_tokens
            if token_tracker is not None:
                token_tracker["token_used"] = token_tracker.get("token_used", 0) + total_tokens
                token_tracker["token_prompt"] = token_tracker.get("token_prompt", 0) + prompt_tokens
                token_tracker["token_completion"] = token_tracker.get("token_completion", 0) + completion_tokens

            # 预算阈值警告（不阻断，只记录）
            used = token_tracker.get("token_used", total_tokens) if token_tracker else total_tokens
            if used > token_budget:
                logger.warning(
                    "[LLMClient] 会话 token 已超预算阈值: used=%d budget=%d",
                    used, token_budget,
                )

            if enable_cache:
                _set_cache(cache_key, parsed)
            return parsed

        except Exception as exc:
            last_exc = exc
            retryable = _is_retryable_error(exc)
            if attempt < max_retries - 1 and retryable:
                delay = min(DEFAULT_BASE_DELAY * (2 ** attempt), DEFAULT_MAX_DELAY)
                logger.warning(
                    "[LLMClient] 调用失败（attempt=%d/%d），%ss 后重试: %s",
                    attempt + 1, max_retries, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                if not retryable and attempt < max_retries - 1:
                    logger.warning("[LLMClient] 非可重试错误，停止重试: %s", exc)
                break

    logger.warning("[LLMClient] LLM 调用最终失败: %s", last_exc)
    if fallback is not None:
        # 缓存 fallback 吗？通常不缓存，因为 fallback 是错误产物
        return fallback
    raise last_exc


def get_cache_stats() -> Dict[str, int]:
    return {"size": len(_llm_cache), "max_size": DEFAULT_CACHE_SIZE}


def check_token_budget(token_tracker: Optional[Dict[str, Any]], budget: int = DEFAULT_TOKEN_BUDGET) -> Optional[str]:
    """返回预算警告消息，未超则返回 None。"""
    if not token_tracker:
        return None
    used = token_tracker.get("token_used", 0)
    if used > budget:
        return f"当前会话已消耗约 {used} tokens，超过预算阈值 {budget}，建议检查长剧本或合并请求。"
    if used > budget * 0.8:
        return f"当前会话已消耗约 {used} tokens，接近预算阈值 {budget}。"
    return None
