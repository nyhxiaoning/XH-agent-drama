"""SSE 流式响应公共工具。

将 agent.py 中重复的 SSE 心跳/消息推送逻辑抽取为统一函数，
避免 4 个 SSE 端点各自维护相同的 queue + heartbeat + yield 代码。
"""
import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


async def sse_event_stream(
    run_fn: Callable[[], Awaitable[None]],
    on_message_fn: Callable[[Any], Awaitable[None]],
    queue: "asyncio.Queue[Any]",
    *,
    heartbeat_interval: float = 5.0,
    heartbeat_fn: Optional[Callable[[int], Any]] = None,
    sentinel: Any = None,
) -> AsyncIterator[str]:
    """通用 SSE 事件流生成器。

    Args:
        run_fn: 后台协程，执行实际业务逻辑。完成后应向 queue 放入 sentinel。
        on_message_fn: 消息回调，将业务消息放入 queue。
        queue: asyncio.Queue，用于在 run_fn 和生成器之间传递消息。
        heartbeat_interval: 无消息时发送心跳的间隔（秒）。
        heartbeat_fn: 构造心跳消息的函数，接收 elapsed_seconds 参数。
        sentinel: 表示流结束的哨兵值。

    Yields:
        SSE 格式的字符串 ``data: {...}\\n\\n``
    """
    start_time = time.time()
    runner = asyncio.create_task(run_fn())
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                elapsed = int(time.time() - start_time)
                if heartbeat_fn:
                    hb = heartbeat_fn(elapsed)
                    if hb is not None:
                        data = json.dumps(hb.__dict__ if hasattr(hb, "__dict__") else hb,
                                          ensure_ascii=False, default=str)
                        yield f"data: {data}\n\n"
                continue
            if msg is sentinel:
                break
            data = json.dumps(msg.__dict__ if hasattr(msg, "__dict__") else msg,
                              ensure_ascii=False, default=str)
            yield f"data: {data}\n\n"
    finally:
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass
