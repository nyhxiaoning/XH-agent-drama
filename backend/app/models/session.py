import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON
from app.core.database import Base, GUID


class AgentSession(Base):
    """AI 创作会话持久化表。"""
    __tablename__ = "agent_sessions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="planning")
    prompt = Column(Text, nullable=True)
    mode = Column(String(16), nullable=True, default="inspiration")
    lock_version = Column(String(64), nullable=True, index=True)
    data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
