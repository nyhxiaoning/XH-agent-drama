import hashlib
import logging
import mimetypes
from typing import BinaryIO, Optional, Union

import requests
from qcloud_cos import CosConfig, CosS3Client

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_cos_client() -> CosS3Client:
    if not settings.TENCENT_COS_SECRET_ID or not settings.TENCENT_COS_SECRET_KEY:
        raise RuntimeError("请在 .env 中配置 TENCENT_COS_SECRET_ID 与 TENCENT_COS_SECRET_KEY")
    config = CosConfig(
        Region=settings.TENCENT_COS_REGION,
        SecretId=settings.TENCENT_COS_SECRET_ID,
        SecretKey=settings.TENCENT_COS_SECRET_KEY,
    )
    return CosS3Client(config)


def _ext_for_mime(content_type: str) -> str:
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
    if ext:
        return ext.lstrip(".")
    mapping = {
        "video/mp4": "mp4",
        "image/webp": "webp",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "application/octet-stream": "bin",
        "binary/octet-stream": "bin",
    }
    return mapping.get(content_type.lower().split(";")[0].strip(), "bin")


def upload_to_cos(
    body: Union[bytes, BinaryIO],
    file_name: str,
    mime_type: str,
    content_length: Optional[int] = None,
) -> str:
    """上传 Buffer 或文件流到腾讯云 COS，返回 HTTPS 公网访问地址。"""
    client = _get_cos_client()
    if not settings.TENCENT_COS_BUCKET or not settings.TENCENT_COS_REGION:
        raise RuntimeError("请在 .env 中配置 TENCENT_COS_BUCKET 与 TENCENT_COS_REGION")

    size_desc = (
        len(body)
        if isinstance(body, (bytes, bytearray))
        else (content_length if content_length is not None else "unknown")
    )
    logger.info(
        "[COS] uploadToCos called: file_name=%s mime=%s size=%s bucket=%s region=%s",
        file_name,
        mime_type,
        size_desc,
        settings.TENCENT_COS_BUCKET,
        settings.TENCENT_COS_REGION,
    )

    params = {
        "Bucket": settings.TENCENT_COS_BUCKET,
        "Key": file_name,
        "Body": body,
        "ContentType": mime_type,
    }
    # bytes 类型 SDK 能自动推断长度，无需传 ContentLength
    # 流类型才需要显式指定，且必须转为字符串（httplib 要求 header 值为 str）
    if content_length is not None and not isinstance(body, (bytes, bytearray)):
        params["ContentLength"] = str(content_length)

    try:
        resp = client.put_object(**params)
    except Exception as exc:
        logger.error("COS Upload Error: %s", exc)
        raise RuntimeError(f"COS上传失败: {exc}") from exc

    location = resp.get("Location") if isinstance(resp, dict) else None
    if not location:
        location = (
            f"{settings.TENCENT_COS_BUCKET}.cos.{settings.TENCENT_COS_REGION}."
            f"myqcloud.com/{file_name}"
        )
    url = f"https://{location}"
    logger.info("[COS] Upload success: %s", url)
    return url


def _cos_object_exists(client: CosS3Client, key: str) -> bool:
    """检查 COS 上指定 key 的对象是否已存在。"""
    try:
        return bool(client.object_exists(
            Bucket=settings.TENCENT_COS_BUCKET,
            Key=key,
        ))
    except Exception:
        # object_exists 失败时不阻塞上传流程，保守返回 False
        return False


def _build_dedup_key(prefix: str, content: bytes, ext: str) -> str:
    """根据内容 MD5 哈希生成去重 COS key。

    相同内容 → 相同 key → 上传前检测到已存在则跳过，节省带宽和存储。
    """
    md5 = hashlib.md5(content).hexdigest()
    return f"{prefix}/{md5}.{ext}"


def _build_cos_url(key: str) -> str:
    """根据 COS key 拼接 HTTPS 公网访问 URL。"""
    return (
        f"https://{settings.TENCENT_COS_BUCKET}.cos."
        f"{settings.TENCENT_COS_REGION}.myqcloud.com/{key}"
    )


def upload_to_cos_dedup(
    body: bytes,
    prefix: str,
    mime_type: str,
    ext: Optional[str] = None,
) -> str:
    """带 MD5 去重的 COS 上传：相同内容只传一次。

    1. 计算内容 MD5 哈希作为 COS key
    2. 先检查 COS 上是否已存在该 key
    3. 已存在 → 直接返回 URL，跳过上传
    4. 不存在 → 上传并返回 URL

    Args:
        body: 文件二进制内容（必须为 bytes，不支持流）
        prefix: COS 路径前缀（如 "seedance-ref"）
        mime_type: MIME 类型
        ext: 文件扩展名，不传则从 mime_type 推断

    Returns:
        COS HTTPS 公网访问 URL
    """
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError("upload_to_cos_dedup 仅支持 bytes 类型，请先读取为完整内容")

    body_bytes = bytes(body)
    if not ext:
        ext = _ext_for_mime(mime_type)

    key = _build_dedup_key(prefix, body_bytes, ext)
    client = _get_cos_client()

    # 去重检测：如果 COS 上已存在相同内容，跳过上传
    if _cos_object_exists(client, key):
        url = _build_cos_url(key)
        logger.info("[COS] 去重命中，跳过上传: key=%s size=%d", key, len(body_bytes))
        return url

    # 不存在则上传
    url = upload_to_cos(body_bytes, key, mime_type)
    logger.info("[COS] 去重上传完成: key=%s size=%d", key, len(body_bytes))
    return url


def cache_url_to_cos(url: str, prefix: str = "cache") -> Optional[str]:
    """从 URL 下载并转存到 COS（带 MD5 去重），已经是 COS 地址则直接返回。"""
    if not url or "myqcloud.com" in url:
        return url

    logger.info("[COS] Starting cache for URL: %s", url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        # 统一使用 Buffer 模式下载，以便计算 MD5 进行去重
        response = requests.get(url, timeout=60, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get("content-type") or "application/octet-stream"
        if content_type.lower() in ("application/octet-stream", "binary/octet-stream"):
            url_ext = url.split("?")[0].split(".")[-1].lower()
            corrected = mimetypes.guess_type(f"x.{url_ext}")[0]
            if corrected:
                content_type = corrected

        body_bytes = response.content
        ext = _ext_for_mime(content_type)
        cos_url = upload_to_cos_dedup(body_bytes, prefix, content_type, ext)
        logger.info("[COS] Successfully cached to: %s", cos_url)
        return cos_url

    except Exception as exc:
        logger.error("[COS] Failed to cache URL to COS (%s): %s", url, exc)
        return None


def upload_file_to_cos(local_path: str, cos_key: str, mime_type: str) -> str:
    """使用腾讯云 COS 分片上传本地大文件（适合视频等大文件）。

    Args:
        local_path: 本地文件绝对路径
        cos_key: COS 对象路径
        mime_type: 文件 MIME 类型

    Returns:
        COS HTTPS 公网访问地址
    """
    client = _get_cos_client()
    if not settings.TENCENT_COS_BUCKET or not settings.TENCENT_COS_REGION:
        raise RuntimeError("请在 .env 中配置 TENCENT_COS_BUCKET 与 TENCENT_COS_REGION")

    logger.info(
        "[COS] uploadFileToCos called: local_path=%s cos_key=%s mime=%s bucket=%s",
        local_path,
        cos_key,
        mime_type,
        settings.TENCENT_COS_BUCKET,
    )

    try:
        resp = client.upload_file(
            Bucket=settings.TENCENT_COS_BUCKET,
            Key=cos_key,
            LocalFilePath=local_path,
            PartSize=10,  # 10MB 每片
            MAXThread=4,
            ContentType=mime_type,
        )
    except Exception as exc:
        logger.error("COS Upload File Error: %s", exc)
        raise RuntimeError(f"COS分片上传失败: {exc}") from exc

    location = resp.get("Location") if isinstance(resp, dict) else None
    if not location:
        location = (
            f"{settings.TENCENT_COS_BUCKET}.cos.{settings.TENCENT_COS_REGION}."
            f"myqcloud.com/{cos_key}"
        )
    url = f"https://{location}"
    logger.info("[COS] Upload file success: %s", url)
    return url
