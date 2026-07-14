"""任务记录模型：将内存中的 Task 状态持久化到数据库。

服务重启后可通过数据库恢复任务状态，避免"任务消失"问题。
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON
from app.core.database import Base, GUID


class TaskRecord(Base):
    __tablename__ = "task_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String(36), nullable=False, index=True)
    canvas_id = Column(String(36), nullable=False, index=True)
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    progress = Column(Integer, default=0)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)
    user_id = Column(String(36), nullable=True, index=True)
    cost = Column(Integer, default=0)
    params = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
