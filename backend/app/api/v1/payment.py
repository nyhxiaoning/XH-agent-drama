import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.payment import (
    CreateOrderRequest,
    CreateOrderResponse,
    OrderStatusResponse,
)
from app.services import payment_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/orders/{channel}", response_model=CreateOrderResponse)
def create_payment_order(
    channel: str,
    payload: CreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """创建支付订单。channel 可选 alipay / wechat。"""
    if channel not in ("alipay", "wechat"):
        raise HTTPException(status_code=400, detail="不支持的支付渠道")

    try:
        order = payment_service.create_order(db, current_user.id, payload.tier_id, channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    resp = CreateOrderResponse(
        order_id=str(order.id),
        out_trade_no=order.out_trade_no,
        channel=channel,
        amount_yuan=order.amount_yuan,
        credits=order.credits,
    )

    try:
        if channel == "alipay":
            resp.pay_url = payment_service.alipay_page_pay(order)
        else:
            resp.pay_code_url = payment_service.wechat_native_pay(order)
    except RuntimeError as exc:
        # 支付 SDK 未配置时允许返回订单，前端提示"联系管理员充值"
        logger.warning("[payment] %s 支付不可用：%s", channel, exc)

    return resp


@router.get("/orders/{out_trade_no}/status", response_model=OrderStatusResponse)
def order_status(
    out_trade_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    order = payment_service.query_order_status(db, out_trade_no)
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return OrderStatusResponse(
        order_id=str(order.id),
        status=order.status,
        amount_yuan=order.amount_yuan,
        credits=order.credits,
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
    )


@router.post("/alipay/notify", response_class=PlainTextResponse)
async def alipay_notify(request: Request, db: Session = Depends(get_db)):
    """支付宝异步通知。"""
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = {}

    sign = data.get("sign", "")
    if not payment_service.verify_alipay_notify(data.copy()):
        logger.warning("[payment] 支付宝通知验签失败: %s", data)
        return PlainTextResponse("fail")

    out_trade_no = data.get("out_trade_no")
    trade_no = data.get("trade_no")
    trade_status = data.get("trade_status")
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return PlainTextResponse("success")

    result = payment_service.fulfill_order_from_notify(db, out_trade_no, "alipay", trade_no)
    db.commit()
    if result.get("ok"):
        return PlainTextResponse("success")
    return PlainTextResponse("fail")


@router.post("/wechat/notify")
async def wechat_notify(request: Request, db: Session = Depends(get_db)):
    """微信支付异步通知。使用 wechatpayv3 SDK 验签并解密。"""
    body_bytes = b""
    try:
        body_bytes = await request.body()
    except Exception:
        pass
    body_text = body_bytes.decode("utf-8", errors="ignore")
    logger.info("[payment] 微信通知 body: %s", body_text[:500])

    client = payment_service.get_wechat_client()
    if not client:
        logger.warning("[payment] 微信支付未配置，无法处理通知")
        return {"code": "FAIL", "message": "微信支付未配置"}

    headers = {
        "Wechatpay-Signature": request.headers.get("Wechatpay-Signature", ""),
        "Wechatpay-Timestamp": request.headers.get("Wechatpay-Timestamp", ""),
        "Wechatpay-Nonce": request.headers.get("Wechatpay-Nonce", ""),
        "Wechatpay-Serial": request.headers.get("Wechatpay-Serial", ""),
    }

    try:
        result = client.callback(headers, body_text)
    except Exception as exc:
        logger.warning("[payment] 微信通知验签/解密失败: %s", exc)
        return {"code": "FAIL", "message": "验签失败"}

    if result.get("trade_state") != "SUCCESS":
        return {"code": "SUCCESS", "message": "非成功状态"}

    payment_service.fulfill_order_from_notify(
        db,
        result.get("out_trade_no"),
        "wechat",
        result.get("transaction_id"),
    )
    db.commit()
    return {"code": "SUCCESS", "message": "ok"}
