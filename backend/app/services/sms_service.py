"""阿里云短信验证码服务。"""
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.sms_code import SmsCode

logger = logging.getLogger(__name__)

# 阿里云短信 SDK（未安装时不影响服务启动）
try:
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
    from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
    ALIYUN_SMS_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    logger.warning("阿里云短信 SDK 未安装或加载失败: %s", exc)
    open_api_models = None  # type: ignore
    DysmsapiClient = None  # type: ignore
    dysmsapi_models = None  # type: ignore
    ALIYUN_SMS_AVAILABLE = False


def generate_code(length: int = 6) -> str:
    """生成数字验证码。"""
    return "".join(random.choices("0123456789", k=length))


def _get_client() -> "DysmsapiClient":
    """初始化阿里云短信客户端。"""
    if not ALIYUN_SMS_AVAILABLE:
        raise RuntimeError("阿里云短信 SDK 未安装")
    config = open_api_models.Config(
        access_key_id=settings.ALIYUN_SMS_ACCESS_KEY_ID,
        access_key_secret=settings.ALIYUN_SMS_ACCESS_KEY_SECRET,
    )
    config.endpoint = "dysmsapi.aliyuncs.com"
    return DysmsapiClient(config)


def send_sms_code(phone: str, code: str) -> None:
    """调用阿里云短信接口发送验证码。"""
    if not settings.ALIYUN_SMS_ACCESS_KEY_ID or not settings.ALIYUN_SMS_ACCESS_KEY_SECRET:
        raise RuntimeError("阿里云短信密钥未配置")
    if not settings.ALIYUN_SMS_SIGN_NAME or not settings.ALIYUN_SMS_TEMPLATE_CODE:
        raise RuntimeError("阿里云短信签名/模板未配置")

    client = _get_client()
    request = dysmsapi_models.SendSmsRequest(
        phone_numbers=phone,
        sign_name=settings.ALIYUN_SMS_SIGN_NAME,
        template_code=settings.ALIYUN_SMS_TEMPLATE_CODE,
        template_param=json.dumps({"code": code}),
    )
    response = client.send_sms(request)
    body = response.body
    if body.code != "OK":
        raise RuntimeError(f"短信发送失败: {body.message} ({body.code})")


def create_sms_code_record(
    db: Session,
    phone: str,
    code: str,
    expires_minutes: int = 5,
) -> SmsCode:
    """在数据库中写入一条待验证的短信验证码。"""
    record = SmsCode(
        phone=phone,
        code=code,
        expires_at=datetime.utcnow() + timedelta(minutes=expires_minutes),
        used=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def verify_sms_code(db: Session, phone: str, code: str) -> bool:
    """校验并作废最新一条未过期的验证码。"""
    record = (
        db.query(SmsCode)
        .filter(
            SmsCode.phone == phone,
            SmsCode.code == code,
            SmsCode.used == False,
            SmsCode.expires_at >= datetime.utcnow(),
        )
        .order_by(SmsCode.created_at.desc())
        .first()
    )
    if not record:
        return False
    record.used = True
    db.add(record)
    db.commit()
    return True


def recent_code_count(db: Session, phone: str, minutes: int = 5) -> int:
    """统计最近 N 分钟内该手机号发送的验证码数量。"""
    since = datetime.utcnow() - timedelta(minutes=minutes)
    return db.query(SmsCode).filter(SmsCode.phone == phone, SmsCode.created_at >= since).count()
