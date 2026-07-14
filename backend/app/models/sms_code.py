import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Boolean, Index

from app.core.database import Base
from app.core.database import GUID


class SmsCode(Base):
    __tablename__ = "sms_codes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    phone = Column(String(32), nullable=False, index=True)
    code = Column(String(8), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_sms_codes_phone_created_at", "phone", "created_at"),
    )
