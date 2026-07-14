"""
#5 Prompt 外置化

从 data/prompts/*.md 文件加载 Agent system_prompt，支持：
  - 内存缓存（首次加载后缓存）
  - 热重载（DEBUG 模式下每次读取文件）
  - 回退（文件不存在时返回 None，调用方可使用内联 prompt）

目录结构：
  backend/app/data/prompts/
    director_brain.md
    script_planner.md
    screenwriter.md
    character_designer.md
    scene_prop_designer.md
    storyboard_director.md
    video_composer.md
    asset_extractor.md
    lite_storyboard.md
    platform_brain_routing.md
    platform_brain_param_extraction.md

使用方式：
  from app.core.prompt_loader import load_prompt
  prompt = load_prompt("script_planner")
  if prompt is None:
      prompt = INLINE_FALLBACK_PROMPT  # 向后兼容
"""
import os
import logging
from typing import Optional, Dict

from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prompts")
_PROMPT_DIR = os.path.normpath(_PROMPT_DIR)

# 内存缓存
_prompt_cache: Dict[str, str] = {}


def load_prompt(name: str) -> Optional[str]:
    """从 data/prompts/{name}.md 加载 prompt 文本。

    Args:
        name: prompt 名称（不含扩展名），如 "script_planner"

    Returns:
        prompt 文本，文件不存在时返回 None
    """
    if not settings.DEBUG and name in _prompt_cache:
        return _prompt_cache[name]

    file_path = os.path.join(_PROMPT_DIR, f"{name}.md")
    if not os.path.isfile(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        _prompt_cache[name] = content
        logger.debug("[PromptLoader] 加载 prompt: %s (%d chars)", name, len(content))
        return content
    except Exception as exc:
        logger.warning("[PromptLoader] 加载 prompt 失败 %s: %s", name, exc)
        return None


def load_prompt_or(name: str, fallback: str) -> str:
    """加载 prompt，文件不存在时返回 fallback。"""
    result = load_prompt(name)
    return result if result is not None else fallback


def clear_cache() -> None:
    """清空 prompt 缓存（热重载时使用）。"""
    _prompt_cache.clear()
