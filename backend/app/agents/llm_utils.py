"""
Agent 层统一 LLM JSON 调用工具。

M6：抽离 short_drama.py / drama_brain.py 中重复的 _llm_json 实现，
提供统一异步 + 同步入口，并自动为 fallback 结果打上 _is_fallback 标记。

#6 集成模型分级策略：通过 tier 参数自动选择轻量/标准/旗舰模型。
#8 集成动态并发控制：通过全局信号量限制 LLM 并发请求数。
"""
import asyncio
import inspect
import json
import logging
from typing import Any, Dict, List, Optional

from app.services.llm_client import llm_json as _llm_json_client, check_token_budget
from app.core.model_tiers import TaskTier, resolve_model, resolve_model_for_agent
from app.core.config import settings

logger = logging.getLogger(__name__)

# #8 全局并发信号量：限制同时进行的 LLM HTTP 请求
_llm_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """懒初始化全局 LLM 并发信号量。"""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
    return _llm_semaphore

# 启动时检测底层 llm_client.llm_json 支持哪些参数，避免运行时 TypeError
_client_params = set(inspect.signature(_llm_json_client).parameters.keys())
_CLIENT_SUPPORTS_MAX_TOKENS = "max_tokens" in _client_params
_CLIENT_SUPPORTS_TEMPERATURE = "temperature" in _client_params
_CLIENT_SUPPORTS_HISTORY = "history" in _client_params
if not _CLIENT_SUPPORTS_MAX_TOKENS:
    logger.warning("[llm_utils] llm_client.llm_json 不支持 max_tokens 参数，将降级忽略")


async def llm_json(
    system_prompt: str,
    user_content: str,
    model: Optional[str] = None,
    fallback: Optional[Dict[str, Any]] = None,
    token_tracker: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.3,
    tier: Optional[TaskTier] = None,
    agent_name: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    统一异步 LLM JSON 调用入口。

    Args:
        max_tokens: 限制输出 token 数。不同 Agent 按输出复杂度设置：
            - ScriptPlanner/Screenwriter: 8192（复杂多集剧本）
            - CharacterDesigner/ScenePropDesigner/AssetExtractor: 4096
            - StoryboardDirector: 6144
            - VideoComposer: 2048（单批 5 个分镜）
        temperature: 采样温度，默认 0.3（结构化 JSON 输出适用低温度）。
        tier: #6 模型分级（lite/standard/creative），未指定时从 agent_name 推断。
        agent_name: Agent 名称，用于自动推断 tier 和模型。

    若调用最终失败且提供了 fallback，返回的 fallback 对象会自动注入
    {"_is_fallback": True}，供下游 Review / 校验节点识别。
    """
    # #6 模型分级：优先用户显式 model > tier/agent_name 推断 > 默认
    if not model:
        if agent_name:
            model = resolve_model_for_agent(agent_name, model)
        elif tier:
            model = resolve_model(tier, model)
        # model 仍为 None 时由 llm_client 内部用 settings.LLM_MODEL_NAME

    # 根据底层 llm_client 支持的参数动态构建调用参数
    call_kwargs: Dict[str, Any] = dict(
        model=model,
        fallback=None,  # 自行处理 fallback 标记
        token_tracker=token_tracker,
    )
    if _CLIENT_SUPPORTS_MAX_TOKENS and max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens
    if _CLIENT_SUPPORTS_TEMPERATURE:
        call_kwargs["temperature"] = temperature
    # 传递多轮对话历史
    if history and _CLIENT_SUPPORTS_HISTORY:
        call_kwargs["history"] = history
    call_kwargs.update(kwargs)

    # #8 动态并发控制：通过信号量限制同时进行的 LLM 请求
    sem = _get_semaphore()
    try:
        async with sem:
            return await _llm_json_client(
                system_prompt,
                user_content,
                **call_kwargs,
            )
    except TypeError as exc:
        # 双保险：即使 inspect 检测遗漏（如 monkey-patch 场景），
        # 仍可捕获 TypeError 并降级重试
        if "max_tokens" in str(exc) and "unexpected keyword argument" in str(exc):
            logger.warning("[llm_utils] 运行时检测到 max_tokens 不被支持，降级重试")
            call_kwargs.pop("max_tokens", None)
            try:
                async with sem:
                    return await _llm_json_client(system_prompt, user_content, **call_kwargs)
            except Exception as inner_exc:
                exc = inner_exc
        if fallback is not None:
            _error_detail = _format_fallback_error(exc, model)
            logger.warning("[llm_utils] LLM 调用失败，使用 fallback: %s", _error_detail)
            marked = dict(fallback)
            marked["_is_fallback"] = True
            marked["_fallback_error"] = _error_detail
            return marked
        raise
    except Exception as exc:
        if fallback is not None:
            _error_detail = _format_fallback_error(exc, model)
            logger.warning("[llm_utils] LLM 调用失败，使用 fallback: %s", _error_detail)
            marked = dict(fallback)
            marked["_is_fallback"] = True
            marked["_fallback_error"] = _error_detail
            return marked
        raise


def llm_json_sync(
    system_prompt: str,
    user_content: str,
    model: Optional[str] = None,
    fallback: Optional[Dict[str, Any]] = None,
    token_tracker: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """同步入口：同步调用方（如 LangGraph 同步节点、旧代码）使用。"""
    return asyncio.run(
        llm_json(
            system_prompt,
            user_content,
            model=model,
            fallback=fallback,
            token_tracker=token_tracker,
            **kwargs,
        )
    )


# #16 LLM 流式输出

async def llm_json_stream(
    system_prompt: str,
    user_content: str,
    model: Optional[str] = None,
    fallback: Optional[Dict[str, Any]] = None,
    token_tracker: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.3,
    tier: Optional[TaskTier] = None,
    agent_name: Optional[str] = None,
    on_token: Optional[Any] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """#16 流式 LLM JSON 调用：逐 token 推送到前端，最终返回解析后的 JSON。

    Args:
        on_token: 异步回调 async (token: str) -> None，每收到一个 token 调用一次。

    Returns:
        解析后的 JSON dict（与 llm_json 一致）
    """
    from app.services.ai_service import AIService
    from app.services.llm_client import _extract_json, _sanitize_control_chars, _fix_invalid_escapes, _repair_truncated_json

    # #6 模型分级
    if not model:
        if agent_name:
            model = resolve_model_for_agent(agent_name, model)
        elif tier:
            model = resolve_model(tier, model)

    messages = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        for msg in history[-20:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                if len(content) > 2000:
                    content = content[:2000] + "...(内容已截断)"
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    # #8 并发控制
    sem = _get_semaphore()
    full_content = ""

    try:
        async with sem:
            async for token in AIService.chat_stream(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                full_content += token
                if on_token:
                    try:
                        await on_token(token)
                    except Exception:
                        pass

        # 解析 JSON
        json_str = _sanitize_control_chars(_extract_json(full_content) or full_content.strip())
        if not json_str:
            raise ValueError("LLM 流式返回为空")
        json_str = _fix_invalid_escapes(json_str)
        try:
            parsed = json.loads(json_str)
        except Exception:
            repaired = _repair_truncated_json(json_str)
            if repaired:
                parsed = json.loads(repaired)
            else:
                raise

        if not isinstance(parsed, dict):
            raise ValueError("LLM 流式返回不是 JSON 对象")

        # Token 计量（粗略估算）
        if token_tracker is not None:
            est_tokens = len(full_content) // 3  # 粗略估算
            token_tracker["token_used"] = token_tracker.get("token_used", 0) + est_tokens

        logger.info("[llm_utils] 流式 LLM 调用成功, model=%s, content_len=%d", model, len(full_content))
        return parsed

    except Exception as exc:
        if fallback is not None:
            _error_detail = _format_fallback_error(exc, model)
            logger.warning("[llm_utils] 流式 LLM 调用失败，使用 fallback: %s", _error_detail)
            marked = dict(fallback)
            marked["_is_fallback"] = True
            marked["_fallback_error"] = _error_detail
            return marked
        raise


def is_fallback_result(result: Any) -> bool:
    """判断一个 LLM 返回结果是否为 fallback 兜底数据。"""
    return isinstance(result, dict) and bool(result.get("_is_fallback"))


def _format_fallback_error(exc: Exception, model: Optional[str] = None) -> str:
    """格式化 fallback 错误信息，包含异常类型和模型名，便于诊断。

    之前只存 str(exc)，如果底层异常消息为空（如 httpx.ConnectError("")），
    则前端只看到 "AI 服务请求异常:" 无法排查。
    现在补充异常类型名和模型名，并检查 __cause__ 链。
    """
    exc_type = type(exc).__name__
    msg = str(exc).strip()

    # 如果主异常消息为空，尝试从 __cause__ 获取
    if not msg and exc.__cause__:
        cause = exc.__cause__
        msg = str(cause).strip()
        exc_type = f"{exc_type} -> {type(cause).__name__}"

    # 仍然为空时给出默认提示
    if not msg:
        msg = f"{exc_type}（无详细错误消息，请查看后端日志）"

    model_hint = f" [model={model}]" if model else ""
    return f"{msg}{model_hint}"
