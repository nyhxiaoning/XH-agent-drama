from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.core.tasks import TaskStatus


class TaskInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_id: str
    canvas_id: str
    task_type: str
    params: Dict[str, Any] = {}
    status: TaskStatus
    progress: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    # #17: 优先级信息
    priority: int = 0


class TaskList(BaseModel):
    tasks: List[TaskInDB]
