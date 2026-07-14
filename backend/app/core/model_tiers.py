"""
#6 模型分级策略

根据任务类型自动选择合适的 LLM 模型：
  - lite     : 路由决策、参数提取、简单审核（快速、低成本）
  - standard : 质检审核、中等复杂度任务
  - creative : 剧本创作、分镜设计等高复杂度创意任务

使用方式：
  from app.core.model_tiers import resolve_model, TaskTier
  model = resolve_model(TaskTier.CREATIVE, user_override)
"""
from typing import Optional
from enum import Enum

from app.core.config import settings


class TaskTier(str, Enum):
    """模型分级。"""
    LITE = "lite"          # 路由、参数提取
    STANDARD = "standard"  # 审核、中等任务
    CREATIVE = "creative"  # 创作类高复杂度任务


_TIER_TO_SETTING = {
    TaskTier.LITE: "LLM_MODEL_LITE",
    TaskTier.STANDARD: "LLM_MODEL_STANDARD",
    TaskTier.CREATIVE: "LLM_MODEL_CREATIVE",
}

# Agent → 默认 tier 映射
AGENT_TIER_MAP = {
    "platform_brain": TaskTier.LITE,       # 路由决策
    "param_extractor": TaskTier.LITE,      # 参数提取
    "reviewer": TaskTier.STANDARD,         # 质检审核
    "script_planner": TaskTier.CREATIVE,   # 剧本策划
    "screenwriter": TaskTier.CREATIVE,     # 文学编剧
    "character_designer": TaskTier.CREATIVE,  # 角色设计
    "scene_prop_designer": TaskTier.CREATIVE, # 场景设计
    "asset_extractor": TaskTier.STANDARD,  # 资产提取
    "storyboard_director": TaskTier.CREATIVE, # 分镜导演
    "video_composer": TaskTier.STANDARD,   # 视频作曲
    "director_brain": TaskTier.STANDARD,   # 导演审核
}


def resolve_model(
    tier: TaskTier = TaskTier.STANDARD,
    user_override: Optional[str] = None,
) -> Optional[str]:
    """根据任务分级解析模型 ID。

    优先级：用户显式选择 > 分级默认 > settings.LLM_MODEL_NAME
    """
    if user_override and user_override.strip():
        return user_override.strip()

    setting_key = _TIER_TO_SETTING.get(tier)
    if setting_key:
        model = getattr(settings, setting_key, None)
        if model and model.strip():
            return model.strip()

    # 回退到默认模型
    return settings.LLM_MODEL_NAME or None


def resolve_model_for_agent(
    agent_name: str,
    user_override: Optional[str] = None,
) -> Optional[str]:
    """根据 Agent 名称解析模型 ID。"""
    tier = AGENT_TIER_MAP.get(agent_name, TaskTier.STANDARD)
    return resolve_model(tier, user_override)
