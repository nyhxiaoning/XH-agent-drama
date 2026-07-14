"""
运行时配置接口 —— 返回 .env 中配置的模型信息，供前端动态展示。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])


class RuntimeModelItem(BaseModel):
    model_id: str
    label: str
    provider: str
    type: str  # llm | image | video | audio


class RuntimeModelsResponse(BaseModel):
    llm_models: List[RuntimeModelItem]
    image_models: List[RuntimeModelItem]
    video_models: List[RuntimeModelItem]
    audio_models: List[RuntimeModelItem]
    default_llm_model: str
    llm_provider: str


def _provider_label() -> str:
    """根据 LLM_PROVIDER 返回中文提供商名。"""
    p = (settings.LLM_PROVIDER or "ark").lower()
    if p == "api91":
        return "91API"
    if p == "ark":
        return "火山方舟"
    if p == "dashscope":
        return "阿里云百炼"
    return p


def _make_label(model_id: str, fallback: str) -> str:
    """从模型 ID 生成可读名称，去掉版本号后缀。"""
    if not model_id:
        return fallback
    # doubao-seed-2-1-turbo-260628 → Doubao Seed 2.1 Turbo
    label = model_id
    # 去掉末尾日期戳
    import re
    label = re.sub(r"-\d{6}$", "", label)
    # 连字符转空格，首字母大写
    label = label.replace("-", " ").title()
    return label or fallback


@router.get("/runtime-models", response_model=RuntimeModelsResponse)
def get_runtime_models():
    """返回 .env 中配置的运行时模型列表，供前端动态同步显示。"""

    provider = _provider_label()

    # ── LLM 模型（去重） ──
    llm_ids = list(dict.fromkeys([
        settings.LLM_MODEL_NAME,
        settings.LLM_MODEL_LITE,
        settings.LLM_MODEL_STANDARD,
        settings.LLM_MODEL_CREATIVE,
    ]))
    # 过滤空值
    llm_ids = [m for m in llm_ids if m and m.strip()]
    llm_models = [
        RuntimeModelItem(
            model_id=m,
            label=_make_label(m, m),
            provider=provider,
            type="llm",
        )
        for m in llm_ids
    ]

    # ── 图片模型（去重） ──
    image_ids = list(dict.fromkeys([
        settings.IMAGE_MODEL_GPT_IMAGE_2,
        settings.IMAGE_MODEL_GEMINI_FLASH_IMAGE,
        settings.IMAGE_MODEL_DOUBAO_SEEDREAM,
    ]))
    image_ids = [m for m in image_ids if m and m.strip()]
    image_models = [
        RuntimeModelItem(
            model_id=m,
            label=_make_label(m, m),
            provider=provider if "doubao" in m.lower() else "91API",
            type="image",
        )
        for m in image_ids
    ]

    # ── 视频模型（去重） ──
    video_ids = list(dict.fromkeys([
        settings.VOLCENGINE_ARK_MODEL_ID_STANDARD,
        settings.VOLCENGINE_ARK_MODEL_ID_FAST,
        settings.MODELINK_VIDEO_MODEL_ID,
    ]))
    video_ids = [m for m in video_ids if m and m.strip()]
    video_models = []
    for m in video_ids:
        m_lower = m.lower()
        if "vidu" in m_lower or m_lower in {"viduq3-turbo", "vidu-q3-turbo"}:
            provider = "Modelink"
        else:
            provider = "火山方舟"
        video_models.append(
            RuntimeModelItem(
                model_id=m,
                label=_make_label(m, m),
                provider=provider,
                type="video",
            )
        )

    # ── 音频模型 ──
    audio_models = [
        RuntimeModelItem(
            model_id="default",
            label="默认语音合成",
            provider="系统",
            type="audio",
        )
    ]

    return RuntimeModelsResponse(
        llm_models=llm_models,
        image_models=image_models,
        video_models=video_models,
        audio_models=audio_models,
        default_llm_model=settings.LLM_MODEL_NAME or "",
        llm_provider=provider,
    )
