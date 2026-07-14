from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=32)
    password: str = Field(..., min_length=6)
    name: Optional[str] = Field(None, max_length=255)


class UserLogin(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=32)
    password: str = Field(..., min_length=1)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    is_admin: bool
    credits: int

    @field_validator("id", mode="before")
    @classmethod
    def _convert_uuid(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class SendSmsRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=32)
    turnstile_token: Optional[str] = None


class LoginSmsRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=32)
    code: str = Field(..., min_length=4, max_length=8)
    name: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = Field(None, min_length=6)
