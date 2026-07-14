import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Text

from app.core.database import Base, GUID


class Announcement(Base):
    """系统公告：支持 Markdown、置顶、类型、启用/禁用。"""
    __tablename__ = "announcements"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(32), default="info", nullable=False)  # info / success / warning / danger
    pinned = Column(Boolean, default=False, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
