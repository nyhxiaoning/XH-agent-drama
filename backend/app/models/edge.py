import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base, GUID


class EdgeType(str, enum.Enum):
    DEFAULT = "default"
    SEQUENCE = "sequence"
    REFERENCE = "reference"
    ASSOCIATION = "association"


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (UniqueConstraint("source_node_id", "target_node_id", "edge_type", name="uq_edge_src_tgt_type"),)

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    canvas_id = Column(GUID(), ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(GUID(), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(GUID(), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(SAEnum(EdgeType), nullable=False, default=EdgeType.DEFAULT)
    label = Column(String(255), nullable=True)
    config = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc), nullable=False)

    canvas = relationship("Canvas", back_populates="edges")
    source_node = relationship("Node", foreign_keys=[source_node_id], back_populates="source_edges")
    target_node = relationship("Node", foreign_keys=[target_node_id], back_populates="target_edges")
