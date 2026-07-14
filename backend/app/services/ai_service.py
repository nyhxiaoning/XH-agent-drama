import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── LLM 废弃模型拦截（唯一拦截点） ──
# 所有 LLM 调用的唯一必经之路：AIService.chat() / chat_stream()
# 用硬编码集合判断，不查数据库，零延迟，零依赖。
# 用户可自由选择数据库中任何已启用的 LLM 模型，只有 DEPRECATED_MODELS 中的才会被拦截。


def _sanitize_llm_model(model_id: Optional[str]) -> str:
    """拦截已废弃的 LLM 模型 ID，替换为硬编码的安全默认模型。

    不依赖 .env 配置，防止 .env 中 LLM_MODEL_NAME 本身就是废弃模型导致死循环：
    - model_id 为 None/空 → 返回硬编码安全模型 gpt-5.6-terra
    - model_id 在 DEPRECATED_MODELS 中 → 返回硬编码安全模型 gpt-5.6-terra，打日志
    - .env 中的 LLM_MODEL_NAME 本身是废弃模型 → 也拦截，返回 gpt-5.6-terra
    - 其他情况 → 原样返回（用户自由选择的模型直接放行）
    """
    SAFE_DEFAULT = "gpt-5.6-terra"

    if not model_id:
        # .env 中的 LLM_MODEL_NAME 如果也是废弃模型，就用硬编码安全值
        env_model = settings.LLM_MODEL_NAME
        if env_model and env_model not in settings.DEPRECATED_MODELS:
            return env_model
        return SAFE_DEFAULT

    if model_id in settings.DEPRECATED_MODELS:
        logger.warning("[AIService] 拦截废弃模型 %s → %s", model_id, SAFE_DEFAULT)
        return SAFE_DEFAULT

    return model_id


# 与 main.py / asset.py / ai_worker.py 保持一致的 uploads 根目录：backend/app/uploads
# ai_service.py 位于 backend/app/services/ai_service.py
# os.path.dirname(os.path.dirname(__file__)) = backend/app
_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")

# 万相 2.7 默认模型 ID（可在调用时通过 options 覆盖）
WAN27_I2V_DASHSCOPE_MODEL = "wan2.7-i2v-2026-04-25"
WAN27_T2V_DASHSCOPE_MODEL = "wan2.7-t2v-2026-04-25"
WAN27_R2V_DASHSCOPE_MODEL = "wan2.7-r2v"


def _is_placeholder_key(key: Optional[str]) -> bool:
    return not key or "YOUR_" in key


def _nested_url(obj: Any) -> Optional[str]:
    """从嵌套对象中提取 url 字段，兼容 fal.ai 的 {"video": {"url": "..."}} 格式。"""
    if isinstance(obj, str) and obj.startswith(("http://", "https://")):
        return obj
    if isinstance(obj, dict):
        return obj.get("url") or obj.get("video_url") or obj.get("download_url")
    return None


def _public_url(url: str) -> str:
    """把 /uploads 或 /api/uploads 相对地址补全为 PUBLIC_BASE_URL 绝对地址。"""
    if not isinstance(url, str):
        return url
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{url}"
    return url


def _is_local_or_localhost(url: str) -> bool:
    """判断 URL 是否为本地路径或 localhost 内网地址（火山方舟服务器无法访问）。"""
    if not isinstance(url, str):
        return False
    low = url.lower()
    return (
        low.startswith("/static/")
        or low.startswith("/uploads/")
        or low.startswith("/api/uploads/")
        or "://localhost" in low
        or "://127.0.0.1" in low
        or "://0.0.0.0" in low
    )


async def _to_public_cos_url(url: str, prefix: str = "seedance-ref") -> str:
    """把本地路径/localhost URL 转存到腾讯云 COS，返回公网可访问 URL。

    火山方舟 Seedance 2.0 服务器在公网，无法访问本地 localhost 或内网地址，
    报错 "resource download failed" 或 "image_url is not valid"。
    本函数把本地资源上传到 COS 后返回公网 URL。
    已是公网 URL（含 COS）则原样返回。
    COS 转存失败时，回退到 PUBLIC_BASE_URL 绝对地址（比相对路径更可能被 Ark 接受）。
    """
    if not isinstance(url, str) or not url.strip():
        return url
    # 已是公网可访问 URL（含 COS myqcloud.com）直接返回
    if not _is_local_or_localhost(url):
        return url

    # COS 未配置则回退到 PUBLIC_BASE_URL 绝对地址
    if not settings.TENCENT_COS_SECRET_ID or not settings.TENCENT_COS_SECRET_KEY:
        fallback = _public_url(url)
        logger.warning("[AIService] COS 未配置，本地参考图回退到绝对地址: %s -> %s", url, fallback)
        return fallback

    import asyncio
    import mimetypes
    from app.services.cos_service import upload_to_cos_dedup

    loop = asyncio.get_event_loop()

    # 优先直接读本地磁盘上传 COS（使用绝对路径，与 main.py 一致）
    local_disk_path: Optional[str] = None
    if url.startswith("/static/"):
        # /static/generated/xxx.png -> backend/app/uploads/generated/xxx.png
        local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/static/"):])
    elif url.startswith("/api/uploads/"):
        local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/api/uploads/"):])
    elif url.startswith("/uploads/"):
        local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/uploads/"):])

    if local_disk_path and os.path.isfile(local_disk_path):
        try:
            ext = os.path.splitext(local_disk_path)[1].lstrip(".") or "png"
            mime = mimetypes.guess_type(local_disk_path)[0] or "image/png"

            def _read_and_upload_dedup():
                with open(local_disk_path, "rb") as f:
                    content = f.read()
                return upload_to_cos_dedup(content, prefix, mime, ext)
            cos_url = await loop.run_in_executor(None, _read_and_upload_dedup)
            if cos_url:
                logger.info("[AIService] 参考图直传 COS 成功（MD5去重）: %s -> %s", url, cos_url)
                return cos_url
            logger.warning("[AIService] 参考图直传 COS 返回空，回退到绝对地址: %s", url)
        except Exception as exc:
            logger.error("[AIService] 参考图直传 COS 失败，尝试 HTTP 下载兜底: %s err=%s", url, exc)
            # 落到下面的 HTTP 下载兜底
            local_disk_path = None

    # 兜底：通过 HTTP 下载（需后端服务运行）再上传 COS
    if local_disk_path is None:
        local_abs = _public_url(url)
        try:
            from app.services.cos_service import cache_url_to_cos
            cos_url = await loop.run_in_executor(None, cache_url_to_cos, local_abs, prefix)
            if cos_url:
                logger.info("[AIService] 参考图 HTTP 转存 COS 成功: %s -> %s", url, cos_url)
                return cos_url
            logger.warning("[AIService] 参考图 HTTP 转存 COS 返回空，回退到绝对地址: %s", url)
        except Exception as exc:
            logger.error("[AIService] 参考图 HTTP 转存 COS 失败，回退到绝对地址: %s err=%s", url, exc)

    # 所有 COS 转存均失败：至少返回绝对 URL（PUBLIC_BASE_URL + 相对路径），
    # 避免发送 /static/xxx 相对路径给 Ark 导致 "image_url is not valid" 400 错误
    return _public_url(url)


def _join_url(base: str, endpoint: str) -> str:
    return base.rstrip("/") + "/" + endpoint.lstrip("/")


def _get_option(options: Dict[str, Any], snake: str, camel: Optional[str] = None, default: Any = None) -> Any:
    if snake in options:
        return options[snake]
    if camel is not None and camel in options:
        return options[camel]
    return default


def _wan27_video_ratio(aspect_ratio: Optional[str]) -> str:
    r = str(aspect_ratio or "16:9").strip()
    return r if r in {"16:9", "9:16", "1:1", "4:3", "3:4"} else "16:9"


def _wan27_video_resolution(resolution: Optional[str]) -> str:
    return "720P" if str(resolution or "").strip().upper() == "720P" else "1080P"


def _resolve_wan27_route(client_model: str, ref_count: int, video_count: int) -> str:
    m = client_model.lower()
    if m == "wan2.7-t2v":
        return "t2v"
    if m == "wan2.7-r2v":
        return "r2v"
    if m == "wan2.7-i2v":
        return "i2v"
    if ref_count == 0 and video_count == 0:
        return "t2v"
    if video_count >= 2 or ref_count >= 3:
        return "r2v"
    if video_count == 1 and ref_count <= 2:
        return "i2v"
    if video_count == 0 and ref_count <= 2:
        return "i2v"
    if video_count == 1 and ref_count > 2:
        return "r2v"
    return "r2v"


def _compute_seedream_size(ar: str, res_level: str, is_pro: bool) -> str:
    """根据宽高比和分辨率等级计算 Seedream API 的 size 参数（像素维度 WxH）。

    使用 API 方式 1（指定宽高像素值）确保比例精确控制。
    方式 2（"1K"/"2K"/"4K" 简写）无法指定宽高比，模型自行判断比例。

    For 5.0 Pro: 总像素范围 [3,686,400, 16,777,216]
    For Lite/4.5/4.0: 总像素范围 [921,600, 4,624,220]
    """
    if is_pro:
        size_table = {
            "1K": {
                "1:1": "2048x2048",
                "16:9": "2560x1440",
                "9:16": "1440x2560",
                "4:3": "2304x1728",
                "3:4": "1728x2304",
                "21:9": "3072x1320",
            },
            "2K": {
                "1:1": "2880x2880",
                "16:9": "3840x2160",
                "9:16": "2160x3840",
                "4:3": "3456x2592",
                "3:4": "2592x3456",
                "21:9": "4608x1984",
            },
            "4K": {
                "1:1": "4096x4096",
                "16:9": "4096x2304",
                "9:16": "2304x4096",
                "4:3": "4096x3072",
                "3:4": "3072x4096",
                "21:9": "4096x1760",
            },
        }
    else:
        # Lite/4.5/4.0: 像素上限 ~4.6M，4K 降级为 2K 维度
        size_table = {
            "1K": {
                "1:1": "1024x1024",
                "16:9": "1280x720",
                "9:16": "720x1280",
                "4:3": "1152x864",
                "3:4": "864x1152",
                "21:9": "1536x640",
            },
            "2K": {
                "1:1": "2048x2048",
                "16:9": "2560x1440",
                "9:16": "1440x2560",
                "4:3": "2304x1728",
                "3:4": "1728x2304",
                "21:9": "3072x1320",
            },
            "4K": {
                "1:1": "2048x2048",
                "16:9": "2560x1440",
                "9:16": "1440x2560",
                "4:3": "2304x1728",
                "3:4": "1728x2304",
                "21:9": "3072x1320",
            },
        }

    sizes = size_table.get(res_level, size_table["1K"])
    return sizes.get(ar, sizes["1:1"])


class AIService:
    """AI 服务封装：LLM Chat、图片生成、视频生成及任务状态查询。"""

    @staticmethod
    async def _to_data_url(url: str) -> str:
        """将图片 URL 转换为 data URL（供 91API/Gemini 图生图使用）。

        优先读取本地磁盘文件（避免 HTTP 下载依赖 PUBLIC_BASE_URL 可达），
        本地文件不存在时再通过 HTTP 下载。
        """
        if url.startswith("data:"):
            return url

        import base64
        import mimetypes

        # 优先读取本地磁盘文件（使用绝对路径，与 main.py 的 StaticFiles 挂载点一致）
        local_disk_path: Optional[str] = None
        if url.startswith("/static/"):
            local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/static/"):])
        elif url.startswith("/api/uploads/"):
            local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/api/uploads/"):])
        elif url.startswith("/uploads/"):
            local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/uploads/"):])

        if local_disk_path and os.path.isfile(local_disk_path):
            try:
                with open(local_disk_path, "rb") as f:
                    content = f.read()
                mime = mimetypes.guess_type(local_disk_path)[0] or "image/png"
                b64 = base64.b64encode(content).decode("ascii")
                logger.info("[AIService] _to_data_url 本地读取成功: %s (%d bytes)", url, len(content))
                return f"data:{mime};base64,{b64}"
            except Exception as exc:
                logger.warning("[AIService] _to_data_url 本地读取失败，回退到 HTTP: %s err=%s", url, exc)

        # 回退：通过 HTTP 下载（COS公网URL或其他远程URL）
        abs_url = _public_url(url)
        logger.info("[AIService] _to_data_url HTTP 下载: %s -> %s", url[:100], abs_url[:100])
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(abs_url, timeout=120)
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
                b64 = base64.b64encode(resp.content).decode("ascii")
                logger.info("[AIService] _to_data_url HTTP 下载成功: %s (%d bytes, %s)", abs_url[:80], len(resp.content), mime)
                return f"data:{mime};base64,{b64}"
        except Exception as exc:
            logger.error("[AIService] _to_data_url HTTP 下载失败: %s -> %s err=%s", url[:100], abs_url[:100], exc)
            raise

    @staticmethod
    async def _post(endpoint: str, data: Dict[str, Any], api_type: str) -> Any:
        """向指定 AI 网关发起 POST 请求。"""
        if api_type == "ark":
            base_url = settings.VOLCENGINE_ARK_API_BASE_URL
            api_key = settings.VOLCENGINE_ARK_API_KEY
            if _is_placeholder_key(api_key):
                raise RuntimeError("请在 .env 中配置 VOLCENGINE_ARK_API_KEY")
        elif api_type == "dashscope":
            base_url = settings.DASHSCOPE_API_BASE_URL
            api_key = settings.DASHSCOPE_API_KEY
            if _is_placeholder_key(api_key):
                raise RuntimeError("请在 .env 中配置 DASHSCOPE_API_KEY")
        elif api_type == "api91":
            base_url = settings.API91_BASE_URL
            api_key = settings.API91_API_KEY
            if _is_placeholder_key(api_key):
                raise RuntimeError("请在 .env 中配置 API91_API_KEY")
        elif api_type == "modelink":
            base_url = settings.MODELINK_API_BASE_URL
            api_key = settings.MODELINK_API_KEY
            if _is_placeholder_key(api_key):
                raise RuntimeError("请在 .env 中配置 MODELINK_API_KEY")
        else:
            raise ValueError(f"不支持的 API 类型: {api_type}")

        url = _join_url(base_url, endpoint)
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_type == "dashscope":
            headers["Authorization"] = f"Bearer {api_key}"
            if "video-synthesis" in endpoint:
                headers["X-DashScope-Async"] = "enable"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        # LLM 对话超时根据 max_tokens 动态计算：
        #   基础 120s + 每 4096 tokens 额外 60s，上限 600s（10 分钟）
        #   这样 max_tokens=4096 → 180s, max_tokens=8192 → 240s, max_tokens=16384 → 360s
        # 生图用 300 秒（5 分钟）；生视频用 3000 秒
        is_chat = "/v1/chat/completions" in endpoint
        is_image = "/images/" in endpoint or "/gemini/" in endpoint
        if is_chat:
            max_tok = int(data.get("max_tokens") or 4096)
            chat_read_timeout = min(120.0 + (max_tok / 4096.0) * 60.0, 600.0)
            read_timeout = chat_read_timeout
        elif is_image:
            read_timeout = 300.0
        else:
            read_timeout = 3000.0
        timeout = httpx.Timeout(
            connect=10.0,   # 连接建立超时 10 秒（DNS + TCP + TLS）
            read=read_timeout,
            write=30.0,     # 发送请求超时 30 秒
            pool=5.0,       # 连接池获取超时 5 秒
        )

        model_name = str(data.get("model", ""))
        logger.info("[AIService] POST %s (type=%s, model=%s, timeout=%ss, max_tokens=%s)", url, api_type, model_name, timeout.read, data.get("max_tokens"))
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            ) as client:
                resp = await client.post(url, json=data, headers=headers)
                resp.raise_for_status()
                # 先读取文本，JSON 解析失败时能记录响应体用于排查
                resp_text = resp.text
                try:
                    return resp.json()
                except Exception as json_exc:
                    logger.error(
                        "[AIService] JSON parse failed: url=%s status=%s body[:500]=%s err=%s",
                        url, resp.status_code, resp_text[:500], json_exc,
                    )
                    raise RuntimeError(
                        f"API 返回非 JSON 响应 (status={resp.status_code}): {resp_text[:300]}"
                    ) from json_exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[AIService] API error: status=%s url=%s response=%s",
                exc.response.status_code,
                url,
                exc.response.text[:1000],
            )
            raise RuntimeError(f"AI 服务请求失败 ({exc.response.status_code}): {exc.response.text[:500]}") from exc
        except httpx.TimeoutException as exc:
            # 超时类异常：ReadTimeout, ConnectTimeout, WriteTimeout, PoolTimeout
            exc_type = type(exc).__name__
            logger.error("[AIService] 请求超时: url=%s type=%s model=%s err=%s", url, exc_type, model_name, exc)
            raise RuntimeError(f"AI 服务请求超时 ({exc_type}): 请求 {model_name} 超时（url={url}），请检查网络或减少输出长度") from exc
        except httpx.ConnectError as exc:
            # 连接类异常：DNS 解析失败、连接被拒绝等
            logger.error("[AIService] 连接失败: url=%s model=%s err=%s", url, model_name, exc)
            raise RuntimeError(f"AI 服务连接失败 (ConnectError): 无法连接到 {url}（model={model_name}），请检查网络/DNS/API地址配置") from exc
        except httpx.HTTPError as exc:
            # 其他 httpx 异常（TransportError 等）
            exc_type = type(exc).__name__
            logger.error("[AIService] HTTP 错误: url=%s type=%s err=%s", url, exc_type, exc)
            raise RuntimeError(f"AI 服务 HTTP 错误 ({exc_type}): {exc}") from exc
        except Exception as exc:
            exc_type = type(exc).__name__
            logger.error("[AIService] API error: url=%s type=%s err=%s", url, exc_type, exc)
            raise RuntimeError(f"AI 服务请求异常 ({exc_type}): {exc}") from exc

    @staticmethod
    async def _post_multipart(endpoint: str, fields: Dict[str, Any], file_field: str, file_bytes: bytes, file_name: str, file_content_type: str, api_type: str = "api91") -> Any:
        """向 AI 网关发起 multipart/form-data POST 请求（用于 /v1/images/edits 等需要文件上传的端点）。

        Args:
            endpoint: API 端点路径
            fields: 普通表单字段（prompt, model, n, size 等）
            file_field: 文件字段名（通常是 "image"）
            file_bytes: 文件二进制内容
            file_name: 文件名（如 "reference.png"）
            file_content_type: 文件 MIME 类型
            api_type: API 类型
        """
        if api_type == "api91":
            base_url = settings.API91_BASE_URL
            api_key = settings.API91_API_KEY
            if _is_placeholder_key(api_key):
                raise RuntimeError("请在 .env 中配置 API91_API_KEY")
        else:
            raise ValueError(f"不支持的 API 类型: {api_type}")

        url = _join_url(base_url, endpoint)
        headers: Dict[str, str] = {"Authorization": f"Bearer {api_key}"}
        # 注意：multipart/form-data 的 Content-Type 由 httpx 自动生成（含 boundary）
        # 不要手动设置 Content-Type，否则 boundary 会丢失

        timeout = httpx.Timeout(connect=10.0, read=300.0, write=120.0, pool=5.0)
        model_name = str(fields.get("model", ""))
        logger.info("[AIService] POST(multipart) %s (model=%s, file=%s %d bytes)", url, model_name, file_name, len(file_bytes))
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            ) as client:
                resp = await client.post(
                    url,
                    data=fields,
                    files={file_field: (file_name, file_bytes, file_content_type)},
                    headers=headers,
                )
                resp.raise_for_status()
                resp_text = resp.text
                try:
                    return resp.json()
                except Exception as json_exc:
                    logger.error(
                        "[AIService] multipart JSON parse failed: url=%s status=%s body[:500]=%s err=%s",
                        url, resp.status_code, resp_text[:500], json_exc,
                    )
                    raise RuntimeError(
                        f"API 返回非 JSON 响应 (status={resp.status_code}): {resp_text[:300]}"
                    ) from json_exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[AIService] multipart API error: status=%s url=%s response=%s",
                exc.response.status_code, url, exc.response.text[:1000],
            )
            raise RuntimeError(f"AI 服务请求失败 ({exc.response.status_code}): {exc.response.text[:500]}") from exc
        except httpx.TimeoutException as exc:
            exc_type = type(exc).__name__
            logger.error("[AIService] multipart 请求超时: url=%s type=%s model=%s err=%s", url, exc_type, model_name, exc)
            raise RuntimeError(f"AI 服务请求超时 ({exc_type}): 请求 {model_name} 超时（url={url}）") from exc
        except httpx.ConnectError as exc:
            logger.error("[AIService] multipart 连接失败: url=%s model=%s err=%s", url, model_name, exc)
            raise RuntimeError(f"AI 服务连接失败 (ConnectError): 无法连接到 {url}") from exc
        except httpx.HTTPError as exc:
            exc_type = type(exc).__name__
            logger.error("[AIService] multipart HTTP 错误: url=%s type=%s err=%s", url, exc_type, exc)
            raise RuntimeError(f"AI 服务 HTTP 错误 ({exc_type}): {exc}") from exc
        except Exception as exc:
            exc_type = type(exc).__name__
            logger.error("[AIService] multipart API error: url=%s type=%s err=%s", url, exc_type, exc)
            raise RuntimeError(f"AI 服务请求异常 ({exc_type}): {exc}") from exc

    @staticmethod
    def _normalize_image_response(response: Any) -> Any:
        if isinstance(response, dict) and isinstance(response.get("data"), list) and response["data"]:
            images = [
                {"url": item.get("url") or item.get("b64_json")}
                for item in response["data"]
                if item.get("url") or item.get("b64_json")
            ]
            if images:
                return {"data": images}
        return response

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    @staticmethod
    async def chat(messages: List[Dict[str, Any]], model: Optional[str] = None, max_tokens: Optional[int] = None, temperature: float = 0.3) -> Any:
        """OpenAI 兼容的 LLM 对话，默认走火山引擎 Ark，可切换至 91API。

        Args:
            max_tokens: 限制输出 token 数，None 时使用默认值 4096。
            temperature: 采样温度，默认 0.3（偏低，适合结构化 JSON 输出，减少发散缩短输出长度）。
        """
        raw_model = model
        model = _sanitize_llm_model(model)
        logger.warning("[AIService] chat() 模型解析: 输入=%s → 实际发送=%s", raw_model, model)
        provider = str(settings.LLM_PROVIDER or "ark").lower()
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        result = await AIService._post("/v1/chat/completions", payload, provider if provider in ("ark", "api91") else "ark")
        # 记录 API 返回的实际模型名（API 服务商可能在后端做了别名映射）
        if isinstance(result, dict):
            resp_model = result.get("model", "")
            if resp_model and resp_model != model:
                logger.warning("[AIService] ⚠️ API 返回模型名与请求不一致! 请求=%s → API返回=%s（可能是服务商别名映射）", model, resp_model)
        return result

    @staticmethod
    async def chat_stream(
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
    ):
        """#16 LLM 流式输出：逐 token 返回 LLM 生成内容。

        Yields:
            str: 每个 delta content chunk
        """
        model = _sanitize_llm_model(model)
        logger.warning("[AIService] chat_stream() 模型: %s", model)
        provider = str(settings.LLM_PROVIDER or "ark").lower()
        api_type = provider if provider in ("ark", "api91") else "ark"

        if api_type == "ark":
            base_url = settings.VOLCENGINE_ARK_API_BASE_URL
            api_key = settings.VOLCENGINE_ARK_API_KEY
        elif api_type == "api91":
            base_url = settings.API91_BASE_URL
            api_key = settings.API91_API_KEY
        else:
            base_url = settings.VOLCENGINE_ARK_API_BASE_URL
            api_key = settings.VOLCENGINE_ARK_API_KEY

        url = _join_url(base_url, "/v1/chat/completions")
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
            "stream": True,
        }

        max_tok = int(payload.get("max_tokens") or 4096)
        read_timeout = min(120.0 + (max_tok / 4096.0) * 60.0, 600.0)
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=5.0)

        logger.info("[AIService] STREAM POST %s (model=%s, max_tokens=%s)", url, model, payload["max_tokens"])
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            ) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue
        except httpx.HTTPStatusError as exc:
            logger.error("[AIService] Stream API error: status=%s url=%s", exc.response.status_code, url)
            raise RuntimeError(f"AI 服务流式请求失败 ({exc.response.status_code})") from exc
        except httpx.TimeoutException as exc:
            exc_type = type(exc).__name__
            logger.error("[AIService] Stream 请求超时: url=%s type=%s", url, exc_type)
            raise RuntimeError(f"AI 服务流式请求超时 ({exc_type})") from exc
        except Exception as exc:
            exc_type = type(exc).__name__
            logger.error("[AIService] Stream 请求异常: url=%s type=%s err=%s", url, exc_type, exc)
            raise RuntimeError(f"AI 服务流式请求异常 ({exc_type}): {exc}") from exc

    # ------------------------------------------------------------------
    # Image Generation
    # 91API 网关 Gemini 模型默认名（实际调用时以用户选择的 model 参数为准）
    _GEMINI_MODEL = "gemini-3.1-flash-lite-image"

    @staticmethod
    async def generate_image(prompt: str, model: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Any:
        options = options or {}
        model = model or settings.IMAGE_MODEL_GPT_IMAGE_2
        normalized = model.lower()

        # 豆包 Seedream 系列走火山方舟 Ark API
        if "seedream" in normalized:
            return await AIService._generate_image_ark(prompt, model, options)

        # Gemini 系列走专用通道（yunwu.ai 不支持 /v1/images/generations 端点调用 Gemini）
        # 需要走 Gemini 原生 generateContent 端点或 chat/completions
        if "gemini" in normalized:
            return await AIService._generate_image_gemini(prompt, model, options)

        known_models = {
            settings.IMAGE_MODEL_GPT_IMAGE_2.lower(),
            settings.IMAGE_MODEL_GEMINI_FLASH_IMAGE.lower(),
            "gemini-3.1-flash-lite-image",
        }
        if normalized not in known_models and not normalized.endswith("-91api"):
            raise ValueError(f"不支持的图像模型: {model}")

        # GPT Image 等非 Gemini 模型走 91API /v1/images/generations 端点
        return await AIService._generate_image_91api(prompt, model, options)

    @staticmethod
    async def _generate_image_ark(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """调用火山方舟 Ark API 豆包 Seedream 系列文生图模型。

        API 端点: POST /api/v3/images/generations  (OpenAI 兼容格式)
        鉴权: Bearer ARK_API_KEY

        支持功能:
          - 文生图 (text-to-image): 仅传 prompt
          - 图生图 (image-to-image): 传 image 字段为参考图 URL 或 Base64
          - 水印控制: watermark true/false
          - 分辨率+宽高比: size 参数使用 "WxH" 像素维度精确控制
          - 输出格式: response_format "url" 或 "b64_json"
          - output_format: "png"/"jpeg"/"webp" (仅 5.0 Pro/5.0 Lite)
          - 组图控制: sequential_image_generation "auto"/"disabled"

        注意: Seedream 5.0 Pro 不支持 negative_prompt、seed、stream 参数，
        传参会报错。negative_prompt 会追加到 prompt 中作为自然语言指令。
        """
        ar = _get_option(options, "aspect_ratio", "aspectRatio", "1:1")
        refs_raw = _get_option(options, "reference_images", "referenceImages", []) or []
        refs = [u for u in refs_raw if isinstance(u, str) and u.strip()]
        negative = _get_option(options, "negative_prompt", "negativePrompt", "")
        watermark_raw = _get_option(options, "watermark", "watermark", False)
        mask_url = _get_option(options, "mask_url", "maskDataUrl", "") or _get_option(options, "mask", "maskDataUrl", "")
        resolution = _get_option(options, "resolution", "resolution", "")

        normalized_model = model.lower()
        is_pro = "pro" in normalized_model

        # 水印布尔值处理：前端可能传 "无水印"/"有水印" 字符串
        if isinstance(watermark_raw, str):
            watermark = "有水印" in watermark_raw
        else:
            watermark = bool(watermark_raw)

        # 分辨率等级：默认 1K
        res_level = "1K"
        if resolution:
            res_upper = str(resolution).strip().upper()
            if res_upper in ("2K", "4K", "1K"):
                res_level = res_upper
            elif "2160" in res_upper or "4K" in res_upper:
                res_level = "4K"
            elif "1080" in res_upper or "720" in res_upper or "480" in res_upper:
                res_level = "1K"
            # 其他值保持默认 1K

        # 根据宽高比 + 分辨率等级计算精确像素维度（方式 1）
        size = _compute_seedream_size(ar, res_level, is_pro)

        # negative_prompt 不被 API 支持，追加到 prompt 中
        final_prompt = prompt
        if negative:
            final_prompt = f"{prompt}\n\n[避免以下元素: {negative}]"

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": final_prompt,
            "size": size,
            "response_format": "url",
            "watermark": watermark,
        }

        # sequential_image_generation 仅 Lite/4.5/4.0 支持，Pro 不支持传参会报错
        if not is_pro:
            payload["sequential_image_generation"] = "disabled"

        # output_format 仅 5.0 Pro 和 5.0 Lite 支持
        if is_pro or "5-0" in normalized_model or "5.0" in normalized_model:
            payload["output_format"] = "png"

        # 图生图：参考图需公网可访问 URL 或 Base64 data URL
        if refs:
            ref_urls = []
            for u in refs[:10]:
                # 先尝试 COS 转存（如果配置了 COS）
                pub_url = await _to_public_cos_url(u, "seedream-ref")
                if pub_url and pub_url.startswith(("http://", "https://")) and not _is_local_or_localhost(pub_url):
                    ref_urls.append(pub_url)
                elif pub_url and pub_url.startswith(("http://", "https://")):
                    # COS 未配置，回退到了 localhost URL — Ark 服务器无法访问
                    # 转为 data URL（base64），Ark API 支持 image 字段传 Base64
                    logger.info("[AIService] Seedream 参考图 COS 不可用，转为 data URL: %s", u)
                    try:
                        data_url = await AIService._to_data_url(u)
                        ref_urls.append(data_url)
                    except Exception as exc:
                        logger.warning("[AIService] Seedream 参考图转 data URL 也失败，已跳过: %s err=%s", u, exc)
                else:
                    logger.warning("[AIService] Seedream 参考图 URL 无效，已跳过: %s -> %s", u, pub_url)
            logger.info("[AIService] Seedream refs=%d 成功转换=%d", len(refs), len(ref_urls))
            if ref_urls:
                payload["image"] = ref_urls[0] if len(ref_urls) == 1 else ref_urls
                logger.info("[AIService] Ark Seedream 图生图 refs=%d", len(ref_urls))

        # 局部重绘 mask：API 文档未列出 mask 参数，暂不发送
        if mask_url and mask_url.strip():
            logger.info("[AIService] Ark Seedream 局部重绘 mask=yes (API暂不支持独立mask参数)")

        logger.info("[AIService] Ark Seedream 生图请求 model=%s size=%s ar=%s res=%s refs=%d", model, size, ar, res_level, len(refs))
        response = await AIService._post("/images/generations", payload, "ark")
        return AIService._normalize_image_response(response)

    @staticmethod
    async def _to_gemini_inline_data(url: str) -> Optional[Dict[str, Any]]:
        """将图片 URL 转为 Gemini 原生 API 的 inline_data 格式。

        优先读取本地磁盘文件，本地不存在时再通过 HTTP 下载。
        """
        if not url or not url.strip():
            return None
        url = url.strip()
        if url.startswith("data:image/"):
            import re
            m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", url)
            if not m:
                return None
            return {"inline_data": {"mime_type": m.group(1), "data": m.group(2)}}

        import base64
        import mimetypes

        # 优先读取本地磁盘文件（使用绝对路径）
        local_disk_path: Optional[str] = None
        if url.startswith("/static/"):
            local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/static/"):])
        elif url.startswith("/api/uploads/"):
            local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/api/uploads/"):])
        elif url.startswith("/uploads/"):
            local_disk_path = os.path.join(_UPLOADS_DIR, url[len("/uploads/"):])

        if local_disk_path and os.path.isfile(local_disk_path):
            try:
                with open(local_disk_path, "rb") as f:
                    content = f.read()
                mime = mimetypes.guess_type(local_disk_path)[0] or "image/png"
                b64 = base64.b64encode(content).decode("ascii")
                logger.info("[AIService] Gemini inline_data 本地读取成功: %s (%d bytes)", url, len(content))
                return {"inline_data": {"mime_type": mime, "data": b64}}
            except Exception as exc:
                logger.warning("[AIService] Gemini inline_data 本地读取失败，回退到 HTTP: %s err=%s", url, exc)

        # 回退：通过 HTTP 下载（COS公网URL或其他远程URL）
        abs_url = _public_url(url)
        logger.info("[AIService] Gemini inline_data HTTP 下载: %s -> %s", url[:100], abs_url[:100])
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(abs_url, timeout=120)
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
                b64 = base64.b64encode(resp.content).decode("ascii")
                logger.info("[AIService] Gemini inline_data HTTP 下载成功: %s (%d bytes, %s)", abs_url[:80], len(resp.content), mime)
                return {"inline_data": {"mime_type": mime, "data": b64}}
        except Exception as exc:
            logger.warning("[AIService] Failed to fetch reference image for Gemini: %s -> %s err=%s", url[:100], abs_url[:100], exc)
            return None

    @staticmethod
    async def _generate_image_gemini(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """调用 Gemini 图片模型生图（Nano Banana Lite）。

        91API (yunwu.ai) 对 Gemini 图片模型仅支持两个端点：
          1. gemini/v1beta/models/{model}:generateContent  (Gemini 原生)
          2. /v1/chat/completions                          (OpenAI 兼容对话)
        不支持 /v1/images/generations。

        策略：先尝试 Gemini 原生端点，失败则回退到 chat/completions。
        """
        last_error = None

        # ---- 尝试 1：Gemini 原生端点 ----
        try:
            result = await AIService._generate_image_gemini_native(prompt, model, options)
            if result:
                return result
        except Exception as exc:
            last_error = exc
            logger.warning("[AIService] Gemini 原生端点失败，回退到 chat/completions: %s", exc)

        # ---- 尝试 2：OpenAI 兼容 chat/completions ----
        try:
            return await AIService._generate_image_gemini_chat(prompt, model, options)
        except Exception as exc:
            logger.error("[AIService] Gemini chat/completions 也失败: %s", exc)
            raise RuntimeError(
                f"Gemini 生图失败（原生端点 + chat/completions 均失败）。"
                f"原生端点错误: {last_error}; chat 错误: {exc}"
            ) from exc

    @staticmethod
    async def _generate_image_gemini_native(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """通过 Gemini 原生 generateContent 端点生图。"""
        ar = _get_option(options, "aspect_ratio", "aspectRatio", "1:1")
        refs_raw = _get_option(options, "reference_images", "referenceImages", []) or []
        # 不调用 _public_url，保留原始路径让 _to_gemini_inline_data 优先读本地磁盘
        refs = [u for u in refs_raw if isinstance(u, str) and u.strip()]

        gemini_prompt = prompt
        if ar and ar != "1:1":
            gemini_prompt = f"{prompt}\n\n[Output requirement] Final image MUST be {ar}."

        parts: List[Dict[str, Any]] = [{"text": gemini_prompt}]
        if refs:
            ref_inline = []
            for u in refs[:14]:
                data = await AIService._to_gemini_inline_data(u)
                if data:
                    ref_inline.append(data)
                else:
                    logger.warning("[AIService] Gemini 参考图转换失败，已跳过: %s", u)
            logger.info("[AIService] Gemini refs=%d 成功转换=%d", len(refs), len(ref_inline))
            if ref_inline:
                parts.extend(ref_inline)
                parts[0]["text"] = (
                    f"{gemini_prompt}\n\n[Reference Strictness] Use reference image(s) "
                    "as primary source and keep character identity/face/costume/style consistent."
                )

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
        }

        raw_model = model.lower()
        if raw_model.endswith("-91api"):
            raw_model = raw_model[:-6]
        endpoint = f"/gemini/v1beta/models/{raw_model}:generateContent"
        logger.info("[AIService] Gemini native image request (model=%s, refs=%d)", raw_model, len(refs))
        resp = await AIService._post(endpoint, payload, "api91")

        # 解析 Gemini 原生返回，提取 base64 图片
        parts_out = []
        if isinstance(resp, dict):
            candidates = resp.get("candidates") or []
            if candidates and isinstance(candidates[0], dict):
                content = candidates[0].get("content") or {}
                parts_out = content.get("parts") or []
        for p in parts_out:
            if not isinstance(p, dict):
                continue
            b64 = (p.get("inlineData") or {}).get("data") or (p.get("inline_data") or {}).get("data") or p.get("data")
            if isinstance(b64, str) and len(b64) > 100:
                return {"data": [{"url": f"data:image/png;base64,{b64}"}]}
        # 兜底：有些网关把 base64 放在 text 字段
        for p in parts_out:
            if not isinstance(p, dict):
                continue
            text = p.get("text")
            if isinstance(text, str) and len(text) > 200 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in text):
                return {"data": [{"url": f"data:image/png;base64,{text}"}]}
        logger.warning("[AIService] Gemini native response has no image data, raw=%s", str(resp)[:500])
        raise RuntimeError(f"Gemini 原生端点未返回图片数据，响应: {str(resp)[:300]}")

    @staticmethod
    async def _generate_image_gemini_chat(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """通过 OpenAI 兼容 /v1/chat/completions 端点调用 Gemini 图片模型。

        Gemini 图片模型支持在对话中生成图片，响应中会包含 base64 图片数据。
        """
        import re as _re

        ar = _get_option(options, "aspect_ratio", "aspectRatio", "1:1")
        refs_raw = _get_option(options, "reference_images", "referenceImages", []) or []
        # 不调用 _public_url，保留原始路径让 _to_data_url 优先读本地磁盘
        refs = [u for u in refs_raw if isinstance(u, str) and u.strip()]

        text_prompt = prompt
        if ar and ar != "1:1":
            text_prompt = f"{prompt}\n\n[Output requirement] Final image MUST be {ar}."
        if refs:
            text_prompt += (
                "\n\n[Reference Strictness] Use reference image(s) as primary source "
                "and keep character identity/face/costume/style consistent."
            )

        # 构建多模态消息内容
        content: List[Dict[str, Any]] = [{"type": "text", "text": text_prompt}]
        if refs:
            for u in refs[:14]:
                data_url = await AIService._to_data_url(u)
                content.append({"type": "image_url", "image_url": {"url": data_url}})

        raw_model = model.lower()
        if raw_model.endswith("-91api"):
            raw_model = raw_model[:-6]

        payload: Dict[str, Any] = {
            "model": raw_model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        }

        logger.info("[AIService] Gemini image via chat/completions (model=%s, refs=%d)", raw_model, len(refs))
        resp = await AIService._post("/v1/chat/completions", payload, "api91")

        # 解析响应，灵活提取图片数据
        if not isinstance(resp, dict):
            raise RuntimeError(f"Gemini chat 返回非 dict: {str(resp)[:300]}")

        choices = resp.get("choices") or []
        if not choices:
            raise RuntimeError(f"Gemini chat 返回无 choices: {str(resp)[:300]}")

        message = choices[0].get("message") or {}
        msg_content = message.get("content")

        # Case 1: content 是列表（多模态响应）
        if isinstance(msg_content, list):
            for part in msg_content:
                if not isinstance(part, dict):
                    continue
                # image_url 格式
                img_url = (part.get("image_url") or {}).get("url")
                if img_url:
                    return {"data": [{"url": img_url}]}
                # inline_data 格式
                b64 = (part.get("inlineData") or {}).get("data") or (part.get("inline_data") or {}).get("data")
                if isinstance(b64, str) and len(b64) > 100:
                    return {"data": [{"url": f"data:image/png;base64,{b64}"}]}

        # Case 2: content 是字符串
        if isinstance(msg_content, str):
            # 检查是否是纯 base64
            clean = msg_content.replace("\n", "").replace("\r", "").replace(" ", "")
            if len(clean) > 200 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in clean):
                return {"data": [{"url": f"data:image/png;base64,{clean}"}]}
            # 检查 markdown 图片链接 ![...](url)
            img_match = _re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', msg_content)
            if img_match:
                return {"data": [{"url": img_match.group(1)}]}
            # 检查 data URL
            data_match = _re.search(r'data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=]+)', msg_content)
            if data_match:
                return {"data": [{"url": data_match.group(0)}]}
            # 检查普通 URL
            url_match = _re.search(r'(https?://[^\s"\'<>]+\.(?:png|jpg|jpeg|webp))', msg_content, _re.IGNORECASE)
            if url_match:
                return {"data": [{"url": url_match.group(1)}]}

        # Case 3: 检查 resp 顶层是否有 data 字段（某些网关兼容格式）
        if isinstance(resp.get("data"), list) and resp["data"]:
            return resp

        logger.warning("[AIService] Gemini chat response has no image data, raw=%s", str(resp)[:500])
        raise RuntimeError(f"Gemini chat/completions 未返回图片数据，响应: {str(resp)[:300]}")

    @staticmethod
    async def _generate_image_91api(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """91API 生图入口。

        仅处理 GPT Image 等非 Gemini 模型，走 OpenAI 兼容 /v1/images/generations + /v1/images/edits 端点。
        Gemini 模型由 _generate_image_gemini() 单独处理（yunwu.ai 不支持 /v1/images/generations 调 Gemini）。
        """
        normalized = model.lower()
        is_91api = normalized.endswith("-91api")
        raw = normalized[:-6] if is_91api else normalized

        # ---- 所有模型（GPT Image + Gemini）统一走 OpenAI 兼容端点 ----
        upstream = raw
        ar = _get_option(options, "aspect_ratio", "aspectRatio", "1:1")
        refs_raw = _get_option(options, "reference_images", "referenceImages", []) or []
        # 关键修复：不调用 _public_url，保留原始路径（/static/xxx）让 _to_data_url 优先读本地磁盘
        refs = [u for u in refs_raw if isinstance(u, str) and u.strip()]
        negative = _get_option(options, "negative_prompt", "negativePrompt", "")
        mask_url = _get_option(options, "mask_url", "maskDataUrl", "") or _get_option(options, "mask", "maskDataUrl", "")

        size_map = {
            "16:9": "1792x1024",
            "9:16": "1024x1792",
            "4:3": "1024x768",
            "3:4": "768x1024",
        }
        size = size_map.get(ar, "1024x1024")

        final_prompt = prompt
        if refs:
            final_prompt = (
                f"{prompt}\n\n[Reference Strictness] Use the reference image(s) as the "
                "primary visual source. Keep character identity, face, hairstyle, costume, and scene style consistent."
            )
            # 图生图模式下，API 倾向于沿用参考图比例，需在 prompt 中强制指定输出比例
            if ar and ar != "1:1":
                final_prompt += f"\n\n[Output requirement] Final image MUST be {ar} aspect ratio. Do not keep the original reference image aspect ratio."

        payload: Dict[str, Any] = {
            "model": upstream,
            "prompt": final_prompt,
            "n": 1,
            "size": size,
        }

        if negative:
            payload["negative_prompt"] = negative

        has_mask = bool(mask_url and mask_url.strip())
        first_ref = ""  # 在 refs 块外初始化，避免后续引用未定义变量

        if refs:
            logger.info("[AIService] GPT Image refs=%d 原始URLs=%s 开始转换data URL...", len(refs), refs[:3])
            data_refs = []
            for u in refs:
                try:
                    data_url = await AIService._to_data_url(u)
                    data_refs.append(data_url)
                    is_data = data_url.startswith("data:")
                    logger.info("[AIService] GPT Image 参考图转换成功: %s -> %s (长度=%d)",
                                u[:80], "data_url" if is_data else "原始URL", len(data_url))
                except Exception as exc:
                    # 转换失败时保留原始URL（与参考项目一致），API可能能直接拉取公网URL
                    logger.warning("[AIService] GPT Image 参考图转换失败，使用原始URL: %s err=%s", u[:80], exc)
                    data_refs.append(u)
            if data_refs:
                # 与参考项目一致：gpt-image-2 只发送第一张参考图
                first_ref = data_refs[0]
                payload["image"] = first_ref
                payload["images"] = [first_ref]
                payload["reference_images"] = [first_ref]
                logger.info("[AIService] GPT Image 参考图就绪=%d/%d, image字段类型=%s, 长度=%d",
                            len(data_refs), len(refs),
                            "data_url" if first_ref.startswith("data:") else "url",
                            len(first_ref))
            else:
                logger.warning("[AIService] GPT Image 无可用参考图，将走纯文生图")

        # 局部重绘：附加 mask 参数
        if has_mask:
            try:
                mask_data_url = await AIService._to_data_url(mask_url)
                payload["mask"] = mask_data_url
            except Exception as exc:
                logger.warning("[AIService] mask 转换失败，跳过mask: %s err=%s", mask_url[:80] if mask_url else "", exc)
                has_mask = False
            if has_mask:
                # inpainting 场景下确保使用 /v1/images/edits 端点
                logger.info("[AIService] 91API inpainting request (model=%s, refs=%d, mask=yes)", upstream, len(refs))
                try:
                    response = await AIService._post("/v1/images/edits", payload, "api91")
                except RuntimeError as exc:
                    # 所有错误都回退到 generations（与参考项目一致），404不再直接抛异常
                    logger.warning("[AIService] 91API inpainting edits failed, fallback to generations: %s", exc)
                    payload.pop("mask", None)
                    response = await AIService._post("/v1/images/generations", payload, "api91")
                return AIService._normalize_image_response(response)

        # 记录发送给91API的完整payload（data URL截断显示）
        log_payload = {k: (v[:100] + "...(truncated)" if isinstance(v, str) and len(v) > 100 else v) for k, v in payload.items()}
        logger.info("[AIService] 91API payload (model=%s, refs=%d, size=%s, ar=%s): %s",
                    upstream, len(refs), size, ar, json.dumps(log_payload, ensure_ascii=False, default=str)[:2000])

        if refs and first_ref.startswith("data:"):
            # 有参考图且已转为 data URL：优先用 multipart/form-data 调 /v1/images/edits
            # 标准 OpenAI API 要求 /v1/images/edits 使用 multipart 上传文件，JSON 格式可能被部分网关拒绝
            import base64 as _b64
            import mimetypes as _mt
            logger.info("[AIService] 91API -> /v1/images/edits (multipart, model=%s, size=%s)", upstream, size)
            try:
                # 从 data URL 解码出二进制数据
                # 格式: data:image/png;base64,xxxx
                data_url_parts = first_ref.split(",", 1)
                if len(data_url_parts) != 2:
                    raise ValueError(f"data URL 格式错误: {first_ref[:60]}...")
                header_part = data_url_parts[0]  # data:image/png;base64
                b64_data = data_url_parts[1]
                # 解析 MIME 类型
                mime_match = header_part.replace("data:", "")
                ref_mime = mime_match.split(";")[0] if ";" in mime_match else "image/png"
                if not ref_mime.startswith("image/"):
                    ref_mime = "image/png"
                ref_bytes = _b64.b64decode(b64_data)
                ref_ext = _mt.guess_extension(ref_mime) or ".png"
                ref_filename = f"reference{ref_ext}"

                # 构建 multipart 表单字段
                multipart_fields: Dict[str, str] = {
                    "model": upstream,
                    "prompt": final_prompt,
                    "n": "1",
                    "size": size,
                }
                if negative:
                    multipart_fields["negative_prompt"] = negative

                response = await AIService._post_multipart(
                    "/v1/images/edits",
                    multipart_fields,
                    "image",
                    ref_bytes,
                    ref_filename,
                    ref_mime,
                    "api91",
                )
                logger.info("[AIService] 91API /v1/images/edits (multipart) 成功: %s", str(response)[:500])
            except RuntimeError as exc:
                # multipart 失败：先尝试 JSON 格式的 /v1/images/edits（部分网关支持）
                logger.warning("[AIService] 91API edits(multipart) failed, trying JSON edits: %s", exc)
                try:
                    response = await AIService._post("/v1/images/edits", payload, "api91")
                    logger.info("[AIService] 91API /v1/images/edits (JSON) 成功: %s", str(response)[:500])
                except RuntimeError as exc2:
                    # JSON 也失败：回退到 /v1/images/generations（保留 image 字段，部分网关支持）
                    logger.warning("[AIService] 91API edits(JSON) also failed, fallback to generations: %s", exc2)
                    response = await AIService._post("/v1/images/generations", payload, "api91")
                    logger.info("[AIService] 91API /v1/images/generations (fallback) 成功: %s", str(response)[:500])
        elif refs:
            # 有参考图但未能转为 data URL（保留了原始URL）：走 JSON 格式
            logger.info("[AIService] 91API -> /v1/images/edits (JSON, model=%s, size=%s, image_refs=%d)", upstream, size, len(refs))
            try:
                response = await AIService._post("/v1/images/edits", payload, "api91")
                logger.info("[AIService] 91API /v1/images/edits 成功: %s", str(response)[:500])
            except RuntimeError as exc:
                logger.warning("[AIService] 91API edits failed, fallback to generations (保留参考图): %s", exc)
                response = await AIService._post("/v1/images/generations", payload, "api91")
                logger.info("[AIService] 91API /v1/images/generations (fallback) 成功: %s", str(response)[:500])
        else:
            response = await AIService._post("/v1/images/generations", payload, "api91")
            logger.info("[AIService] 91API /v1/images/generations 成功: %s", str(response)[:500])

        return AIService._normalize_image_response(response)

    # ------------------------------------------------------------------
    # Video Generation
    # ------------------------------------------------------------------
    @staticmethod
    async def generate_video(prompt: str, model: str = "wan2.7-video", options: Optional[Dict[str, Any]] = None) -> Any:
        options = options or {}
        normalized = model.lower()

        if normalized.startswith("doubao-seedance-2-0"):
            return await AIService._generate_video_seedance(prompt, model, options)
        if normalized in {"wan2.7-video", "wan2.7-i2v", "wan2.7-t2v", "wan2.7-r2v"}:
            return await AIService._generate_video_wan27(prompt, model, options)
        if normalized in {"viduq3-turbo", "vidu-q3-turbo", settings.MODELINK_VIDEO_MODEL_ID.lower()}:
            return await AIService._generate_video_modelink(prompt, model, options)

        raise ValueError(f"不支持的视频模型: {model}")

    @staticmethod
    async def _generate_video_seedance(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        refs_raw = options.get("reference_images") or []
        # 关键修复：本地/localhost 参考图先转存 COS，否则火山方舟服务器无法访问，报 resource download failed
        refs_pub = [await _to_public_cos_url(u, "seedance-ref") for u in refs_raw if isinstance(u, str) and u.strip()][:9]
        # 过滤掉非 http/https 的无效 URL（Ark 会拒绝相对路径并返回 400 InvalidParameter）
        refs = [u for u in refs_pub if u and u.startswith(("http://", "https://"))]

        # 兼容 camelCase 和 snake_case 键名：node.py 传 reference_video（字符串）和 reference_audio（字符串），
        # 旧代码期望 videoUrls（列表）和 audioUrl（字符串），此处统一兼容
        raw_video_urls = options.get("videoUrls") or options.get("reference_video") or []
        if isinstance(raw_video_urls, str):
            raw_video_urls = [raw_video_urls] if raw_video_urls.strip() else []
        video_urls_pub = [await _to_public_cos_url(u, "seedance-video") for u in raw_video_urls if isinstance(u, str) and u.strip()]
        video_urls = [u for u in video_urls_pub if u and u.startswith(("http://", "https://"))]
        raw_audio_url = options.get("audioUrl") or options.get("reference_audio")
        audio_url_pub = await _to_public_cos_url(raw_audio_url, "seedance-audio") if raw_audio_url else None
        audio_url = audio_url_pub if audio_url_pub and audio_url_pub.startswith(("http://", "https://")) else None

        has_figure_refs = "[图" in prompt
        ark_text = (
            f"（共{len(refs)}张参考图，按上传顺序为[图1]至[图{len(refs)}]，请在描述中用[图1][图2]等指代。）\n{prompt}"
            if len(refs) >= 3 and not has_figure_refs
            else prompt
        )

        content: List[Dict[str, Any]] = [{"type": "text", "text": ark_text}]
        for idx, url in enumerate(refs):
            item: Dict[str, Any] = {"type": "image_url", "image_url": {"url": url}}
            if len(refs) == 2:
                item["role"] = "first_frame" if idx == 0 else "last_frame"
            elif len(refs) >= 3:
                item["role"] = "reference_image"
            content.append(item)

        if video_urls:
            content.append({
                "type": "video_url",
                "video_url": {"url": video_urls[0]},
                "role": "reference_video",
            })

        if audio_url:
            content.append({
                "type": "audio_url",
                "audio_url": {"url": audio_url},
                "role": "reference_audio",
            })

        ark_model_id = model
        if model == "doubao-seedance-2-0-260128":
            ark_model_id = settings.VOLCENGINE_ARK_MODEL_ID_STANDARD
        elif model == "doubao-seedance-2-0-fast-260128":
            ark_model_id = settings.VOLCENGINE_ARK_MODEL_ID_FAST

        ar = _get_option(options, "aspect_ratio", "aspectRatio", "16:9")
        ratio = "adaptive" if ar.lower() in {"auto", "adaptive"} else ar

        # Seedance 2.0 仅支持 5/10/15 三个时长档位，非法值映射到最近的合法档位
        raw_duration = int(options.get("durationSec") or 5)
        if raw_duration not in (5, 10, 15):
            if raw_duration < 8:
                duration = 5
            elif raw_duration < 12:
                duration = 10
            else:
                duration = 15
        else:
            duration = raw_duration

        payload: Dict[str, Any] = {
            "model": ark_model_id,
            "content": content,
            "generate_audio": bool(options.get("sound", True)),
            "ratio": ratio,
            "duration": duration,
            "watermark": bool(options.get("watermark")),
        }
        callback_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/ark/callback"
        if callback_url:
            payload["callback_url"] = callback_url

        res_norm = str(options.get("resolution") or "").strip().lower()
        if res_norm in {"480p", "720p", "1080p"}:
            payload["resolution"] = res_norm

        # 详细日志：记录最终发送给 Ark 的 content 数组，便于排查 400 错误
        logger.info(
            "[AIService] Seedance payload: model=%s refs=%d video=%d audio=%s content_types=%s",
            ark_model_id, len(refs), len(video_urls), bool(audio_url),
            [c.get("type") for c in content],
        )
        for i, c in enumerate(content):
            if c.get("type") == "image_url":
                logger.info("[AIService] content[%d] image_url=%s role=%s", i, c["image_url"]["url"][:120], c.get("role"))
            elif c.get("type") in ("video_url", "audio_url"):
                key = "video_url" if c["type"] == "video_url" else "audio_url"
                logger.info("[AIService] content[%d] %s=%s role=%s", i, c["type"], c[key]["url"][:120], c.get("role"))

        response = await AIService._post("/contents/generations/tasks", payload, "ark")
        if response and response.get("id"):
            return {"taskId": str(response["id"]), "status": "pending", **response}
        return response

    @staticmethod
    async def _generate_video_wan27(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        refs_raw = options.get("reference_images") or []
        refs = [_public_url(u) for u in refs_raw if isinstance(u, str) and u.strip()]
        # 兼容 camelCase (videoUrls) 和 snake_case (reference_video)
        raw_video_urls = options.get("videoUrls") or options.get("reference_video") or []
        if isinstance(raw_video_urls, str):
            raw_video_urls = [raw_video_urls] if raw_video_urls.strip() else []
        video_urls = [_public_url(u) for u in raw_video_urls if isinstance(u, str) and u.strip()]
        # 兼容 camelCase (audioUrl) 和 snake_case (reference_audio)
        raw_audio_url = options.get("audioUrl") or options.get("reference_audio")
        audio_url = _public_url(raw_audio_url) if raw_audio_url else None

        route = _resolve_wan27_route(model, len(refs), len(video_urls))
        media: List[Dict[str, Any]] = []
        input_data: Dict[str, Any] = {"prompt": prompt}

        if route == "i2v":
            if video_urls:
                media.append({"type": "first_clip", "url": video_urls[0]})
                if refs:
                    last_ref = refs[1] if len(refs) >= 2 else refs[0]
                    media.append({"type": "last_frame", "url": last_ref})
            else:
                if refs:
                    media.append({"type": "first_frame", "url": refs[0]})
                    if len(refs) > 1:
                        media.append({"type": "last_frame", "url": refs[1]})
                if audio_url and refs:
                    media.append({"type": "driving_audio", "url": audio_url})
            if media:
                input_data["media"] = media
        elif route == "t2v":
            if audio_url:
                input_data["audio_url"] = audio_url
        elif route == "r2v":
            voice_attached = False
            for url in refs[:5]:
                item: Dict[str, Any] = {"type": "reference_image", "url": url}
                if audio_url and not voice_attached:
                    item["reference_voice"] = audio_url
                    voice_attached = True
                media.append(item)
            for url in video_urls[:5]:
                item = {"type": "reference_video", "url": url}
                if audio_url and not voice_attached:
                    item["reference_voice"] = audio_url
                    voice_attached = True
                media.append(item)
            if media:
                input_data["media"] = media

        negative = _get_option(options, "negative_prompt", "negativePrompt", "")
        if negative:
            input_data["negative_prompt"] = negative.strip()

        if route == "i2v":
            aliyun_model = options.get("model_id") or WAN27_I2V_DASHSCOPE_MODEL
        elif route == "t2v":
            aliyun_model = options.get("model_id") or WAN27_T2V_DASHSCOPE_MODEL
        else:
            aliyun_model = options.get("model_id") or WAN27_R2V_DASHSCOPE_MODEL

        duration_raw = max(2, min(15, int(options.get("durationSec") or 5)))
        watermark = bool(options.get("watermark"))
        resolution = _wan27_video_resolution(options.get("resolution"))

        if route == "i2v":
            parameters = {
                "resolution": resolution,
                "duration": duration_raw,
                "prompt_extend": options.get("promptExtend") is not False,
                "watermark": watermark,
            }
        elif route in {"t2v", "r2v"}:
            parameters = {
                "resolution": resolution,
                "ratio": _wan27_video_ratio(_get_option(options, "aspect_ratio", "aspectRatio", "16:9")),
                "duration": duration_raw,
                "prompt_extend": options.get("promptExtend") is not False,
                "watermark": watermark,
            }
        else:
            parameters = {}

        payload = {
            "model": aliyun_model,
            "input": input_data,
            "parameters": parameters,
        }

        response = await AIService._post(
            "/services/aigc/video-generation/video-synthesis", payload, "dashscope"
        )
        task_id = response.get("output", {}).get("task_id") if isinstance(response, dict) else None
        if task_id:
            return {"taskId": task_id, "status": "pending", **response}
        return response

    @staticmethod
    async def _generate_video_modelink(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """调用 Modelink API 创建 Vidu Q3 Turbo 视频生成任务。

        支持四种生成模式（自动路由）：
          - text-to-video: 无参考图
          - image-to-video: 1 张参考图
          - reference-to-video: 2-7 张参考图（非首尾帧）
          - start-end-to-video: 2 张参考图标记为首尾帧

        所有端点路径带 /turbo 后缀，服务端内部模型 ID 为 viduq3-turbo。
        鉴权: Bearer MODELINK_API_KEY
        """
        refs_raw = options.get("reference_images") or []
        # 本地/localhost 参考图先转存 COS，否则 Modelink 服务器无法访问
        refs_pub = [await _to_public_cos_url(u, "vidu-ref") for u in refs_raw if isinstance(u, str) and u.strip()]
        refs = [u for u in refs_pub if u and u.startswith(("http://", "https://"))]

        # 是否为首尾帧模式：前端通过 options["start_end_frame"] = true 标记
        is_start_end = bool(options.get("start_end_frame") or options.get("startEndFrame"))

        # 选择端点
        if not refs:
            endpoint = "/queue/fal-ai/vidu/q3/text-to-video/turbo"
            payload: Dict[str, Any] = {"prompt": prompt}
            # 文生视频支持 aspect_ratio、style
            ar = _get_option(options, "aspect_ratio", "aspectRatio", "16:9")
            if ar:
                payload["aspect_ratio"] = ar
            style = _get_option(options, "style", "style", "")
            if style:
                payload["style"] = style
            bgm = options.get("bgm")
            if bgm is not None:
                payload["bgm"] = bool(bgm)
            logger.info("[AIService] Modelink Vidu Q3 Turbo text-to-video refs=0")
        elif len(refs) == 1 and not is_start_end:
            endpoint = "/queue/fal-ai/vidu/q3/image-to-video/turbo"
            payload = {"prompt": prompt, "image_url": refs[0]}
            logger.info("[AIService] Modelink Vidu Q3 Turbo image-to-video refs=1")
        elif len(refs) == 2 and is_start_end:
            endpoint = "/queue/fal-ai/vidu/q3/start-end-to-video/turbo"
            payload = {"start_image_url": refs[0], "end_image_url": refs[1]}
            if prompt:
                payload["prompt"] = prompt
            logger.info("[AIService] Modelink Vidu Q3 Turbo start-end-to-video refs=2")
        else:
            # 1-7 张参考图走 reference-to-video
            endpoint = "/queue/fal-ai/vidu/q3/reference-to-video/turbo"
            payload = {"prompt": prompt, "reference_image_urls": refs[:7]}
            ar = _get_option(options, "aspect_ratio", "aspectRatio", "16:9")
            if ar:
                payload["aspect_ratio"] = ar
            bgm = options.get("bgm")
            if bgm is not None:
                payload["bgm"] = bool(bgm)
            audio = options.get("audio")
            if audio is not None:
                payload["audio"] = bool(audio)
            logger.info("[AIService] Modelink Vidu Q3 Turbo reference-to-video refs=%d", len(refs))

        # 公共可选参数
        duration = int(options.get("durationSec") or options.get("duration") or 5)
        # Vidu Q3 Turbo 支持 1-16 秒（reference-to-video 为 3-16 秒）
        duration = max(1, min(16, duration))
        payload["duration"] = duration

        resolution = str(options.get("resolution") or "").strip().lower()
        if resolution in {"540p", "720p", "1080p"}:
            payload["resolution"] = resolution

        movement_amplitude = _get_option(options, "movement_amplitude", "movementAmplitude", "")
        if movement_amplitude in {"auto", "small", "medium", "large"}:
            payload["movement_amplitude"] = movement_amplitude

        seed = options.get("seed")
        if seed and int(seed) != 0:
            payload["seed"] = int(seed)

        logger.info("[AIService] Modelink payload: endpoint=%s duration=%s res=%s", endpoint, duration, resolution)
        response = await AIService._post(endpoint, payload, "modelink")
        logger.info("[AIService] Modelink 创建任务响应: %s", json.dumps(response, ensure_ascii=False)[:1000] if isinstance(response, dict) else str(response)[:1000])

        # Modelink 返回 {"status": "IN_QUEUE", "request_id": "...", "response_url": "..."}
        request_id = response.get("request_id") if isinstance(response, dict) else None
        if request_id:
            return {
                "taskId": str(request_id),
                "status": "pending",
                "response_url": response.get("response_url", ""),
                **response,
            }
        return response

    # ------------------------------------------------------------------
    # Status Checks
    # ------------------------------------------------------------------
    @staticmethod
    async def check_video_status(task_id: str, model: str) -> Dict[str, Any]:
        normalized = model.lower()

        if normalized.startswith("doubao-seedance-2-0") or normalized.startswith("ep-"):
            url = _join_url(
                settings.VOLCENGINE_ARK_API_BASE_URL,
                f"/contents/generations/tasks/{task_id}",
            )
            headers = {"Authorization": f"Bearer {settings.VOLCENGINE_ARK_API_KEY}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=120)
                resp.raise_for_status()
                data = resp.json()
            raw_status = str(data.get("status") or data.get("task_status") or "").lower()
            mapped = "completed" if raw_status in {"success", "completed", "succeeded", "done"} else (
                "failed" if raw_status in {"failed", "error", "canceled", "cancelled", "expired"} else "processing"
            )
            video_url = data.get("video_url")
            if isinstance(video_url, dict):
                video_url = video_url.get("url")
            if not video_url and isinstance(data.get("content"), list):
                for item in data["content"]:
                    if isinstance(item.get("video_url"), dict) and item["video_url"].get("url"):
                        video_url = item["video_url"]["url"]
                        break
                    if isinstance(item.get("video_url"), str) and item["video_url"]:
                        video_url = item["video_url"]
                        break
                    if item.get("url"):
                        video_url = item["url"]
                        break
            if not video_url and isinstance(data.get("content"), dict):
                video_url = data["content"].get("video_url") or data["content"].get("url")
                if isinstance(video_url, dict):
                    video_url = video_url.get("url")
            # output.video_url fallback（Ark V3 部分响应格式）
            if not video_url:
                output_data = data.get("output") or {}
                if isinstance(output_data, dict):
                    video_url = output_data.get("video_url")
                    if isinstance(video_url, dict):
                        video_url = video_url.get("url")
            return {**data, "status": mapped, "video_url": video_url}

        if normalized in {"wan2.7-video", "wan2.7-i2v", "wan2.7-t2v", "wan2.7-r2v"}:
            url = _join_url(settings.DASHSCOPE_API_BASE_URL, f"/tasks/{task_id}")
            headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=120)
                resp.raise_for_status()
                data = resp.json()
            task_status = data.get("output", {}).get("task_status")
            mapped = (
                "completed" if task_status == "SUCCEEDED" else
                "failed" if task_status in {"FAILED", "CANCELED"} else "processing"
            )
            return {**data, "status": mapped, "video_url": data.get("output", {}).get("video_url")}

        if normalized in {"viduq3-turbo", "vidu-q3-turbo", settings.MODELINK_VIDEO_MODEL_ID.lower()}:
            # Modelink 通过 response_url 轮询任务状态（fal.ai 队列模式）
            if "|" in task_id:
                _real_id, response_url = task_id.split("|", 1)
            else:
                # fallback：根据 API 文档，response_url 格式为 /queue/fal-ai/vidu/requests/{task_id}
                response_url = _join_url(
                    settings.MODELINK_API_BASE_URL,
                    f"/queue/fal-ai/vidu/requests/{task_id}",
                )

            headers = {"Authorization": f"Bearer {settings.MODELINK_API_KEY}", "Accept": "application/json"}
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(response_url, headers=headers, timeout=120)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as exc:
                logger.warning("[AIService] Modelink 状态查询失败 task=%s err=%s", task_id, exc)
                return {"status": "processing"}

            logger.info("[AIService] Modelink 状态响应 task=%s body=%s", task_id, json.dumps(data, ensure_ascii=False)[:1000])

            raw_status = str(data.get("status") or "").lower()
            mapped = (
                "completed" if raw_status in {"completed", "success", "succeeded", "done", "COMPLETED"} else
                "failed" if raw_status in {"failed", "error", "canceled", "cancelled"} else "processing"
            )

            # 提取 video_url：兼容多种响应格式
            # fal.ai 标准格式: {"output": {"video": {"url": "..."}}}
            # Modelink 可能格式: {"video_url": "..."} 或 {"output": {"video_url": "..."}}
            video_url = data.get("video_url")
            if not video_url:
                output = data.get("output") or data.get("data") or {}
                if isinstance(output, dict):
                    video_url = (
                        output.get("video_url")
                        or output.get("url")
                        or _nested_url(output.get("video"))  # output.video.url
                    )
                elif isinstance(output, list) and output and isinstance(output[0], dict):
                    video_url = output[0].get("video_url") or output[0].get("url") or _nested_url(output[0].get("video"))
            # 兜底：顶层 video.url
            if not video_url:
                video_url = _nested_url(data.get("video"))

            if mapped == "completed":
                logger.info("[AIService] Modelink 视频完成 task=%s video_url=%s", task_id, video_url)

            return {**data, "status": mapped, "video_url": video_url}

        return {"status": "processing"}

    @staticmethod
    async def cancel_ark_task(task_id: str) -> Dict[str, Any]:
        """取消火山方舟 Ark V3 异步任务（best-effort，失败不阻塞流程）。"""
        if _is_placeholder_key(settings.VOLCENGINE_ARK_API_KEY):
            return {"ok": False, "reason": "ARK_API_KEY not configured"}
        url = _join_url(
            settings.VOLCENGINE_ARK_API_BASE_URL,
            f"/contents/generations/tasks/{task_id}",
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.VOLCENGINE_ARK_API_KEY}",
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(url, headers=headers, timeout=30)
                resp.raise_for_status()
                logger.info("[AIService] Ark 任务取消成功 task=%s", task_id)
                return {"ok": True}
        except Exception as exc:
            logger.warning("[AIService] Ark 任务取消失败 task=%s err=%s", task_id, exc)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    async def check_image_status(task_id: str, model: str) -> Dict[str, Any]:
        """查询 91API 图片生成任务状态。"""
        if _is_placeholder_key(settings.API91_API_KEY):
            raise RuntimeError("请在 .env 中配置 API91_API_KEY")

        base = settings.API91_BASE_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {settings.API91_API_KEY}",
            "Content-Type": "application/json",
        }
        candidates = [
            f"{base}/v1/images/generations/{task_id}",
            f"{base}/v1/images/{task_id}",
            f"{base}/v1/tasks/{task_id}",
        ]
        last_err: Optional[Exception] = None
        for url in candidates:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=headers, timeout=120)
                    resp.raise_for_status()
                    data = resp.json()
                raw_status = str(
                    data.get("status")
                    or data.get("state")
                    or data.get("task_status")
                    or data.get("taskStatus")
                    or data.get("data", {}).get("status")
                    or data.get("output", {}).get("task_status")
                    or ""
                ).lower()
                data_block = data.get("data") or {}
                first_data_item = data_block[0] if isinstance(data_block, list) and data_block else {}
                possible_url = (
                    data.get("url")
                    or data.get("image")
                    or data.get("image_url")
                    or (data_block if isinstance(data_block, dict) else {}).get("url")
                    or (data.get("output") or {}).get("url")
                    or (first_data_item if isinstance(first_data_item, dict) else {}).get("url")
                )
                is_completed = raw_status in {"completed", "success", "succeeded", "done", "finished"}
                is_failed = raw_status in {"failed", "error", "canceled", "cancelled"}
                status = (
                    "completed" if (possible_url or is_completed) else
                    "failed" if is_failed else "processing"
                )
                return {**data, "status": status, "image_url": possible_url}
            except Exception as exc:
                last_err = exc
        if last_err:
            raise last_err
        return {"status": "processing"}
