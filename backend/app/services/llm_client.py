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
import traceback
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Callable

import httpx

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


# JSON 合法转义字符（反斜杠后可跟的字符）
# " \ / b f n r t u
_VALID_JSON_ESCAPES = frozenset('"\\/bfnrtu')


def _fix_invalid_escapes(text: str) -> str:
    """修复 JSON 文本中的非法转义序列。

    LLM 输出的 JSON 中常出现非法转义，如正则风格 \d, \w, \s 或
    Markdown 风格 \!, \#, \[ 等，导致 json.loads() 报
    "Invalid \\escape" 错误。

    策略：逐字符扫描，仅在 JSON 字符串值内部（双引号之间）处理。
    遇到反斜杠时，检查后续字符：
    - 合法转义（" \ / b f n r t u）：原样保留
    - 非法转义：将反斜杠加倍为 \\，使原字符变为字面量
    """
    if not text:
        return text

    result: list[str] = []
    in_string = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        # 在字符串内部
        if ch == "\\":
            if i + 1 < n:
                next_ch = text[i + 1]
                if next_ch in _VALID_JSON_ESCAPES:
                    # 合法转义，原样保留
                    result.append(ch)
                    result.append(next_ch)
                    i += 2
                else:
                    # 非法转义：将反斜杠转义为 \\，保留后续字符
                    result.append("\\\\")
                    result.append(next_ch)
                    i += 2
            else:
                # 反斜杠在末尾，转义为 \\
                result.append("\\\\")
                i += 1
        elif ch == '"':
            result.append(ch)
            in_string = False
            i += 1
        else:
            result.append(ch)
            i += 1

    return "".join(result)


def _repair_truncated_json(text: str) -> Optional[str]:
    """尝试修复被截断的 JSON 文本。

    当 LLM 输出因 max_tokens 不足而被截断时，JSON 会断在字符串中间，
    导致 json.loads() 报 "Unterminated string" 错误。

    策略：
    1. 逐字符扫描，追踪字符串状态和括号/花括号嵌套栈
    2. 记录最后一个"安全逗号"位置（在字符串外部、结构内的逗号）
    3. 如果结尾在字符串内部：截断到安全逗号，闭合所有未关闭结构
    4. 如果结尾在字符串外部：移除尾部逗号，闭合所有未关闭结构
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 先修复非法转义，再尝试直接解析
    text = _fix_invalid_escapes(text)

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # 逐字符扫描，追踪状态
    in_string = False
    escape = False
    stack: list[str] = []           # 未关闭的 { 和 [
    last_safe_comma = -1            # 最后一个字符串外部的逗号位置

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
        elif ch == ",":
            last_safe_comma = i

    # 确定截断点
    if in_string:
        # 在字符串中间被截断 → 截断到最后一个安全逗号
        if last_safe_comma > 0:
            fragment = text[:last_safe_comma].rstrip()
        else:
            # 没有安全逗号，无法修复
            return None
    else:
        # 不在字符串中，直接使用全文（移除尾部逗号）
        fragment = text
    if fragment.endswith(","):
        fragment = fragment[:-1]

    # 重新扫描 fragment 计算未关闭结构
    stack2: list[str] = []
    in_str2 = False
    esc2 = False
    for ch in fragment:
        if esc2:
            esc2 = False
            continue
        if ch == "\\":
            esc2 = True
            continue
        if ch == '"':
            in_str2 = not in_str2
            continue
        if in_str2:
            continue
        if ch in "{[":
            stack2.append(ch)
        elif ch == "}":
            if stack2 and stack2[-1] == "{":
                stack2.pop()
        elif ch == "]":
            if stack2 and stack2[-1] == "[":
                stack2.pop()

    # 闭合所有未关闭结构（从内到外）
    closing = ""
    for opener in reversed(stack2):
        closing += "}" if opener == "{" else "]"

    if not closing:
        return None

    result = fragment + closing
    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        return None


def _make_cache_key(system_prompt: str, user_content: str, model: Optional[str]) -> str:
    key = f"{model or 'default'}::{system_prompt}::{user_content}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _set_cache(cache_key: str, value: Any) -> None:
    _llm_cache[cache_key] = value
    _llm_cache.move_to_end(cache_key)
    while len(_llm_cache) > DEFAULT_CACHE_SIZE:
        _llm_cache.popitem(last=False)


# 可重试的 httpx 异常类型（按类型判断，避免依赖消息内容）
_RETRYABLE_EXC_TYPES = (
    httpx.TimeoutException,   # ReadTimeout, ConnectTimeout, WriteTimeout, PoolTimeout
    httpx.ConnectError,       # DNS 解析失败、连接被拒绝
    httpx.NetworkError,       # ReadError, WriteError 等
    httpx.ProtocolError,      # 协议级错误
    httpx.ProxyError,         # 代理错误
    httpx.UnsupportedProtocol,
    ConnectionError,          # Python 内置连接错误
    TimeoutError,             # Python 内置超时
    OSError,                  # 网络层 OS 错误（含 ConnectionRefusedError 等）
)


def _is_retryable_error(exc: Exception) -> bool:
    """判断异常是否值得重试。

    双层判断：
    1. 按异常类型：httpx 网络类异常、Python 连接/超时异常直接可重试
    2. 按消息关键词：RuntimeError 包装的消息中包含可重试信号也可重试
    """
    # 层 1：按异常类型判断（最可靠）
    if isinstance(exc, _RETRYABLE_EXC_TYPES):
        return True

    # 检查异常链（__cause__）中的原始异常类型
    cause = exc.__cause__
    if cause and isinstance(cause, _RETRYABLE_EXC_TYPES):
        return True

    # 层 2：按消息关键词判断（兜底）
    msg = str(exc).lower()
    exc_type_name = type(exc).__name__.lower()
    retryable_signals = [
        "429", "rate limit", "too many requests",
        "503", "502", "500", "504", "gateway",
        "timeout", "timed out", "超时",
        "connection", "network", "连接",
        "connecterror", "timeoutexception",
        "readtimeout", "connecttimeout", "writetimeout", "pooltimeout",
        "networkerror", "protocolerror",
    ]
    if any(s in msg or s in exc_type_name for s in retryable_signals):
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
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    调用 LLM 并解析 JSON；内置缓存、重试、token 计量。

    token_tracker: 调用方传入的可变 dict，会累计 token_used。
    history: 多轮对话历史 [{"role": "user"|"assistant", "content": "..."}, ...]，
            以标准 OpenAI messages 格式注入，让 LLM 正确理解上下文。
    """
    cache_key = _make_cache_key(system_prompt, user_content, model)
    if cache_key_suffix:
        cache_key = f"{cache_key}::{cache_key_suffix}"
    # 有历史对话时不使用缓存（每次上下文不同）
    if history:
        enable_cache = False

    if enable_cache:
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            logger.info("[LLMClient] cache hit %s...", cache_key[:8])
            return cached

    # 构造标准 OpenAI 多轮消息：system + 历史轮次 + 当前 user
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        # 取最近 20 条，避免 token 爆炸
        for msg in history[-20:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                # 截断过长的历史消息（单条最多 2000 字）
                if len(content) > 2000:
                    content = content[:2000] + "...(内容已截断)"
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    # 诊断日志：记录 LLM 调用前的关键信息
    prompt_preview = (system_prompt[:80] + "...") if len(system_prompt) > 80 else system_prompt
    user_preview = (user_content[:80] + "...") if len(user_content) > 80 else user_content
    logger.info(
        "[LLMClient] 开始调用 LLM: model=%s max_tokens=%s temp=%.1f retries=%d prompt_len=%d user_len=%d history=%d msgs=%d",
        model, max_tokens, temperature, max_retries, len(system_prompt), len(user_content),
        len(history) if history else 0, len(messages),
    )
    logger.debug("[LLMClient] system_prompt preview: %s", prompt_preview)
    logger.debug("[LLMClient] user_content preview: %s", user_preview)

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            logger.info("[LLMClient] 发送 HTTP 请求 (attempt=%d/%d)", attempt + 1, max_retries)
            response = await AIService.chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            logger.info("[LLMClient] HTTP 响应已收到 (attempt=%d/%d)", attempt + 1, max_retries)

            # 检查 API 是否返回了错误
            if isinstance(response, dict) and response.get("error"):
                err_obj = response["error"]
                err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
                logger.error("[LLMClient] API 返回错误: model=%s error=%s", model, err_msg)
                raise RuntimeError(f"API 返回错误: {err_msg}")

            content = response["choices"][0]["message"]["content"]
            if not content or not content.strip():
                logger.error("[LLMClient] LLM 返回空 content, model=%s, 完整响应: %s", model, json.dumps(response, ensure_ascii=False)[:2000])
                raise ValueError(f"LLM 返回为空 (model={model})")

            json_str = _sanitize_control_chars(_extract_json(content) or content.strip())
            if not json_str:
                logger.error("[LLMClient] JSON 提取为空, model=%s, content[:500]=%s", model, content[:500])
                raise ValueError(f"LLM 返回内容无法解析为 JSON (model={model})")
            # 修复 LLM 输出中的非法 JSON 转义序列（如 \d, \w, \! 等）
            json_str = _fix_invalid_escapes(json_str)
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError as json_exc:
                # 尝试修复被截断的 JSON（LLM 输出因 max_tokens 不足被截断）
                repaired = _repair_truncated_json(json_str)
                if repaired:
                    logger.warning(
                        "[LLMClient] JSON 解析失败，已自动修复截断: %s -> 修复后长度=%d",
                        str(json_exc)[:120], len(repaired),
                    )
                    parsed = json.loads(repaired)
                else:
                    raise
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
            logger.info("[LLMClient] LLM 调用成功 (attempt=%d/%d) tokens=%d", attempt + 1, max_retries, total_tokens)
            return parsed

        except Exception as exc:
            last_exc = exc
            retryable = _is_retryable_error(exc)
            logger.warning(
                "[LLMClient] 调用异常 (attempt=%d/%d) retryable=%s: %s [%s]",
                attempt + 1, max_retries, retryable, exc, type(exc).__name__,
            )
            if attempt < max_retries - 1 and retryable:
                delay = min(DEFAULT_BASE_DELAY * (2 ** attempt), DEFAULT_MAX_DELAY)
                logger.warning(
                    "[LLMClient] %ss 后重试...",
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                if not retryable and attempt < max_retries - 1:
                    logger.warning("[LLMClient] 非可重试错误，停止重试: %s [%s]", exc, type(exc).__name__)
                else:
                    logger.warning(
                        "[LLMClient] 重试已耗尽（attempt=%d/%d）: %s [%s]\n%s",
                        attempt + 1, max_retries, exc, type(exc).__name__,
                        traceback.format_exc(),
                    )
                break

    logger.warning("[LLMClient] LLM 调用最终失败: %s [%s] (model=%s)", last_exc, type(last_exc).__name__ if last_exc else "None", model)
    if fallback is not None:
        # 缓存 fallback 吗？通常不缓存，因为 fallback 是错误产物
        return fallback
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("LLM 调用失败但无异常对象")


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
