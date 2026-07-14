import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime

from app.core.database import Base, GUID


class RechargeTier(Base):
    """人民币充值档位：1 元 = 100 积分。"""
    __tablename__ = "recharge_tiers"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    yuan = Column(Float, nullable=False)
    credits = Column(Integer, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
