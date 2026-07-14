import json
import logging
import random
import string
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_admin, get_current_active_user
from app.core.database import get_db
from app.models.announcement import Announcement
from app.models.credit import CreditLedger
from app.models.model_config import ModelConfig
from app.models.node import Node, NodeStatus
from app.models.recharge_order import RechargeOrder
from app.models.recharge_tier import RechargeTier
from app.models.redeem_code import RedeemCode
from app.models.user import User
from app.schemas.admin import (
    AdminAnnouncementCreate,
    AdminAnnouncementList,
    AdminAnnouncementOut,
    AdminAnnouncementUpdate,
    AdminModelConfigCreate,
    AdminModelConfigOut,
    AdminModelConfigUpdate,
    AdminRedeemCodeList,
    AdminRedeemCodeOut,
    AdminRedeemCreate,
    AdminRechargeTierCreate,
    AdminRechargeTierOut,
    AdminStatsOut,
    AdminUserGenerationRecord,
    AdminUserList,
    AdminUserOut,
    AdminUserUpdate,
)
from app.services import auth_service, credit_service
from app.services.credit_service import InsufficientCreditsError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _audit_log(admin: User, action: str, details: dict):
    logger.info(
        json.dumps(
            {"level": "audit", "admin": admin.email or admin.phone or str(admin.id), "action": action, **details},
            ensure_ascii=False,
            default=str,
        )
    )


def _generate_code(length: int = 16) -> str:
    """生成大写字母+数字的随机兑换码，每 4 位一组。"""
    chars = string.ascii_uppercase + string.digits
    raw = "".join(random.choice(chars) for _ in range(length))
    return "-".join([raw[i:i + 4] for i in range(0, length, 4)])


# ------------------------------------------------------------------
# 统计
# ------------------------------------------------------------------
@router.get("/stats", response_model=AdminStatsOut)
def admin_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())

    total_users = db.query(User).count()
    today_active_users = db.query(User).filter(User.last_login_at >= today_start).count()
    week_active_users = db.query(User).filter(User.last_login_at >= week_start).count()

    total_images = db.query(Node).filter(Node.node_type.in_(["image", "character", "scene", "storyboard"])).count()
    total_videos = db.query(Node).filter(Node.node_type == "video").count()
    total_scripts = db.query(Node).filter(Node.node_type == "script").count()

    total_recharged_yuan = db.query(func.sum(RechargeOrder.amount_yuan)).filter(
        RechargeOrder.status == "paid"
    ).scalar() or 0
    today_recharged_yuan = db.query(func.sum(RechargeOrder.amount_yuan)).filter(
        RechargeOrder.status == "paid",
        RechargeOrder.paid_at >= today_start,
    ).scalar() or 0
    week_recharged_yuan = db.query(func.sum(RechargeOrder.amount_yuan)).filter(
        RechargeOrder.status == "paid",
        RechargeOrder.paid_at >= week_start,
    ).scalar() or 0

    # 模型排行：按节点 config.model 简单分组（仅统计生成成功的节点）
    model_counts = {}
    for node in db.query(Node).filter(
        Node.config.isnot(None),
        Node.status == NodeStatus.SUCCESS,
    ).all():
        cfg = node.config or {}
        model = cfg.get("model") or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1
    model_ranking = sorted(
        [{"model": k, "count": v} for k, v in model_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    _audit_log(admin, "admin_view_stats", {})
    return AdminStatsOut(
        total_users=total_users,
        today_active_users=today_active_users,
        week_active_users=week_active_users,
        total_images=total_images,
        total_videos=total_videos,
        total_scripts=total_scripts,
        total_recharged_yuan=round(float(total_recharged_yuan), 2),
        today_recharged_yuan=round(float(today_recharged_yuan), 2),
        week_recharged_yuan=round(float(week_recharged_yuan), 2),
        model_ranking=model_ranking,
    )


# ------------------------------------------------------------------
# 用户管理
# ------------------------------------------------------------------
@router.get("/users", response_model=AdminUserList)
def list_users(
    q: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (User.name.ilike(like)) | (User.email.ilike(like)) | (User.phone.ilike(like))
        )
    total = query.count()
    items = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return AdminUserList(total=total, items=items)


@router.get("/users/{user_id}", response_model=AdminUserOut)
def get_user(user_id: UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/users/{user_id}/generations", response_model=List[AdminUserGenerationRecord])
def get_user_generations(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    records = []
    from app.models.canvas import Canvas
    nodes = (
        db.query(Node)
        .join(Canvas, Node.canvas_id == Canvas.id)
        .filter(Canvas.user_id == str(user_id))
        .order_by(Node.created_at.desc())
        .limit(200)
        .all()
    )
    for n in nodes:
        records.append(AdminUserGenerationRecord(
            node_id=str(n.id),
            node_type=n.node_type.value if hasattr(n.node_type, "value") else str(n.node_type),
            status=n.status.value if hasattr(n.status, "value") else str(n.status),
            prompt=n.prompt,
            result_url=n.result_url,
            created_at=n.created_at,
            updated_at=n.updated_at,
        ))
    return records


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if payload.credits_delta is not None and payload.credits_delta != 0:
        try:
            credit_service.adjust_credits_by_admin(
                db=db,
                user_id=user.id,
                delta=payload.credits_delta,
                admin_id=admin.id,
                note=payload.note,
            )
        except InsufficientCreditsError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"积分余额不足：需要扣减 {exc.required}，当前余额 {exc.balance}",
            )

    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.new_password:
        user.password_hash = auth_service.get_password_hash(payload.new_password)

    db.add(user)
    db.commit()
    db.refresh(user)

    _audit_log(
        admin,
        "admin_update_user",
        {
            "target_user_id": str(user_id),
            "credits_delta": payload.credits_delta,
            "is_admin": payload.is_admin,
            "is_active": payload.is_active,
            "reset_password": bool(payload.new_password),
        },
    )
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 不允许删除自己
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    # 不允许删除最后一个管理员
    if user.is_admin:
        admin_count = db.query(User).filter(User.is_admin == True, User.is_active == True).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="系统至少需要保留一个管理员")
    db.delete(user)
    db.commit()
    _audit_log(admin, "admin_delete_user", {"target_user_id": str(user_id)})
    return None


# ------------------------------------------------------------------
# 兑换码
# ------------------------------------------------------------------
@router.get("/redeem-codes", response_model=AdminRedeemCodeList)
def list_redeem_codes(
    batch_id: Optional[str] = None,
    used: Optional[bool] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = db.query(RedeemCode)
    if batch_id:
        query = query.filter(RedeemCode.batch_id == batch_id)
    if used is True:
        query = query.filter(RedeemCode.used_at.isnot(None))
    elif used is False:
        query = query.filter(RedeemCode.used_at.is_(None))
    total = query.count()
    items = query.order_by(RedeemCode.created_at.desc()).offset(offset).limit(limit).all()
    return AdminRedeemCodeList(total=total, items=items)


class RedeemCodeBatchResponse(BaseModel):
    codes: List[str]
    count: int
    points: int
    batch_id: Optional[str]


@router.post("/redeem-codes", response_model=RedeemCodeBatchResponse)
def create_redeem_codes(
    payload: AdminRedeemCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    batch_id = payload.batch_id or datetime.utcnow().strftime("%Y%m%d%H%M%S")
    codes = []
    for _ in range(payload.count):
        for attempt in range(10):
            code = _generate_code()
            existing = db.query(RedeemCode).filter(RedeemCode.code == code).first()
            if not existing:
                break
        else:
            raise HTTPException(status_code=500, detail="兑换码生成冲突，请重试")

        expires_at = None
        if payload.expires_days:
            expires_at = datetime.utcnow() + timedelta(days=payload.expires_days)

        db.add(RedeemCode(
            code=code,
            points=payload.points,
            batch_id=batch_id,
            note=payload.note,
            expires_at=expires_at,
        ))
        codes.append(code)

    db.commit()
    _audit_log(admin, "admin_create_redeem_codes", {"count": payload.count, "points": payload.points, "batch_id": batch_id})
    return RedeemCodeBatchResponse(codes=codes, count=len(codes), points=payload.points, batch_id=batch_id)


# ------------------------------------------------------------------
# 充值档位
# ------------------------------------------------------------------
@router.get("/recharge-tiers", response_model=List[AdminRechargeTierOut])
def list_recharge_tiers(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return db.query(RechargeTier).order_by(RechargeTier.order.asc(), RechargeTier.yuan.asc()).all()


@router.post("/recharge-tiers", response_model=AdminRechargeTierOut)
def create_recharge_tier(
    payload: AdminRechargeTierCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    tier = RechargeTier(
        yuan=payload.yuan,
        credits=payload.credits,
        enabled=payload.enabled,
        order=payload.order,
    )
    db.add(tier)
    db.commit()
    db.refresh(tier)
    _audit_log(admin, "admin_create_recharge_tier", {"yuan": payload.yuan, "credits": payload.credits})
    return tier


@router.patch("/recharge-tiers/{tier_id}", response_model=AdminRechargeTierOut)
def update_recharge_tier(
    tier_id: UUID,
    payload: AdminRechargeTierCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    tier = db.query(RechargeTier).filter(RechargeTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="充值档位不存在")
    tier.yuan = payload.yuan
    tier.credits = payload.credits
    tier.enabled = payload.enabled
    tier.order = payload.order
    db.commit()
    db.refresh(tier)
    _audit_log(admin, "admin_update_recharge_tier", {"tier_id": str(tier_id)})
    return tier


@router.delete("/recharge-tiers/{tier_id}", status_code=204)
def delete_recharge_tier(
    tier_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    tier = db.query(RechargeTier).filter(RechargeTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="充值档位不存在")
    db.delete(tier)
    db.commit()
    _audit_log(admin, "admin_delete_recharge_tier", {"tier_id": str(tier_id)})
    return None


# ------------------------------------------------------------------
# 模型配置
# ------------------------------------------------------------------
@router.get("/model-configs", response_model=List[AdminModelConfigOut])
def list_model_configs(
    type: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = db.query(ModelConfig)
    if type:
        query = query.filter(ModelConfig.type == type)
    return query.order_by(ModelConfig.type.asc(), ModelConfig.order.asc()).all()


@router.post("/model-configs", response_model=AdminModelConfigOut)
def create_model_config(
    payload: AdminModelConfigCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.query(ModelConfig).filter(ModelConfig.model_id == payload.model_id).first():
        raise HTTPException(status_code=409, detail="model_id 已存在")
    cfg = ModelConfig(
        model_id=payload.model_id,
        name=payload.name,
        type=payload.type,
        description=payload.description,
        enabled=payload.enabled,
        order=payload.order,
        credits=payload.credits,
        credits_5s=payload.credits_5s or 0,
        credits_10s=payload.credits_10s or 0,
        credits_15s=payload.credits_15s or 0,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    _audit_log(admin, "admin_create_model_config", {"config_id": str(cfg.id), "model_id": cfg.model_id})
    return cfg


@router.patch("/model-configs/{config_id}", response_model=AdminModelConfigOut)
def update_model_config(
    config_id: UUID,
    payload: AdminModelConfigUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    cfg = db.query(ModelConfig).filter(ModelConfig.id == config_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    if payload.name is not None:
        cfg.name = payload.name
    if payload.description is not None:
        cfg.description = payload.description
    if payload.enabled is not None:
        cfg.enabled = payload.enabled
    if payload.order is not None:
        cfg.order = payload.order
    if payload.credits is not None:
        cfg.credits = payload.credits
    if payload.credits_5s is not None:
        cfg.credits_5s = payload.credits_5s
    if payload.credits_10s is not None:
        cfg.credits_10s = payload.credits_10s
    if payload.credits_15s is not None:
        cfg.credits_15s = payload.credits_15s
    db.commit()
    db.refresh(cfg)
    _audit_log(admin, "admin_update_model_config", {"config_id": str(config_id), "model_id": cfg.model_id})
    return cfg


# ------------------------------------------------------------------
# 公告管理
# ------------------------------------------------------------------
@router.get("/announcements", response_model=AdminAnnouncementList)
def list_announcements(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    query = db.query(Announcement)
    total = query.count()
    items = query.order_by(Announcement.pinned.desc(), Announcement.created_at.desc()).offset(offset).limit(limit).all()
    return AdminAnnouncementList(total=total, items=items)


@router.post("/announcements", response_model=AdminAnnouncementOut)
def create_announcement(
    payload: AdminAnnouncementCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ann = Announcement(
        title=payload.title,
        content=payload.content,
        type=payload.type,
        pinned=payload.pinned,
        enabled=payload.enabled,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    _audit_log(admin, "admin_create_announcement", {"title": payload.title})
    return ann


@router.patch("/announcements/{ann_id}", response_model=AdminAnnouncementOut)
def update_announcement(
    ann_id: UUID,
    payload: AdminAnnouncementUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="公告不存在")
    if payload.title is not None:
        ann.title = payload.title
    if payload.content is not None:
        ann.content = payload.content
    if payload.type is not None:
        ann.type = payload.type
    if payload.pinned is not None:
        ann.pinned = payload.pinned
    if payload.enabled is not None:
        ann.enabled = payload.enabled
    db.commit()
    db.refresh(ann)
    _audit_log(admin, "admin_update_announcement", {"ann_id": str(ann_id)})
    return ann


@router.delete("/announcements/{ann_id}", status_code=204)
def delete_announcement(
    ann_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="公告不存在")
    db.delete(ann)
    db.commit()
    _audit_log(admin, "admin_delete_announcement", {"ann_id": str(ann_id)})
    return None


# ------------------------------------------------------------------
# 充值订单管理
# ------------------------------------------------------------------
class AdminOrderOut(BaseModel):
    id: str
    user_id: str
    channel: str
    out_trade_no: str
    amount_yuan: float
    credits: int
    status: str
    trade_no: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime

    @field_validator("id", "user_id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class AdminOrderList(BaseModel):
    total: int
    items: List[AdminOrderOut]


@router.get("/orders", response_model=AdminOrderList)
def list_orders(
    status: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """管理员查看充值订单列表，支持按状态/渠道筛选。"""
    query = db.query(RechargeOrder)
    if status:
        query = query.filter(RechargeOrder.status == status)
    if channel:
        query = query.filter(RechargeOrder.channel == channel)
    total = query.count()
    items = query.order_by(RechargeOrder.created_at.desc()).offset(offset).limit(limit).all()
    return AdminOrderList(total=total, items=items)


# ------------------------------------------------------------------
# 积分流水审计
# ------------------------------------------------------------------
class AdminLedgerOut(BaseModel):
    id: str
    user_id: str
    amount: int
    balance_after: int
    reason: str
    ref_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    @field_validator("id", "user_id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class AdminLedgerList(BaseModel):
    total: int
    items: List[AdminLedgerOut]


@router.get("/credits/ledger", response_model=AdminLedgerList)
def list_all_ledger(
    user_id: Optional[UUID] = None,
    reason: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """管理员查看全局积分流水，支持按用户/原因筛选。"""
    query = db.query(CreditLedger)
    if user_id:
        query = query.filter(CreditLedger.user_id == user_id)
    if reason:
        query = query.filter(CreditLedger.reason == reason)
    total = query.count()
    items = query.order_by(CreditLedger.created_at.desc()).offset(offset).limit(limit).all()
    return AdminLedgerList(total=total, items=items)
