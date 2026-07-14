import logging
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import engine
from app.models.credit import CreditLedger
from app.models.model_config import ModelConfig
from app.models.redeem_code import RedeemCode
from app.models.user import User

logger = logging.getLogger(__name__)


def _is_sqlite() -> bool:
    return "sqlite" in str(engine.url).lower()


if _is_sqlite():
    logger.warning(
        "[credit] 检测到 SQLite，with_for_update() 行锁将被静默忽略，"
        "高并发场景下可能出现超额扣费，生产环境请使用 PostgreSQL"
    )


class InsufficientCreditsError(Exception):
    """积分不足异常。"""

    def __init__(self, required: int, balance: int):
        self.required = required
        self.balance = balance
        super().__init__(f"积分不足：需要 {required}，当前余额 {balance}")


# 基础定价表（单位：积分）
# 后续可从后台配置读取，目前硬编码为最小可用版本
BASE_PRICING = {
    "generate_image": {
        "base": 10,
        "model_multiplier": {
            "gpt-image-2": 1.0,
            "gemini-3.1-flash-lite-image": 1.0,
            "doubao-seedream-5-0-pro-260628": 1.0,
            "dall-e-3": 1.0,
            "default": 1.0,
        },
        "resolution_multiplier": {
            "1024x1024": 1.0,
            "1024x1536": 1.2,
            "1536x1024": 1.2,
            "1k": 1.0,
            "2k": 1.5,
            "4k": 2.0,
            "default": 1.0,
        },
    },
    "generate_video": {
        "base": 50,
        "duration_factor": 10,  # 每秒 10 积分，与 base 取较大值
        "model_multiplier": {
            "seedance": 1.0,
            "wanxiang": 1.0,
            "default": 1.0,
        },
    },
    "generate_audio": {
        "base": 5,
    },
    "generate_script": {
        "base": 0,  # 剧本策划不扣费
    },
}


def _quantize(value: float) -> int:
    """四舍五入到整数积分。"""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_model_credit_config(db: Session, model_id: str, model_type: str) -> Optional[ModelConfig]:
    """查询数据库中的模型积分配置。"""
    if not model_id:
        return None
    try:
        return (
            db.query(ModelConfig)
            .filter(
                ModelConfig.model_id.ilike(model_id.strip()),
                ModelConfig.type == model_type,
                ModelConfig.enabled == True,
            )
            .first()
        )
    except Exception:
        return None


def _get_video_tier_cost(cfg: ModelConfig, duration: float) -> Optional[int]:
    """根据视频时长匹配三档定价（5s/10s/15s）。

    匹配规则：向上取最近的档位（duration <= 5s 用 5s 档，<= 10s 用 10s 档，<= 15s 用 15s 档）。
    如果对应档位积分为 0（未设置），返回 None，由调用方回退到按秒计费。
    """
    if duration <= 5:
        return cfg.credits_5s if cfg.credits_5s and cfg.credits_5s > 0 else None
    if duration <= 10:
        return cfg.credits_10s if cfg.credits_10s and cfg.credits_10s > 0 else None
    if duration <= 15:
        return cfg.credits_15s if cfg.credits_15s and cfg.credits_15s > 0 else None
    # 超过 15s：回退到按秒计费
    return None


def calculate_cost(task_type: str, node_config: Optional[dict] = None, db: Session = None) -> int:
    """根据任务类型和节点配置计算所需积分。

    优先级（视频模型）：
    1. 三档定价（credits_5s / credits_10s / credits_15s）—— 管理员按 5/10/15 秒固定档位设置
    2. 按秒计费（credits 字段）—— 向后兼容
    3. BASE_PRICING 兜底

    图片模型：credits 字段 = 每张积分。
    """
    node_config = node_config or {}
    model = (node_config.get("model") or "default").strip().lower()

    # 优先读取数据库中的模型定价
    model_type = "image" if task_type == "generate_image" else "video" if task_type == "generate_video" else None
    if db and model_type and model and model != "default":
        cfg = get_model_credit_config(db, model, model_type)
        if cfg:
            if task_type == "generate_image":
                if cfg.credits > 0:
                    return cfg.credits
            elif task_type == "generate_video":
                duration = node_config.get("duration") or node_config.get("durationSec") or node_config.get("duration_seconds") or 5
                try:
                    duration = float(duration)
                except (TypeError, ValueError):
                    duration = 5
                duration = max(1, duration)

                # 优先使用三档定价（即使 credits=0 也可以用三档）
                tier_cost = _get_video_tier_cost(cfg, duration)
                if tier_cost is not None:
                    return tier_cost

                # 回退到按秒计费
                if cfg.credits > 0:
                    return _quantize(duration * cfg.credits)

    pricing = BASE_PRICING.get(task_type)
    if not pricing:
        return 0

    base = pricing.get("base", 0)

    if task_type == "generate_image":
        resolution = node_config.get("resolution") or "default"
        multiplier = pricing["model_multiplier"].get(model, pricing["model_multiplier"]["default"])
        res_multiplier = pricing["resolution_multiplier"].get(resolution, pricing["resolution_multiplier"]["default"])
        return _quantize(base * multiplier * res_multiplier)

    if task_type == "generate_video":
        duration = node_config.get("duration") or node_config.get("durationSec") or node_config.get("duration_seconds") or 5
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 5
        multiplier = pricing["model_multiplier"].get(model, pricing["model_multiplier"]["default"])
        duration_cost = max(base, duration * pricing["duration_factor"])
        return _quantize(duration_cost * multiplier)

    return _quantize(base)


def has_refund_record(db: Session, user_id: UUID, ref_id: str, reason: str) -> bool:
    """检查是否已存在相同 ref_id 和 reason 的退款记录（幂等保障）。

    在执行退款前调用此函数，避免因回调重试或双重通知导致重复退款。
    """
    try:
        return db.query(CreditLedger).filter(
            CreditLedger.user_id == user_id,
            CreditLedger.ref_id == ref_id,
            CreditLedger.reason == reason,
            CreditLedger.amount > 0,
        ).first() is not None
    except Exception:
        logger.warning("[credit] 查询退款记录失败，跳过幂等检查 user=%s ref=%s", user_id, ref_id)
        return False


def get_balance(db: Session, user_id: UUID) -> int:
    """查询用户当前积分余额。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return 0
    return user.credits or 0


def add_credits(
    db: Session,
    user_id: UUID,
    amount: int,
    reason: str,
    ref_id: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    """给用户增加积分并记录流水。

    适用于充值、赠送、退款、管理员调整等场景。
    """
    if amount <= 0:
        raise ValueError("增加积分必须为正数")

    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        raise ValueError("用户不存在")

    previous_balance = user.credits or 0
    new_balance = previous_balance + amount
    user.credits = new_balance

    ledger = CreditLedger(
        user_id=user_id,
        amount=amount,
        balance_after=new_balance,
        reason=reason,
        ref_id=ref_id,
        description=description,
        created_at=datetime.utcnow(),
    )
    db.add(ledger)
    db.flush()

    logger.info(
        "[credit] add user=%s amount=+%s balance=%s reason=%s ref=%s",
        user_id, amount, new_balance, reason, ref_id,
    )
    return new_balance


def deduct_credits(
    db: Session,
    user_id: UUID,
    amount: int,
    reason: str,
    ref_id: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    """扣减用户积分并记录流水。

    若余额不足抛出 InsufficientCreditsError。
    """
    if amount <= 0:
        raise ValueError("扣减积分必须为正数")

    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        raise ValueError("用户不存在")

    balance = user.credits or 0
    if balance < amount:
        raise InsufficientCreditsError(required=amount, balance=balance)

    new_balance = balance - amount
    user.credits = new_balance

    ledger = CreditLedger(
        user_id=user_id,
        amount=-amount,
        balance_after=new_balance,
        reason=reason,
        ref_id=ref_id,
        description=description,
        created_at=datetime.utcnow(),
    )
    db.add(ledger)
    db.flush()

    logger.info(
        "[credit] deduct user=%s amount=-%s balance=%s reason=%s ref=%s",
        user_id, amount, new_balance, reason, ref_id,
    )
    return new_balance


def refund_credits(
    db: Session,
    user_id: UUID,
    amount: int,
    reason: str,
    ref_id: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    """退还积分并记录流水（任务失败/取消等场景）。"""
    if amount <= 0:
        logger.warning(
            "[credit] refund 跳过：amount=%s user=%s ref=%s reason=%s（非正数）",
            amount, user_id, ref_id, reason,
        )
        return get_balance(db, user_id)
    return add_credits(
        db=db,
        user_id=user_id,
        amount=amount,
        reason=reason,
        ref_id=ref_id,
        description=description or "积分退还",
    )


def adjust_credits_by_admin(
    db: Session,
    user_id: UUID,
    delta: int,
    admin_id: UUID,
    note: Optional[str] = None,
) -> int:
    """管理员手动调整积分（正数增加，负数扣减）。"""
    if delta == 0:
        raise ValueError("调整量不能为 0")

    if delta > 0:
        return add_credits(
            db=db,
            user_id=user_id,
            amount=delta,
            reason="admin_adjust",
            ref_id=str(admin_id),
            description=note or "管理员手动增加积分",
        )
    else:
        amount = abs(delta)
        return deduct_credits(
            db=db,
            user_id=user_id,
            amount=amount,
            reason="admin_adjust",
            ref_id=str(admin_id),
            description=note or "管理员手动扣减积分",
        )


def get_ledger(
    db: Session,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> List[CreditLedger]:
    """查询用户积分流水。"""
    return (
        db.query(CreditLedger)
        .filter(CreditLedger.user_id == user_id)
        .order_by(CreditLedger.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_ledger(db: Session, user_id: UUID) -> int:
    """统计用户积分流水总数。"""
    return db.query(CreditLedger).filter(CreditLedger.user_id == user_id).count()


def _normalize_redeem_code(raw: str) -> str:
    """归一化兑换码：去空格、转大写、只保留字母数字。"""
    return re.sub(r"[^A-Z0-9]", "", str(raw or "").strip().upper())


def redeem_code(db: Session, user_id: UUID, raw_code: str) -> dict:
    """用户兑换积分码。

    返回 {"points": int, "balance_after": int}
    """
    normalized = _normalize_redeem_code(raw_code)
    if len(normalized) < 8:
        raise ValueError("兑换码格式不正确")

    code_row = db.query(RedeemCode).filter(RedeemCode.code == normalized).first()
    if not code_row:
        raise ValueError("兑换码无效")
    if code_row.used_at:
        raise ValueError("兑换码已使用")
    if code_row.expires_at and code_row.expires_at < datetime.utcnow():
        raise ValueError("兑换码已过期")

    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        raise ValueError("用户不存在")

    new_balance = (user.credits or 0) + code_row.points
    user.credits = new_balance

    code_row.used_at = datetime.utcnow()
    code_row.used_by_id = user_id

    ledger = CreditLedger(
        user_id=user_id,
        amount=code_row.points,
        balance_after=new_balance,
        reason="redeem",
        ref_id=str(code_row.id),
        description=f"兑换码充值 batch={code_row.batch_id}",
        created_at=datetime.utcnow(),
    )
    db.add(ledger)
    db.flush()

    logger.info(
        "[credit] redeem user=%s code=%s points=+%s balance=%s",
        user_id, normalized, code_row.points, new_balance,
    )
    return {"points": code_row.points, "balance_after": new_balance}


def fulfill_recharge_order(
    db: Session,
    out_trade_no: str,
    channel: str,
    trade_no: Optional[str],
) -> dict:
    """支付异步通知/查询成功后，给订单入账并增加用户积分。

    幂等处理：同一 out_trade_no 仅首次入账。
    返回 {"ok": bool, "already": bool, "credits": int, "balance_after": int}
    """
    from app.models.recharge_order import RechargeOrder

    order = db.query(RechargeOrder).filter(
        RechargeOrder.out_trade_no == out_trade_no,
        RechargeOrder.channel == channel,
    ).with_for_update().first()

    if not order:
        return {"ok": False, "reason": "order_not_found"}
    if order.status == "paid":
        return {"ok": True, "already": True}
    if order.status != "pending":
        return {"ok": False, "reason": "bad_status"}

    order.status = "paid"
    order.trade_no = trade_no or order.trade_no
    order.paid_at = datetime.utcnow()

    new_balance = add_credits(
        db=db,
        user_id=order.user_id,
        amount=order.credits,
        reason=f"{channel}_recharge",
        ref_id=str(order.id),
        description=f"{channel} 充值 ¥{order.amount_yuan}",
    )

    logger.info(
        "[credit] recharge user=%s channel=%s out_trade_no=%s credits=+%s balance=%s",
        order.user_id, channel, out_trade_no, order.credits, new_balance,
    )
    return {"ok": True, "credits": order.credits, "balance_after": new_balance}
