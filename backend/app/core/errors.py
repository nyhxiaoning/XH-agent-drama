"""
Agent 错误分类体系：区分可重试错误与致命错误，提升流水线健壮性。

P15 优化：错误恢复机制不够健壮。
#9 细粒度错误处理：针对不同错误类型采用不同重试策略。
"""
import logging
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorStrategy(str, Enum):
    """#9 细粒度重试策略。"""
    RETRY_SAME = "retry_same"           # 用相同参数重试
    RETRY_REPAIR = "retry_repair"       # 重试 + JSON 修复
    RETRY_BACKOFF = "retry_backoff"     # 指数退避重试（限流/429）
    RETRY_LIGHTER = "retry_lighter"     # 降级到更轻量模型重试
    RETRY_LONGER = "retry_longer"       # 增加超时重试
    STOP_FATAL = "stop_fatal"           # 致命错误，立即停止
    STOP_BUDGET = "stop_budget"         # 预算超限，立即停止


# 错误码 → 重试策略映射
ERROR_STRATEGY_MAP = {
    "RETRYABLE": ErrorStrategy.RETRY_SAME,
    "FATAL": ErrorStrategy.STOP_FATAL,
    "BUDGET_EXCEEDED": ErrorStrategy.STOP_BUDGET,
    "LLM_FALLBACK": ErrorStrategy.RETRY_REPAIR,
    "JSON_PARSE": ErrorStrategy.RETRY_REPAIR,
    "TIMEOUT": ErrorStrategy.RETRY_LONGER,
    "RATE_LIMIT": ErrorStrategy.RETRY_BACKOFF,
    "MODEL_UNAVAILABLE": ErrorStrategy.RETRY_LIGHTER,
    "NETWORK": ErrorStrategy.RETRY_BACKOFF,
}


class AgentError(Exception):
    """Agent 错误基类。"""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        stage: Optional[str] = None,
        agent: Optional[str] = None,
        error_code: str = "AGENT_ERROR",
        detail: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.stage = stage
        self.agent = agent
        self.error_code = error_code
        self.detail = detail or {}


class RetryableError(AgentError):
    """可重试错误：LLM 超时、API 429/5xx、网络抖动等。"""

    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("retryable", True)
        kwargs.setdefault("error_code", "RETRYABLE")
        super().__init__(message, **kwargs)


class FatalError(AgentError):
    """致命错误：配置缺失、数据结构不可解析、鉴权失败等，重试无意义。"""

    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("retryable", False)
        kwargs.setdefault("error_code", "FATAL")
        super().__init__(message, **kwargs)


class BudgetExceededError(AgentError):
    """Token 预算或积分预算超限。"""

    def __init__(self, message: str, used: int = 0, budget: int = 0, **kwargs):
        kwargs.setdefault("retryable", False)
        kwargs.setdefault("error_code", "BUDGET_EXCEEDED")
        kwargs.setdefault("detail", {})
        kwargs["detail"]["used"] = used
        kwargs["detail"]["budget"] = budget
        super().__init__(message, **kwargs)


class LLMFallbackError(AgentError):
    """LLM 返回 fallback 兜底数据。"""

    def __init__(self, message: str, fallback_data: Optional[Dict] = None, **kwargs):
        kwargs.setdefault("retryable", True)
        kwargs.setdefault("error_code", "LLM_FALLBACK")
        kwargs.setdefault("detail", {})
        if fallback_data:
            kwargs["detail"]["fallback_error"] = fallback_data.get("_fallback_error", "")
        super().__init__(message, **kwargs)


# #9 细粒度错误子类

class JSONParseError(RetryableError):
    """JSON 解析失败（LLM 输出格式错误）。"""

    def __init__(self, message: str, raw_content: str = "", **kwargs):
        kwargs.setdefault("error_code", "JSON_PARSE")
        kwargs.setdefault("detail", {})
        if raw_content:
            kwargs["detail"]["raw_preview"] = raw_content[:200]
        super().__init__(message, **kwargs)


class TimeoutError(RetryableError):
    """LLM 调用超时。"""

    def __init__(self, message: str, timeout_seconds: float = 0, **kwargs):
        kwargs.setdefault("error_code", "TIMEOUT")
        kwargs.setdefault("detail", {})
        if timeout_seconds:
            kwargs["detail"]["timeout_seconds"] = timeout_seconds
        super().__init__(message, **kwargs)


class RateLimitError(RetryableError):
    """API 限流（429）。"""

    def __init__(self, message: str, retry_after: float = 0, **kwargs):
        kwargs.setdefault("error_code", "RATE_LIMIT")
        kwargs.setdefault("detail", {})
        if retry_after:
            kwargs["detail"]["retry_after"] = retry_after
        super().__init__(message, **kwargs)


class ModelUnavailableError(RetryableError):
    """模型不可用（503/模型不存在）。"""

    def __init__(self, message: str, model: str = "", **kwargs):
        kwargs.setdefault("error_code", "MODEL_UNAVAILABLE")
        kwargs.setdefault("detail", {})
        if model:
            kwargs["detail"]["model"] = model
        super().__init__(message, **kwargs)


# ---- 错误分类映射 ----

_FATAL_KEYWORDS = [
    "api key", "未配置", "not configured", "invalid key",
    "authentication", "forbidden", "403", "401",
    "not supported", "不支持", "valueerror",
    "json decode", "json.loads",
    "attributeerror", "typeerror",
]

_RETRYABLE_KEYWORDS = [
    "timeout", "timed out", "超时",
    "429", "rate limit", "too many requests",
    "502", "503", "504", "gateway", "500",
    "connection", "network", "连接", "网络",
    "temporary", "暂不可用",
    "fallback", "兜底",
    "ai 服务请求", "ai 服务连接", "ai 服务请求超时", "ai 服务 http",
    "connecterror", "readtimeout", "connecttimeout",
    "writetimeout", "pooltimeout", "networkerror", "protocolerror",
    "runtimeerror",
]


def classify_exception(exc: Exception) -> AgentError:
    """将任意异常分类为 AgentError 子类。

    #9 细粒度分类规则：
    1. 已经是 AgentError → 原样返回。
    2. 异常类型/消息命中特定模式 → 返回对应细粒度子类。
    3. 异常消息命中致命关键词 → FatalError。
    4. 默认 → RetryableError（保守策略，倾向于重试）。
    """
    if isinstance(exc, AgentError):
        return exc

    msg = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    # 致命关键词
    for kw in _FATAL_KEYWORDS:
        if kw in msg or kw in exc_type:
            return FatalError(str(exc))

    # #9 细粒度：JSON 解析错误
    _JSON_KEYWORDS = ["json decode", "json.loads", "invalid \\escape", "unterminated string",
                       "expecting property", "expecting value", "extra data"]
    if any(kw in msg or kw in exc_type for kw in _JSON_KEYWORDS):
        return JSONParseError(str(exc))

    # #9 细粒度：限流错误（429）
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return RateLimitError(str(exc))

    # #9 细粒度：模型不可用（503）
    if "503" in msg or "model not found" in msg or "model not available" in msg:
        return ModelUnavailableError(str(exc))

    # #9 细粒度：超时错误
    _TIMEOUT_KEYWORDS = ["timeout", "timed out", "超时", "readtimeout", "connecttimeout",
                          "writetimeout", "pooltimeout"]
    if any(kw in msg or kw in exc_type for kw in _TIMEOUT_KEYWORDS):
        return TimeoutError(str(exc))

    # #9 细粒度：网络错误
    _NETWORK_KEYWORDS = ["connection", "network", "连接", "网络", "connecterror",
                          "networkerror", "protocolerror", "proxyerror"]
    if any(kw in msg or kw in exc_type for kw in _NETWORK_KEYWORDS):
        return RetryableError(str(exc), error_code="NETWORK")

    # 可重试关键词（兜底）
    for kw in _RETRYABLE_KEYWORDS:
        if kw in msg or kw in exc_type:
            return RetryableError(str(exc))

    # 默认可重试
    return RetryableError(str(exc))


def get_error_strategy(exc: Exception) -> ErrorStrategy:
    """#9 获取错误对应的重试策略。"""
    agent_err = classify_exception(exc)
    return ERROR_STRATEGY_MAP.get(agent_err.error_code, ErrorStrategy.RETRY_SAME)


def should_stop_retrying(exc: Exception, retry_count: int, max_retries: int) -> bool:
    """判断是否应该停止重试。

    致命错误立即停止；可重试错误达到上限停止。
    """
    agent_err = classify_exception(exc)

    if not agent_err.retryable:
        logger.warning(
            "[ErrorHandler] 致命错误，停止重试: code=%s msg=%s",
            agent_err.error_code, str(exc)[:200],
        )
        return True

    if retry_count >= max_retries:
        logger.warning(
            "[ErrorHandler] 重试次数已达上限 (%d/%d): %s",
            retry_count, max_retries, str(exc)[:200],
        )
        return True

    return False


def format_error_for_state(exc: Exception, stage: str = "", agent: str = "") -> Dict[str, Any]:
    """格式化错误信息供 DramaProductionState 使用。"""
    agent_err = classify_exception(exc)
    return {
        "last_error": str(exc),
        "error_code": agent_err.error_code,
        "error_retryable": agent_err.retryable,
        "error_stage": stage or agent_err.stage or "",
        "error_agent": agent or agent_err.agent or "",
        "error_detail": agent_err.detail,
    }
