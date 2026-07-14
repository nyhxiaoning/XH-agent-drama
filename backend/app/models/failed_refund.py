import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from app.core.database import Base, GUID


class FailedRefund(Base):
    __tablename__ = "failed_refunds"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    reason = Column(String(64), nullable=False)
    ref_id = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc), nullable=False)
