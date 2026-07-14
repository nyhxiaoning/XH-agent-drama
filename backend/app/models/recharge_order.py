import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship, backref

from app.core.database import Base, GUID


class RechargeOrder(Base):
    """充值订单：统一支付宝/微信支付订单。"""
    __tablename__ = "recharge_orders"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(32), nullable=False, index=True)  # alipay / wechat
    out_trade_no = Column(String(128), unique=True, nullable=False, index=True)
    amount_yuan = Column(Float, nullable=False)
    credits = Column(Integer, nullable=False)
    status = Column(String(32), default="pending", nullable=False, index=True)  # pending / paid / closed
    trade_no = Column(String(128), nullable=True)  # 支付宝 trade_no / 微信 transaction_id
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", backref=backref("recharge_orders", passive_deletes=True))
