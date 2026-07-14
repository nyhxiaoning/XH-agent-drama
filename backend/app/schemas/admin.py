from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdminUserOut(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    credits: int
    is_admin: bool
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class AdminUserList(BaseModel):
    total: int
    items: List[AdminUserOut]


class AdminUserUpdate(BaseModel):
    credits_delta: Optional[int] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = Field(None, min_length=6, max_length=128)
    note: Optional[str] = None


class AdminRedeemCreate(BaseModel):
    points: int = Field(..., gt=0)
    count: int = Field(..., gt=0, le=1000)
    batch_id: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = None
    expires_days: Optional[int] = None


class AdminRedeemCodeOut(BaseModel):
    id: str
    code: str
    points: int
    batch_id: Optional[str]
    note: Optional[str]
    expires_at: Optional[datetime]
    used_at: Optional[datetime]
    used_by_id: Optional[str]
    created_at: datetime

    @field_validator("id", "used_by_id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class AdminRedeemCodeList(BaseModel):
    total: int
    items: List[AdminRedeemCodeOut]


class AdminModelConfigOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), from_attributes=True)

    id: str
    model_id: str
    name: str
    type: str
    description: Optional[str]
    enabled: bool
    order: int
    credits: int
    credits_5s: int = 0
    credits_10s: int = 0
    credits_15s: int = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v


class AdminModelConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    order: Optional[int] = None
    credits: Optional[int] = Field(None, ge=0)
    credits_5s: Optional[int] = Field(None, ge=0)
    credits_10s: Optional[int] = Field(None, ge=0)
    credits_15s: Optional[int] = Field(None, ge=0)


class AdminModelConfigCreate(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(image|video|audio|llm)$")
    description: Optional[str] = Field(None, max_length=512)
    enabled: Optional[bool] = True
    order: Optional[int] = 0
    credits: Optional[int] = Field(0, ge=0)
    credits_5s: Optional[int] = Field(0, ge=0)
    credits_10s: Optional[int] = Field(0, ge=0)
    credits_15s: Optional[int] = Field(0, ge=0)


class AdminRechargeTierCreate(BaseModel):
    yuan: float = Field(..., gt=0)
    credits: int = Field(..., gt=0)
    enabled: Optional[bool] = True
    order: Optional[int] = 0


class AdminRechargeTierOut(BaseModel):
    id: str
    yuan: float
    credits: int
    enabled: bool
    order: int
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class AdminAnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    type: Optional[str] = "info"
    pinned: Optional[bool] = False
    enabled: Optional[bool] = True


class AdminAnnouncementUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = None
    type: Optional[str] = None
    pinned: Optional[bool] = None
    enabled: Optional[bool] = None


class AdminAnnouncementOut(BaseModel):
    id: str
    title: str
    content: str
    type: str
    pinned: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class AdminAnnouncementList(BaseModel):
    total: int
    items: List[AdminAnnouncementOut]


class AdminStatsOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    total_users: int
    today_active_users: int
    week_active_users: int
    total_images: int
    total_videos: int
    total_scripts: int
    total_recharged_yuan: float
    today_recharged_yuan: float
    week_recharged_yuan: float
    model_ranking: List[dict]


class AdminUserGenerationRecord(BaseModel):
    node_id: str
    node_type: str
    status: str
    prompt: Optional[str]
    result_url: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
