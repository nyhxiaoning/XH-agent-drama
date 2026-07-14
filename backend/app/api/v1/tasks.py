from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.core.tasks import task_manager, Task, TaskStatus
from app.schemas.task import TaskInDB
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _sanitize_task_result(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return result
    cleaned = dict(result)
    if "raw_response" in cleaned:
        cleaned["raw_response"] = "<trimmed>"
    return cleaned


def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "node_id": task.node_id,
        "canvas_id": task.canvas_id,
        "task_type": task.task_type,
        "params": task.params,
        "status": task.status,
        "progress": task.progress,
        "result": _sanitize_task_result(task.result),
        "error": task.error,
        "retry_count": task.retry_count,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        # #17: 优先级信息
        "priority": task.sort_priority,
    }


@router.get("", response_model=List[TaskInDB])
def list_tasks(
    canvas_id: str = None,
    node_id: str = None,
    status: TaskStatus = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
):
    if node_id:
        tasks = task_manager.get_tasks_by_node(node_id)
    elif canvas_id:
        tasks = task_manager.get_tasks_by_canvas(canvas_id)
    else:
        tasks = task_manager.get_all_tasks()
    if status:
        tasks = [t for t in tasks if t.status == status]
    tasks = sorted(tasks, key=lambda t: t.created_at, reverse=True)
    tasks = tasks[offset:offset + limit]
    return [_task_to_dict(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskInDB)
def get_task(task_id: str, current_user: User = Depends(get_current_user)):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_dict(task)


@router.post("/{task_id}/cancel", status_code=200)
async def cancel_task(task_id: str, current_user: User = Depends(get_current_user)):
    success = await task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="无法取消该任务")
    return {"task_id": task_id, "status": "cancelled"}


# ─── #17 队列状态与批量操作 ──────────────────────────────

@router.get("/queue/status")
def get_queue_status(canvas_id: str = None, current_user: User = Depends(get_current_user)):
    """返回生成队列状态统计（待处理/运行中/已完成/失败数量）。"""
    return task_manager.get_queue_status(canvas_id=canvas_id)


@router.post("/cancel-by-canvas")
async def cancel_tasks_by_canvas(canvas_id: str, current_user: User = Depends(get_current_user)):
    """批量取消指定画布的所有未完成任务。"""
    result = await task_manager.cancel_tasks_by_canvas(canvas_id)
    return result
