"""
技能对话历史持久化模型。
每个用户对每个技能的每次对话都会创建一条 SkillConversation 记录，
对话中的每条消息（用户输入 + AI 回复）存储为 SkillMessage。
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, JSON, Integer, ForeignKey
from app.core.database import Base, GUID


class SkillConversation(Base):
    """技能对话会话。"""
    __tablename__ = "skill_conversations"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    skill_id = Column(String(128), nullable=False, index=True)
    skill_title = Column(String(255), nullable=True)
    title = Column(String(512), nullable=True)  # 对话标题（取首条用户消息前40字）
    params = Column(JSON, nullable=True, default=dict)  # 该对话使用的技能参数快照
    message_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SkillMessage(Base):
    """技能对话中的单条消息。"""
    __tablename__ = "skill_messages"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(GUID(), ForeignKey("skill_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)  # user | assistant | error
    content = Column(Text, nullable=False)
    raw_data = Column(JSON, nullable=True)  # AI回复的原始结构化数据
    params_used = Column(JSON, nullable=True)  # 该次执行使用的参数快照
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
