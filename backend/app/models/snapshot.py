import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON
from app.core.database import Base, GUID


class CanvasSnapshot(Base):
    __tablename__ = "canvas_snapshots"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    canvas_id = Column(GUID(), ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=True, default="")
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
