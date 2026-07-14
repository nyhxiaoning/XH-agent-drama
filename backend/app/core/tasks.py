import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, List, Callable, Awaitable, Any
from dataclasses import dataclass, field

from app.core.config import settings


logger = logging.getLogger(__name__)


# #17 任务优先级：数字越小优先级越高
TASK_PRIORITY = {
    "generate_image": 0,   # 角色/场景图片优先
    "generate_video": 10,  # 视频最后
}


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass(order=True)
class Task:
    # #17: sort_priority 用于 PriorityQueue 排序（数字越小越先出队）
    # 注意：必须提供 default=0，否则 Python 3.11 某些版本会在类定义时报 TypeError
    sort_priority: int = field(init=False, default=0, compare=True)
    # #17: tiebreaker，确保同优先级任务 FIFO 出队
    sort_seq: int = field(init=False, compare=True, default=0)
    id: str = field(compare=False)
    node_id: str = field(compare=False)
    canvas_id: str = field(compare=False)
    task_type: str = field(compare=False)
    params: Dict[str, Any] = field(compare=False, default_factory=dict)
    status: TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    progress: int = field(compare=False, default=0)
    result: Optional[Dict[str, Any]] = field(compare=False, default=None)
    error: Optional[str] = field(compare=False, default=None)
    retry_count: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default_factory=lambda: settings.TASK_MAX_RETRIES)
    created_at: datetime = field(compare=False, default_factory=datetime.utcnow)
    started_at: Optional[datetime] = field(compare=False, default=None)
    completed_at: Optional[datetime] = field(compare=False, default=None)
    cancel_event: asyncio.Event = field(compare=False, default_factory=asyncio.Event)
    user_id: Optional[str] = field(compare=False, default=None)
    cost: int = field(compare=False, default=0)
    # #17: 优先级字段（None=自动推断，0=最高优先级）
    priority: Optional[int] = field(compare=False, default=None)

    def __post_init__(self):
        # 根据 task_type 自动设置优先级
        self.sort_priority = self.priority if self.priority is not None else TASK_PRIORITY.get(self.task_type, 5)
        # 全局递增序号，确保同优先级任务按提交顺序出队
        global _task_seq
        _task_seq += 1
        self.sort_seq = _task_seq


class TaskManager:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        # #17: 使用 PriorityQueue 支持优先级调度
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._tasks: Dict[str, Task] = {}
        self._running = False
        self._workers: List[asyncio.Task] = []
        self._status_callbacks: List[Callable[[Task], Awaitable[None]]] = []
        self._worker_fn: Optional[Callable[[Task], Awaitable[Dict[str, Any]]]] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def set_worker(self, fn: Callable[[Task], Awaitable[Dict[str, Any]]]):
        self._worker_fn = fn

    def on_status_change(self, callback: Callable[[Task], Awaitable[None]]):
        self._status_callbacks.append(callback)

    async def _notify(self, task: Task):
        self._persist_task(task)
        for cb in self._status_callbacks:
            try:
                await cb(task)
            except Exception as exc:
                logger.warning("[TaskManager] notify error: %s", exc)

    async def submit(self, task: Task) -> Task:
        self._cleanup_old_tasks()
        task.status = TaskStatus.QUEUED
        self._tasks[task.id] = task
        self._persist_task(task)
        await self._queue.put(task)
        await self._notify(task)
        return task

    def _persist_task(self, task: Task):
        """将任务状态持久化到数据库（best-effort，失败不阻塞主流程）。"""
        try:
            from app.core.database import SessionLocal
            from app.models.task_record import TaskRecord
            db = SessionLocal()
            try:
                record = db.query(TaskRecord).filter(TaskRecord.id == task.id).first()
                if not record:
                    record = TaskRecord(id=task.id, node_id=task.node_id, canvas_id=task.canvas_id)
                    db.add(record)
                record.task_type = task.task_type
                record.status = task.status.value
                record.progress = task.progress
                record.result = task.result
                record.error = task.error
                record.retry_count = task.retry_count
                record.max_retries = task.max_retries
                record.user_id = task.user_id
                record.cost = task.cost
                record.params = task.params
                record.started_at = task.started_at
                record.completed_at = task.completed_at
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("[TaskManager] 持久化任务失败 task=%s", task.id, exc_info=True)

    def restore_from_db(self):
        """服务重启时从数据库恢复任务状态。

        只恢复状态信息到内存，不重新执行（已运行的任务由 main.py 标记为 FAILED）。
        终态任务恢复后供前端查询历史。
        """
        try:
            from app.core.database import SessionLocal
            from app.models.task_record import TaskRecord
            db = SessionLocal()
            try:
                records = db.query(TaskRecord).filter(
                    TaskRecord.status.in_(["success", "failed", "cancelled"])
                ).order_by(TaskRecord.created_at.desc()).limit(200).all()
                for r in records:
                    if r.id not in self._tasks:
                        task = Task(
                            id=r.id,
                            node_id=r.node_id,
                            canvas_id=r.canvas_id,
                            task_type=r.task_type,
                            params=r.params or {},
                            status=TaskStatus(r.status),
                            progress=r.progress,
                            result=r.result,
                            error=r.error,
                            retry_count=r.retry_count,
                            max_retries=r.max_retries,
                            user_id=r.user_id,
                            cost=r.cost,
                        )
                        task.started_at = r.started_at
                        task.completed_at = r.completed_at
                        self._tasks[task.id] = task
                logger.info("[TaskManager] 从数据库恢复 %d 条任务记录", len(records))
            finally:
                db.close()
        except Exception:
            logger.warning("[TaskManager] 从数据库恢复任务失败", exc_info=True)

    def _cleanup_old_tasks(self):
        """清理 1 小时前已进入终态的任务，避免 _tasks 无限增长。"""
        cutoff = datetime.utcnow() - timedelta(hours=1)
        terminal = (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t.status in terminal and (t.completed_at or t.created_at) < cutoff
        ]
        for tid in to_remove:
            del self._tasks[tid]

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_tasks_by_node(self, node_id: str) -> List[Task]:
        return [t for t in self._tasks.values() if t.node_id == node_id]

    def get_tasks_by_canvas(self, canvas_id: str) -> List[Task]:
        return [t for t in self._tasks.values() if t.canvas_id == canvas_id]

    def get_all_tasks(self) -> List[Task]:
        return list(self._tasks.values())

    # ─── #17 队列状态与批量操作 ──────────────────────────

    def get_queue_status(self, canvas_id: str = None) -> Dict[str, Any]:
        """返回队列状态统计。"""
        tasks = self.get_tasks_by_canvas(canvas_id) if canvas_id else self.get_all_tasks()
        pending = [t for t in tasks if t.status in (TaskStatus.QUEUED, TaskStatus.RETRYING)]
        running = [t for t in tasks if t.status == TaskStatus.RUNNING]
        success = [t for t in tasks if t.status == TaskStatus.SUCCESS]
        failed = [t for t in tasks if t.status == TaskStatus.FAILED]
        cancelled = [t for t in tasks if t.status == TaskStatus.CANCELLED]
        return {
            "total": len(tasks),
            "pending": len(pending),
            "running": len(running),
            "success": len(success),
            "failed": len(failed),
            "cancelled": len(cancelled),
            "max_concurrent": self.max_concurrent,
            "pending_details": [
                {
                    "task_id": t.id,
                    "node_id": t.node_id,
                    "task_type": t.task_type,
                    "priority": t.sort_priority,
                    "created_at": t.created_at.isoformat(),
                }
                for t in sorted(pending, key=lambda x: x.sort_priority)
            ],
            "running_details": [
                {
                    "task_id": t.id,
                    "node_id": t.node_id,
                    "task_type": t.task_type,
                    "started_at": t.started_at.isoformat() if t.started_at else None,
                    "progress": t.progress,
                }
                for t in running
            ],
        }

    async def cancel_tasks_by_canvas(self, canvas_id: str) -> Dict[str, Any]:
        """批量取消指定画布的所有未完成任务。"""
        tasks = self.get_tasks_by_canvas(canvas_id)
        cancelled_ids = []
        for t in tasks:
            if t.status in (TaskStatus.QUEUED, TaskStatus.RETRYING, TaskStatus.PENDING):
                await self.cancel_task(t.id)
                cancelled_ids.append(t.id)
            elif t.status == TaskStatus.RUNNING:
                await self.cancel_task(t.id)
                cancelled_ids.append(t.id)
        return {"canvas_id": canvas_id, "cancelled_count": len(cancelled_ids), "cancelled_ids": cancelled_ids}

    def get_task_by_video_id(self, video_task_id: str) -> Optional[Task]:
        """根据外部视频平台返回的 taskId 查找内部 Task（用于回调场景）。"""
        for t in self._tasks.values():
            if t.result and str(t.result.get("task_id")) == video_task_id:
                return t
            # 轮询中的任务 result 为 None，检查 params 中的暂存
            if t.params and str(t.params.get("_video_task_id")) == video_task_id:
                return t
        return None

    async def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        # 记录取消前的状态：RUNNING 任务由 _execute_task 负责通知，
        # 避免双重通知导致重复退款
        was_running = task.status == TaskStatus.RUNNING
        task.status = TaskStatus.CANCELLED
        task.cancel_event.set()
        if not was_running:
            await self._notify(task)
        return True

    async def _execute_task(self, task: Task):
        retry_pending = False
        async with self._semaphore:
            if task.status == TaskStatus.CANCELLED:
                return

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            task.progress = 0
            task.error = None
            await self._notify(task)

            try:
                result = await asyncio.wait_for(self._worker_fn(task), timeout=3600)
            except asyncio.TimeoutError:
                exc_msg = "任务执行超时（超过 3600 秒）"
                result = None
            except Exception as e:
                exc_msg = str(e)
                result = None
            else:
                exc_msg = None

            if exc_msg is not None:
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = TaskStatus.RETRYING
                    task.error = exc_msg
                    await self._notify(task)
                    retry_pending = True
                else:
                    task.status = TaskStatus.FAILED
                    task.error = exc_msg
                    task.completed_at = datetime.utcnow()
                    await self._notify(task)
            elif task.status == TaskStatus.CANCELLED:
                # 执行期间被取消，保持 CANCELLED，不覆盖为 SUCCESS
                await self._notify(task)
            else:
                task.status = TaskStatus.SUCCESS
                task.progress = 100
                task.result = result
                task.completed_at = datetime.utcnow()
                await self._notify(task)

        # 重试的 sleep 移到 semaphore 外部，释放并发槽位后再重新排队
        if retry_pending:
            await asyncio.sleep(2 * task.retry_count)
            await self._queue.put(task)

    async def _worker_loop(self):
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if task.status != TaskStatus.CANCELLED:
                    await self._execute_task(task)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

    async def start(self):
        if self._running:
            return
        self._running = True
        for _ in range(self.max_concurrent):
            worker = asyncio.create_task(self._worker_loop())
            self._workers.append(worker)

    async def stop(self):
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    @staticmethod
    def new_task_id() -> str:
        return str(uuid.uuid4())


task_manager = TaskManager(max_concurrent=3)

# #17: 全局递增计数器，用作 PriorityQueue 的 tiebreaker
_task_seq = 0
