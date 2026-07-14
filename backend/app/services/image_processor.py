"""
图像处理服务：宫格切分、聚焦裁剪。
使用 Pillow 进行本地图像处理，支持从本地路径或远程 URL 加载图片。
"""
import logging
import os
import uuid
from typing import Dict, Any, List, Optional, Tuple
import asyncio

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


def _get_upload_dir() -> str:
    """获取 uploads 目录的绝对路径。"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


async def _load_image(image_url: str, local_path: Optional[str] = None) -> Image.Image:
    """从本地路径或远程 URL 加载 PIL Image。

    优先读取本地磁盘文件，本地不存在时通过 HTTP 下载。
    """
    # 优先读取本地文件
    if local_path and os.path.isfile(local_path):
        try:
            img = Image.open(local_path)
            img.load()
            logger.info("[image_processor] 本地加载成功: %s (%dx%d)", local_path, img.width, img.height)
            return img
        except Exception as exc:
            logger.warning("[image_processor] 本地加载失败: %s err=%s", local_path, exc)
    else:
        logger.info("[image_processor] 本地文件不存在: %s, 将通过 HTTP 下载", local_path)

    # 通过 HTTP 下载
    abs_url = image_url
    if not abs_url.startswith(("http://", "https://")):
        # 补全为绝对 URL
        from app.services.ai_service import _public_url
        abs_url = _public_url(image_url)

    logger.info("[image_processor] HTTP 下载: %s", abs_url[:120])
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(abs_url, timeout=120)
            resp.raise_for_status()
            import io
            img = Image.open(io.BytesIO(resp.content))
            img.load()
            logger.info("[image_processor] HTTP 加载成功: %dx%d", img.width, img.height)
            return img
    except httpx.HTTPStatusError as exc:
        logger.error("[image_processor] HTTP 下载失败 (status=%s): %s", exc.response.status_code, abs_url[:200])
        raise
    except Exception as exc:
        logger.error("[image_processor] HTTP 下载异常: %s url=%s", exc, abs_url[:200])
        raise


def _save_image(img: Image.Image, upload_dir: str, prefix: str = "split") -> str:
    """保存 PIL Image 到 uploads/generated 目录，返回可访问 URL。

    如果配置了腾讯云 COS，同时上传到 COS 并返回 COS HTTPS URL；
    否则返回本地 /static 路径。
    """
    save_dir = os.path.join(upload_dir, "generated")
    os.makedirs(save_dir, exist_ok=True)
    file_id = str(uuid.uuid4())
    filename = f"{file_id}_{prefix}.png"
    file_path = os.path.join(save_dir, filename)

    # 确保是 RGB 模式（RGBA 转 RGB 时用白色背景）
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    img.save(file_path, "PNG")

    # 尝试上传到 COS（生产环境使用 COS，本地开发降级为 /static）
    try:
        from app.core.config import settings
        if (settings.TENCENT_COS_SECRET_ID
                and settings.TENCENT_COS_SECRET_KEY
                and settings.TENCENT_COS_BUCKET
                and settings.TENCENT_COS_REGION):
            from app.services.cos_service import upload_to_cos
            with open(file_path, "rb") as f:
                content = f.read()
            cos_key = f"uploads/generated/{filename}"
            cos_url = upload_to_cos(content, cos_key, "image/png", len(content))
            logger.info("[image_processor] 已上传至 COS: %s", cos_url)
            return cos_url
    except Exception as exc:
        logger.warning("[image_processor] COS 上传失败，降级使用本地路径: %s", exc)

    return f"/static/generated/{filename}"


async def split_image(
    image_url: str,
    local_path: Optional[str],
    rows: int,
    cols: int,
    upload_dir: str,
) -> List[Dict[str, Any]]:
    """将图片切分为 rows×cols 个子图。

    Args:
        image_url: 图片 URL（本地路径或远程 URL）
        local_path: 本地磁盘路径（优先使用）
        rows: 行数
        cols: 列数
        upload_dir: uploads 根目录

    Returns:
        子图列表，每个元素包含 url 和 grid 位置信息
    """
    img = await _load_image(image_url, local_path)
    width, height = img.size

    cell_w = width // cols
    cell_h = height // rows

    # 微调：确保切分覆盖整个图片（避免边缘像素丢失）
    results: List[Dict[str, Any]] = []

    def _do_split():
        for row in range(rows):
            for col in range(cols):
                left = col * cell_w
                top = row * cell_h
                # 最后一个单元格取到图片边缘
                right = (col + 1) * cell_w if col < cols - 1 else width
                bottom = (row + 1) * cell_h if row < rows - 1 else height

                sub = img.crop((left, top, right, bottom))
                url = _save_image(sub, upload_dir, prefix=f"split_{row}_{col}")
                results.append({
                    "url": url,
                    "row": row,
                    "col": col,
                    "index": row * cols + col,
                })

    # 在线程池中执行 CPU 密集的图像操作
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_split)

    logger.info("[image_processor] 宫格切分完成: %dx%d = %d 张子图", rows, cols, len(results))
    return results


async def crop_image(
    image_url: str,
    local_path: Optional[str],
    region: Dict[str, int],
    upload_dir: str,
) -> Dict[str, Any]:
    """按百分比区域裁剪图片。

    Args:
        image_url: 图片 URL
        local_path: 本地磁盘路径
        region: {x, y, w, h} 百分比值 (0-100)
        upload_dir: uploads 根目录

    Returns:
        包含裁剪后图片 URL 的字典
    """
    img = await _load_image(image_url, local_path)
    width, height = img.size

    # 百分比转像素
    x_pct = max(0, min(100, region.get("x", 0)))
    y_pct = max(0, min(100, region.get("y", 0)))
    w_pct = max(1, min(100, region.get("w", 50)))
    h_pct = max(1, min(100, region.get("h", 50)))

    left = int(width * x_pct / 100)
    top = int(height * y_pct / 100)
    right = min(int(width * (x_pct + w_pct) / 100), width)
    bottom = min(int(height * (y_pct + h_pct) / 100), height)

    if right <= left or bottom <= top:
        raise ValueError(f"裁剪区域无效: left={left}, top={top}, right={right}, bottom={bottom}")

    def _do_crop():
        cropped = img.crop((left, top, right, bottom))
        # 放大裁剪结果到至少 512x512（避免特写图太小）
        min_size = 512
        cw, ch = cropped.size
        if cw < min_size or ch < min_size:
            scale = max(min_size / cw, min_size / ch)
            new_w = int(cw * scale)
            new_h = int(ch * scale)
            cropped = cropped.resize((new_w, new_h), Image.LANCZOS)
        url = _save_image(cropped, upload_dir, prefix="crop")
        return url

    loop = asyncio.get_event_loop()
    url = await loop.run_in_executor(None, _do_crop)

    logger.info("[image_processor] 裁剪完成: region=%s -> %s", region, url)
    return {"url": url}
