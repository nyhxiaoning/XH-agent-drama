import logging
import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recharge_order import RechargeOrder
from app.models.recharge_tier import RechargeTier
from app.services import credit_service

logger = logging.getLogger(__name__)


# 尝试导入支付宝 SDK；未安装时降级为不可用
try:
    from alipay import AliPay
    ALIPAY_AVAILABLE = True
except Exception:
    AliPay = None
    ALIPAY_AVAILABLE = False


# 尝试导入微信支付 V3 SDK
try:
    import wechatpayv3
    WECHAT_AVAILABLE = True
except Exception:
    wechatpayv3 = None
    WECHAT_AVAILABLE = False


def _has_real_alipay_config() -> bool:
    keys = [settings.ALIPAY_APP_ID, settings.ALIPAY_PRIVATE_KEY, settings.ALIPAY_PUBLIC_KEY]
    return all(keys) and all("YOUR_" not in (k or "") for k in keys)


def _normalize_pem_key(raw: str, kind: str) -> str:
    """把 .env 里可能是一行的裸 base64 密钥补成 PEM 格式。

    python-alipay-sdk 要求密钥必须带 BEGIN/END 头尾；
    如果 .env 里已经是完整 PEM，则原样返回。
    """
    if not raw:
        return raw
    raw = raw.strip()
    if "-----BEGIN" in raw:
        return raw

    body = "".join(raw.split())
    if not body:
        return raw

    def _chunk(s: str, size: int = 64) -> str:
        return "\n".join(s[i : i + size] for i in range(0, len(s), size))

    if kind == "private":
        return f"-----BEGIN RSA PRIVATE KEY-----\n{_chunk(body)}\n-----END RSA PRIVATE KEY-----"
    if kind == "public":
        return f"-----BEGIN PUBLIC KEY-----\n{_chunk(body)}\n-----END PUBLIC KEY-----"
    return raw


def _has_real_wechat_config() -> bool:
    keys = [settings.WECHAT_MCH_ID, settings.WECHAT_API_V3_KEY, settings.WECHAT_CERT_SERIAL_NO, settings.WECHAT_PRIVATE_KEY]
    return all(keys) and all("YOUR_" not in (k or "") for k in keys)


def create_order(db: Session, user_id: UUID, tier_id: str, channel: str) -> RechargeOrder:
    """创建充值订单（未支付）。"""
    try:
        tier_uuid = UUID(tier_id)
    except ValueError:
        raise ValueError("充值档位 ID 格式错误")

    tier = db.query(RechargeTier).filter(
        RechargeTier.id == tier_uuid,
        RechargeTier.enabled == True,
    ).first()
    if not tier:
        raise ValueError("充值档位不存在或已禁用")

    out_trade_no = f"RC{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
    order = RechargeOrder(
        user_id=user_id,
        channel=channel,
        out_trade_no=out_trade_no,
        amount_yuan=tier.yuan,
        credits=tier.credits,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_alipay_client():
    if not ALIPAY_AVAILABLE or not _has_real_alipay_config():
        return None
    return AliPay(
        appid=settings.ALIPAY_APP_ID,
        app_notify_url=_auto_notify_url(),
        app_private_key_string=_normalize_pem_key(settings.ALIPAY_PRIVATE_KEY, "private"),
        alipay_public_key_string=_normalize_pem_key(settings.ALIPAY_PUBLIC_KEY, "public"),
        sign_type="RSA2",
        debug=settings.ALIPAY_DEBUG,
    )


def _auto_notify_url() -> str:
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if base and not settings.ALIPAY_NOTIFY_URL:
        return f"{base}/api/v1/payments/alipay/notify"
    return settings.ALIPAY_NOTIFY_URL

def _auto_return_url() -> str:
    if settings.ALIPAY_RETURN_URL:
        return settings.ALIPAY_RETURN_URL
    return None

def alipay_page_pay(order: RechargeOrder) -> str:
    """生成支付宝电脑网站支付跳转 URL。"""
    client = get_alipay_client()
    if not client:
        raise RuntimeError("支付宝支付未配置")
    signed_string = client.api_alipay_trade_page_pay(
        subject=f"充值 {order.credits} 积分",
        out_trade_no=order.out_trade_no,
        total_amount=str(order.amount_yuan),
        return_url=_auto_return_url(),
        notify_url=_auto_notify_url(),
    )
    return f"{client._gateway}?{signed_string}"


def verify_alipay_notify(data: dict) -> bool:
    client = get_alipay_client()
    if not client:
        return False
    return client.verify(data, data.pop("sign", ""))


def get_wechat_client():
    if not WECHAT_AVAILABLE or not _has_real_wechat_config():
        return None
    return wechatpayv3.WeChatPay(
        wechatpay_type=wechatpayv3.WeChatPayType.NATIVE,
        mchid=settings.WECHAT_MCH_ID,
        private_key=settings.WECHAT_PRIVATE_KEY,
        cert_serial_no=settings.WECHAT_CERT_SERIAL_NO,
        apiv3_key=settings.WECHAT_API_V3_KEY,
        appid=settings.WECHAT_APP_ID or "",
        notify_url=settings.WECHAT_NOTIFY_URL,
    )


def wechat_native_pay(order: RechargeOrder) -> str:
    """生成微信支付 Native 二维码内容（code_url）。"""
    client = get_wechat_client()
    if not client:
        raise RuntimeError("微信支付未配置")
    amount_cents = int(order.amount_yuan * 100)
    code, message = client.pay(
        description=f"充值 {order.credits} 积分",
        out_trade_no=order.out_trade_no,
        amount={"total": amount_cents},
    )
    if code != 200:
        raise RuntimeError(f"微信支付下单失败：{message}")
    # wechatpayv3 返回 dict 时取 code_url
    if isinstance(message, dict):
        return message.get("code_url", "")
    return ""


def query_order_status(db: Session, out_trade_no: str) -> Optional[RechargeOrder]:
    order = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == out_trade_no).first()
    if not order:
        return None

    if order.status == "pending":
        # 主动查询上游
        try:
            if order.channel == "alipay" and ALIPAY_AVAILABLE and _has_real_alipay_config():
                client = get_alipay_client()
                if client:
                    resp = client.api_alipay_trade_query(out_trade_no=out_trade_no)
                    if resp.get("trade_status") == "TRADE_SUCCESS":
                        credit_service.fulfill_recharge_order(
                            db=db,
                            out_trade_no=out_trade_no,
                            channel="alipay",
                            trade_no=resp.get("trade_no"),
                        )
                        db.commit()
            elif order.channel == "wechat" and WECHAT_AVAILABLE and _has_real_wechat_config():
                client = get_wechat_client()
                if client:
                    code, message = client.query(out_trade_no=out_trade_no)
                    if code == 200 and isinstance(message, dict) and message.get("trade_state") == "SUCCESS":
                        credit_service.fulfill_recharge_order(
                            db=db,
                            out_trade_no=out_trade_no,
                            channel="wechat",
                            trade_no=message.get("transaction_id"),
                        )
                        db.commit()
        except Exception:
            logger.exception("[payment] 主动查询订单失败 %s", out_trade_no)
            db.rollback()

    return order


def fulfill_order_from_notify(db: Session, out_trade_no: str, channel: str, trade_no: str) -> dict:
    return credit_service.fulfill_recharge_order(
        db=db,
        out_trade_no=out_trade_no,
        channel=channel,
        trade_no=trade_no,
    )
