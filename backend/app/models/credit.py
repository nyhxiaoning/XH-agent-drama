import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship, backref

from app.core.database import Base, GUID


class CreditLedger(Base):
    """积分流水记录。"""
    __tablename__ = "credit_ledger"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # 正数：充值/赠送；负数：消费
    balance_after = Column(Integer, nullable=False)
    reason = Column(String(64), nullable=False)  # generate_image / generate_video / recharge / refund / admin_adjust
    ref_id = Column(String(64), nullable=True, index=True)  # 关联节点 ID / 订单号
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", backref=backref("credit_ledgers", passive_deletes=True))
