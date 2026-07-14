"""火山方舟 Ark V3 视频生成回调端点。

Ark 在视频生成完成后会向 callback_url 发送 POST 请求，
本端点解析回调内容，根据 video_task_id 找到内部 Task 并提前结束轮询。

回调体格式（参考火山方舟文档）：
{
    "id": "task_xxx",           # 任务 ID
    "status": "succeeded",       # 状态
    "content": {
        "video_url": {
            "url": "https://..."
        }
    }
}
"""
import logging
from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.tasks import task_manager, TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ark", tags=["callback"])


def _pick_first_string(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        for x in v:
            s = _pick_first_string(x)
            if s:
                return s
    if isinstance(v, dict):
        for k in ("id", "taskId", "task_id", "taskID"):
            s = _pick_first_string(v.get(k))
            if s:
                return s
    return ""


def _extract_task_id(body: dict) -> str:
    return (
        _pick_first_string(body.get("id"))
        or _pick_first_string(body.get("taskId"))
        or _pick_first_string(body.get("task_id"))
        or _pick_first_string((body.get("data") or {}).get("id"))
        or _pick_first_string((body.get("data") or {}).get("taskId"))
        or _pick_first_string((body.get("data") or {}).get("task_id"))
        or ""
    )


def _extract_status(body: dict) -> str:
    return str(
        body.get("status")
        or body.get("task_status")
        or (body.get("data") or {}).get("status")
        or (body.get("data") or {}).get("task_status")
        or ""
    ).lower()


def _extract_video_url(body: dict) -> str:
    direct = (
        body.get("video_url")
        or (body.get("data") or {}).get("video_url")
        or (body.get("output") or {}).get("video_url")
        or (body.get("data") or {}).get("output", {}).get("video_url")
        or ""
    )
    if isinstance(direct, str) and direct.startswith("http"):
        return direct
    if isinstance(direct, dict) and isinstance(direct.get("url"), str):
        return direct["url"]

    content = (
        body.get("content")
        or (body.get("data") or {}).get("content")
        or (body.get("output") or {}).get("content")
        or (body.get("data") or {}).get("output", {}).get("content")
    )
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            u = (item.get("video_url") or {}).get("url") if isinstance(item.get("video_url"), dict) else item.get("video_url")
            if isinstance(u, str) and u.startswith("http"):
                return u
            if isinstance(item.get("url"), str) and item["url"].startswith("http"):
                return item["url"]
    elif isinstance(content, dict):
        u = content.get("video_url") or content.get("url")
        if isinstance(u, dict):
            u = u.get("url")
        if isinstance(u, str) and u.startswith("http"):
            return u
    return ""


@router.post("/callback")
async def ark_callback(request: Request):
    """接收火山方舟视频生成完成回调。

    回调与轮询是双保险机制：即使回调先到达，轮询循环也会在下次查询时检测到完成状态；
    如果回调因网络问题未到达，轮询仍能正常工作。
    此端点只需返回 200 OK，核心完成逻辑由轮询循环处理。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        body = {}

    task_id = _extract_task_id(body)
    status = _extract_status(body)
    video_url = _extract_video_url(body)

    logger.info("[ark_callback] received task_id=%s status=%s has_url=%s", task_id, status, bool(video_url))

    if not task_id:
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    is_success = status in ("succeeded", "success", "completed", "done")
    is_failed = status in ("failed", "error", "canceled", "cancelled", "expired")

    # 尝试找到内部 Task，提前暂存结果以加速轮询循环的下次检测
    internal_task = task_manager.get_task_by_video_id(task_id)
    if internal_task and internal_task.status in (TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.RETRYING):
        if is_success and video_url:
            # 暂存回调结果，轮询循环下次 check 时会读取到 completed + url
            internal_task.result = {
                "type": "video",
                "task_id": task_id,
                "status": "completed",
                "url": video_url,
                "prompt": internal_task.params.get("prompt", ""),
                "duration": internal_task.params.get("durationSec", 5),
                "_from_callback": True,
            }
            logger.info("[ark_callback] 视频完成回调已暂存 task=%s", internal_task.id)
        elif is_failed:
            internal_task.error = f"视频生成失败（回调通知）：{status}"
            logger.info("[ark_callback] 视频失败回调已暂存 task=%s", internal_task.id)

    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
