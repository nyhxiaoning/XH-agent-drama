import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.model_config import ModelConfig
from app.models.user import User
from app.services import credit_service
from app.services.credit_service import (
    BASE_PRICING,
    calculate_cost,
    get_balance,
    get_ledger,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credits", tags=["credits"])


class RechargeReq(BaseModel):
    user_id: UUID = Field(..., description="目标用户 ID")
    amount: int = Field(..., ge=1, description="充值积分数量")
    reason: str = "recharge"
    description: Optional[str] = None


class CreditLedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: int
    balance_after: int
    reason: str
    ref_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime


class CreditBalanceOut(BaseModel):
    user_id: UUID
    balance: int


class CreditEstimateOut(BaseModel):
    task_type: str
    cost: int
    model: Optional[str] = None
    duration: Optional[float] = None
    resolution: Optional[str] = None


class PricingOut(BaseModel):
    pricing: dict


@router.get("/balance", response_model=CreditBalanceOut)
def get_credits_balance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前登录用户的积分余额。"""
    balance = get_balance(db, current_user.id)
    return {"user_id": current_user.id, "balance": balance}


@router.get("/ledger", response_model=List[CreditLedgerOut])
def get_credits_ledger(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前登录用户的积分流水。"""
    entries = get_ledger(db, current_user.id, limit=limit, offset=offset)
    return entries


@router.post("/recharge", response_model=CreditBalanceOut)
def recharge_credits(
    req: RechargeReq,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员给指定用户充值积分。"""
    target_user = db.query(User).filter(User.id == req.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    new_balance = credit_service.add_credits(
        db=db,
        user_id=req.user_id,
        amount=req.amount,
        reason=req.reason,
        description=req.description or f"管理员充值（操作者：{current_user.email or current_user.phone or current_user.id}）",
    )
    db.commit()
    return {"user_id": req.user_id, "balance": new_balance}


@router.get("/pricing", response_model=PricingOut)
def get_credits_pricing(current_user: User = Depends(get_current_user)):
    """获取积分定价表。"""
    return {"pricing": BASE_PRICING}


class ModelPricingItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    type: str
    credits: int
    credits_5s: int
    credits_10s: int
    credits_15s: int


class EnabledModelItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    name: str
    type: str


@router.get("/enabled-models", response_model=List[EnabledModelItem])
def get_enabled_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有已启用的模型列表，供前端动态过滤已禁用的模型。"""
    configs = (
        db.query(ModelConfig)
        .filter(ModelConfig.enabled == True)
        .order_by(ModelConfig.type.asc(), ModelConfig.order.asc())
        .all()
    )
    return [
        EnabledModelItem(
            model_id=c.model_id,
            name=c.name,
            type=c.type,
        )
        for c in configs
    ]


@router.get("/model-pricing", response_model=List[ModelPricingItem])
def get_model_pricing(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有已启用模型的积分定价（含三档定价），供前端预估扣费。"""
    configs = db.query(ModelConfig).filter(ModelConfig.enabled == True).all()
    return [
        ModelPricingItem(
            model_id=c.model_id,
            type=c.type,
            credits=c.credits or 0,
            credits_5s=c.credits_5s or 0,
            credits_10s=c.credits_10s or 0,
            credits_15s=c.credits_15s or 0,
        )
        for c in configs
    ]


@router.post("/estimate", response_model=CreditEstimateOut)
def estimate_cost(
    task_type: str,
    node_config: Optional[dict] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """估算单次生成所需积分（不扣费）。"""
    cost = calculate_cost(task_type, node_config or {}, db=db)
    return {
        "task_type": task_type,
        "cost": cost,
        "model": (node_config or {}).get("model"),
        "duration": (node_config or {}).get("duration") or (node_config or {}).get("durationSec") or (node_config or {}).get("duration_seconds"),
        "resolution": (node_config or {}).get("resolution"),
    }

