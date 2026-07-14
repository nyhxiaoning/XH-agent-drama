from typing import Optional
from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    tier_id: str = Field(..., min_length=1)


class CreateOrderResponse(BaseModel):
    order_id: str
    out_trade_no: str
    channel: str
    amount_yuan: float
    credits: int
    pay_url: Optional[str] = None  # 支付宝跳转 URL
    pay_code_url: Optional[str] = None  # 微信支付二维码内容


class AlipayNotifyForm(BaseModel):
    # 支付宝异步通知标准字段
    out_trade_no: str
    trade_no: str
    trade_status: str
    total_amount: str


class OrderStatusResponse(BaseModel):
    order_id: str
    status: str  # pending / paid / closed
    amount_yuan: float
    credits: int
    paid_at: Optional[str]
