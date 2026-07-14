from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class UserStatsOut(BaseModel):
    canvas_count: int = 0
    image_count: int = 0
    video_count: int = 0
    script_count: int = 0
    audio_count: int = 0
    credits_used_this_month: int = 0
    total_recharged: int = 0


class UserMeOut(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    avatar_url: Optional[str]
    is_admin: bool
    credits: int
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class PasswordChange(BaseModel):
    current_password: Optional[str] = None
    new_password: str = Field(..., min_length=6, max_length=128)


class CreditLedgerItem(BaseModel):
    id: str
    amount: int
    balance_after: int
    reason: str
    description: Optional[str]
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class CreditLedgerList(BaseModel):
    total: int
    items: List[CreditLedgerItem]
    balance: int


class RedeemInput(BaseModel):
    code: str = Field(..., min_length=8, max_length=64)


class RedeemResult(BaseModel):
    points: int
    balance_after: int
