import logging
from typing import Any, Dict, List, Optional, Union

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 万相 2.7 默认模型 ID（可在调用时通过 options 覆盖）
WAN27_I2V_DASHSCOPE_MODEL = "wan2.7-i2v-2026-04-25"
WAN27_T2V_DASHSCOPE_MODEL = "wan2.7-t2v-2026-04-25"
WAN27_R2V_DASHSCOPE_MODEL = "wan2.7-r2v"


def _is_placeholder_key(key: Optional[str]) -> bool:
    return not key or "YOUR_" in key


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
    报错 "resource download failed"。本函数把本地资源上传到 COS 后返回公网 URL。
    已是公网 URL（含 COS）则原样返回。
    """
    if not isinstance(url, str) or not url.strip():
        return url
    # 已是公网可访问 URL（含 COS myqcloud.com）直接返回
    if not _is_local_or_localhost(url):
        return url

    # COS 未配置则无法转存，直接返回原 URL（让上游报错，便于发现配置问题）
    if not settings.TENCENT_COS_SECRET_ID or not settings.TENCENT_COS_SECRET_KEY:
        logger.warning("[AIService] COS 未配置，本地参考图无法转存公网: %s", url)
        return url

    import asyncio
    import mimetypes
    import os
    import uuid
    from app.services.cos_service import upload_to_cos

    loop = asyncio.get_event_loop()

    # 优先直接读本地磁盘上传 COS（避免 HTTP 下载依赖后端服务运行）
    local_disk_path: Optional[str] = None
    if url.startswith("/static/"):
        # /static/generated/xxx.png -> uploads/generated/xxx.png
        local_disk_path = os.path.join("uploads", url[len("/static/"):])
    elif url.startswith("/api/uploads/"):
        local_disk_path = os.path.join("uploads", url[len("/api/uploads/"):])
    elif url.startswith("/uploads/"):
        local_disk_path = url[1:]

    if local_disk_path and os.path.isfile(local_disk_path):
        try:
            ext = os.path.splitext(local_disk_path)[1].lstrip(".") or "png"
            mime = mimetypes.guess_type(local_disk_path)[0] or "image/png"
            file_name = f"{prefix}/{uuid.uuid4()}.{ext}"

            def _read_and_upload():
                with open(local_disk_path, "rb") as f:
                    return upload_to_cos(f, file_name, mime)
            cos_url = await loop.run_in_executor(None, _read_and_upload)
            if cos_url:
                logger.info("[AIService] 参考图直传 COS 成功: %s -> %s", url, cos_url)
                return cos_url
            logger.warning("[AIService] 参考图直传 COS 返回空，使用原 URL: %s", url)
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
            logger.warning("[AIService] 参考图 HTTP 转存 COS 返回空，使用原 URL: %s", url)
        except Exception as exc:
            logger.error("[AIService] 参考图 HTTP 转存 COS 失败，使用原 URL: %s err=%s", url, exc)
    return url


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


class AIService:
    """AI 服务封装：LLM Chat、图片生成、视频生成及任务状态查询。"""

    @staticmethod
    async def _to_data_url(url: str) -> str:
        """将图片 URL 下载并转换为 data URL（供 91API 图生图使用）。"""
        if url.startswith("data:"):
            return url
        import base64
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=120)
            resp.raise_for_status()
            mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
            b64 = base64.b64encode(resp.content).decode("ascii")
            return f"data:{mime};base64,{b64}"

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
        else:
            raise ValueError(f"不支持的 API 类型: {api_type}")

        url = _join_url(base_url, endpoint)
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_type == "dashscope":
            headers["Authorization"] = f"Bearer {api_key}"
            if "video-synthesis" in endpoint:
                headers["X-DashScope-Async"] = "enable"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        # LLM 对话用 180 秒超时（max_tokens 已限制输出长度）；生图/生视频仍用 3000 秒
        is_chat = "/v1/chat/completions" in endpoint
        timeout = 180 if is_chat else 3000

        model_name = str(data.get("model", ""))
        logger.info("[AIService] POST %s (type=%s, model=%s)", url, api_type, model_name)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=data, headers=headers, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[AIService] API error: status=%s url=%s response=%s",
                exc.response.status_code,
                url,
                exc.response.text[:1000],
            )
            raise RuntimeError(f"AI 服务请求失败 ({exc.response.status_code}): {exc.response.text[:500]}") from exc
        except Exception as exc:
            logger.error("[AIService] API error: url=%s err=%s", url, exc)
            raise RuntimeError(f"AI 服务请求异常: {exc}") from exc

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
        model = model or settings.LLM_MODEL_NAME
        provider = str(settings.LLM_PROVIDER or "ark").lower()
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        return await AIService._post("/v1/chat/completions", payload, provider if provider in ("ark", "api91") else "ark")

    # ------------------------------------------------------------------
    # Image Generation
    # 91API 网关 Gemini 模型名（与 91API 后台一致，不带 -2k 后缀）
    _GEMINI_MODEL = "gemini-3.1-flash-image-preview"

    @staticmethod
    async def generate_image(prompt: str, model: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Any:
        options = options or {}
        model = model or settings.IMAGE_MODEL_GPT_IMAGE_2
        normalized = model.lower()

        known_models = {
            settings.IMAGE_MODEL_GPT_IMAGE_2.lower(),
            settings.IMAGE_MODEL_GEMINI_FLASH_IMAGE.lower(),
            "gemini-3.1-flash-image-preview-2k",
        }
        if normalized not in known_models and not normalized.endswith("-91api"):
            raise ValueError(f"不支持的图像模型: {model}")

        return await AIService._generate_image_91api(prompt, model, options)

    @staticmethod
    async def _to_gemini_inline_data(url: str) -> Optional[Dict[str, Any]]:
        """将图片 URL 转为 Gemini 原生 API 的 inline_data 格式。"""
        if not url or not url.strip():
            return None
        url = url.strip()
        if url.startswith("data:image/"):
            import re
            m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", url)
            if not m:
                return None
            return {"inline_data": {"mime_type": m.group(1), "data": m.group(2)}}
        try:
            import base64
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=120)
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
                b64 = base64.b64encode(resp.content).decode("ascii")
                return {"inline_data": {"mime_type": mime, "data": b64}}
        except Exception as exc:
            logger.warning("[AIService] Failed to fetch reference image for Gemini: %s err=%s", url, exc)
            return None

    @staticmethod
    async def _generate_image_gemini(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        """使用 Gemini 原生 API 生图。

        91API 对 Gemini 仅支持以下端点：
          - gemini/v1beta/models/gemini-3.1-flash-image-preview:generateContent
          - openai/v1/chat/completions
        不支持 /v1/images/generations，因此必须走 Gemini 原生端点。
        """
        ar = _get_option(options, "aspect_ratio", "aspectRatio", "1:1")
        refs_raw = _get_option(options, "reference_images", "referenceImages", []) or []
        refs = [_public_url(u) for u in refs_raw if isinstance(u, str) and u.strip()]

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
            if ref_inline:
                parts.extend(ref_inline)
                parts[0]["text"] = (
                    f"{gemini_prompt}\n\n[Reference Strictness] Use reference image(s) "
                    "as primary source and keep character identity/face/costume/style consistent."
                )

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
        }

        endpoint = f"/gemini/v1beta/models/{AIService._GEMINI_MODEL}:generateContent"
        logger.info("[AIService] Gemini image request (model=%s, refs=%d)", model, len(refs))
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
        logger.warning("[AIService] Gemini response has no image data, raw=%s", str(resp)[:500])
        raise RuntimeError(f"Gemini 生图未返回图片数据，响应: {str(resp)[:300]}")

    @staticmethod
    async def _generate_image_91api(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        normalized = model.lower()
        is_91api = normalized.endswith("-91api")
        raw = normalized[:-6] if is_91api else normalized
        is_nano = "gemini" in raw

        # Gemini 模型走 Gemini 原生端点（91API 不支持 /v1/images/generations 对 Gemini 的调用）
        if is_nano:
            return await AIService._generate_image_gemini(prompt, model, options)

        # GPT Image 模型走 OpenAI 兼容端点
        upstream = raw
        ar = _get_option(options, "aspect_ratio", "aspectRatio", "1:1")
        refs_raw = _get_option(options, "reference_images", "referenceImages", []) or []
        refs = [_public_url(u) for u in refs_raw if isinstance(u, str) and u.strip()]
        negative = _get_option(options, "negative_prompt", "negativePrompt", "")

        size_map = {
            "16:9": "1792x1024",
            "9:16": "1024x1792",
            "4:3": "1024x768",
            "3:4": "768x1024",
        }
        payload: Dict[str, Any] = {
            "model": upstream,
            "prompt": prompt,
            "n": 1,
            "size": size_map.get(ar, "1024x1024"),
        }

        if negative:
            payload["negative_prompt"] = negative

        if refs:
            payload["prompt"] = (
                f"{payload['prompt']}\n\n[Reference Strictness] Use the reference image(s) as the "
                "primary visual source. Keep character identity, face, hairstyle, costume, and scene style consistent."
            )
            data_refs = [await AIService._to_data_url(u) for u in refs]
            payload["image"] = data_refs[0]
            payload["images"] = data_refs
            payload["reference_images"] = data_refs

        logger.info("[AIService] 91API image request (%s, refs=%d)", model, len(refs))

        if refs:
            try:
                response = await AIService._post("/v1/images/edits", payload, "api91")
            except RuntimeError as exc:
                msg = str(exc)
                if "404" in msg:
                    raise RuntimeError(
                        "91API 不支持 /v1/images/edits 端点（返回 404），无法使用参考图编辑。"
                        "请检查 API91_BASE_URL 配置或确认 91API 是否支持该端点。"
                    ) from exc
                logger.warning("[AIService] 91API edits failed, fallback to generations: %s", exc)
                payload.pop("image", None)
                payload.pop("images", None)
                payload.pop("reference_images", None)
                response = await AIService._post("/v1/images/generations", payload, "api91")
        else:
            response = await AIService._post("/v1/images/generations", payload, "api91")

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

        raise ValueError(f"不支持的视频模型: {model}")

    @staticmethod
    async def _generate_video_seedance(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        refs_raw = options.get("reference_images") or []
        # 关键修复：本地/localhost 参考图先转存 COS，否则火山方舟服务器无法访问，报 resource download failed
        refs_pub = [await _to_public_cos_url(u, "seedance-ref") for u in refs_raw if isinstance(u, str) and u.strip()][:9]
        refs = refs_pub
        # 兼容 camelCase 和 snake_case 键名：node.py 传 reference_video（字符串）和 reference_audio（字符串），
        # 旧代码期望 videoUrls（列表）和 audioUrl（字符串），此处统一兼容
        raw_video_urls = options.get("videoUrls") or options.get("reference_video") or []
        if isinstance(raw_video_urls, str):
            raw_video_urls = [raw_video_urls] if raw_video_urls.strip() else []
        video_urls = [await _to_public_cos_url(u, "seedance-video") for u in raw_video_urls if isinstance(u, str) and u.strip()]
        raw_audio_url = options.get("audioUrl") or options.get("reference_audio")
        audio_url = await _to_public_cos_url(raw_audio_url, "seedance-audio") if raw_audio_url else None

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
            "generate_audio": bool(options.get("sound")),
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

        response = await AIService._post("/contents/generations/tasks", payload, "ark")
        if response and response.get("id"):
            return {"taskId": str(response["id"]), "status": "pending", **response}
        return response

    @staticmethod
    async def _generate_video_wan27(prompt: str, model: str, options: Dict[str, Any]) -> Any:
        refs_raw = options.get("reference_images") or []
        refs = [_public_url(u) for u in refs_raw if isinstance(u, str) and u.strip()]
        video_urls = [_public_url(u) for u in (options.get("videoUrls") or []) if isinstance(u, str) and u.strip()]
        audio_url = _public_url(options.get("audioUrl")) if options.get("audioUrl") else None

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
