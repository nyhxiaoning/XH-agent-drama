import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.recharge_tier import RechargeTier
from app.schemas.admin import AdminRechargeTierOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recharge", tags=["recharge"])


@router.get("/tiers", response_model=List[AdminRechargeTierOut])
def list_enabled_tiers(db: Session = Depends(get_db)):
    """用户端：列出启用的充值档位。"""
    return (
        db.query(RechargeTier)
        .filter(RechargeTier.enabled == True)
        .order_by(RechargeTier.order.asc(), RechargeTier.yuan.asc())
        .all()
    )
