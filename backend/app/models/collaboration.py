"""
P10: 多人协作功能基础 - 画布共享与权限模型。
"""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint
from app.core.database import Base, GUID


class CollaboratorRole(str, Enum):
    """协作者角色。"""
    OWNER = "owner"        # 所有者（创建者）
    EDITOR = "editor"      # 编辑者（可修改画布内容）
    VIEWER = "viewer"      # 只读查看者
    COMMENTER = "commenter"  # 评论者（可查看+评论，不可编辑）


class CanvasCollaborator(Base):
    """画布协作者关系。"""
    __tablename__ = "canvas_collaborators"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    canvas_id = Column(GUID(), ForeignKey("canvases.id"), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    username = Column(String(255), nullable=True)
    role = Column(SAEnum(CollaboratorRole), nullable=False, default=CollaboratorRole.VIEWER)
    invited_by = Column(String(255), nullable=True)
    invite_status = Column(String(50), default="pending")  # pending | accepted | rejected
    permissions = Column(JSON, nullable=True, default=dict)  # 细粒度权限覆盖
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("canvas_id", "user_id", name="uq_canvas_user"),
    )


class CollaborationEvent(Base):
    """协作事件日志（审计+实时同步）。"""
    __tablename__ = "collaboration_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    canvas_id = Column(GUID(), nullable=False, index=True)
    user_id = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    event_type = Column(String(50), nullable=False)  # join | leave | edit_node | add_node | delete_node | comment
    event_data = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
