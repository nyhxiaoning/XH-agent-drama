"""Cloudflare Turnstile 服务端校验。"""
import logging
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(token: Optional[str], remote_ip: Optional[str] = None) -> bool:
    """校验 Turnstile token。未配置密钥时开发环境默认通过。"""
    secret = settings.TURNSTILE_SECRET_KEY
    if not secret:
        logger.warning("[turnstile] TURNSTILE_SECRET_KEY 未配置，跳过校验")
        return True
    if not token:
        return False

    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        resp = requests.post(VERIFY_URL, data=data, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("success") is True:
            return True
        logger.warning("[turnstile] 校验失败: %s", result.get("error-codes"))
        return False
    except Exception as exc:
        logger.warning("[turnstile] 请求异常: %s", exc)
        return False
