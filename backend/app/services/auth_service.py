"""用户认证服务：密码哈希、JWT 生成与校验。"""
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User

# 直接引用 settings.SECRET_KEY，确保 config.py 的安全校验生效
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def authenticate_user(db: Session, email: Optional[str] = None, phone: Optional[str] = None, password: Optional[str] = None) -> Optional[User]:
    """邮箱或手机号 + 密码登录。"""
    user = None
    if email:
        user = db.query(User).filter(User.email == email).first()
    if not user and phone:
        user = db.query(User).filter(User.phone == phone).first()
    if not user:
        return None
    if not user.password_hash:
        return None
    if password and not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id: UUID) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()
