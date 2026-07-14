import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_admin
from app.core.database import get_db
from app.models.canvas import Canvas
from app.models.credit import CreditLedger
from app.models.node import Node
from app.models.recharge_order import RechargeOrder
from app.models.user import User
from app.schemas.user import (
    UserMeOut,
    UserStatsOut,
    PasswordChange,
    CreditLedgerList,
    RedeemInput,
    RedeemResult,
)
from app.services import auth_service, credit_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMeOut)
def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user


@router.get("/me/stats", response_model=UserStatsOut)
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    canvas_count = db.query(Canvas.id).filter(Canvas.user_id == str(current_user.id)).count()

    image_count = db.query(Node).join(Canvas, Node.canvas_id == Canvas.id).filter(
        Canvas.user_id == str(current_user.id),
        Node.node_type.in_(["image", "character", "scene", "storyboard"])
    ).count()
    video_count = db.query(Node).join(Canvas, Node.canvas_id == Canvas.id).filter(
        Canvas.user_id == str(current_user.id), Node.node_type == "video"
    ).count()
    script_count = db.query(Node).join(Canvas, Node.canvas_id == Canvas.id).filter(
        Canvas.user_id == str(current_user.id), Node.node_type == "script"
    ).count()
    audio_count = db.query(Node).join(Canvas, Node.canvas_id == Canvas.id).filter(
        Canvas.user_id == str(current_user.id), Node.node_type == "audio"
    ).count()

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    credits_used_this_month = db.query(func.sum(CreditLedger.amount)).filter(
        CreditLedger.user_id == current_user.id,
        CreditLedger.amount < 0,
        CreditLedger.created_at >= month_start,
    ).scalar() or 0
    credits_used_this_month = abs(int(credits_used_this_month))

    total_recharged = db.query(func.sum(RechargeOrder.amount_yuan)).filter(
        RechargeOrder.user_id == current_user.id,
        RechargeOrder.status == "paid",
    ).scalar() or 0

    return UserStatsOut(
        canvas_count=canvas_count,
        image_count=image_count,
        video_count=video_count,
        script_count=script_count,
        audio_count=audio_count,
        credits_used_this_month=credits_used_this_month,
        total_recharged=round(float(total_recharged), 2),
    )


@router.put("/me/password", status_code=200)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """修改密码。已设置过密码的用户必须提供当前密码；未设置过密码可直接设置。"""
    if current_user.password_hash and current_user.password_hash.startswith("$2b$"):
        if not payload.current_password:
            raise HTTPException(status_code=400, detail="当前密码不能为空")
        if not auth_service.verify_password(payload.current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="当前密码错误")

    current_user.password_hash = auth_service.get_password_hash(payload.new_password)
    db.add(current_user)
    db.commit()
    return {"message": "密码修改成功"}


@router.get("/me/ledger", response_model=CreditLedgerList)
def get_my_ledger(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    total = credit_service.count_ledger(db, current_user.id)
    items = credit_service.get_ledger(db, current_user.id, limit=limit, offset=offset)
    balance = credit_service.get_balance(db, current_user.id)
    return CreditLedgerList(total=total, items=items, balance=balance)


@router.post("/me/redeem", response_model=RedeemResult)
def redeem(
    payload: RedeemInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    try:
        result = credit_service.redeem_code(db, current_user.id, payload.code)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
