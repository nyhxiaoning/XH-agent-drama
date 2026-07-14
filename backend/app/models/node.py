import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Integer, Text, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base, GUID


class NodeType(str, enum.Enum):
    CHARACTER = "character"
    SCENE = "scene"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    GROUP = "group"


class NodeStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Node(Base):
    __tablename__ = "nodes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    canvas_id = Column(GUID(), ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True)
    node_type = Column(SAEnum(NodeType), nullable=False, default=NodeType.SCRIPT)
    title = Column(String(255), nullable=True, default="")
    x = Column(Float, nullable=False, default=0.0)
    y = Column(Float, nullable=False, default=0.0)
    width = Column(Float, nullable=True, default=240.0)
    height = Column(Float, nullable=True, default=160.0)
    status = Column(SAEnum(NodeStatus), nullable=False, default=NodeStatus.PENDING)
    progress = Column(Integer, nullable=False, default=0)
    prompt = Column(Text, nullable=True)
    style = Column(String(100), nullable=True)
    result_url = Column(String(512), nullable=True)
    thumbnail_url = Column(String(512), nullable=True)
    error_msg = Column(Text, nullable=True)
    config = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc), nullable=False)

    canvas = relationship("Canvas", back_populates="nodes")
    source_edges = relationship("Edge", foreign_keys="Edge.source_node_id", back_populates="source_node", cascade="all, delete-orphan")
    target_edges = relationship("Edge", foreign_keys="Edge.target_node_id", back_populates="target_node", cascade="all, delete-orphan")
