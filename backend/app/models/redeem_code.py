import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base, GUID


class RedeemCode(Base):
    """积分兑换码：线下/人工发卡充值使用。"""
    __tablename__ = "redeem_codes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    code = Column(String(32), unique=True, nullable=False, index=True)
    points = Column(Integer, nullable=False)
    batch_id = Column(String(64), nullable=True, index=True)
    note = Column(String(500), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    used_by_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    used_by = relationship("User", backref="redeemed_codes")
