"""用户认证接口：注册、登录、刷新 Token、获取当前用户。"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.auth import (
    UserLogin,
    UserRegister,
    Token,
    UserOut,
    SendSmsRequest,
    LoginSmsRequest,
)
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    ACCESS_TOKEN_EXPIRE_DAYS,
)
from app.services import sms_service, turnstile_service

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=UserOut)
@limiter.limit("5/minute")
async def register(request: Request, req: UserRegister, db: Session = Depends(get_db)):
    """邮箱或手机号注册。"""
    if not req.email and not req.phone:
        raise HTTPException(status_code=400, detail="邮箱或手机号至少填一个")

    # 检查是否已存在
    existing = None
    if req.email:
        existing = db.query(User).filter(User.email == req.email).first()
    if not existing and req.phone:
        existing = db.query(User).filter(User.phone == req.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱或手机号已注册")

    name = req.name or (f"用户{req.phone[-4:]}" if req.phone else (req.email.split("@")[0] if req.email else "用户"))
    user = User(
        email=req.email,
        phone=req.phone,
        name=name,
        password_hash=get_password_hash(req.password),
        credits=100,  # 新用户赠送 100 积分体验
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, req: UserLogin, db: Session = Depends(get_db)):
    """邮箱或手机号 + 密码登录。"""
    if not req.email and not req.phone:
        raise HTTPException(status_code=400, detail="邮箱或手机号至少填一个")
    user = authenticate_user(db, email=req.email, phone=req.phone, password=req.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.commit()

    access_token = create_access_token({"sub": str(user.id)})
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


@router.get("/me", response_model=UserOut)
async def read_current_user(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return current_user


@router.post("/send-sms")
@limiter.limit("3/minute")
async def send_sms(
    request: Request,
    req: SendSmsRequest,
    db: Session = Depends(get_db),
):
    """发送手机验证码（需先通过 Turnstile 人机验证）。"""
    remote_ip = request.client.host if request.client else None
    if not turnstile_service.verify_turnstile(req.turnstile_token, remote_ip):
        raise HTTPException(status_code=403, detail="人机验证失败，请刷新页面重试")

    # 简单频率限制：同一手机号 5 分钟内最多 3 条
    recent = sms_service.recent_code_count(db, req.phone, minutes=5)
    if recent >= 3:
        raise HTTPException(status_code=429, detail="发送过于频繁，请稍后再试")

    code = sms_service.generate_code()
    try:
        sms_service.send_sms_code(req.phone, code)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    sms_service.create_sms_code_record(db, req.phone, code)
    return {"message": "验证码已发送", "phone": req.phone}


@router.post("/login-sms", response_model=Token)
@limiter.limit("10/minute")
async def login_sms(request: Request, req: LoginSmsRequest, db: Session = Depends(get_db)):
    """手机号+验证码登录/注册。验证码验证通过后，新用户自动注册。"""
    if not sms_service.verify_sms_code(db, req.phone, req.code):
        raise HTTPException(status_code=401, detail="验证码错误或已过期")

    user = db.query(User).filter(User.phone == req.phone).first()
    if not user:
        name = req.name or f"用户{req.phone[-4:]}"
        password_hash = get_password_hash(req.password) if req.password else None
        user = User(
            phone=req.phone,
            name=name,
            password_hash=password_hash,
            credits=100,  # 新用户赠送 100 积分体验
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.commit()

    access_token = create_access_token({"sub": str(user.id)})
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
