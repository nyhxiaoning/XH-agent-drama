import asyncio
import base64
import json
import logging
import os
import random
import time
import uuid
from typing import Dict, Any, Callable, Awaitable, List, Optional

import httpx

from app.core.config import settings
from app.core.tasks import Task, TaskStatus
from app.services.ai_service import AIService
from app.data.preset_prompts import (
    get_image_preset_prompt,
    get_llm_preset_messages,
    PRESET_CONFIG_OVERRIDES,
)


logger = logging.getLogger(__name__)


# 与 main.py / asset.py 保持一致的 uploads 根目录：backend/app/uploads
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def _cos_configured() -> bool:
    """检查腾讯云 COS 是否已配置。"""
    return bool(
        settings.TENCENT_COS_SECRET_ID
        and settings.TENCENT_COS_SECRET_KEY
        and settings.TENCENT_COS_BUCKET
        and settings.TENCENT_COS_REGION
    )


def _upload_file_to_cos(content: bytes, cos_key: str, mime_type: str) -> str | None:
    """上传文件到 COS，成功返回 HTTPS URL，失败返回 None。"""
    if not _cos_configured():
        return None
    try:
        from app.services.cos_service import upload_to_cos
        cos_url = upload_to_cos(content, cos_key, mime_type, len(content))
        logger.info("[AIWorker] 已上传至 COS: %s", cos_url)
        return cos_url
    except Exception as exc:
        logger.warning("[AIWorker] COS 上传失败，降级使用本地路径: %s", exc)
        return None


def _has_real_key(key: str) -> bool:
    return bool(key and "YOUR_" not in key)


def _llm_key_ready() -> bool:
    """根据 LLM_PROVIDER 判断 LLM 是否已配置可用密钥。"""
    provider = str(settings.LLM_PROVIDER or "ark").lower()
    if provider == "api91":
        return _has_real_key(settings.API91_API_KEY)
    return _has_real_key(settings.VOLCENGINE_ARK_API_KEY)


class AIWorker:
    def __init__(self):
        self._progress_callback: Callable[[str, int], Awaitable[None]] = None
        self._sd_webui_url: str = None
        self._comfyui_url: str = None

    def configure(self, sd_webui_url: str = None, comfyui_url: str = None):
        self._sd_webui_url = sd_webui_url
        self._comfyui_url = comfyui_url

    def set_progress_callback(self, cb: Callable[[str, int], Awaitable[None]]):
        self._progress_callback = cb

    async def _report_progress(self, task_id: str, progress: int):
        if self._progress_callback:
            await self._progress_callback(task_id, progress)

    async def _generate_image_mock(self, task: Task) -> Dict[str, Any]:
        prompt = task.params.get("prompt", "")
        style = task.params.get("style", "realistic")
        total_steps = 10
        for step in range(1, total_steps + 1):
            await asyncio.sleep(1.0 + random.uniform(0.3, 0.8))
            progress = int(step / total_steps * 100)
            task.progress = progress
            await self._report_progress(task.id, progress)

        if random.random() < 0.1 and task.retry_count == 0:
            raise RuntimeError("NSFW content detected")

        # 生成占位 SVG，确保前端能正常显示；文件名带 placeholder 标记，避免被分镜误当作参考图
        save_dir = os.path.join(UPLOAD_DIR, "generated")
        os.makedirs(save_dir, exist_ok=True)
        file_id = str(uuid.uuid4())
        filename = f"{file_id}_placeholder.svg"
        file_path = os.path.join(save_dir, filename)
        short_prompt = (prompt or "演示图")[:80]
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
            <defs>
                <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#1e1b4b"/>
                    <stop offset="100%" stop-color="#312e81"/>
                </linearGradient>
            </defs>
            <rect width="512" height="512" fill="url(#g)"/>
            <rect x="20" y="20" width="472" height="472" rx="20" fill="none" stroke="#6366f1" stroke-width="4"/>
            <text x="256" y="220" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#e2e8f0">AI 生图占位</text>
            <text x="256" y="270" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#94a3b8">上游 503 暂不可用，已回退</text>
            <text x="256" y="320" text-anchor="middle" font-family="monospace" font-size="11" fill="#64748b">{short_prompt}</text>
        </svg>'''
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(svg)

        return {
            "type": "image",
            "url": f"/static/generated/{filename}",
            "thumbnail_url": f"/static/generated/{filename}",
            "prompt": prompt,
            "style": style,
            "seed": random.randint(1, 999999),
        }

    async def _generate_video_mock(self, task: Task) -> Dict[str, Any]:
        prompt = task.params.get("prompt", "")
        total_steps = 15
        for step in range(1, total_steps + 1):
            await asyncio.sleep(1.5 + random.uniform(0.5, 1.0))
            progress = int(step / total_steps * 100)
            task.progress = progress
            await self._report_progress(task.id, progress)

        if random.random() < 0.1 and task.retry_count == 0:
            raise RuntimeError("GPU out of memory")

        return {
            "type": "video",
            "url": f"/static/generated/{task.id}.mp4",
            "thumbnail_url": f"/static/generated/{task.id}_thumb.png",
            "prompt": prompt,
            "duration": random.randint(3, 10),
        }

    async def _generate_script_mock(self, task: Task) -> Dict[str, Any]:
        prompt = task.params.get("prompt", "")
        total_steps = 5
        for step in range(1, total_steps + 1):
            await asyncio.sleep(0.8 + random.uniform(0.2, 0.5))
            progress = int(step / total_steps * 100)
            task.progress = progress
            await self._report_progress(task.id, progress)

        return {
            "type": "script",
            "content": f"[剧本生成结果] 基于「{prompt}」的剧本：\n第一幕：开场...\n第二幕：发展...\n第三幕：高潮...\n结局：收尾...",
            "scenes": random.randint(3, 8),
        }

    async def _generate_storyboard_mock(self, task: Task) -> Dict[str, Any]:
        prompt = task.params.get("prompt", "")
        total_steps = 8
        for step in range(1, total_steps + 1):
            await asyncio.sleep(1.0 + random.uniform(0.3, 0.6))
            progress = int(step / total_steps * 100)
            task.progress = progress
            await self._report_progress(task.id, progress)

        return {
            "type": "storyboard",
            "panels": [
                {"index": i, "description": f"分镜{i+1}：{prompt[:20]}...", "prompt": prompt}
                for i in range(random.randint(3, 6))
            ],
        }

    # ------------------------------------------------------------------
    # 真实 AI  provider 调用（未配置 key 或调用失败时回退到 mock）
    # ------------------------------------------------------------------
    async def _save_image_result(self, task_id: str, raw_url: str) -> str:
        """把 AI 返回的图片（远程 URL 或 base64）下载/解码后保存到 uploads/generated，返回可访问的 /static 路径。"""
        save_dir = os.path.join(UPLOAD_DIR, "generated")
        os.makedirs(save_dir, exist_ok=True)
        file_id = str(uuid.uuid4())

        content: bytes = b""
        ext = ".png"

        if raw_url.startswith("data:"):
            header, b64 = raw_url.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            ext = ".png" if mime == "image/png" else ".jpg" if mime == "image/jpeg" else ".webp" if mime == "image/webp" else ".png"
            content = base64.b64decode(b64)
        elif raw_url.startswith(("http://", "https://")):
            async with httpx.AsyncClient() as client:
                resp = await client.get(raw_url, timeout=120)
                resp.raise_for_status()
                content = resp.content
                ctype = resp.headers.get("content-type", "").lower()
                ext = ".webp" if "webp" in ctype else ".png" if "png" in ctype else ".jpg" if "jpeg" in ctype else ".png"
        else:
            # 假设是纯 base64 字符串
            try:
                content = base64.b64decode(raw_url)
            except Exception:
                raise ValueError(f"无法识别的图片结果格式: {raw_url[:80]}")

        filename = f"{file_id}{ext}"
        file_path = os.path.join(save_dir, filename)
        with open(file_path, "wb") as f:
            f.write(content)

        # 配置了 COS 时上传到云存储，返回公网 HTTPS URL
        mime_type = "image/png" if ext == ".png" else "image/jpeg" if ext == ".jpg" else "image/webp" if ext == ".webp" else "image/png"
        cos_url = _upload_file_to_cos(content, f"uploads/generated/{filename}", mime_type)
        if cos_url:
            return cos_url

        return f"/static/generated/{filename}"

    def _build_character_sheet_prompt(self, description: str) -> str:
        """构造角色标准设定图提示词：白底、三视图 + 人脸特写，全部中性表情，无文字无道具。"""
        return (
            "Professional character design sheet, pure white background, "
            "divided into 4 panels arranged horizontally. "
            "All 4 panels MUST follow these strict rules: "
            "neutral calm expression with relaxed eyes and closed mouth, "
            "no smiling, no smirking, no eye-rolling, no raised eyebrows, no sneering, "
            "no hand gestures, no pointing, no raised fingers, no dynamic poses, no head tilting. "
            "Panels 1-3 are full-body character turns: "
            "front view, side view, back view, standing straight facing forward, "
            "arms relaxed at sides with hands open and empty. "
            "Panel 4 is a neutral face close-up portrait: head and shoulders only, "
            f"showing these character features without any expression: {description}. "
            "Same character consistently shown from multiple angles, "
            "clean simple clothing, no text, no letters, no watermark, "
            "no props, no accessories, no background elements, no weapons, "
            "highly detailed, 8k, realistic lighting."
        )

    async def _generate_image_ai(self, task: Task) -> Dict[str, Any]:
        node_type = task.params.get("node_type", "")
        prompt = task.params.get("prompt", "")
        model = task.params.get("model") or settings.IMAGE_MODEL_GPT_IMAGE_2
        options = {k: v for k, v in task.params.items() if k not in ("model",)}
        refs = options.get("reference_images") or []
        preset_feature = task.params.get("preset_feature")

        # ── 预设功能：使用预设 prompt 模板 ──
        if preset_feature:
            base_prompt = task.params.get("_original_prompt") or prompt
            style = task.params.get("style") or ""
            prompt = get_image_preset_prompt(preset_feature, base_prompt, style)
            # 应用预设强制配置覆盖
            overrides = PRESET_CONFIG_OVERRIDES.get(preset_feature, {})
            for k, v in overrides.items():
                options[k] = v
            logger.info("[AIWorker] 预设生图 feature=%s task=%s", preset_feature, task.id)
        # 角色节点（非预设）：强制使用标准人物设定图提示词
        elif node_type == "character":
            prompt = self._build_character_sheet_prompt(prompt)

        # 分镜节点：明确告知 AI 参考图是角色三视图/脸特写，必须保持人物一致性
        if node_type == "storyboard" and refs and not preset_feature:
            prompt = (
                "[CRITICAL CHARACTER CONSISTENCY INSTRUCTION]\n"
                "The provided reference images are the OFFICIAL character design sheets (front view, side view, back view, plus face close-up).\n"
                "You MUST treat these reference images as the HIGHEST AUTHORITY for character appearance.\n"
                "- Face: exactly match the face, eye shape, facial structure, and distinctive marks from the reference.\n"
                "- Hairstyle: exactly match the hair color, length, texture, and style from the reference.\n"
                "- Costume: exactly match the clothing color, material, cut, and details from the reference.\n"
                "- Body type: exactly match the build, height, and posture from the reference.\n"
                "If the text prompt below describes any character feature differently from the reference images, IGNORE THE TEXT and follow the reference images.\n"
                "Only use the text prompt for action, pose, camera, lighting, and environment.\n"
                "Do NOT copy the multi-panel layout of the reference sheet into the output image; generate a single cinematic shot.\n\n"
                f"{prompt}"
            )

        logger.info("[AIWorker] 开始生图 task=%s node=%s model=%s refs_count=%d refs=%s", task.id, task.node_id, model, len(refs), refs[:5])
        logger.info("[AIWorker] 生图最终 prompt task=%s prompt=%s", task.id, prompt[:800])

        # 进度心跳：只在 task.progress < expected 时推进，不回退已上报的真实进度
        async def _progress_heartbeat():
            progress_values = [5, 10, 20, 35, 50, 65, 80, 90]
            for p in progress_values:
                await asyncio.sleep(5)
                if task.status == TaskStatus.CANCELLED:
                    return
                if task.progress < p:
                    task.progress = p
                    await self._report_progress(task.id, p)
            p = 90
            while True:
                await asyncio.sleep(30)
                if task.status == TaskStatus.CANCELLED:
                    return
                p = min(p + 1, 99)
                if task.progress < p:
                    task.progress = p
                    await self._report_progress(task.id, p)

        heartbeat_task = asyncio.create_task(_progress_heartbeat())
        try:
            # 尊重用户显式选择的模型，不再自动降级到其他模型。
            # Gemini 原生 API 偶有 503 波动，增加重试而非静默切换模型。
            is_gemini = "gemini" in model.lower()
            max_retries = 3 if is_gemini else 1
            retry_delay = 5  # 秒

            last_error = None
            result = None
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info("[AIWorker] 尝试模型 %s task=%s attempt=%d/%d", model, task.id, attempt, max_retries)
                    result = await asyncio.wait_for(
                        AIService.generate_image(prompt, model=model, options=options),
                        timeout=300,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning("[AIWorker] 模型 %s 生图失败 task=%s attempt=%d err=%s", model, task.id, attempt, exc)
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避

            if result is None:
                raise RuntimeError(f"模型 {model} 生图失败（已重试 {max_retries} 次）：{last_error}")
        except asyncio.TimeoutError:
            raise RuntimeError("AI 生图超时（超过 300 秒未返回结果）")
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        raw_url = None
        if isinstance(result, dict) and isinstance(result.get("data"), list) and result["data"]:
            raw_url = result["data"][0].get("url") or result["data"][0].get("b64_json")

        if not raw_url:
            raise RuntimeError("AI 未返回图片地址")

        public_url = await self._save_image_result(task.id, raw_url)
        logger.info("[AIWorker] 生图完成 task=%s url=%s", task.id, public_url)

        return {
            "type": "image",
            "url": public_url,
            "thumbnail_url": public_url,
            "prompt": prompt,
            "style": task.params.get("style", "realistic"),
            "raw_response": result,
        }

    async def _generate_image_multi(self, task: Task, count: int) -> Dict[str, Any]:
        """单任务批量出图：循环调用 _generate_image_ai，按张数推进进度。任意一张失败抛出整体失败，task_manager 会退全部 cost。"""
        logger.info("[AIWorker] 批量生图 task=%s count=%s", task.id, count)
        images: List[Dict[str, Any]] = []
        for i in range(count):
            if task.status == TaskStatus.CANCELLED:
                raise RuntimeError("任务已取消")
            progress = int((i + 1) / count * 100)
            task.progress = progress
            await self._report_progress(task.id, progress)
            single = await self._generate_image_ai(task)
            images.append(single)
            logger.info("[AIWorker] 批量生图完成 %d/%d task=%s", i + 1, count, task.id)
        return {
            "type": "image",
            "url": images[0]["url"],
            "thumbnail_url": images[0]["thumbnail_url"],
            "prompt": images[0]["prompt"],
            "style": task.params.get("style", "realistic"),
            "images": images,
        }

    async def _save_video_result(self, task_id: str, raw_url: str) -> str:
        """把 AI 返回的视频下载保存到 uploads/videos，返回可访问的 /static 路径。

        火山方舟/万相返回的视频 URL 是临时的（通常 24h 过期），必须下载到本地持久化。
        """
        save_dir = os.path.join(UPLOAD_DIR, "videos")
        os.makedirs(save_dir, exist_ok=True)
        file_id = str(uuid.uuid4())

        content: bytes = b""
        ext = ".mp4"

        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            async with httpx.AsyncClient() as client:
                resp = await client.get(raw_url, timeout=300)
                resp.raise_for_status()
                content = resp.content
                ctype = resp.headers.get("content-type", "").lower()
                if "quicktime" in ctype or "mov" in ctype:
                    ext = ".mov"
                elif "webm" in ctype:
                    ext = ".webm"
        else:
            raise ValueError(f"无法识别的视频结果格式: {raw_url[:80]}")

        filename = f"{file_id}{ext}"
        file_path = os.path.join(save_dir, filename)
        with open(file_path, "wb") as f:
            f.write(content)
        logger.info("[AIWorker] 视频已保存 task=%s path=%s size=%d", task_id, file_path, len(content))

        # 配置了 COS 时上传到云存储，返回公网 HTTPS URL
        mime_type = "video/mp4" if ext == ".mp4" else "video/webm" if ext == ".webm" else "video/quicktime" if ext == ".mov" else "video/mp4"
        cos_url = _upload_file_to_cos(content, f"uploads/videos/{filename}", mime_type)
        if cos_url:
            return cos_url

        return f"/static/videos/{filename}"

    async def _generate_video_ai(self, task: Task) -> Dict[str, Any]:
        prompt = task.params.get("prompt", "")
        model = task.params.get("model") or "wan2.7-video"
        options = {k: v for k, v in task.params.items() if k not in ("model",)}

        # 提交前上报进度
        task.progress = 5
        await self._report_progress(task.id, 5)

        result = await AIService.generate_video(prompt, model=model, options=options)
        if not isinstance(result, dict):
            raise RuntimeError(f"视频生成返回异常：{result}")

        video_task_id = result.get("taskId")
        video_url = result.get("url") or result.get("video_url")

        # 已直接返回 url 的情况（万相偶尔会同步返回）
        if video_url:
            task.progress = 90
            await self._report_progress(task.id, 90)
            # 下载到本地持久化，避免远程 URL 过期
            try:
                local_url = await self._save_video_result(task.id, video_url)
            except Exception as exc:
                logger.warning("[AIWorker] 视频下载失败，使用远程 URL task=%s err=%s", task.id, exc)
                local_url = video_url
            return {
                "type": "video",
                "task_id": video_task_id,
                "status": "completed",
                "url": local_url,
                "prompt": prompt,
                "duration": options.get("durationSec", 5),
                "raw_response": result,
            }

        # 有 taskId 需要轮询任务状态直到完成或超时（最多 15 分钟）
        if not video_task_id:
            raise RuntimeError("视频生成未返回 taskId 也未返回 url")

        logger.info("[AIWorker] 视频任务已提交 task=%s video_task=%s，开始轮询", task.id, video_task_id)
        # 暂存外部 video_task_id 到 params，供 /api/ark/callback 回调查找使用
        task.params["_video_task_id"] = video_task_id
        # Modelink 需要暂存 response_url 用于轮询
        is_modelink = model.lower() in {"viduq3-turbo", "vidu-q3-turbo"}
        response_url = result.get("response_url", "") if is_modelink else ""
        if response_url:
            task.params["_response_url"] = response_url
            logger.info("[AIWorker] Modelink response_url=%s", response_url)
        # 超时从 5 分钟提升到 15 分钟（Seedance 2.0 生成 10s/15s 视频通常需要 5-10 分钟）
        poll_timeout = 900
        deadline = time.monotonic() + poll_timeout
        poll_interval = 10
        last_status = None
        start_time = time.monotonic()

        while True:
            # 用户取消：通知火山方舟上游取消，避免浪费 GPU 资源
            if task.status == TaskStatus.CANCELLED:
                if video_task_id and model.lower().startswith(("doubao-seedance", "ep-")):
                    logger.info("[AIWorker] 用户取消，通知 Ark 上游取消 task=%s ark=%s", task.id, video_task_id)
                    try:
                        await AIService.cancel_ark_task(video_task_id)
                    except Exception:
                        pass
                raise RuntimeError("任务已取消")

            # 检查回调是否已提前暂存结果（/api/ark/callback 收到完成通知后会写入 task.result）
            if task.result and isinstance(task.result, dict) and task.result.get("_from_callback"):
                cb_url = task.result.get("url")
                if cb_url:
                    logger.info("[AIWorker] 回调已提前通知完成，直接使用回调结果 task=%s", task.id)
                    task.progress = 95
                    await self._report_progress(task.id, 95)
                    try:
                        local_url = await self._save_video_result(task.id, cb_url)
                    except Exception as exc:
                        logger.warning("[AIWorker] 视频下载失败，使用远程 URL task=%s err=%s", task.id, exc)
                        local_url = cb_url
                    return {
                        "type": "video",
                        "task_id": video_task_id,
                        "status": "completed",
                        "url": local_url,
                        "prompt": prompt,
                        "duration": options.get("durationSec", 5),
                        "raw_response": task.result,
                    }

            if time.monotonic() > deadline:
                raise RuntimeError(f"视频生成轮询超时（超过 {poll_timeout // 60} 分钟）")

            # 根据已用时间计算模拟进度（5% → 90%），让用户看到进度在推进
            elapsed = time.monotonic() - start_time
            simulated_progress = min(90, 5 + int(elapsed / poll_timeout * 85))
            if task.progress < simulated_progress:
                task.progress = simulated_progress
                await self._report_progress(task.id, simulated_progress)

            try:
                # Modelink 需要传 response_url 给 check_video_status
                if is_modelink and response_url:
                    status_resp = await AIService.check_video_status(f"{video_task_id}|{response_url}", model)
                else:
                    status_resp = await AIService.check_video_status(video_task_id, model)
            except Exception as exc:
                logger.warning("[AIWorker] 视频状态查询失败 task=%s err=%s", task.id, exc)
                await asyncio.sleep(poll_interval)
                continue

            mapped = str(status_resp.get("status") or "").lower()
            if mapped != last_status:
                logger.info("[AIWorker] 视频任务 %s 状态=%s", video_task_id, mapped)
                last_status = mapped

            if mapped == "completed":
                url = status_resp.get("video_url") or status_resp.get("url")
                if not url:
                    raise RuntimeError("视频任务完成但未返回 url")
                task.progress = 95
                await self._report_progress(task.id, 95)
                # 下载到本地持久化，避免火山方舟临时 URL 过期
                try:
                    local_url = await self._save_video_result(task.id, url)
                except Exception as exc:
                    logger.warning("[AIWorker] 视频下载失败，使用远程 URL task=%s err=%s", task.id, exc)
                    local_url = url
                return {
                    "type": "video",
                    "task_id": video_task_id,
                    "status": "completed",
                    "url": local_url,
                    "prompt": prompt,
                    "duration": options.get("durationSec", 5),
                    "raw_response": status_resp,
                }
            if mapped == "failed":
                raise RuntimeError(f"视频生成失败：{status_resp}")

            await asyncio.sleep(poll_interval)

    async def _generate_script_ai(self, task: Task) -> Dict[str, Any]:
        # ── 预设功能：走预设 LLM 分支 ──
        preset_feature = task.params.get("preset_feature")
        if preset_feature:
            return await self._generate_preset_llm(task, preset_feature)

        prompt = task.params.get("prompt", "")
        model = task.params.get("model") or settings.LLM_MODEL_NAME
        messages = [
            {
                "role": "system",
                "content": "你是一位短视频剧本生成专家。请根据用户要求输出剧本正文，保持结构清晰。",
            },
            {"role": "user", "content": prompt},
        ]
        response = await AIService.chat(messages, model=model, max_tokens=8192)
        content = ""
        if isinstance(response, dict) and isinstance(response.get("choices"), list):
            content = response["choices"][0].get("message", {}).get("content", "")
        else:
            content = str(response)
        scenes = content.count("幕") or content.count("场景") or 3
        return {"type": "script", "content": content, "scenes": scenes, "raw_response": response}

    async def _generate_storyboard_ai(self, task: Task) -> Dict[str, Any]:
        prompt = task.params.get("prompt", "")
        model = task.params.get("model") or settings.LLM_MODEL_NAME
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位短视频分镜师。请根据用户提示词生成故事板，仅返回 JSON："
                    '{"panels":[{"index":1,"description":"画面描述","prompt":"用于生图的提示词"}]}'
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = await AIService.chat(messages, model=model)
        content = ""
        if isinstance(response, dict) and isinstance(response.get("choices"), list):
            content = response["choices"][0].get("message", {}).get("content", "")
        else:
            content = str(response)

        panels = []
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
            parsed = json.loads(cleaned)
            panels = parsed.get("panels", [])
        except Exception:
            lines = [line.strip("- ").strip() for line in content.splitlines() if line.strip()]
            panels = [
                {"index": i + 1, "description": line, "prompt": line}
                for i, line in enumerate(lines[:6])
            ]

        return {"type": "storyboard", "panels": panels, "raw_response": response}

    async def _generate_preset_llm(self, task: Task, feature_id: str) -> Dict[str, Any]:
        """处理需要 LLM 的预设功能（剧本解析、脚本优化、拉片分析、25宫格分镜）。"""
        content = task.params.get("prompt", "")
        video_url = task.params.get("result_url", "")
        style = task.params.get("style", "")
        model = task.params.get("model") or settings.LLM_MODEL_NAME

        # storyboard_25 需要更多输出 token（25 个分镜的 JSON 很长）
        max_tokens = 16384 if feature_id == "storyboard_25" else 8192

        messages = get_llm_preset_messages(feature_id, content, video_url=video_url, style=style)
        logger.info("[AIWorker] 预设 LLM feature=%s task=%s tokens=%d", feature_id, task.id, max_tokens)

        task.progress = 10
        await self._report_progress(task.id, 10)

        response = await AIService.chat(messages, model=model, max_tokens=max_tokens)
        task.progress = 70
        await self._report_progress(task.id, 70)

        resp_content = ""
        if isinstance(response, dict) and isinstance(response.get("choices"), list):
            resp_content = response["choices"][0].get("message", {}).get("content", "")
        else:
            resp_content = str(response)

        task.progress = 90
        await self._report_progress(task.id, 90)

        # 根据功能类型构建返回结果
        result: Dict[str, Any] = {
            "type": "script",
            "content": resp_content,
            "preset_feature": feature_id,
            "raw_response": response,
        }

        # storyboard_25: 尝试解析 JSON 以便后端批量创建节点
        if feature_id == "storyboard_25":
            panels = self._parse_storyboard_panels(resp_content)
            result["panels"] = panels
            result["type"] = "storyboard"
            result["panel_count"] = len(panels)

        # script_parse: 尝试解析结构化 JSON
        if feature_id == "script_parse":
            parsed = self._try_parse_json(resp_content)
            if parsed:
                result["parsed_data"] = parsed
                result["characters"] = parsed.get("characters", [])
                result["scenes"] = parsed.get("scenes", [])
                result["storyboards"] = parsed.get("storyboards", [])

        # film_analysis: 尝试解析 JSON
        if feature_id == "film_analysis":
            parsed = self._try_parse_json(resp_content)
            if parsed:
                result["analysis"] = parsed

        task.progress = 100
        await self._report_progress(task.id, 100)

        return result

    def _parse_storyboard_panels(self, content: str) -> List[Dict[str, Any]]:
        """从 LLM 返回文本中解析分镜 panel 列表。"""
        parsed = self._try_parse_json(content)
        if parsed and isinstance(parsed.get("panels"), list):
            return parsed["panels"]
        # 兜底：逐行解析
        lines = [line.strip("- ").strip() for line in content.splitlines() if line.strip()]
        return [
            {"index": i + 1, "description": line, "prompt": line}
            for i, line in enumerate(lines[:25])
        ]

    @staticmethod
    def _try_parse_json(content: str) -> Optional[Dict[str, Any]]:
        """尝试从文本中提取并解析 JSON。"""
        if not content:
            return None
        import re
        # 尝试提取 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content, re.IGNORECASE)
        if m:
            content = m.group(1).strip()
        # 尝试提取 { ... } 块
        start = content.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    async def _generate_audio(self, task: Task) -> Dict[str, Any]:
        raise RuntimeError("音频生成暂未实现")

    async def process(self, task: Task) -> Dict[str, Any]:
        task_type = task.task_type
        logger.info("[AIWorker] 领取任务 task=%s type=%s node=%s", task.id, task_type, task.node_id)

        if task_type == "generate_image":
            count = task.params.get("count", 1)
            model = (task.params.get("model") or "").lower()
            # Seedream 系列走火山方舟 Ark API，检查 ARK key
            is_ark_model = "seedream" in model
            has_ark_key = _has_real_key(settings.VOLCENGINE_ARK_API_KEY)
            has_91api_key = _has_real_key(settings.API91_API_KEY)
            if (is_ark_model and has_ark_key) or (not is_ark_model and has_91api_key):
                try:
                    if count <= 1:
                        return await self._generate_image_ai(task)
                    return await self._generate_image_multi(task, count)
                except Exception as exc:
                    import traceback
                    logger.warning("[AIWorker] 生图失败 task=%s err=%s\n%s", task.id, repr(exc), traceback.format_exc())
                    logger.warning("[AIWorker] 生图失败 task=%s err=%s", task.id, exc)
                    raise RuntimeError(f"AI 生图失败：{exc}") from exc
            key_name = "ARK" if is_ark_model else "API91"
            logger.info("[AIWorker] %s key 未配置，使用演示图 task=%s", key_name, task.id)
            return await self._generate_image_mock(task)

        elif task_type == "generate_video":
            model = (task.params.get("model") or "wan2.7-video").lower()
            provider_ready = (
                (model.startswith("doubao-seedance") and _has_real_key(settings.VOLCENGINE_ARK_API_KEY))
                or ("wan" in model and _has_real_key(settings.DASHSCOPE_API_KEY))
                or (model in {"viduq3-turbo", "vidu-q3-turbo"} and _has_real_key(settings.MODELINK_API_KEY))
            )
            if provider_ready:
                return await self._generate_video_ai(task)
            return await self._generate_video_mock(task)

        elif task_type == "generate_script":
            if _llm_key_ready():
                return await self._generate_script_ai(task)
            return await self._generate_script_mock(task)

        elif task_type == "generate_storyboard":
            if _llm_key_ready():
                return await self._generate_storyboard_ai(task)
            return await self._generate_storyboard_mock(task)

        elif task_type == "generate_audio":
            return await self._generate_audio(task)

        else:
            raise ValueError(f"不支持的任务类型: {task_type}")


ai_worker = AIWorker()
