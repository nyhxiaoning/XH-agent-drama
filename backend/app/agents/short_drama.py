import os
import re
import json
import uuid
import time
import html
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.crud import asset as crud_asset
from app.schemas.asset import AssetCreate
from app.models.asset import AssetType
from app.services.ai_service import AIService
from app.services.session_store import get_store
from app.agents.llm_utils import llm_json as _llm_json, is_fallback_result

logger = logging.getLogger(__name__)


def _validate_llm_result(result: Dict[str, Any], required_keys: List[str], agent_name: str) -> Dict[str, Any]:
    """校验 LLM 返回结果：fallback 或缺少关键字段时补默认值，尽量避免直接抛异常。"""
    if is_fallback_result(result):
        raise ValueError(f"{agent_name} 返回 fallback 兜底数据，需重试: {result.get('_fallback_error')}")
    missing = [k for k in required_keys if not result.get(k)]
    if missing:
        # 先尝试从 result 里找近似字段补上（大小写/下划线变体）
        for k in missing:
            for variant in (k.lower(), k.upper(), k.replace("_", ""), k.replace("-", "_")):
                if variant in result and result[variant]:
                    result[k] = result[variant]
                    break
        # 仍缺的：logline/episodes 给默认值，其他字段才 raise
        still_missing = [k for k in missing if not result.get(k)]
        for k in still_missing:
            if k == "logline":
                result[k] = result.get("synopsis") or result.get("summary") or result.get("project_title") or "暂无故事梗概"
            elif k == "episodes":
                result[k] = []
            elif k in ("project_title", "title"):
                result[k] = "未命名项目"
            elif k in ("scenes", "characters"):
                result[k] = []
            else:
                # 关键字段仍缺，才抛异常进重试
                raise ValueError(f"{agent_name} 返回结果缺少关键字段: {still_missing}")
    return result


@dataclass
class WorkflowMessage:
    role: str  # "user" | "agent" | "system"
    agent: Optional[str]
    step: Optional[str]
    content: str
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class StepResult:
    step: str
    status: str  # "success" | "failed"
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def _extract_json(text: str) -> Optional[str]:
    """从 LLM 返回文本中提取 JSON 代码块或 JSON 对象。"""
    if not text:
        return None
    # 优先匹配 ```json ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 再尝试从文本中找第一个 { ... }
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# ---------------------------------------------------------------------------
# 全局参数体系：所有子 Agent 必须继承的统一约束
# ---------------------------------------------------------------------------
GLOBAL_PARAM_KEYS = [
    "项目ID",
    "核心题材",
    "视觉主风格",
    "目标画幅",
    "单集时长",
    "目标平台",
    "渲染基准",
    "镜头基准",
]

DEFAULT_GLOBAL_PARAMS = {
    "目标画幅": "9:16竖屏",
    "单集时长": "60-90秒",
    "目标平台": "抖音",
    "渲染基准": "UE5离线渲染、PBR物理材质、写实电影感",
    "镜头基准": "35mm定焦镜头，f/1.8光圈，柯达5207胶片质感",
}


def _render_global_params(prompt: str, params: Optional[Dict[str, str]]) -> str:
    """将 system_prompt 中的 {{占位符}} 替换为用户确认的全局参数。

    安全网：替换完毕后，清除所有未匹配的 {{...}} 占位符，
    防止 LLM 看到原始模板语法导致输出混乱。
    """
    import re
    rendered = prompt or ""
    if params:
        for key, value in params.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    # 清除所有剩余未解析的 {{...}} 占位符（跨行匹配）
    rendered = re.sub(r"\{\{[^}]+\}\}", "", rendered)
    return rendered


def _resolve_llm_model(options: Optional[Dict[str, Any]]) -> Optional[str]:
    """从 options 中解析用户选中的语言模型 ID，未选择则返回 None（使用默认模型）。

    用户可自由选择任何已接入的 LLM 模型，废弃模型的拦截在 AIService.chat() 出口处统一处理。
    """
    if not options:
        return None
    return options.get("start.llm_model") or options.get("llm_model") or None


# ============================================================
# P1/P2/P3 公共后处理兜底：LLM 漏字段时代码层补齐，保证下游消费稳定
# ============================================================

def _slim_script_outline(script_data: Dict[str, Any]) -> Dict[str, Any]:
    """精简剧本大纲，只保留下游 Agent 需要的关键字段，减少 input token。
    
    去掉 raw_script_text（可能几千字）、source_prompt 等大文本字段，
    只保留 episodes / scenes / characters_involved / location / time / action_summary。
    """
    if not isinstance(script_data, dict):
        return script_data
    slimmed = {k: v for k, v in script_data.items() if k not in ("raw_script_text", "source_prompt")}
    return slimmed


def _slim_screenwriter_data(sw_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """精简编剧输出，只保留分镜/角色/场景 Agent 需要的字段。
    
    保留：project_title, episodes[].scenes[].scene_id/location/time/characters_involved/action_description/duration/dialogues
    去掉：style_bible, color_palette（由 script_outline 传递即可）, 以及过长的 action_description（截断到 200 字）
    """
    if not sw_data or not isinstance(sw_data, dict):
        return sw_data
    screenplay = sw_data.get("screenplay") or sw_data
    if not isinstance(screenplay, dict):
        return sw_data
    slim_eps = []
    for ep in (screenplay.get("episodes") or []):
        if not isinstance(ep, dict):
            continue
        slim_scenes = []
        for sc in (ep.get("scenes") or []):
            if not isinstance(sc, dict):
                continue
            slim_sc = {
                "scene_id": sc.get("scene_id", ""),
                "location": sc.get("location", ""),
                "time": sc.get("time", ""),
                "characters_involved": sc.get("characters_involved", []),
                "action_description": (sc.get("action_description") or "")[:200],
                "duration": sc.get("duration", 0),
                "dialogues": sc.get("dialogues", []),
            }
            slim_scenes.append(slim_sc)
        slim_eps.append({
            "episode_num": ep.get("episode_num", 1),
            "logline": ep.get("logline", ""),
            "total_duration": ep.get("total_duration", 0),
            "scenes": slim_scenes,
        })
    return {
        "screenplay": {
            "project_title": screenplay.get("project_title", ""),
            "total_episodes": screenplay.get("total_episodes", 1),
            "total_duration": screenplay.get("total_duration", 0),
            "episodes": slim_eps,
        }
    }


def _slim_storyboard_data(sb_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """精简分镜数据，只保留场景/视频 Agent 需要的字段。"""
    if not sb_data or not isinstance(sb_data, dict):
        return sb_data
    slim_sbs = []
    for sb in (sb_data.get("storyboards") or []):
        if not isinstance(sb, dict):
            continue
        slim_sbs.append({
            "storyboard_id": sb.get("storyboard_id", ""),
            "prev_storyboard_id": sb.get("prev_storyboard_id"),
            "linked_scene_id": sb.get("linked_scene_id", ""),
            "linked_char_ids": sb.get("linked_char_ids", []),
            "shot_type": sb.get("shot_type", ""),
            "camera_movement": sb.get("camera_movement", ""),
            "composition": sb.get("composition", ""),
            "visual_description": sb.get("visual_description", ""),
            "final_image_prompt": sb.get("final_image_prompt", ""),
            "duration_seconds": sb.get("duration_seconds", 5),
        })
    return {"storyboards": slim_sbs}


def _extract_character_names_from_text(text: str) -> List[str]:
    """从原始剧本文本中启发式提取角色名，用于在 prompt 中明确要求保留。
    
    策略：
    1. 匹配 "角色名（" 或 "角色名:" 或 "角色名：" 模式
    2. 匹配 "角色名说" / "角色名道" 模式
    3. 匹配英文人名（大写开头连续字母）
    4. 过滤常见非角色名词
    """
    if not text:
        return []
    names: List[str] = []
    seen = set()
    
    # 中文角色名 + 括号/冒号模式："Jerry（粤语）" / "许乐（内心独白）" / "阿强："
    for m in re.finditer(r'([\u4e00-\u9fff]{1,4}|[A-Z][a-z]+)[\s]*[（(：:]', text):
        name = m.group(1).strip()
        if name and name not in seen and name not in ("环境", "音乐", "音效", "镜头", "画面", "上方", "下方", "结尾", "字体", "渐黑", "粤语", "内心独白", "画外音"):
            seen.add(name)
            names.append(name)
    
    # "XXX说" / "XXX道" 模式
    for m in re.finditer(r'([\u4e00-\u9fff]{2,4}|[A-Z][a-z]+)\s*[说道]', text):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    
    return names[:10]  # 最多 10 个


def _extract_scene_locations_from_text(text: str) -> List[str]:
    """从原始剧本文本中启发式提取场景地点，用于在 prompt 中明确要求保留。
    
    策略：
    1. 匹配 "场景一/二/三/四：" 后面的地点
    2. 匹配 "场景X：XXX" 或 "场景X · XXX" 模式
    3. 匹配 "· 地点" 模式
    """
    if not text:
        return []
    locations: List[str] = []
    seen = set()
    
    # "场景X：地点" 或 "场景X · 地点" 模式
    for m in re.finditer(r'场景[一二三四五六七八九十\d]+[：:·\s]+([^\n（(]+)', text):
        loc = m.group(1).strip().rstrip('·：: ')
        if loc and len(loc) > 1 and loc not in seen:
            seen.add(loc)
            locations.append(loc)
    
    return locations[:10]


def _count_original_scenes(text: str) -> int:
    """统计原始剧本中的场景数量（按"场景X"标记计数）。"""
    if not text:
        return 0
    # 匹配 "场景一" "场景二" "场景1" "场景 1" 等
    matches = re.findall(r'场景[一二三四五六七八九十\d]+', text)
    return len(matches)


def _ensure_episode_cliffhanger(result: Dict[str, Any]) -> None:
    """P1：确保每个 episode 都有 cliffhanger 字段（LLM 漏写时按位置生成默认钩子）。"""
    if not isinstance(result, dict):
        return
    episodes = result.get("episodes") or []
    if not isinstance(episodes, list):
        return
    total = len(episodes)
    for idx, ep in enumerate(episodes):
        if not isinstance(ep, dict):
            continue
        if not ep.get("cliffhanger"):
            # 末集默认全剧终，非末集默认留悬念
            ep["cliffhanger"] = "全剧终，无下集钩子" if idx == total - 1 else "本集悬念未消，下集揭晓"


def _ensure_scene_reuse_from(result: Dict[str, Any]) -> None:
    """P3：确保每个 scene 都有 reuse_from_scene 字段（首次出现填 null，复用按 location 匹配）。"""
    if not isinstance(result, dict):
        return
    episodes = result.get("episodes") or []
    if not isinstance(episodes, list):
        return
    # 按 location 建立首次出现索引：location -> scene_id
    location_first_seen: Dict[str, str] = {}
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        for sc in ep.get("scenes", []) or []:
            if not isinstance(sc, dict):
                continue
            sid = sc.get("scene_id")
            loc = sc.get("location")
            if "reuse_from_scene" not in sc or sc.get("reuse_from_scene") is None:
                if loc and loc in location_first_seen and location_first_seen[loc] != sid:
                    sc["reuse_from_scene"] = location_first_seen[loc]
                else:
                    sc["reuse_from_scene"] = None
            if loc and loc not in location_first_seen:
                location_first_seen[loc] = sid


def _ensure_scene_lighting_spec(scene: Dict[str, Any]) -> None:
    """P2：确保单个 scene 有 lighting_spec 四字段（direction/color_temp_k/contrast_ratio/shadow_hardness）。"""
    if not isinstance(scene, dict):
        return
    ls = scene.get("lighting_spec")
    if not isinstance(ls, dict):
        ls = {}
        scene["lighting_spec"] = ls
    ls.setdefault("direction", "from left")
    ls.setdefault("color_temp_k", 5600)
    ls.setdefault("contrast_ratio", "3:1")
    ls.setdefault("shadow_hardness", "soft")
    # color_temp_k 必须是 int
    try:
        ls["color_temp_k"] = int(ls["color_temp_k"])
    except Exception:
        ls["color_temp_k"] = 5600


def _ensure_dialogue_type(dialogues: Any) -> None:
    """P2：确保每条对白有 type 字段（dialogue/OS/VO），缺失默认 dialogue。"""
    if not isinstance(dialogues, list):
        return
    for d in dialogues:
        if isinstance(d, dict) and not d.get("type"):
            d["type"] = "dialogue"


def _normalize_scene_id(scene_id: Any) -> Any:
    """P3：清理 AssetExtractorAgent 残留 S001 格式，统一为 S1_1 格式（仅在明确匹配时转换）。

    规则：S+3位数字(如 S001/S002) → S1_1/S1_2...（按序号拆为 episode_scene 格式）。
    单集场景 S001 → S1_1；若原 ID 已是 S1_1 格式则不动。
    """
    if not isinstance(scene_id, str):
        return scene_id
    # 已是正确格式 S1_1 / S2_3 等则跳过
    if re.match(r"^S\d+_\d+$", scene_id):
        return scene_id
    # 匹配 S001 / S002 等三位数字残留格式
    m = re.match(r"^S(\d{3,})$", scene_id)
    if m:
        seq = int(m.group(1))
        # 简单映射：001→1_1, 002→1_2, ... 按每集 10 场拆分（保守映射，避免与真实 ID 冲突）
        ep_num = (seq - 1) // 10 + 1
        scene_num = (seq - 1) % 10 + 1
        return f"S{ep_num}_{scene_num}"
    return scene_id


def _normalize_all_scene_ids(result: Dict[str, Any]) -> None:
    """P3：递归清理结果中所有 scene_id 的 S001 残留格式。"""
    if not isinstance(result, dict):
        return
    # 顶层 scenes 列表（AssetExtractorAgent 输出）
    for sc in result.get("scenes", []) or []:
        if isinstance(sc, dict) and "scene_id" in sc:
            sc["scene_id"] = _normalize_scene_id(sc["scene_id"])
    # episodes 内的 scenes
    for ep in result.get("episodes", []) or []:
        if not isinstance(ep, dict):
            continue
        for sc in ep.get("scenes", []) or []:
            if isinstance(sc, dict) and "scene_id" in sc:
                sc["scene_id"] = _normalize_scene_id(sc["scene_id"])


def _post_process_script_planner(result: Dict[str, Any]) -> Dict[str, Any]:
    """ScriptPlannerAgent 后处理：P1 cliffhanger + P3 reuse_from_scene + P3 scene_id 规范化 + 卡点/情绪/信息差兑底。"""
    _normalize_all_scene_ids(result)
    _ensure_episode_cliffhanger(result)
    _ensure_scene_reuse_from(result)
    _ensure_episode_hooks(result)
    return result


def _ensure_episode_hooks(result: Dict[str, Any]) -> None:
    """确保每个 episode 都有 emotion_hook / info_gap / is_checkpoint / checkpoint_type 字段。"""
    if not isinstance(result, dict):
        return
    episodes = result.get("episodes") or []
    if not isinstance(episodes, list):
        return
    total = len(episodes)
    # 卡点位置：10%, 30%, 50%, 70%, 90%
    checkpoint_positions = {max(1, int(total * 0.1)), max(1, int(total * 0.3)), max(1, int(total * 0.5)), max(1, int(total * 0.7)), max(1, int(total * 0.9))}
    for idx, ep in enumerate(episodes):
        if not isinstance(ep, dict):
            continue
        ep_num = ep.get("episode_num", idx + 1)
        if "emotion_hook" not in ep:
            ep["emotion_hook"] = ""
        if "info_gap" not in ep:
            ep["info_gap"] = ""
        if "is_checkpoint" not in ep:
            ep["is_checkpoint"] = ep_num in checkpoint_positions
        if "checkpoint_type" not in ep:
            ep["checkpoint_type"] = "无"


def _post_process_screenwriter(result: Dict[str, Any]) -> Dict[str, Any]:
    """ScreenwriterAgent 后处理：P2 dialogue type + P3 scene_id 规范化。"""
    _normalize_all_scene_ids(result)
    screenplay = result.get("screenplay") or result
    if isinstance(screenplay, dict):
        for ep in screenplay.get("episodes", []) or []:
            if not isinstance(ep, dict):
                continue
            for sc in ep.get("scenes", []) or []:
                if not isinstance(sc, dict):
                    continue
                _ensure_dialogue_type(sc.get("dialogues"))
    return result


def _validate_user_script_fidelity(result: Dict[str, Any], raw_script_text: str) -> Dict[str, Any]:
    """校验用户上传剧本的忠实度：检测角色名篡改、场景遗漏、场景地点更换。
    
    如果检测到偏差，在 result 中添加 _fidelity_warnings 字段记录警告，
    供调用方决定是否重试或提示用户。
    """
    if not raw_script_text or not isinstance(result, dict):
        return result
    
    warnings: List[str] = []
    
    # 1. 校验角色名
    original_names = _extract_character_names_from_text(raw_script_text)
    if original_names:
        output_names: set = set()
        screenplay = result.get("screenplay") or result
        if isinstance(screenplay, dict):
            for ep in screenplay.get("episodes", []) or []:
                if not isinstance(ep, dict):
                    continue
                for sc in ep.get("scenes", []) or []:
                    if not isinstance(sc, dict):
                        continue
                    for c in sc.get("characters_involved", []) or []:
                        output_names.add(str(c).strip())
                    for d in sc.get("dialogues", []) or []:
                        if isinstance(d, dict):
                            output_names.add(str(d.get("character", "")).strip())
        
        missing_names = [n for n in original_names if n not in output_names]
        if missing_names:
            warnings.append(
                f"角色名偏差：原文角色 {original_names} 中，以下角色在输出中缺失：{missing_names}。"
                f"输出中出现的角色名：{list(output_names)}。请检查是否被改名。"
            )
    
    # 2. 校验场景数
    original_scene_count = _count_original_scenes(raw_script_text)
    if original_scene_count > 0:
        output_scene_count = 0
        screenplay = result.get("screenplay") or result
        if isinstance(screenplay, dict):
            for ep in screenplay.get("episodes", []) or []:
                if isinstance(ep, dict):
                    output_scene_count += len(ep.get("scenes", []) or [])
        if output_scene_count < original_scene_count:
            warnings.append(
                f"场景数偏差：原文有 {original_scene_count} 个场景，输出只有 {output_scene_count} 个 scene。"
                f"可能存在场景遗漏，请检查是否覆盖了原文全部场景。"
            )
    
    # 3. 校验场景地点
    original_locations = _extract_scene_locations_from_text(raw_script_text)
    if original_locations:
        output_locations: set = set()
        screenplay = result.get("screenplay") or result
        if isinstance(screenplay, dict):
            for ep in screenplay.get("episodes", []) or []:
                if not isinstance(ep, dict):
                    continue
                for sc in ep.get("scenes", []) or []:
                    if isinstance(sc, dict):
                        loc = sc.get("location", "")
                        if loc:
                            output_locations.add(str(loc).strip())
        
        # 检查原文地点是否在输出中出现（模糊匹配：原文地点的关键词出现在输出地点中即可）
        missing_locations = []
        for orig_loc in original_locations:
            # 提取地点关键词（取前 2-4 个字）
            keywords = [orig_loc[:2], orig_loc[:3], orig_loc[:4]]
            found = any(any(kw in out_loc for kw in keywords) for out_loc in output_locations)
            if not found:
                missing_locations.append(orig_loc)
        
        if missing_locations:
            warnings.append(
                f"场景地点偏差：原文地点 {original_locations} 中，以下地点在输出中未找到：{missing_locations}。"
                f"输出中出现的地点：{list(output_locations)}。请检查是否被更换。"
            )
    
    if warnings:
        result["_fidelity_warnings"] = warnings
        logger.warning("[ScreenwriterAgent] 用户剧本忠实度校验发现偏差：%s", "; ".join(warnings))
    
    return result


def _post_process_character_designer(result: Dict[str, Any]) -> Dict[str, Any]:
    """CharacterDesignerAgent 后处理：P2 三视图布局兜底 + 人种约束安全网。"""
    if not isinstance(result, dict):
        return result
    layout_keyword = "four-panel horizontal layout"
    # 人种关键词列表，用于检测 base_prompt 是否已包含人种约束
    ethnicity_keywords = [
        "asian", "east asian", "caucasian", "african", "european",
        "latino", "hispanic", "mixed race", "south asian", "southeast asian",
    ]
    for c in result.get("characters", []) or []:
        if not isinstance(c, dict):
            continue
        bp = c.get("base_prompt") or ""
        if layout_keyword not in bp:
            # 在 base_prompt 开头补三视图布局规范
            prefix = (
                "character design sheet, four-panel horizontal layout, "
                "front view 0 degree, side view 90 degree, back view 180 degree, "
                "face close-up portrait 60-70% panel size, "
                "consistent height and proportion across all views, pure white background, "
            )
            c["base_prompt"] = prefix + bp
            bp = c["base_prompt"]

        # 人种约束安全网：如果 base_prompt 中没有人种关键词，从 immutable_features/visual_anchor 推断并补充
        bp_lower = bp.lower()
        has_ethnicity = any(k in bp_lower for k in ethnicity_keywords)
        if not has_ethnicity:
            # 从 immutable_features 和 visual_anchor 中查找人种关键词
            feats = c.get("immutable_features") or []
            anchor = c.get("visual_anchor") or ""
            combined = " ".join(feats) + " " + anchor
            combined_lower = combined.lower()
            found_ethnicity = None
            for k in ethnicity_keywords:
                if k in combined_lower:
                    found_ethnicity = k
                    break
            if found_ethnicity:
                # 在 base_prompt 中补充人种关键词
                c["base_prompt"] = bp.rstrip(", ") + f", {found_ethnicity}"
            else:
                # 无法推断人种时，默认添加 East Asian（短剧平台以中文内容为主）
                # 并记录警告
                logger.warning("[CharacterDesigner] 角色 %s 缺少人种约束，默认补充 East Asian", c.get("char_id"))
                c["base_prompt"] = bp.rstrip(", ") + ", East Asian"

        # 负面提示词安全网：确保包含防止人种偏移的约束
        np = c.get("negative_prompt") or ""
        np_lower = np.lower()
        if "western face" not in np_lower and "caucasian" not in np_lower:
            c["negative_prompt"] = (np.rstrip(", ") + ", western face, caucasian features") if np else "western face, caucasian features"

        # 出镜位置安全网：确保 appearance_scenes 字段存在
        if "appearance_scenes" not in c:
            c["appearance_scenes"] = []
    return result


def _post_process_scene_prop_designer(result: Dict[str, Any]) -> Dict[str, Any]:
    """ScenePropDesignerAgent 后处理：P2 lighting_spec + P3 scene_id 规范化。"""
    _normalize_all_scene_ids(result)
    if isinstance(result, dict):
        for sc in result.get("scenes", []) or []:
            _ensure_scene_lighting_spec(sc)
    return result


def _post_process_asset_extractor(result: Dict[str, Any]) -> Dict[str, Any]:
    """AssetExtractorAgent 后处理：P3 scene_id 规范化 + P2 lighting_spec + P2 三视图布局兜底 + 人种约束安全网。"""
    _normalize_all_scene_ids(result)
    if isinstance(result, dict):
        for sc in result.get("scenes", []) or []:
            _ensure_scene_lighting_spec(sc)
        layout_keyword = "four-panel horizontal layout"
        ethnicity_keywords = [
            "asian", "east asian", "caucasian", "african", "european",
            "latino", "hispanic", "mixed race", "south asian", "southeast asian",
        ]
        for c in result.get("characters", []) or []:
            if not isinstance(c, dict):
                continue
            bp = c.get("base_prompt") or ""
            if layout_keyword not in bp:
                prefix = (
                    "character design sheet, four-panel horizontal layout, "
                    "front view 0 degree, side view 90 degree, back view 180 degree, "
                    "face close-up portrait 60-70% panel size, "
                    "consistent height and proportion across all views, pure white background, "
                )
                c["base_prompt"] = prefix + bp
                bp = c["base_prompt"]

            # 人种约束安全网
            bp_lower = bp.lower()
            has_ethnicity = any(k in bp_lower for k in ethnicity_keywords)
            if not has_ethnicity:
                feats = c.get("immutable_features") or []
                anchor = c.get("visual_anchor") or ""
                combined = " ".join(feats) + " " + anchor
                combined_lower = combined.lower()
                found_ethnicity = None
                for k in ethnicity_keywords:
                    if k in combined_lower:
                        found_ethnicity = k
                        break
                if found_ethnicity:
                    c["base_prompt"] = bp.rstrip(", ") + f", {found_ethnicity}"
                else:
                    logger.warning("[AssetExtractor] 角色 %s 缺少人种约束，默认补充 East Asian", c.get("char_id"))
                    c["base_prompt"] = bp.rstrip(", ") + ", East Asian"

            # 负面提示词安全网
            np = c.get("negative_prompt") or ""
            np_lower = np.lower()
            if "western face" not in np_lower and "caucasian" not in np_lower:
                c["negative_prompt"] = (np.rstrip(", ") + ", western face, caucasian features") if np else "western face, caucasian features"
    return result


def _post_process_storyboard_director(result: Dict[str, Any]) -> Dict[str, Any]:
    """StoryboardDirectorAgent 后处理：P1 episode_durations/total_storyboard_duration 兜底 + P3 scene_id 规范化。"""
    _normalize_all_scene_ids(result)
    if not isinstance(result, dict):
        return result
    storyboards = result.get("storyboards", []) or []
    if not isinstance(storyboards, list):
        return result
    # 兜底：若 LLM 未输出 episode_durations，按分镜 duration_seconds 聚合统计
    if not result.get("episode_durations"):
        ep_durations: Dict[int, Dict[str, Any]] = {}
        for sb in storyboards:
            if not isinstance(sb, dict):
                continue
            try:
                ep_num = int(sb.get("episode_num", 1))
            except Exception:
                ep_num = 1
            try:
                dur = int(sb.get("duration_seconds", 0))
            except Exception:
                dur = 0
            sid = sb.get("linked_scene_id")
            slot = ep_durations.setdefault(ep_num, {
                "episode_num": ep_num,
                "total_storyboard_duration": 0,
                "storyboard_count": 0,
                "scene_ids": [],
            })
            slot["total_storyboard_duration"] += dur
            slot["storyboard_count"] += 1
            if sid and sid not in slot["scene_ids"]:
                slot["scene_ids"].append(sid)
        result["episode_durations"] = sorted(ep_durations.values(), key=lambda x: x["episode_num"])
    return result


class ScriptPlannerAgent:
    name = "script_planner"
    description = "剧本架构Agent：将灵感转化为可工业化落地的结构化故事骨架"
    system_prompt = """
【身份】
你是专业级 AI 短剧剧本架构师，精通短视频叙事节奏与三幕式工业化编剧，是故事生产线的总设计师。只输出可落地的结构化故事骨架：剧情节奏、戏剧功能、场次划分。不输出任何表演细节、微表情或镜头级指令。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 核心题材: {{核心题材}}
- 视觉主风格: {{视觉主风格}}
- 目标画幅: {{目标画幅}}
- 单集时长: {{单集时长}}
- 目标平台: {{目标平台}}
- 渲染基准: {{渲染基准}}
- 镜头基准: {{镜头基准}}

【输入参数】
- 核心创意点：{{一句话核心故事钩子}}
- 主角核心设定：{{主角身份+核心困境+核心目标}}
- 结局走向：{{HE/BE/开放式+核心落点}}
- 核心卖点：{{反转/情绪/爽点/悬念}}

【核心执行公式】
1. 按「钩子-发展-反转-收尾」四节拍拆解全片节奏，严格匹配单集时长：
   - 0-15%: 强钩子开场（抛出悬念/冲突/爽点）
   - 15-50%: 剧情推进 + 矛盾升级
   - 50-80%: 核心反转/高潮爆发
   - 80-100%: 收尾 + 下集钩子
2. 输出三幕式结构大纲，每幕标注明确的戏剧功能、情绪曲线、关键情节点。
3. 输出分场清单，每场标注唯一 scene_id、关联场景名、核心事件、戏剧功能、预估时长（秒）。
4. 每个 episode 必须输出 cliffhanger 字段：本集结尾的下集钩子（一句话留悬念，确保用户追更；末集可写"全剧终，无下集钩子"）。
5. 标注场景复用方案：每个 scene 必须输出 reuse_from_scene 字段，符合工业化「低场景、高复用」生产原则。首次出现的场景填 null，复用此前场景空间时填被复用场景的 scene_id（如 "S1_1"），下游 ScenePropDesigner 据此跳过重复设计。
6. 所有划分仅服务于镜头转化，不做任何文学化、散文化描写。
7. 【卡点设计】按总集数计算关键卡点位置：
   - 约 10%：首次卡点，核心矛盾升级
   - 约 30%：二次卡点，陷害/真相逼近/生死或情感危机
   - 约 50%：中期卡点，阶段目标达成后重大反转
   - 约 70%：后期卡点，伏笔爆发，局势翻盘
   - 约 90%：收尾卡点，最终对决前的最大阻碍或真相揭露
   每集在 logline 中标注是否为卡点集及类型（身份差/感情错位/命运巨变/环境剧变）。
8. 【情绪点设计】每集至少包含爆点/虐点/爽点之一：
   - 爆点：令人震惊/意外/骇人/惊羡的事件（替身/穿书/重生/离婚反杀/伪装拆穿）
   - 虐点：让观众心疼或愤怒的伤害/误会/牺牲/遗忘/失去
   - 爽点：主角受压后反击，形成“装+打脸+震惊+收获”
   先压后爆，小情绪累积成大爆发，不要在同一集堆太多核心情绪。
9. 【信息差设计】每集标注信息差类型：
   - 观众先知型：主角知道，观众知道，配角不知道（适合期待打脸）
   - 观众焦急型：配角知道，观众知道，主角不知道（适合虐恋/悬疑/危机）
   - 观众上帝型：观众知道，主角和配角都不知道（适合寻亲/身份错位/真相揭露）
   - 同步发现型：观众跟主角一起发现（适合悬疑/升级流/世界观探索）

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "project_title": "短剧名称",
  "genre": "题材分类",
  "source_prompt": "原始用户输入",
  "style_bible": "视觉风格圣经，一句话概括本剧视觉风格",
  "color_palette": ["#1a1a2e", "#e94560", "#f5f5f5"],
  "core_conflicts": [
    {"conflict": "核心冲突简述", "resolution": "对应解决路径"}
  ],
  "character_arcs": [
    {"character": "主角名", "start": "起点状态", "turning": "转折点", "end": "终点状态"}
  ],
  "episodes": [
    {
      "episode_num": 1,
      "logline": "本集一句话核心看点",
      "cliffhanger": "本集结尾的下集钩子，一句话留悬念（末集可写'全剧终，无下集钩子'）",
      "emotion_hook": "爆点/虐点/爽点 + 具体内容",
      "info_gap": "信息差类型 + 具体设计",
      "is_checkpoint": false,
      "checkpoint_type": "无/身份差/感情错位/命运巨变/环境剧变",
      "scenes": [
        {
          "scene_id": "S1_1",
          "location": "场景地点",
          "time": "日/夜/黄昏",
          "reuse_from_scene": null,
          "characters_involved": [
            {"name": "角色A", "one_line_visual": "一句话外观描述，禁止抽象形容词"},
            {"name": "角色B", "one_line_visual": "一句话外观描述，禁止抽象形容词"}
          ],
          "action_description": "可拍摄的宏观动作与核心行为，禁止微表情/心理/镜头细节",
          "emotion_intensity": 3,
          "estimated_duration": 25,
          "dialogues": [
            {"character": "角色A", "line": "台词", "emotion": "轻蔑"}
          ]
        }
      ],
      "emotion_curve": [
        {"scene_id": "S1_1", "intensity": 3, "note": "情绪简述"}
      ]
    }
  ]
}

【动作描写铁律】
1. 禁止抽象形容词，必须转化为可拍摄、可 AI 生成的视觉符号。
2. 正确示例："紧握拳头指节发白"、"雨水中单膝跪地"、"用手指点着对方鼻尖"。
3. 错误示例："很愤怒"、"气质高冷"、"眼神中充满悲伤"。
4. 不拆解微表情、不细化肢体动作、不写心理活动。

【用户上传原始文本时的额外约束】
- 你是大纲提取器，不是创作者：必须严格按原文内容提取结构，禁止改写、禁止扩写、禁止添加原文没有的情节。
- 【角色名锁定】原文中的角色名必须原样保留在 characters_involved 中，禁止改名、禁止新增、禁止删除。
- 【场景地点锁定】原文中的场景地点必须原样保留在 location 字段中，禁止更换地点。
- 【场景覆盖完整】原文有多少个场景/段落，输出就必须有多少个 scene，禁止遗漏、禁止合并不同场景。
- 严格按原文时间线与空间线输出：原文写古代就输出古代场景，原文写现代就输出现代场景，禁止把不同时代/空间的人物强行串联、穿越或混编。
- 每个 scene 的核心事件、人物、地点必须与原文一致，logline 只能概括原文实际发生的事。
- 按原文顺序输出 scene，不要合并独立情节，不要遗漏任何场景。
- project_title 必须使用原文标题，禁止自行编造。

【工业化刚性约束】
- 禁止无戏剧功能的水戏，每场必须承担「推进剧情/塑造人物/铺垫反转」其一功能。
- 钩子必须前置，开场 3 秒内必须有可视觉化的冲突点。
- 所有人物行为必须符合底层动机，禁止工具人式强行推进剧情。
- 台词必须口语化、接地气、符合人物身份，严禁书面语。
- 输出全程使用结构化表述，禁止散文式描写与心理活动刻画。
- 不涉及任何表演细节、微表情、肢体细节、镜头级指令。
- 每个 scene 必须提供 estimated_duration（整数秒），episode 内所有 scene 的 estimated_duration 之和与单集时长误差 ≤ 5 秒。

【质量校验项】
□ 时长分配误差 ≤ 5 秒
□ 每个 scene 都有 estimated_duration 字段
□ 每个 episode 都有 cliffhanger 字段（末集可写"全剧终"）
□ 每个 scene 都有 reuse_from_scene 字段（首次出现填 null，复用填来源 scene_id）
□ 单集反转/爽点 ≥ 2 个
□ 每集有 emotion_hook（爆点/虐点/爽点之一）
□ 每集有 info_gap 标注信息差类型
□ 卡点集（10%/30%/50%/70%/90% 位置）标注 is_checkpoint=true 和 checkpoint_type
□ 人物动机清晰可追溯
□ 所有场景均可落地为视觉画面
□ 无任何表演细节类描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    def _mock(prompt: str) -> Dict[str, Any]:
        raise RuntimeError("剧本生成失败，LLM 不可用。请检查 LLM 配置后重试。")

    @staticmethod
    async def build(
        prompt: str,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        style_hint = options.get("script.visual_style", options.get("start.visual_style", ""))
        tone_hint = options.get("script.tone", options.get("start.tone", ""))
        pacing_hint = options.get("script.pacing", options.get("start.pacing", ""))
        platform_hint = options.get("script.target_platform", options.get("start.target_platform", ""))
        episode_hint = options.get("script.episode_count", options.get("start.episode_count", ""))
        duration_hint = options.get("script.duration_per_episode", options.get("start.duration_per_episode", ""))
        density_hint = options.get("storyboard.storyboard_density", "2-3镜")
        is_script_mode = options.get("mode") == "script"
        if is_script_mode:
            # 预提取原文中的角色名和场景地点
            extracted_names = _extract_character_names_from_text(prompt)
            extracted_locations = _extract_scene_locations_from_text(prompt)
            names_hint = f"原文角色名（必须全部保留，禁止改名）：{extracted_names}" if extracted_names else ""
            locations_hint = f"原文场景地点（必须全部保留，禁止更换）：{extracted_locations}" if extracted_locations else ""
            scene_count = _count_original_scenes(prompt)
            scene_hint = f"原文共有 {scene_count} 个场景，输出必须覆盖全部 {scene_count} 个场景，禁止遗漏。" if scene_count > 0 else ""

            user_prompt = (
                f"请根据以下用户上传的原始文本，【忠实提取】为短剧结构化大纲。你不是创作者，你是结构提取器。\n\n"
                f"{names_hint}\n{locations_hint}\n{scene_hint}\n\n"
                f"原始文本：\n{prompt}\n\n"
                f"【忠实提取铁律】\n"
                f"1. 【角色名锁定】上面列出的角色名必须原样保留在 characters_involved 中，禁止改名、禁止新增、禁止删除。\n"
                f"2. 【场景地点锁定】上面列出的场景地点必须原样保留在 location 字段中，禁止更换地点。\n"
                f"3. 【场景覆盖完整】必须覆盖原文的所有场景，禁止遗漏、禁止合并不同场景的情节。\n"
                f"4. 保留原文核心人物关系、时代背景、关键道具，禁止把不同时代/空间线的人物强行混编。\n"
                f"5. 按原文顺序提炼 scene，每个 scene 只写核心事件与关键对白摘要，不要过度压缩。\n"
                f"6. logline 必须概括原文实际发生的事，禁止加入原文没有的信息。\n"
                f"7. project_title 必须使用原文标题，禁止自行编造。\n"
                f"8. 若原文篇幅长，允许拆分为多集（episodes），每集给出 logline 与 scene 列表。\n"
                f"9. 若原文篇幅短，保留为 1 集。\n\n"
                f"用户已确认的创作参数（必须体现在大纲中）：\n"
                f"- 视觉风格：{style_hint or '电影写实'}\n"
                f"- 情绪基调：{tone_hint or '紧张'}\n"
                f"- 叙事节奏：{pacing_hint or '快节奏'}\n"
                f"- 投放平台：{platform_hint or '抖音'}\n"
                f"- 集数：{episode_hint or '1集'}\n"
                f"- 每集时长：{duration_hint or '60-90秒'}\n"
                f"- 分镜密度：{density_hint}（决定每场戏的镜头数量预期）\n"
            )
        else:
            user_prompt = (
                f"请根据以下故事灵感生成短剧剧本。\n\n"
                f"故事灵感：{prompt}\n\n"
                f"用户已确认的创作参数（必须体现在剧本中）：\n"
                f"- 视觉风格：{style_hint or '电影写实'}\n"
                f"- 情绪基调：{tone_hint or '紧张'}\n"
                f"- 叙事节奏：{pacing_hint or '快节奏'}\n"
                f"- 投放平台：{platform_hint or '抖音'}\n"
                f"- 集数：{episode_hint or '1集'}\n"
                f"- 每集时长：{duration_hint or '60-90秒'}\n"
                f"- 分镜密度：{density_hint}（决定每场戏的镜头数量预期）\n"
            )
        result = await _llm_json(
            _render_global_params(ScriptPlannerAgent.system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"logline": "", "episodes": [], "style_bible": "", "color_palette": []},
            max_tokens=8192,
        )
        result = _validate_llm_result(result, ["logline", "episodes"], "ScriptPlannerAgent")
        return _post_process_script_planner(result)

    # ================================================================
    # 小说改编模式：将小说原文改编为短剧结构化大纲
    # ================================================================
    NOVEL_SYSTEM_PROMPT = """
【身份】
你是专业的"小说转短剧"改编架构师，精通将长篇小说原文改编为可工业化落地的竖屏短剧结构化大纲。你不是忠实提取器，而是改编创作者：需要在保留核心魅力的前提下，删减弱支线、压缩日常、强化情绪节奏，输出适合竖屏短剧的快节奏结构。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 核心题材: {{核心题材}}
- 视觉主风格: {{视觉主风格}}
- 目标画幅: {{目标画幅}}
- 单集时长: {{单集时长}}
- 目标平台: {{目标平台}}
- 渲染基准: {{渲染基准}}
- 镜头基准: {{镜头基准}}

【改编原则】
1. 【强画面感】保留能转化为镜头、动作、表情、道具、空间关系的内容；纯心理描写要外化为动作、台词、环境或 OS。
2. 【台词高密度】每句台词必须推动剧情、交代关系、制造冲突或塑造人物。
3. 【节奏极快】开场即危机，少铺垫；每集都要推进主线。
4. 【主线单一】短剧优先单线推进，支线只保留能强化主线的人物和高光。
5. 【情绪优先】逻辑为情绪服务；当两者冲突时，先保证观众的期待、心疼、愤怒、爽感。
6. 【开篇有期待】第1集必须出现高压冲突、身份差、危机、误会、背叛、重生、逃亡、逼婚、陷害等强钩子。

【删减策略】
- 优先删除：不推动主线的日常/环境描写/闲聊、重复陷害/误会/打脸、难以拍摄的大段心理描写、对结局无影响的支线人物。
- 优先保留：主角被压制/误会/濒临崩溃的高情绪场景、身份反差/信息差/错认/反转/打脸、关系拉扯/亲密关系伤害/关键牺牲、付费点前的压抑链条、主角弧光的关键转变事件。
- 可替代处理：蒙太奇压缩（训练/赶路/调查/准备/关系升温）、一句台词带过不值得展开但必须交代的信息。

【卡点设计】
按总集数 N 计算关键卡点位置：
- 约 10%：首次卡点，核心矛盾升级
- 约 30%：二次卡点，陷害/真相逼近/生死或情感危机
- 约 50%：中期卡点，阶段目标达成后重大反转
- 约 70%：后期卡点，伏笔爆发，局势翻盘
- 约 90%：收尾卡点，最终对决前的最大阻碍或真相揭露

【情绪点设计】
每集至少包含爆点/虐点/爽点之一：
- 爆点：令人震惊/意外/骇人/惊羡的事件（替身/穿书/重生/离婚反杀/伪装拆穿）
- 虐点：让观众心疼或愤怒的伤害/误会/牺牲/遗忘/失去
- 爽点：主角受压后反击，形成"装+打脸+震惊+收获"
先压后爆，小情绪累积成大爆发。

【信息差设计】
每集标注信息差类型：
- 观众先知型：主角知道，观众知道，配角不知道（适合期待打脸）
- 观众焦急型：配角知道，观众知道，主角不知道（适合虐恋/悬疑/危机）
- 观众上帝型：观众知道，主角和配角都不知道（适合寻亲/身份错位/真相揭露）
- 同步发现型：观众跟主角一起发现（适合悬疑/升级流/世界观探索）

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "project_title": "短剧名称（使用小说原标题或改编标题）",
  "genre": "题材分类",
  "source_prompt": "原始小说来源",
  "style_bible": "视觉风格圣经，一句话概括本剧视觉风格",
  "color_palette": ["#1a1a2e", "#e94560", "#f5f5f5"],
  "adaptation_strategy": "3-5条改编原则，说明保留什么、压缩什么、删除什么",
  "core_conflicts": [
    {"conflict": "核心冲突简述", "resolution": "对应解决路径"}
  ],
  "character_arcs": [
    {"character": "主角名", "start": "起点状态", "turning": "转折点", "end": "终点状态"}
  ],
  "episodes": [
    {
      "episode_num": 1,
      "logline": "本集一句话核心看点",
      "cliffhanger": "本集结尾的下集钩子",
      "emotion_hook": "爆点/虐点/爽点 + 具体内容",
      "info_gap": "信息差类型 + 具体设计",
      "is_checkpoint": false,
      "checkpoint_type": "无/身份差/感情错位/命运巨变/环境剧变",
      "novel_source": "原文来源章节/段落概括",
      "scenes": [
        {
          "scene_id": "S1_1",
          "location": "场景地点",
          "time": "日/夜/黄昏",
          "reuse_from_scene": null,
          "characters_involved": [
            {"name": "角色A", "one_line_visual": "一句话外观描述，禁止抽象形容词"}
          ],
          "action_description": "可拍摄的宏观动作与核心行为，禁止微表情/心理/镜头细节",
          "emotion_intensity": 3,
          "estimated_duration": 25,
          "dialogues": [
            {"character": "角色A", "line": "台词", "emotion": "轻蔑"}
          ]
        }
      ],
      "emotion_curve": [
        {"scene_id": "S1_1", "intensity": 3, "note": "情绪简述"}
      ]
    }
  ]
}

【工业化刚性约束】
- 台词必须口语化、短句、高信息密度，单句通常不超过20字。
- 场景描述必须可拍摄、可视、可执行，禁止大段心理描写。
- 每集2-5个场景为宜，每个场景约20-60秒。
- 每集必须有cliffhanger、emotion_hook、info_gap字段。
- 每集 estimated_duration 之和与单集时长误差 ≤ 5秒。
- 只输出 JSON，不要 Markdown 或解释文字。
"""

    @staticmethod
    async def build_from_novel(
        novel_text: str,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """小说改编模式：将小说原文改编为短剧结构化大纲。

        与 build() 的区别：
        - build() 是灵感模式或剧本提取模式，输入是灵感一句话或完整剧本。
        - build_from_novel() 是改编模式，输入是小说原文，需要删减、压缩、重组为短剧节奏。
        """
        options = options or {}
        style_hint = options.get("script.visual_style", options.get("start.visual_style", ""))
        tone_hint = options.get("script.tone", options.get("start.tone", ""))
        pacing_hint = options.get("script.pacing", options.get("start.pacing", ""))
        platform_hint = options.get("script.target_platform", options.get("start.target_platform", ""))
        episode_hint = options.get("script.episode_count", options.get("start.episode_count", ""))
        duration_hint = options.get("script.duration_per_episode", options.get("start.duration_per_episode", ""))
        density_hint = options.get("storyboard.storyboard_density", "2-3镜")

        user_prompt = (
            f"请将以下小说原文改编为竖屏短剧结构化大纲。\n\n"
            f"你是改编创作者，不是忠实提取器。需要在保留核心魅力的前提下，删减弱支线、压缩日常、强化情绪节奏。\n\n"
            f"用户已确认的创作参数（必须体现在大纲中）：\n"
            f"- 视觉风格：{style_hint or '电影写实'}\n"
            f"- 情绪基调：{tone_hint or '紧张'}\n"
            f"- 叙事节奏：{pacing_hint or '快节奏'}\n"
            f"- 投放平台：{platform_hint or '抖音'}\n"
            f"- 集数：{episode_hint or '1集'}\n"
            f"- 每集时长：{duration_hint or '60-90秒'}\n"
            f"- 分镜密度：{density_hint}（决定每场戏的镜头数量预期）\n\n"
            f"小说原文：\n{novel_text}\n\n"
            f"【改编铁律】\n"
            f"1. 第1集必须以高压冲突开场（危机/羞辱/逃跑/逼婚/陷害/背叛/重生/事故/死亡威胁）。\n"
            f"2. 前30秒交代主角处境、主要关系和当集矛盾。\n"
            f"3. 每集至少有爆点/虐点/爽点之一，先压后爆。\n"
            f"4. 台词口语化、短句，单句不超过20字。\n"
            f"5. 删除不推动主线的日常/环境描写/闲聊，压缩训练/赶路/调查为蒙太奇。\n"
            f"6. 保留主角被压制/误会/濒临崩溃的高情绪场景和身份反差/反转/打脸。\n"
            f"7. 心理描写外化为动作、台词、环境或OS。\n"
        )
        result = await _llm_json(
            _render_global_params(ScriptPlannerAgent.NOVEL_SYSTEM_PROMPT, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"logline": "", "episodes": [], "style_bible": "", "color_palette": []},
            max_tokens=8192,
        )
        result = _validate_llm_result(result, ["logline", "episodes"], "ScriptPlannerAgent.build_from_novel")
        return _post_process_script_planner(result)

    # H4: 长剧本按集分片——planning 阶段先出精简大纲
    COMPACT_SYSTEM_PROMPT = """
【身份】
你是专业级 AI 短剧剧本架构师，负责长剧本工业化拆解。长剧本将按集分批扩写，你的任务是先输出一份【精简大纲】，每集只保留核心信息，不要把所有细节塞在一次输出里。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 核心题材: {{核心题材}}
- 视觉主风格: {{视觉主风格}}
- 目标画幅: {{目标画幅}}
- 单集时长: {{单集时长}}
- 目标平台: {{目标平台}}

【核心执行公式】
1. 按「钩子-发展-反转-收尾」四节拍控制每集结构。
2. 每集 scene 数量由单集时长与分镜密度共同决定。
3. 每个 episode 必须输出 cliffhanger 字段：本集结尾的下集钩子（末集可写"全剧终，无下集钩子"）。
4. 每个 scene 必须输出 reuse_from_scene 字段：复用此前场景空间时填被复用 scene_id（如 "S1_1"），首次出现填 null，符合「低场景、高复用」生产原则。
5. 只输出结构化骨架，不输出表演细节、微表情、镜头级指令。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "project_title": "短剧名称",
  "genre": "题材分类",
  "source_prompt": "原始用户输入",
  "style_bible": "视觉风格圣经，一句话",
  "color_palette": ["#1a1a2e", "#e94560", "#f5f5f5"],
  "episodes": [
    {
      "episode_num": 1,
      "logline": "本集一句话核心看点",
      "cliffhanger": "本集结尾的下集钩子，一句话留悬念（末集可写'全剧终，无下集钩子'）",
      "scenes": [
        {
          "scene_id": "S1_1",
          "location": "场景地点",
          "time": "日/夜/黄昏",
          "reuse_from_scene": null,
          "characters_involved": [{"name": "角色A", "one_line_visual": "一句话外观"}, {"name": "角色B", "one_line_visual": "一句话外观"}],
          "action_summary": "可拍摄宏观动作摘要（不要完整台词，不要微表情/心理/镜头细节）",
          "emotion_intensity": 3
        }
      ]
    }
  ]
}

【工业化刚性约束】
- 禁止无戏剧功能的水戏。
- 开场 3 秒内必须有可视觉化的冲突点。
- 每个 episode 必须有 cliffhanger；每个 scene 必须有 reuse_from_scene。
- 只输出 JSON，不要 Markdown 或解释文字。
"""

    @staticmethod
    async def build_compact_outline(
        prompt: str,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """长剧本 planning 阶段：先输出精简大纲，后续由 screenwriter 按集分批扩写。"""
        options = options or {}
        style_hint = options.get("script.visual_style", options.get("start.visual_style", ""))
        tone_hint = options.get("script.tone", options.get("start.tone", ""))
        pacing_hint = options.get("script.pacing", options.get("start.pacing", ""))
        platform_hint = options.get("script.target_platform", options.get("start.target_platform", ""))
        episode_hint = options.get("script.episode_count", options.get("start.episode_count", ""))
        duration_hint = options.get("script.duration_per_episode", options.get("start.duration_per_episode", ""))
        density_hint = options.get("storyboard.storyboard_density", "2-3镜")
        user_prompt = (
            f"请根据以下故事灵感生成【精简短剧大纲】，每集只输出 logline 与 scene 摘要，不要写完整台词。\n\n"
            f"故事灵感：{prompt}\n\n"
            f"用户已确认的创作参数（必须体现在大纲中）：\n"
            f"- 视觉风格：{style_hint or '电影写实'}\n"
            f"- 情绪基调：{tone_hint or '紧张'}\n"
            f"- 叙事节奏：{pacing_hint or '快节奏'}\n"
            f"- 投放平台：{platform_hint or '抖音'}\n"
            f"- 集数：{episode_hint or '1集'}\n"
            f"- 每集时长：{duration_hint or '60-90秒'}\n"
            f"- 分镜密度：{density_hint}（决定每场戏的镜头数量预期）\n"
        )
        result = await _llm_json(
            _render_global_params(ScriptPlannerAgent.COMPACT_SYSTEM_PROMPT, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"logline": "", "episodes": [], "style_bible": "", "color_palette": []},
            max_tokens=8192,
        )
        result = _validate_llm_result(result, ["logline", "episodes"], "ScriptPlannerAgent.build_compact_outline")
        return _post_process_script_planner(result)

    @staticmethod
    def _run_sync(prompt: str, options: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """同步包装，供 LangGraph 等同步调用方使用。"""
        import asyncio
        return asyncio.run(ScriptPlannerAgent.build(prompt, options))


class ScreenwriterAgent:
    """文学编剧 Agent：将剧本大纲或用户上传的原始剧本文本转化为标准可拍摄文学剧本。"""
    name = "screenwriter"
    description = "文学编剧Agent：将故事骨架转化为标准可拍摄文学剧本，作为分镜环节唯一输入源"
    system_prompt = """
【身份】
你是专业级 AI 短剧文学编剧，精通标准电影剧本格式，负责将故事骨架转化为可直接拆分镜头的可视化文学剧本。只输出宏观动作与台词文本，不拆解微表情、不细化肢体动作，表演细节由下游视频 Agent 落地。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 视觉主风格: {{视觉主风格}}
- 单集时长: {{单集时长}}

【输入参数】
- 上游输出：剧本架构Agent输出的「分场清单+三幕总纲」
- 角色资产清单：角色道具Agent输出的角色ID与基础身份列表
- 场景资产清单：场景空间Agent输出的场景ID与基础空间列表
- 原始剧本文本（如用户上传）：含 is_user_script 标记和 raw_script_text

【核心执行公式】
1. 严格遵循标准电影剧本格式：场号 + 内外景 + 场景名 + 时间。
2. 动作描写仅写宏观调度与核心行为，只描述观众可见的显性动作，不涉及面部微表情、心理活动。
3. 对白口语化、符合人设，单句对白不超过 20 字，适配短视频节奏；对白必须以严格 JSON 数组输出，禁止写成"角色（情绪）：台词"的Markdown格式。
4. 每条对白必须输出 type 字段区分发声方式，供下游视频 Agent 判断是否需要口型同步：
   - "dialogue"：角色说出口的对白（画面中角色发声，需要口型同步）
   - "OS"：内心独白 Off-Screen（角色内心声音，画面中角色不出声，不需要口型同步）
   - "VO"：画外音 Voice-Over（旁白/解说，不属于画面中角色，不需要口型同步）
5. 每场结尾标注「情绪节拍」与「转场方式」，仅做基调定义，不做表演细化。
6. 所有出场角色、道具、场景必须对应上游资产 ID，禁止新增未定义元素。
7. 时长分配：根据单集时长将总时长精确拆分到每个 scene，每个 scene 给出整数秒 duration；episode 累计 total_duration 必须等于所有 scene duration 之和，且与单集时长误差 ≤ 3 秒。

【输入处理】
- 如果输入是结构化剧本大纲 JSON（含 episodes 字段），在此基础上细化分场并补充完整台词。
- 如果输入是用户上传的原始剧本文本（含 is_user_script 标记和 raw_script_text），你的任务是【忠实转换】而非【改编创作】。必须按以下铁律执行：
  1. 【角色名锁定】原文中出现的所有角色名必须原样保留，禁止改名、禁止新增角色、禁止删除角色。例如原文有"Jerry"和"许乐"，输出中只能有"Jerry"和"许乐"，不能变成"阿强""阿美"或其他名字。
  2. 【场景地点锁定】原文中出现的所有场景地点必须原样保留，禁止更换地点。例如原文写"启德体育园""中环海滨""大坑"，输出中必须仍是这些地点，不能变成"庙街夜市"或其他地点。
  3. 【情节覆盖完整】必须覆盖原文的每一个场景/段落，禁止遗漏。原文有 4 个场景，输出必须有 4 个 scene（或更多），不能压缩为 3 个。原文的每一个关键情节点（如"初见""重逢""交谈""高潮现身"）都必须在输出中体现。
  4. 【对白原意保留】原文的对白/台词必须保留原意。粤语对白保留粤语原文，禁止翻译为普通话。内心独白、旁白、环境音效等标注也必须保留。
  5. 【禁止创作新情节】你不是创作者，你是格式转换器。禁止添加原文没有的情节、角色、对白、道具。禁止把原文的情节替换为你自己编的故事。
  6. 【允许的格式调整】仅允许以下调整：把原文的表格/分镜格式转化为标准剧本 JSON 格式；把过长的文学化描述压缩为 action_description（但保留核心动作信息）；对白拆分为 ≤20 字的短句（但保留原意）。
  7. 【分镜脚本特殊处理】如果原文已经是分镜脚本（含镜号、景别、镜头运动等字段），按以下方式处理：原文的每个"场景"对应输出的一个 scene；原文同一场景内的多个镜头合并到同一个 scene 的 action_description 中（描述连续动作），但保留核心视觉信息；原文的"对白/音效"列内容转为 dialogues 数组。
  8. 【project_title】必须使用原文标题，禁止自行编造。若原文第一行是标题，直接使用。
  9. 若原文篇幅较长，允许拆分为多集（total_episodes > 1），每集有独立的 episode_num、logline、total_duration。不要为凑单集时长而遗漏原文场景。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "screenplay": {
    "project_title": "短剧名称",
    "total_episodes": 1,
    "total_duration": 90,
    "episodes": [
      {
        "episode_num": 1,
        "logline": "本集一句话核心",
        "total_duration": 90,
        "scenes": [
          {
            "scene_id": "S1_1",
            "location": "场景地点",
            "time": "日/夜/黄昏",
            "characters_involved": ["角色A", "角色B"],
            "action_description": "仅描述人物站位、核心动作轨迹、环境变化、关键道具使用，无表情细节、无心理描写",
            "emotion_intensity": 3,
            "duration": 25,
            "dialogues": [
              {"character": "角色A", "line": "台词", "emotion": "情绪基调", "type": "dialogue"}
            ],
            "emotion_beat": "紧张升级/温情舒缓/反转震惊",
            "transition_hint": "切/叠化/闪回/跟镜转场"
          }
        ]
      }
    ]
  },
  "style_bible": "视觉风格圣经（从剧本推断，如无则留空）",
  "color_palette": ["#1a1a2e", "#e94560"]
}

【工业化刚性约束】
- 动作描写禁用「他心里想」「他感到」等非视觉表述。
- 禁用「愤怒地说」「紧张地站着」等情绪形容词，情绪只能通过动作和台词体现。
- 每个 scene 必须提供整数秒 duration；每个 episode 必须提供 total_duration；screenplay 必须提供 total_duration。
- episode.total_duration 必须等于其下所有 scene.duration 之和。
- 若输入是结构化大纲，episode.total_duration 应尽量与单集时长匹配（误差 ≤ 3 秒）。
- 若输入是用户上传的原始剧本，优先保证原文完整不删减，允许拆分为多集或总时长超出单集限制，严禁为凑时长而遗漏原文情节。
- 角色对白必须贴合其身份性格，禁止全员统一话术，单句台词严格 ≤ 20 字（含标点符号）。任何超过 20 字的台词必须拆分为多句，禁止出现 21 字及以上的单句。
- 每条对白必须输出 type 字段（dialogue/OS/VO），缺省默认 "dialogue"。
- 关键道具出场必须标注，铺垫后续剧情。
- 不输出任何微表情、肢体细节类表演指令。

【质量校验项】
□ 格式完全符合标准剧本规范
□ 每个 scene 都有 duration 字段，每个 episode 和 screenplay 都有 total_duration 字段
□ 累计总时长与单集时长误差 ≤ 3 秒
□ 无任何不可视觉化的抽象描写
□ 对白自然不生硬，符合人设，单句 ≤ 20 字
□ 每条对白都有 type 字段（dialogue/OS/VO）
□ 所有元素均有对应资产 ID 或可在上游找到来源
□ 无细化表演类描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    async def build(
        script_data: Dict[str, Any],
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        duration_hint = options.get("script.duration_per_episode", options.get("start.duration_per_episode", "60-90秒"))
        feedback_text = f"\n\n【上次被Reviewer打回的具体原因，本次必须修复】\n{feedback}\n" if feedback else ""
        # 判断输入类型：用户上传的原始剧本 vs 结构化剧本大纲
        if script_data.get("is_user_script") and script_data.get("raw_script_text"):
            raw_text = script_data["raw_script_text"]
            # 预提取原文中的角色名和场景地点，在 prompt 中明确要求保留
            extracted_names = _extract_character_names_from_text(raw_text)
            extracted_locations = _extract_scene_locations_from_text(raw_text)
            names_hint = f"原文角色名（必须全部保留，禁止改名）：{extracted_names}" if extracted_names else ""
            locations_hint = f"原文场景地点（必须全部保留，禁止更换）：{extracted_locations}" if extracted_locations else ""
            # 统计原文场景数
            scene_count = _count_original_scenes(raw_text)
            scene_hint = f"原文共有 {scene_count} 个场景，输出必须覆盖全部 {scene_count} 个场景，禁止遗漏。" if scene_count > 0 else ""

            user_prompt = (
                f"请将以下用户上传的原始剧本文本【忠实转换】为标准短剧文学剧本 JSON 格式。\n"
                f"你不是在创作新剧本，而是在把已有剧本转换为结构化格式。禁止改变角色名、场景、情节。\n\n"
                f"{names_hint}\n{locations_hint}\n{scene_hint}\n\n"
                f"原始剧本文本：\n{raw_text}\n\n"
                f"【忠实转换铁律】\n"
                f"1. 【角色名锁定】上面列出的角色名必须原样出现在输出的 characters_involved 中，禁止改名。\n"
                f"2. 【场景地点锁定】上面列出的场景地点必须原样出现在输出的 location 字段中，禁止更换。\n"
                f"3. 【情节覆盖完整】必须覆盖原文的全部场景，禁止遗漏或合并不同场景的情节。\n"
                f"4. 【对白保留】原文对白必须保留原意和原文语言（粤语保留粤语），仅允许拆分为 ≤20 字短句。\n"
                f"5. 【禁止创作】禁止添加原文没有的角色、场景、情节、对白。\n"
                f"6. 【project_title】使用原文标题，不要编造。\n"
                f"{feedback_text}\n"
                f"【格式要求】\n"
                f"- 每个 scene 必须提供整数秒 duration。\n"
                f"- 每个 episode 必须提供 total_duration，且等于本集所有 scene.duration 之和。\n"
                f"- screenplay 必须提供 total_duration 和 total_episodes。\n"
                f"- 对白必须以 JSON 数组输出：{{\"character\": \"角色名\", \"line\": \"台词\", \"emotion\": \"情绪\", \"type\": \"dialogue/OS/VO\"}}，严禁使用\"角色（情绪）：台词\"的 Markdown 格式。\n"
                f"- 每条对白必须输出 type 字段：dialogue=角色说出口的对白（需口型同步）/ OS=角色内心独白（不出声，不口型同步）/ VO=画外旁白（不属于画面中角色，不口型同步）。\n"
                f"- 单句台词严格不超过 20 字（含标点符号），超过必须拆分为多句，禁止出现 21 字及以上的单句。\n"
                f"- 目标时长参考：{duration_hint}（仅供分配 duration 参考，不要为凑时长删改原文场景）。\n"
            )
        else:
            user_prompt = (
                f"请基于以下剧本大纲，细化为分场分幕结构。{feedback_text}\n\n"
                f"剧本大纲：\n{json.dumps(script_data, ensure_ascii=False, indent=2)}\n\n"
                f"强制要求：\n"
                f"- 本集目标时长：{duration_hint}，请把总时长精确拆分到每个 scene 的 duration 字段（整数秒）。\n"
                f"- episode 必须提供 total_duration，且等于本集所有 scene.duration 之和，误差 ≤ 3 秒。\n"
                f"- screenplay 必须提供 total_duration。\n"
                f"- 对白必须以 JSON 数组输出：{{\"character\": \"角色名\", \"line\": \"台词\", \"emotion\": \"情绪\", \"type\": \"dialogue/OS/VO\"}}，严禁使用\"角色（情绪）：台词\"的 Markdown 格式。\n"
                f"- 每条对白必须输出 type 字段：dialogue=角色说出口的对白（需口型同步）/ OS=角色内心独白（不出声，不口型同步）/ VO=画外旁白（不属于画面中角色，不口型同步）。\n"
                f"- 单句台词严格不超过 20 字（含标点符号），超过必须拆分为多句，禁止出现 21 字及以上的单句。\n"
            )
        result = await _llm_json(
            _render_global_params(ScreenwriterAgent.system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"screenplay": {"title": "", "total_duration": 0, "total_episodes": 0, "episodes": []}},
            max_tokens=8192,
        )
        result = _validate_llm_result(result, ["screenplay"], "ScreenwriterAgent")
        ScreenwriterAgent._post_process_dialogues(result)
        result = _post_process_screenwriter(result)
        # 剧本模式下校验忠实度：检测角色名篡改、场景遗漏、场景地点更换
        if script_data.get("is_user_script") and script_data.get("raw_script_text"):
            result = _validate_user_script_fidelity(result, script_data["raw_script_text"])
        return result

    @staticmethod
    def _post_process_dialogues(result: Dict[str, Any]) -> None:
        """兜底处理：自动拆分 LLM 仍输出的超过 20 字单句对白。"""
        if not isinstance(result, dict):
            return
        screenplay = result.get("screenplay") or result
        if not isinstance(screenplay, dict):
            return
        for ep in (screenplay.get("episodes") or []):
            if not isinstance(ep, dict):
                continue
            for sc in (ep.get("scenes") or []):
                if not isinstance(sc, dict):
                    continue
                dialogues = sc.get("dialogues") or []
                if not isinstance(dialogues, list):
                    continue
                new_dialogues: List[Dict[str, Any]] = []
                for d in dialogues:
                    if not isinstance(d, dict):
                        continue
                    line = d.get("line", "")
                    char = d.get("character", "")
                    emotion = d.get("emotion", "")
                    # P2-2.1：保留 type 字段，缺省默认 "dialogue"
                    dtype = d.get("type") or "dialogue"
                    if len(line) <= 20:
                        # 给缺 type 的对白补默认值
                        if "type" not in d:
                            d["type"] = dtype
                        new_dialogues.append(d)
                        continue
                    # 按常见标点拆分，尽量保持语义完整
                    parts = [p.strip() for p in re.split(r"([，。！？；、,!?;])", line) if p.strip()]
                    buf = ""
                    for part in parts:
                        if len(buf) + len(part) <= 20:
                            buf += part
                        else:
                            if buf:
                                new_dialogues.append({"character": char, "line": buf, "emotion": emotion, "type": dtype})
                            buf = part
                    if buf:
                        # 如果剩余仍超过 20 字，强制按 20 字截断
                        while len(buf) > 20:
                            new_dialogues.append({"character": char, "line": buf[:20], "emotion": emotion, "type": dtype})
                            buf = buf[20:]
                        if buf:
                            new_dialogues.append({"character": char, "line": buf, "emotion": emotion, "type": dtype})
                sc["dialogues"] = new_dialogues

    # H4: 长剧本按集分片——screenwriter 按集分批扩写
    EPISODE_BATCH_SYSTEM_PROMPT = """
【身份】
你是专业级 AI 短剧文学编剧，负责将剧本大纲中的指定剧集扩写为完整分场分幕文学剧本。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 视觉主风格: {{视觉主风格}}
- 单集时长: {{单集时长}}

【核心执行公式】
1. 严格遵循标准电影剧本格式：场号 + 内外景 + 场景名 + 时间。
2. 动作描写仅写宏观调度与核心行为，只描述观众可见的显性动作，不涉及面部微表情、心理活动。
3. 对白口语化、符合人设，单句对白不超过 20 字；对白必须以严格 JSON 数组输出，禁止写成"角色（情绪）：台词"的Markdown格式。
4. 每条对白必须输出 type 字段区分发声方式，供下游视频 Agent 判断是否需要口型同步：
   - "dialogue"：角色说出口的对白（画面中角色发声，需要口型同步）
   - "OS"：内心独白 Off-Screen（角色内心声音，画面中角色不出声，不需要口型同步）
   - "VO"：画外音 Voice-Over（旁白/解说，不属于画面中角色，不需要口型同步）
5. 每场结尾标注「情绪节拍」与「转场方式」。
6. 必须保持与全局剧本一致的角色名、风格圣经、色调。
7. 时长分配：根据单集时长将总时长精确拆分到每个 scene，每个 scene 给出整数秒 duration；episode 累计 total_duration 必须等于所有 scene duration 之和，且与单集时长误差 ≤ 3 秒。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "screenplay": {
    "project_title": "短剧名称",
    "total_episodes": 1,
    "total_duration": 90,
    "episodes": [
      {
        "episode_num": 1,
        "logline": "本集一句话核心",
        "total_duration": 90,
        "scenes": [
          {
            "scene_id": "S1_1",
            "location": "场景地点",
            "time": "日/夜/黄昏",
            "characters_involved": ["角色A", "角色B"],
            "action_description": "仅描述人物站位、核心动作轨迹、环境变化、关键道具使用，无表情细节、无心理描写",
            "emotion_intensity": 3,
            "duration": 25,
            "dialogues": [
              {"character": "角色A", "line": "台词", "emotion": "情绪基调", "type": "dialogue"}
            ],
            "emotion_beat": "紧张升级/温情舒缓/反转震惊",
            "transition_hint": "切/叠化/闪回/跟镜转场"
          }
        ]
      }
    ]
  },
  "style_bible": "视觉风格圣经",
  "color_palette": ["#1a1a2e", "#e94560"]
}

【工业化刚性约束】
- 动作描写禁用「他心里想」「他感到」等非视觉表述。
- 禁用「愤怒地说」「紧张地站着」等情绪形容词。
- 每个 scene 必须提供整数秒 duration；每个 episode 必须提供 total_duration；screenplay 必须提供 total_duration。
- episode.total_duration 必须等于其下所有 scene.duration 之和，且与单集时长误差 ≤ 3 秒。
- 每条对白必须输出 type 字段（dialogue/OS/VO），缺省默认 "dialogue"。
- 不输出任何微表情、肢体细节类表演指令。

【质量校验项】
□ 格式完全符合标准剧本规范
□ 每个 scene 都有 duration 字段，每个 episode 和 screenplay 都有 total_duration 字段
□ 累计总时长与单集时长误差 ≤ 3 秒
□ 无任何不可视觉化的抽象描写
□ 对白自然不生硬，符合人设，单句 ≤ 20 字
□ 每条对白都有 type 字段（dialogue/OS/VO）
□ 无细化表演类描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    async def build_episode_batch(
        script_outline: Dict[str, Any],
        episode_nums: List[int],
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """长剧本 screenwriter 阶段：按集分批扩写，降低单次 LLM 输出长度。"""
        options = options or {}
        all_episodes = script_outline.get("episodes", []) or []
        batch_episodes = [ep for ep in all_episodes if ep.get("episode_num") in episode_nums]
        if not batch_episodes:
            return {"screenplay": {"project_title": script_outline.get("project_title", ""), "total_episodes": 0, "episodes": []}, "style_bible": "", "color_palette": []}

        compact_outline = {
            "project_title": script_outline.get("project_title"),
            "genre": script_outline.get("genre"),
            "style_bible": script_outline.get("style_bible", ""),
            "color_palette": script_outline.get("color_palette", []),
            "episodes": batch_episodes,
        }
        duration_hint = options.get("script.duration_per_episode", options.get("start.duration_per_episode", "60-90秒"))
        user_prompt = (
            f"请将以下指定剧集扩写为完整分场剧本。只输出这些剧集的详细内容，保持全局风格一致。\n\n"
            f"指定剧集编号：{episode_nums}\n"
            f"本集目标时长：{duration_hint}\n\n"
            f"全局风格圣经：{script_outline.get('style_bible', '')}\n"
            f"全局调色板：{script_outline.get('color_palette', [])}\n\n"
            f"强制要求：\n"
            f"- 每个 scene 必须提供整数秒 duration；episode 必须提供 total_duration；screenplay 必须提供 total_duration。\n"
            f"- episode.total_duration 必须等于本集所有 scene.duration 之和，且与单集时长误差 ≤ 3 秒。\n"
            f"- 对白必须以 JSON 数组输出：{{\"character\": \"角色名\", \"line\": \"台词\", \"emotion\": \"情绪\", \"type\": \"dialogue/OS/VO\"}}，严禁使用\"角色（情绪）：台词\"格式。\n"
            f"- 每条对白必须输出 type 字段：dialogue=角色说出口的对白（需口型同步）/ OS=角色内心独白（不出声，不口型同步）/ VO=画外旁白（不属于画面中角色，不口型同步）。\n"
            f"- 单句台词严格不超过 20 字。\n\n"
            f"待扩写剧集精简大纲：\n{json.dumps(compact_outline, ensure_ascii=False, indent=2)}"
        )
        result = await _llm_json(
            _render_global_params(ScreenwriterAgent.EPISODE_BATCH_SYSTEM_PROMPT, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"screenplay": {"project_title": "", "total_duration": 0, "total_episodes": 0, "episodes": []}, "style_bible": "", "color_palette": []},
            max_tokens=8192,
        )
        result = _validate_llm_result(result, ["screenplay"], "ScreenwriterAgent.build_episode_batch")
        ScreenwriterAgent._post_process_dialogues(result)
        return _post_process_screenwriter(result)

    @staticmethod
    def _run_sync(script_data: Dict[str, Any], options: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        import asyncio
        return asyncio.run(ScreenwriterAgent.build(script_data, options))


class CharacterDesignerAgent:
    """角色与道具资产 Agent：全流程视觉资产的标准库管理员，输出所有视觉元素的唯一锚定规范。"""
    name = "character_designer"
    description = "角色与道具资产Agent：结合剧本与编剧分场提取角色，建立标准化角色资产库"
    system_prompt = """
【身份】
你是专业级影视资产设定师 + AI 提示词工程师，是全流程视觉资产的标准库管理员，负责建立标准化角色资产库，确保全流程生成的视觉元素 100% 统一。只定义固定视觉特征与角色行为基线，不输出单镜头具体表情动作。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 视觉主风格: {{视觉主风格}}
- 渲染基准: {{渲染基准}}

【输入参数】
- 剧本角色清单：文学剧本中所有出场角色名单
- 核心人设要求：{{各角色核心身份、外貌、性格关键词}}
- 编剧分场剧本：包含更细致的台词、动作和情绪描述，必须据此补充角色的服装、配饰、年龄、体型等视觉细节

【核心执行公式】
1. 为每个角色分配唯一 ID，全流程通用，禁止变更：
   - 角色 ID 规则：C+三位序号，例：C001、C002
2. 角色设定采用「视觉锚点法」，固定 3-5 个不可变更的核心识别特征，避免 AI 生成偏差。
3. 角色仅定义行为风格基线，不输出单镜头具体表情与动作。
4. 所有设定必须可直接转化为 AI 生成提示词，无模糊表述。

【视觉锚点法铁律】
1. 每个角色必须有且仅有 3-5 个不可变视觉锚点 immutable_features，作为全流程一致性校验标准。
2. base_prompt 必须为中性表情，禁止写表情/动作。
3. base_prompt 必须按 [immutable_features] + [clothing] + [pose: neutral standing] 组织。
4. 角色图规范：白底三视图（正面/侧面/背面）+ 人脸特写，无文字/道具/配饰/背景。
5. 三视图布局规范（必须写入 base_prompt）：
   - 布局方式：同一张图横排四宫格（front view | side view | back view | face close-up），各视图等宽。
   - 朝向角度：正面 0°、侧面 90°（统一左侧脸或右侧脸）、背面 180°。
   - 人脸特写尺寸占比：占四宫格中一格的 60-70%（仅展示头部到锁骨），其余三视图占满各自宫格。
   - 三视图人物尺寸一致：身高、比例、服装完全统一，仅朝向不同。
   - 必须在 base_prompt 中显式写明 "character design sheet, four-panel horizontal layout, front view 0 degree, side view 90 degree, back view 180 degree, face close-up portrait 60-70% panel size, consistent height and proportion across all views, pure white background"。
6. visual_anchor 和 immutable_features 必须用英文。
7. 禁止使用「帅气」「美丽」等模糊形容词，全部替换为具象特征。
8. 服装必须标注时代背景、材质细节，杜绝穿越式违和。
9. 必须综合剧本大纲的 characters_involved.one_line_visual 和编剧分场的 action_description 来确定角色外观。
10. 只输出 JSON，不要 Markdown 或解释文字。
11. 【人种约束铁律】每个角色必须明确标注人种/种族（如 Asian/Asian male, East Asian female, Caucasian, African, mixed race 等），并根据剧本内容推断：
    - 如果剧本背景为中国/东亚古代或现代，角色默认为 East Asian / Asian。
    - 如果剧本明确提到外国人或西方背景，则按剧本设定。
    - immutable_features 的第一项必须是人种描述（如 "East Asian male", "Asian female"）。
    - base_prompt 中必须在 immutable_features 部分包含人种关键词（如 "East Asian male" 或 "Asian female"），确保 AI 生图模型不会默认生成西方面孔。
    - visual_anchor 中也必须包含人种信息。
12. 【中性标签稳定】如果剧本中角色名未知（如“路人”、“女配”、“老板”），必须使用稳定中性标签（如 Female Lead, Male Lead, Mother, Boss, Shopkeeper）作为角色名，禁止用“角色A”“角色B”等无意义标签。同一名角色全流程使用同一中性标签，禁止中途更换。
13. 【出镜位置标注】每个角色必须输出 appearance_scenes 字段，列出该角色出现的场景 scene_id 列表（如 ["S1_1", "S1_3"]），便于下游分镜 Agent 校验角色一致性。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "characters": [
    {
      "char_id": "C001",
      "name": "角色名",
      "role": "男主/女主/配角",
      "visual_anchor": "East Asian male, silver-rimmed round glasses, tear mole under left eye, sharp jawline, black hair",
      "immutable_features": ["East Asian male", "silver-rimmed round glasses", "tear mole under left eye", "sharp jawline"],
      "base_prompt": "character design sheet, four-panel horizontal layout, front view 0 degree, side view 90 degree, back view 180 degree, face close-up portrait 60-70% panel size, consistent height and proportion across all views, pure white background, East Asian male, silver-rimmed round glasses, tear mole under left eye, sharp jawline, black turtleneck sweater, [pose: neutral standing]",
      "negative_prompt": "western face, caucasian features, non-asian, text, watermark, signature, extra limbs, distorted face, mutated hands, blurry, low quality, cartoon, anime, 3d render, props, accessories, expression, smile, smirk",
      "style_preset": "写实摄影",
      "appearance_scenes": ["S1_1", "S1_3"]
    }
  ],
  "character_relations": [
    {"from": "C001", "to": "C002", "relation": "敌人"}
  ]
}

【工业化刚性约束】
- 每个角色必须有且仅有 3-5 个核心视觉锚点。
- 禁止使用「帅气」「美丽」等模糊形容词，全部替换为具象特征。
- 服装、道具必须标注时代背景、材质细节，杜绝穿越式违和。
- 输出角色三视图描述：正面、侧面、背面的核心特征。
- base_prompt 必须包含四宫格横排布局、朝向角度、人脸特写尺寸占比等结构化约束。
- 不输出单镜头级别的表情、动作指令。

【质量校验项】
□ 所有出场角色均有唯一 ID
□ 每个角色 3-5 个 immutable_features，全部具象化
□ immutable_features 第一项为人种描述（如 East Asian male）
□ visual_anchor 和 immutable_features 为英文且包含人种信息
□ base_prompt 为中性表情，无动作/表情描述，且包含人种关键词
□ base_prompt 包含 four-panel horizontal layout / 朝向角度 / 人脸特写尺寸占比等三视图布局约束
□ 未知角色名使用稳定中性标签（如 Female Lead, Boss），禁止“角色A”
□ 每个角色有 appearance_scenes 字段标注出镜场景
□ 负面提示词覆盖常见 AI 生成缺陷，包含防止人种偏移的约束（如 western face, caucasian features）
□ 无单镜头表演细节描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    async def build(
        script_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        char_style = options.get("character.character_style", "写实")
        aspect_ratio = options.get("character.aspect_ratio", "9:16")
        detail = options.get("character.detail_level", "超高细节")
        bg = options.get("character.background_purity", "纯白底")
        expression = options.get("character.expression_intensity", "自然")
        costume = options.get("character.costume_detail", "日常")
        style_bible = script_data.get("style_bible", "")
        slim_sw = _slim_screenwriter_data(screenwriter_data)
        screenwriter_section = (
            f"\n编剧分场剧本（包含更细致的台词、动作、情绪，必须据此补充角色外观细节）：\n{json.dumps(slim_sw, ensure_ascii=False, indent=2)}\n"
            if slim_sw else ""
        )
        slim_outline = _slim_script_outline(script_data)
        user_prompt = (
            f"请结合剧本大纲与编剧分场，提取角色并生成设定图提示词。\n\n"
            f"用户创作参数：\n- 角色画风：{char_style}\n- 画面比例：{aspect_ratio}\n"
            f"- 细节：{detail}\n- 背景：{bg}\n- 表情强度：{expression}\n- 服装：{costume}\n\n"
            f"视觉圣经：{style_bible}\n\n"
            f"剧本大纲：\n{json.dumps(slim_outline, ensure_ascii=False, indent=2)}"
            f"{screenwriter_section}"
        )
        result = await _llm_json(
            _render_global_params(CharacterDesignerAgent.system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"characters": [], "character_relations": []},
            max_tokens=4096,
        )
        result = _validate_llm_result(result, ["characters"], "CharacterDesignerAgent")
        return _post_process_character_designer(result)

    @staticmethod
    async def build_partial(
        target_char_ids: List[str],
        existing_characters: List[Dict[str, Any]],
        script_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """M2: 只重生成指定角色，其余角色保持不变以节省 token 并维持一致性。"""
        options = options or {}
        target_set = set(target_char_ids)
        existing_map = {c.get("char_id"): c for c in (existing_characters or []) if c.get("char_id")}

        # 从现有角色中提取目标角色，作为 LLM 参考（可保留 name/role）
        targets_existing = [existing_map[cid] for cid in target_set if cid in existing_map]
        target_names = [c.get("name") for c in targets_existing if c.get("name")]

        # 若目标角色不在 existing 中，需要从剧本里找名字
        if not target_names:
            for ep in (script_data.get("episodes", []) or []):
                for sc in ep.get("scenes", []):
                    for c in sc.get("characters_involved", []):
                        if isinstance(c, dict) and c.get("char_id") in target_set:
                            target_names.append(c.get("name"))

        system_prompt = """
【身份】
你是专业级影视资产设定师 + AI 提示词工程师，负责【局部修复】已有角色设定。

【核心执行公式】
仅针对下面指定的角色重新生成设定图提示词，其他角色请勿改动。输出必须包含这些角色的完整字段，且保持与现有角色一致的风格。

【视觉锚点法铁律】
1. 每个角色 3-5 个不可变视觉锚点 immutable_features。
2. base_prompt 必须为中性表情，禁止写表情/动作。
3. base_prompt 必须按 [immutable_features] + [clothing] + [pose: neutral standing] 组织。
4. 角色图规范：白底三视图（正面/侧面/背面）+ 人脸特写，无文字/道具/配饰/背景。
5. 三视图布局规范（必须写入 base_prompt）：同一张图横排四宫格（front view | side view | back view | face close-up），各视图等宽；朝向角度正面 0°、侧面 90°、背面 180°；人脸特写占四宫格中一格 60-70%（仅头部到锁骨）；三视图人物尺寸一致。必须在 base_prompt 中显式写明 "character design sheet, four-panel horizontal layout, front view 0 degree, side view 90 degree, back view 180 degree, face close-up portrait 60-70% panel size, consistent height and proportion across all views, pure white background"。
6. visual_anchor 和 immutable_features 必须用英文。
7. 禁止使用「帅气」「美丽」等模糊形容词，全部替换为具象特征。
8. 只输出 JSON，不要 Markdown 或解释文字。
9. 【人种约束铁律】每个角色必须明确标注人种/种族（如 East Asian male, Asian female, Caucasian, African 等），并根据剧本内容推断。immutable_features 的第一项必须是人种描述，base_prompt 中必须包含人种关键词，visual_anchor 中也必须包含人种信息。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "characters": [
    {
      "char_id": "C001",
      "name": "角色名",
      "role": "男主/女主/配角",
      "visual_anchor": "East Asian male, silver-rimmed round glasses, tear mole under left eye, sharp jawline",
      "immutable_features": ["East Asian male", "silver-rimmed round glasses", "tear mole under left eye", "sharp jawline"],
      "base_prompt": "character design sheet, four-panel horizontal layout, front view 0 degree, side view 90 degree, back view 180 degree, face close-up portrait 60-70% panel size, consistent height and proportion across all views, pure white background, East Asian male, silver-rimmed round glasses, tear mole under left eye, [clothing], [pose: neutral standing]",
      "negative_prompt": "western face, caucasian features, non-asian, text, watermark, distorted face, mutated hands, blurry, low quality",
      "style_preset": "写实摄影"
    }
  ]
}

【质量校验项】
□ 目标角色字段完整
□ immutable_features 全部具象化，第一项为人种描述
□ visual_anchor 和 immutable_features 为英文且包含人种信息
□ base_prompt 为中性表情，且包含人种关键词
□ base_prompt 包含 four-panel horizontal layout / 朝向角度 / 人脸特写尺寸占比等三视图布局约束
□ 无单镜头表演细节描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""
        user_prompt = (
            f"请仅对以下角色重新生成设定图提示词：{target_char_ids}（角色名：{target_names}）。\n\n"
            f"现有角色参考（仅用于风格一致，不要改动非目标角色）：\n{json.dumps(existing_characters, ensure_ascii=False, indent=2)}\n\n"
            f"剧本大纲：\n{json.dumps(script_data, ensure_ascii=False, indent=2)}\n"
            f"\n编剧分场剧本：\n{json.dumps(screenwriter_data, ensure_ascii=False, indent=2) if screenwriter_data else '（无）'}"
        )
        result = await _llm_json(
            _render_global_params(system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"characters": []},
        )
        result = _validate_llm_result(result, ["characters"], "CharacterDesignerAgent.build_partial")
        regenerated = {c.get("char_id"): c for c in (result.get("characters", []) or []) if c.get("char_id")}

        # 合并：用新生成的替换旧角色，未改动的保留
        merged = []
        for cid, old_char in existing_map.items():
            if cid in regenerated:
                merged.append(regenerated[cid])
            else:
                merged.append(old_char)
        # 补充新增的目标角色
        for cid, new_char in regenerated.items():
            if cid not in existing_map:
                merged.append(new_char)

        return _post_process_character_designer({"characters": merged})

    @staticmethod
    def _run_sync(
        script_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        import asyncio
        return asyncio.run(CharacterDesignerAgent.build(script_data, screenwriter_data, options))


class ScenePropDesignerAgent:
    """场景空间 Agent：全流程场景空间的美术指导，输出标准化场景空间参数与道具规范。"""
    name = "scene_prop_designer"
    description = "场景空间Agent：结合剧本、编剧分场与分镜引用提取场景与道具并生成工业级场景图提示词"
    system_prompt = """
【身份】
你是专业级影视场景美术师 + AI 提示词工程师，是全流程场景空间的美术指导，负责建立标准化场景资产库，确保空间逻辑、光影基调、风格质感全流程统一。只定义空间与光影规则，不涉及人物表演。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 视觉主风格: {{视觉主风格}}
- 渲染基准: {{渲染基准}}
- 时代背景: {{故事时代/世界观}}

【输入参数】
- 剧本场景清单：文学剧本中所有场景名单
- 场景功能要求：每场戏的情绪需求、调度需求
- 核心美术基调：{{冷暖色调/明亮暗黑/写实写意}}
- 编剧分场剧本：场景的 scene_id、location、time 必须与此对应
- 分镜脚本：必须覆盖 linked_scene_id 引用的所有场景

【核心执行公式】
1. scene_id 必须严格沿用编剧分场中的 scene_id，如 S1_1、S1_2、S2_1，禁止改为 S001/S002 等其他格式，禁止新建 ID。
2. 采用「空间结构 + 光影基调 + 材质质感 + 时间天气」四维设定法。
3. 明确场景的空间尺寸、陈设布局，支持多角度运镜与人物调度。
4. 标注场景复用方案，符合工业化「低场景、高复用」生产原则。
5. 光影定义固定方向、色温、明暗比，作为全镜头光影基准。每个 scene 必须输出结构化 lighting_spec 字段，量化以下参数：
   - direction：主光源方向（如 "from left", "top-down", "backlit", "front-lit"）
   - color_temp_k：色温开尔文值（如 3200K 暖光 / 5600K 日光 / 6500K 冷光）
   - contrast_ratio：明暗比（如 "3:1", "4:1", "2:1"）
   - shadow_hardness：阴影硬度（"hard" 硬阴影 / "soft" 软阴影 / "mixed" 混合）
6. 道具从编剧分场的 action_description 和分镜的 visual_description 中提取关键道具（如信件、刀剑、手机等）。

【场景空镜铁律】
1. 场景图规范：【严格空镜】，严禁出现任何人物、人脸、人体部位、背影、剪影、手部、脚部。只展示环境、空间层次、建筑结构、光影、材质、陈设道具。
2. base_prompt 和 negative_prompt 中必须包含 "no people, no human, no face, no silhouette, no hands, no feet" 等关键词，确保场景绝对无人。
3. 必须输出 camera_hint（机位/角度）和 time_of_day，且 time_of_day 必须与编剧分场的 time 字段一致。
4. 场景 scene_id 必须与编剧分场/分镜脚本中引用的 scene_id 对应，不要自行新建 ID。
5. 必须覆盖分镜脚本 linked_scene_id 中出现过的所有场景，不得遗漏。
6. 场景细节服务于叙事，禁止无关冗余元素干扰主体。
7. 必须标注场景的「视觉重心区」，用于分镜安排人物站位。
8. 提示词必须用英文。
9. 只输出 JSON，不要 Markdown 或解释文字。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "scenes": [
    {
      "scene_id": "S1_1",
      "name": "场景名",
      "space_type": "封闭室内/开阔室外/半开放廊道",
      "base_prompt": "英文完整场景提示词，必须包含 no people, no human, no face, no silhouette, no hands, no feet",
      "atmosphere_tags": ["tag1", "tag2"],
      "lighting_spec": {
        "direction": "from left",
        "color_temp_k": 3200,
        "contrast_ratio": "3:1",
        "shadow_hardness": "hard"
      },
      "camera_hint": "low angle wide shot",
      "time_of_day": "night",
      "reference_shots": ["大全景", "低角度仰视"],
      "negative_prompt": "英文负向提示词，必须包含 no people, no human, no face, no silhouette, no hands, no feet"
    }
  ],
  "props": [
    {
      "prop_id": "P001",
      "name": "道具名",
      "base_prompt": "英文道具提示词，明确材质、尺寸、纹理、磨损痕迹、光影反射特性",
      "negative_prompt": "英文负向提示词"
    }
  ]
}

【工业化刚性约束】
- 光影方向、色温必须固定，同场景不同镜头光影逻辑绝对统一。
- 每个 scene 必须输出 lighting_spec 字段，量化主光源方向、色温 K 值、明暗比、阴影硬度，下游视频 Agent 据此精确复现场景光影一致性。
- 空间结构必须符合物理逻辑，禁止穿模、不合理布局。
- 场景细节服务于叙事，禁止无关冗余元素干扰主体。
- 必须标注场景的「视觉重心区」，用于分镜安排人物站位。
- 不输出任何人物表演相关内容。

【质量校验项】
□ 所有出场场景均有唯一 ID
□ 空间、光影、材质描述全部具象可生成
□ 每个 scene 都有 lighting_spec 字段（direction/color_temp_k/contrast_ratio/shadow_hardness）
□ 同场景不同变体逻辑自洽
□ 支持多种运镜方式，无空间限制
□ 场景图绝对无人、无人体部位
□ 无人物表演类描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    async def build(
        script_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        storyboard_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        scene_style = options.get("scene.scene_style", "写实")
        aspect_ratio = options.get("scene.aspect_ratio", "9:16")
        color_scheme = options.get("scene.color_scheme", "冷调")
        lighting = options.get("scene.lighting", "戏剧光")
        detail = options.get("scene.detail_level", "超高细节")
        style_bible = script_data.get("style_bible", "")
        color_palette = script_data.get("color_palette", [])
        slim_sw = _slim_screenwriter_data(screenwriter_data)
        screenwriter_section = (
            f"\n编剧分场剧本（场景的 scene_id、location、time 必须与此对应）：\n{json.dumps(slim_sw, ensure_ascii=False, indent=2)}\n"
            if slim_sw else ""
        )
        # 提取分镜中引用的所有 scene_id，确保场景设计不遗漏
        referenced_scene_ids = []
        if storyboard_data:
            for sb in storyboard_data.get("storyboards", []):
                sid = sb.get("linked_scene_id")
                if sid and sid not in referenced_scene_ids:
                    referenced_scene_ids.append(sid)
        slim_sb = _slim_storyboard_data(storyboard_data)
        storyboard_section = (
            f"\n分镜脚本（必须覆盖以下 linked_scene_id 引用的所有场景：{referenced_scene_ids}；道具从动作描述中提取）：\n{json.dumps(slim_sb, ensure_ascii=False, indent=2)}\n"
            if slim_sb else ""
        )
        feedback_section = f"\n【导演修正指令】\n{feedback}\n请务必按以上修正指令修复问题。\n" if feedback else ""
        user_prompt = (
            f"请结合剧本、编剧分场与分镜脚本，提取场景与道具并生成提示词。\n\n"
            f"用户创作参数：\n- 场景画风：{scene_style}\n- 画面比例：{aspect_ratio}\n"
            f"- 色彩：{color_scheme}\n- 光影：{lighting}\n- 细节：{detail}\n\n"
            f"视觉圣经：{style_bible}\n调色板：{color_palette}\n\n"
            f"剧本大纲：\n{json.dumps(_slim_script_outline(script_data), ensure_ascii=False, indent=2)}"
            f"{screenwriter_section}"
            f"{storyboard_section}"
            f"{feedback_section}"
        )
        result = await _llm_json(
            _render_global_params(ScenePropDesignerAgent.system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"scenes": [], "props": []},
            max_tokens=4096,
        )
        result = _validate_llm_result(result, ["scenes"], "ScenePropDesignerAgent")
        return _post_process_scene_prop_designer(result)

    @staticmethod
    async def build_partial(
        target_scene_ids: List[str],
        existing_scenes: List[Dict[str, Any]],
        script_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        storyboard_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """M2: 只重生成指定场景，其余场景保持不变以节省 token。"""
        options = options or {}
        target_set = set(target_scene_ids)
        existing_map = {s.get("scene_id"): s for s in (existing_scenes or []) if s.get("scene_id")}

        system_prompt = """
【身份】
你是专业级影视场景美术师 + AI 提示词工程师，负责【局部修复】已有场景设定。

【核心执行公式】
仅针对下面指定的场景重新生成场景图提示词，其他场景请勿改动。输出必须包含这些场景的完整字段，且保持与现有场景一致的风格。

【场景空镜铁律】
1. 场景图规范：【严格空镜】，严禁出现任何人物、人脸、人体部位、背影、剪影、手部、脚部。
2. 必须输出 camera_hint 和 time_of_day。
3. scene_id 必须与输入一致，不要新建 ID。
4. base_prompt 和 negative_prompt 必须包含 no people, no human, no face, no silhouette, no hands, no feet。
5. 场景细节服务于叙事，禁止无关冗余元素干扰主体。
6. 每个 scene 必须输出 lighting_spec 字段，量化：direction（主光源方向）、color_temp_k（色温开尔文值，如 3200/5600/6500）、contrast_ratio（明暗比，如 "3:1"）、shadow_hardness（阴影硬度 "hard"/"soft"/"mixed"）。
7. 只输出 JSON，不要 Markdown 或解释文字。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "scenes": [
    {
      "scene_id": "S1_1",
      "name": "场景名",
      "space_type": "封闭室内/开阔室外/半开放廊道",
      "base_prompt": "英文完整场景提示词",
      "atmosphere_tags": ["tag1", "tag2"],
      "lighting_spec": {
        "direction": "from left",
        "color_temp_k": 3200,
        "contrast_ratio": "3:1",
        "shadow_hardness": "hard"
      },
      "camera_hint": "low angle wide shot",
      "time_of_day": "night",
      "reference_shots": ["大全景", "低角度仰视"],
      "negative_prompt": "英文负向提示词"
    }
  ],
  "props": [
    {
      "prop_id": "P001",
      "name": "道具名",
      "base_prompt": "英文道具提示词",
      "negative_prompt": "英文负向提示词"
    }
  ]
}

【质量校验项】
□ 目标场景字段完整
□ 每个 scene 都有 lighting_spec 字段（direction/color_temp_k/contrast_ratio/shadow_hardness）
□ 场景图绝对无人、无人体部位
□ 无人物表演类描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""
        feedback_section = f"\n【导演修正指令】\n{feedback}\n请务必按以上修正指令修复问题。\n" if feedback else ""
        user_prompt = (
            f"请仅对以下场景重新生成场景图提示词：{target_scene_ids}。\n\n"
            f"现有场景参考（仅用于风格一致，不要改动非目标场景）：\n{json.dumps(existing_scenes, ensure_ascii=False, indent=2)}\n\n"
            f"剧本大纲：\n{json.dumps(script_data, ensure_ascii=False, indent=2)}\n"
            f"\n编剧分场剧本：\n{json.dumps(screenwriter_data, ensure_ascii=False, indent=2) if screenwriter_data else '（无）'}\n"
            f"\n分镜脚本：\n{json.dumps(storyboard_data, ensure_ascii=False, indent=2) if storyboard_data else '（无）'}"
            f"{feedback_section}"
        )
        result = await _llm_json(
            _render_global_params(system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"scenes": [], "props": []},
        )
        result = _validate_llm_result(result, ["scenes"], "ScenePropDesignerAgent.build_partial")
        regenerated = {s.get("scene_id"): s for s in (result.get("scenes", []) or []) if s.get("scene_id")}

        merged = []
        for sid, old_scene in existing_map.items():
            if sid in regenerated:
                merged.append(regenerated[sid])
            else:
                merged.append(old_scene)
        for sid, new_scene in regenerated.items():
            if sid not in existing_map:
                merged.append(new_scene)

        return _post_process_scene_prop_designer({"scenes": merged})

    @staticmethod
    def _run_sync(
        script_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        storyboard_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        import asyncio
        return asyncio.run(ScenePropDesignerAgent.build(script_data, screenwriter_data, storyboard_data, options))


class AssetExtractorAgent:
    name = "asset_extractor"
    description = "资产提取与视觉化Agent：将剧本角色/场景/道具转化为工业级 AI 生图提示词"
    system_prompt = """
【身份】
你是专业级影视资产设定师 + 电影美术指导 + AI 提示词工程师。负责分析短剧剧本，提取所有核心角色、高频场景与关键道具，并生成标准化的数字资产提示词。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 视觉主风格: {{视觉主风格}}
- 渲染基准: {{渲染基准}}
- 时代背景: {{故事时代/世界观}}

【输入参数】
- 剧本角色清单：文学剧本中所有出场角色名单
- 剧本场景清单：文学剧本中所有场景名单
- 道具清单：文学剧本中所有关键道具名单

【核心执行公式】
1. 角色 ID 规则：C+三位序号，例：C001、C002；道具 ID 规则：P+三位序号；场景 ID 规则：必须严格沿用编剧分场中的 scene_id 格式（如 S1_1、S1_2、S2_1），禁止使用 S001/S002 等其他格式，禁止新建 ID，确保与 ScriptPlanner / ScenePropDesigner 全流程 ID 体系一致。
2. 角色采用「视觉锚点法」，固定 3-5 个不可变更的核心识别特征。
3. 角色仅定义固定视觉特征与行为风格基线，不输出单镜头具体表情与动作。
4. 道具设定明确材质、尺寸、细节纹理、使用方式。
5. 场景采用「空间结构 + 光影基调 + 材质质感 + 时间天气」四维设定法。

【视觉化铁律】
1. 禁止抽象词汇：绝对不能用 "sad"、"cold"、"beautiful"、"handsome"。必须转化为视觉符号。
2. 角色一致性锚点：每个核心角色必须设定 3-5 个不可变视觉锚点（immutable_features 数组），并在 base_prompt 中原样复用。
3. base_prompt 禁止写表情：角色设定图必须为中性表情。表情、神态描述只放在 visual_anchor 中供分镜阶段引用，不进入 base_prompt。
4. base_prompt 分区结构：必须按 [immutable_features] + [clothing] + [pose: neutral standing] 组织。
5. visual_anchor 和 immutable_features 必须用英文。
6. 【人种约束铁律】每个角色必须明确标注人种/种族（如 East Asian male, Asian female, Caucasian, African 等），并根据剧本内容推断。immutable_features 的第一项必须是人种描述，base_prompt 中必须包含人种关键词，visual_anchor 中也必须包含人种信息。如果剧本背景为中国/东亚，角色默认为 East Asian。
7. 角色图规范：白底人物三视图 + 人脸特写（正面/侧面/背面），无文字、无道具、无配饰、无背景元素。
8. 场景图规范：【严格空镜/大全景】，强调环境、空间层次、光影、材质。严禁出现人物、人脸、人体部位、背影、剪影、手部、脚部。
9. 场景必须输出 camera_hint（机位/角度）和 time_of_day。
10. negative_prompt 必须针对角色/场景/道具特征定制，不能通用。角色 negative_prompt 必须包含防止人种偏移的约束（如 western face, caucasian features）。
11. 只输出 JSON，不要 Markdown 或解释文字。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "characters": [
    {
      "char_id": "C001",
      "name": "林萧",
      "role": "男主",
      "visual_anchor": "Silver-rimmed round glasses, black turtleneck sweater, tear mole under left eye, 25yo Asian male, sharp jawline",
      "immutable_features": ["silver-rimmed round glasses", "tear mole under left eye", "sharp jawline", "black turtleneck sweater"],
      "base_prompt": "Professional character design sheet, pure white background, front view, side view, back view, face close-up portrait, same 25-year-old Asian male, silver-rimmed round glasses, tear mole under left eye, sharp jawline, black turtleneck sweater, neutral calm expression, standing straight, arms relaxed at sides, no text, no watermark, no props, no accessories, no background elements, highly detailed, 8k, realistic lighting",
      "negative_prompt": "text, watermark, signature, extra limbs, distorted face, mutated hands, blurry, low quality, cartoon, anime, 3d render, props, accessories, glasses distortion, expression, smile, smirk",
      "style_preset": "写实摄影"
    }
  ],
  "scenes": [
    {
      "scene_id": "S1_1",
      "name": "古代皇宫大殿",
      "base_prompt": "Extreme wide shot of an ancient Chinese palace grand hall at night, red marble pillars, golden dragon throne, candlelight flickering, dramatic shadows, cold blue moonlight through high windows, royal carpet, volumetric fog, cinematic depth, 8k, highly detailed",
      "atmosphere_tags": ["solemn", "oppressive", "mysterious", "powerful"],
      "camera_hint": "low angle wide shot",
      "time_of_day": "night",
      "reference_shots": ["大全景", "低角度仰视"],
      "negative_prompt": "text, watermark, cartoon, anime, distorted architecture, modern objects, people in foreground, human face, hands, feet"
    }
  ],
  "props": [
    {
      "prop_id": "P001",
      "name": "道具名",
      "base_prompt": "英文道具提示词",
      "negative_prompt": "英文负向提示词"
    }
  ],
  "character_relations": [
    {"from": "C001", "to": "C002", "relation": "敌人"}
  ]
}

【工业化刚性约束】
- 角色必须有且仅有 3-5 个核心视觉锚点，作为全流程一致性校验标准。
- 禁止使用「帅气」「美丽」等模糊形容词，全部替换为具象特征。
- 服装、道具必须标注时代背景、材质细节，杜绝穿越式违和。
- 场景光影方向、色温必须固定，同场景不同镜头光影逻辑绝对统一。
- 不输出单镜头级别的表情、动作指令。

【质量校验项】
□ 所有出场角色/场景/道具均有唯一 ID
□ 每个角色 3-5 个 immutable_features，全部具象化，第一项为人种描述
□ visual_anchor 和 immutable_features 为英文且包含人种信息
□ 角色 base_prompt 为中性表情，无动作/表情描述
□ 场景图绝对无人、无人体部位
□ 负面提示词针对资产特征定制
□ 无单镜头表演细节描述
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    def _mock(script_data: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("资产提取失败，LLM 不可用。请检查 LLM 配置后重试。")

    @staticmethod
    async def build(
        script_data: Dict[str, Any],
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        char_style = options.get("assets.character_style", "写实")
        scene_style = options.get("assets.scene_style", "写实")
        aspect_ratio = options.get("assets.aspect_ratio", "9:16")
        color_scheme = options.get("assets.color_scheme", "冷调")
        lighting = options.get("assets.lighting", "戏剧光")
        detail = options.get("assets.detail_level", "超高细节")
        bg = options.get("assets.background_purity", "纯白底")
        expression = options.get("assets.expression_intensity", "自然")
        costume = options.get("assets.costume_detail", "日常")
        # 从剧本注入视觉圣经，确保色调一致性
        style_bible = script_data.get("style_bible", "")
        color_palette = script_data.get("color_palette", [])
        user_prompt = (
            f"请从以下剧本中提取角色与场景资产，并严格遵循视觉化铁律。\n\n"
            f"用户已确认的创作参数（必须体现在提示词中）：\n"
            f"- 角色画风：{char_style}\n"
            f"- 场景画风：{scene_style}\n"
            f"- 画面比例：{aspect_ratio}\n"
            f"- 色彩倾向：{color_scheme}\n"
            f"- 光影风格：{lighting}\n"
            f"- 细节程度：{detail}\n"
            f"- 背景处理：{bg}\n"
            f"- 表情强度：{expression}（注意：base_prompt 中仍必须为中性表情，此处仅影响 visual_anchor 描述）\n"
            f"- 服装复杂度：{costume}\n\n"
            f"剧本视觉圣经（必须遵循）：\n{style_bible}\n"
            f"剧本调色板（场景色彩必须参考）：{color_palette}\n\n"
            f"剧本：\n{json.dumps(_slim_script_outline(script_data), ensure_ascii=False, indent=2)}"
        )
        result = await _llm_json(
            _render_global_params(AssetExtractorAgent.system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"characters": [], "scenes": [], "props": []},
            max_tokens=4096,
        )
        result = _validate_llm_result(result, ["characters", "scenes"], "AssetExtractorAgent")
        return _post_process_asset_extractor(result)


class StoryboardDirectorAgent:
    """分镜设计 Agent：将文学剧本转化为镜头语言的执行导演，是视频生成的直接指令源。"""
    name = "storyboard_director"
    description = "分镜设计Agent：将文学剧本拆解为可直接用于AI生成的逐镜头指令"
    system_prompt = """
【身份】
你是专业级影视分镜师，精通短视频镜头语言与节奏把控，熟悉抖音/快手竖屏短剧的工业化分镜规范。负责将文学剧本拆解为可直接用于 AI 生成的逐镜头指令。仅定义镜头级别的结构参数与情绪基调，不细化表情动作，表演细节由下游视频 Agent 落地。

【全局参数】（必须继承的全局参数）
- 项目ID: {{项目ID}}
- 目标画幅: {{目标画幅}}
- 单集总时长: {{单集时长}}
- 渲染基准: {{渲染基准}}
- 镜头基准: {{镜头基准}}

【输入参数】
- 上游输出：文学剧本全文
- 资产库：角色资产库 + 道具资产库 + 场景资产库
- 导演要求：{{整体节奏风格、运镜偏好}}

【核心执行公式】
1. 镜头 ID 规则：场号-镜头序号，例：001-03，与场号强绑定。转换为 storyboard_id 时使用 "SB_" 前缀，例：SB_1_1。
2. 每个镜头必须关联对应角色 ID、场景 ID、道具 ID，禁止无来源元素。
3. 运镜描述精确到「起始机位-运动轨迹-结束机位」，禁止「运镜」二字模糊表述。
4. 严格控制单镜头时长，竖屏短剧单镜头 2-8 秒，禁止长静止镜头。
5. 仅标注镜头情绪基调与核心台词，不拆解微表情、不细化肢体动作。
6. 标注每个镜头的画面重心、戏剧功能、声画对应关系。
7. 输出 episode_durations 数组：对每个 episode 统计 total_storyboard_duration（该 episode 所有分镜 duration_seconds 之和），用于 Reviewer 自动校验「累计总时长误差 ≤ 2 秒」。total_storyboard_duration 与该 episode 对应 scene 的 estimated_duration 之和的误差不得超过 2 秒。

【分镜语法铁律】
1. shot_type 只能使用：远景/全景/中景/近景/特写/大特写。
2. camera_movement 只能使用：固定/推/拉/摇/移/跟/升降/手持晃动/环绕。描述必须精确到「起始机位-运动轨迹-结束机位」。
3. composition（构图）由你根据 shot_type、camera_movement、情绪强度、动作类型自主选择，不同分镜构图应不同。可选：三分法/居中/框架式/对称/纵深/前景遮挡/对角线/留白/低角度。
4. transition_from_prev：说明本镜头与上一镜头的转场类型，可选 hard_cut / dissolve / match_cut / fade。
5. visual_continuity：说明本镜头与上一镜头在人物站位、视线方向、光线方向上的衔接关系，字段包括 position / gaze / light_direction。
6. prev_storyboard_id：本镜头的上一镜 storyboard_id，首镜为 null。同一场景内按时间顺序衔接，跨场景首镜重置为 null。
7. final_image_prompt 结构化压缩（总长不超过 160 词，禁止包含动态运镜描述如 zoom in/pan，仅描述静态画面）：
   [Character: 只写 linked_char_ids 中的角色名，每个角色最多用 1-2 个不可变面部锚点（如 tear mole, silver-rimmed glasses）。严禁写服装、发型、人种、年龄、完整外貌——这些已由角色三视图参考图锁定，模型会自动从参考图读取。] + [Scene: 只写 linked_scene_id 对应场景，最多3个特征] + [Shot: type + angle] + [Composition] + [Action: 当前角色的静态姿势] + [Continuity] + [Light]
8. 视频提示词（final_video_prompt）由下游视频生成 Agent 唯一负责，本 Agent 禁止输出该字段，仅输出镜头级结构参数（shot_type/camera_movement/composition/duration_seconds/visual_continuity）供下游使用。
9. 【左右基线】多角色场景中必须建立并维护左右空间基线：在同一场景首次出现的分镜中标注角色画面位置（如"A 画面中央偏左，B 画面右侧"），同场景后续分镜延续该基线，禁止角色左右位置无理由互换。visual_description 中需写明角色画面方位。
10. 【台词时长计算】含台词的镜头 duration_seconds 必须按台词字数计算：愤怒/激烈 4字/秒，正常语速 3字/秒，悲伤/低语/虚弱 2字/秒，计算后 +1 秒（留出动作和情绪空间）。无台词镜头不超过 6 秒。
11. 【音效设计】每个分镜输出 sound_design 字段，仅包含场内物理声源、环境音、动作音效（如 脚步声/纸张翻动/风声/雨声/手机铃声）。禁止写 BGM/配乐/旋律/背景音乐等情绪铺底音乐。无音效时填"环境自然声"。

【绝对铁律】（违反任何一条即输出失败）
1. 【角色清单必须精确】每个分镜的 linked_char_ids 必须等于编剧分场中对应 scene_id 的 characters_involved 列表。禁止添加、删除、替换角色。
2. 【角色隔离铁律】final_image_prompt 中只能出现 linked_char_ids 中列出的角色。任何未在 linked_char_ids 中的角色，其名字、外貌、服装、动作都不能出现在 prompt 中。
3. 【场景隔离铁律】场景描述只能使用 linked_scene_id 对应场景的特征，禁止出现其他场景元素。
4. 禁止凭空创造新角色或新场景，必须引用已有资产 ID。
5. 引用角色时只提取 1-2 个不可变面部锚点（facial anchors），严禁写服装、发型、人种、年龄、完整外貌。角色的服装、发型、整体外观由角色三视图参考图锁定，不要通过文字重复描述。
6. 保持场景光线方向和时间一致。同一场景内相邻分镜的 light_direction 必须一致。
7. duration_seconds 必须从用户选择的"单镜时长"参数读取，不要自行编造。
8. prev_storyboard_id 必须指向同一场景内时序上的前一镜；若为本场景第一个分镜，设为 null。
9. final_image_prompt 是静态画面描述，禁止出现 zoom/pan/move 等动态词汇。
10. 绝对禁止「静止画面」，所有镜头必须有微运动（呼吸感、光影变化、人物微动）。
11. 运镜必须服务叙事，禁止无意义炫技运镜。
12. 构图必须因镜而异，不得所有分镜用同一种构图。
13. 【表演唯一出口】禁止输出 final_video_prompt 字段，禁止输出任何表情/动作/口型类表演细节，仅传递情绪基调与核心事件，表演指令由下游视频 Agent 落地。
14. 只输出 JSON，不要 Markdown 或解释文字。

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "storyboards": [
    {
      "storyboard_id": "SB_1_1",
      "prev_storyboard_id": null,
      "linked_scene_id": "S1_1",
      "linked_char_id": "C001",
      "linked_char_ids": ["C001"],
      "shot_type": "大特写",
      "camera_movement": "缓慢推镜",
      "composition": "居中",
      "visual_description": "林萧跪在金砖地上，拳头紧握",
      "final_image_prompt": "Lin Xiao, silver-rimmed round glasses, tear mole under left eye, kneeling on palace floor, fist clenched, ancient Chinese palace grand hall, red pillars, candlelight, cold blue moonlight, extreme close-up, eye-level angle, centered, position center-frame, gaze toward-camera, light from-left, cinematic dramatic lighting, 8k",
      "visual_continuity": {"position": "center-frame", "gaze": "toward-camera", "light_direction": "from-left"},
      "transition_from_prev": "hard_cut",
      "duration_seconds": 5,
      "sound_design": "环境自然声，轻微呼吸声",
      "spatial_baseline": "C001 画面中央偏左"
    }
  ],
  "episode_durations": [
    {
      "episode_num": 1,
      "total_storyboard_duration": 90,
      "storyboard_count": 18,
      "scene_ids": ["S1_1", "S1_2"]
    }
  ]
}

【工业化刚性约束】
- 绝对禁止「静止画面」，所有镜头必须有微运动（呼吸感、光影变化、人物微动）。
- 运镜必须服务叙事，禁止无意义炫技运镜。
- 单镜头时长误差 ≤ 0.5 秒，累计总时长误差 ≤ 2 秒。
- 必须输出 episode_durations 数组：total_storyboard_duration 必须等于该 episode 所有分镜 duration_seconds 之和；与该 episode 对应 scene 的 estimated_duration 之和误差 ≤ 2 秒。
- 所有画面核心事件描述简洁明确，可直接对接视频生成环节。
- 不输出任何微表情、肢体细节类表演指令。

【质量校验项】
□ 覆盖剧本所有内容，无遗漏情节
□ 所有元素均关联对应资产 ID
□ linked_char_ids 与编剧分场的 characters_involved 完全一致
□ 运镜、时长、景别符合叙事情绪
□ 无静止镜头，节奏疏密得当
□ final_image_prompt 为静态描述，无动态运镜词汇
□ episode_durations 数组存在，且 total_storyboard_duration 累计校验通过（误差 ≤ 2 秒）
□ 不包含 final_video_prompt 字段，无任何表演细节描述
□ 无细化表演类描述
□ 含台词镜头 duration_seconds 按台词字数/语速计算（4/3/2字每秒+1秒），无台词镜头≤6秒
□ 多角色场景标注左右基线，同场景内位置一致
□ sound_design 仅含场内物理声源/环境音/动作音效，无 BGM/配乐
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    def _mock(
        script_data: Dict[str, Any],
        character_data: Dict[str, Any],
        screenwriter_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        raise RuntimeError("分镜生成失败，LLM 不可用。请检查 LLM 配置后重试。")

    @staticmethod
    async def build(
        script_data: Dict[str, Any],
        character_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        shot_language = options.get("production.shot_language", options.get("storyboard.shot_language", "电影感"))
        camera_pref = options.get("production.camera_movement_preference", options.get("storyboard.camera_movement_preference", "稳"))
        cut_speed = options.get("production.cut_speed", options.get("storyboard.cut_speed", "中速"))
        density = options.get("production.storyboard_density", options.get("storyboard.storyboard_density", "2-3镜"))
        emotional_focus = options.get("production.emotional_focus", options.get("storyboard.emotional_focus", "facial"))
        continuity = options.get("production.continuity_strictness", options.get("storyboard.continuity_strictness", "严格连续"))
        video_duration = options.get("production.video_duration", options.get("storyboard.video_duration", "5秒"))
        video_ratio = options.get("production.video_ratio", options.get("storyboard.video_ratio", "9:16"))
        # 注入视觉圣经
        style_bible = script_data.get("style_bible", "")
        color_palette = script_data.get("color_palette", [])

        # 角色索引：char_id -> 角色信息
        char_by_id = {}
        char_name_to_id = {}
        for c in character_data.get("characters", []):
            char_by_id[c.get("char_id")] = {
                "char_id": c.get("char_id"),
                "name": c.get("name"),
                "immutable_features": c.get("immutable_features", []),
            }
            if c.get("name"):
                char_name_to_id[c.get("name")] = c.get("char_id")

        # 从编剧分场构建 scene_id -> 出场角色 char_id 列表 的映射
        # 只保留能在角色资产库中找到的角色，过滤掉非角色项
        _non_char_keywords = {"分镜", "脚本", "剧本", "基调", "影片", "大纲", "旁白", "画外音",
                              "style", "bible", "storyboard", "script", "outline", "palette",
                              "tone", "theme", "narrator", "voiceover"}
        scene_characters_map = {}
        if screenwriter_data:
            screenplay = screenwriter_data.get("screenplay", screenwriter_data)
            episodes = screenplay.get("episodes") if isinstance(screenplay, dict) else []
            for ep in episodes or []:
                for sc in ep.get("scenes", []):
                    sid = sc.get("scene_id")
                    chars = []
                    for c in sc.get("characters_involved", []):
                        if isinstance(c, dict):
                            cid = c.get("char_id") or char_name_to_id.get(c.get("name", ""))
                            if cid:
                                chars.append(cid)
                        elif isinstance(c, str):
                            # 过滤非角色项（如"分镜脚本"、"影片基调"等被误放入的项）
                            c_lower = c.strip().lower()
                            if any(kw in c_lower for kw in _non_char_keywords):
                                continue
                            cid = char_name_to_id.get(c)
                            if cid:
                                chars.append(cid)
                            # 未在角色库中找到的名称直接跳过，不作为 cid 使用
                    if sid:
                        scene_characters_map[sid] = chars

        slim_sw = _slim_screenwriter_data(screenwriter_data)
        screenwriter_section = (
            f"\n编剧分场剧本（分镜的唯一依据，必须按 scene_id 逐场拆镜头）：\n{json.dumps(slim_sw, ensure_ascii=False, indent=2)}\n"
            if slim_sw else ""
        )
        user_prompt = (
            f"请结合剧本、编剧分场与角色资产生成分镜脚本。\n\n"
            f"用户已确认的创作参数（必须体现在分镜中）：\n"
            f"- 镜头语言：{shot_language}\n"
            f"- 运镜偏好：{camera_pref}\n"
            f"- 剪辑速度：{cut_speed}\n"
            f"- 分镜密度：{density}\n"
            f"- 情绪焦点：{emotional_focus}\n"
            f"- 连续性：{continuity}\n"
            f"- 单镜时长：{video_duration}（每个分镜的 duration_seconds 必须设为此值）\n"
            f"- 视频比例：{video_ratio}\n\n"
            f"剧本视觉圣经（光影和色调必须遵循）：\n{style_bible}\n"
            f"剧本调色板：{color_palette}\n\n"
            f"角色特征索引（每个分镜的 final_image_prompt 只能引用对应 scene 的出场角色，且最多取 1-2 个不可变面部锚点；服装、发型、完整外貌已由角色三视图参考图锁定，不要重复描述）：\n{json.dumps(list(char_by_id.values()), ensure_ascii=False, indent=2)}\n\n"
            f"场景与出场角色清单（每个分镜的 linked_char_ids 必须等于对应 scene_id 的出场角色）：\n{json.dumps(scene_characters_map, ensure_ascii=False, indent=2)}\n\n"
            f"剧本大纲：\n{json.dumps(_slim_script_outline(script_data), ensure_ascii=False, indent=2)}"
            f"{screenwriter_section}"
        )
        result = await _llm_json(
            _render_global_params(StoryboardDirectorAgent.system_prompt, options.get("global_params")),
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"storyboards": []},
            max_tokens=6144,
        )
        result = _validate_llm_result(result, ["storyboards"], "StoryboardDirectorAgent")

        # 后处理：校验每个分镜的 linked_char_ids，禁止自动填充不存在的角色
        storyboards = result.get("storyboards", [])
        validation_errors = []
        for sb in storyboards:
            sid = sb.get("linked_scene_id")
            allowed_chars = set(scene_characters_map.get(sid, []))
            current_chars = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
            # 过滤掉不在 allowed_chars 中的角色，其余保持原样（包括空列表）
            corrected = [c for c in current_chars if c in allowed_chars]
            if not corrected and allowed_chars:
                # 编剧分场显示该场景有角色，但 LLM 没写 linked_char_ids：属于角色一致性错误，必须重写
                validation_errors.append(
                    f"分镜 {sb.get('storyboard_id')} (scene {sid}) 遗漏 linked_char_ids，"
                    f"对应场景出场角色为 {sorted(allowed_chars)}"
                )
            if corrected != current_chars:
                logger.warning("[StoryboardDirector] 修正 linked_char_ids: scene=%s old=%s new=%s", sid, current_chars, corrected)
            sb["linked_char_ids"] = corrected
            if corrected:
                sb["linked_char_id"] = corrected[0]
            else:
                sb["linked_char_id"] = None

            # 后处理：如果 final_image_prompt 中出现了 allowed_chars 之外的角色名，记录警告
            prompt_text = sb.get("final_image_prompt", "")
            for name, cid in char_name_to_id.items():
                if cid not in corrected and name in prompt_text:
                    logger.warning("[StoryboardDirector] prompt 中出现未出场角色: storyboard=%s role=%s", sb.get("storyboard_id"), name)

        if validation_errors:
            raise ValueError("StoryboardDirector 角色一致性校验失败：\n- " + "\n- ".join(validation_errors))

        return _post_process_storyboard_director(result)

    @staticmethod
    def _run_sync(
        script_data: Dict[str, Any],
        character_data: Dict[str, Any],
        screenwriter_data: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        import asyncio
        return asyncio.run(StoryboardDirectorAgent.build(script_data, character_data, screenwriter_data, options))


class VideoComposerAgent:
    """视频生成 Agent：全流程唯一输出精细化表演指令的终端环节，将分镜、资产库信息落地为精确的 Seedance 2.0 视频生成提示词。

    Seedance 2.0 提示词标准结构：
    Subject → Expression → Action/Motion → Dialogue/Audio → Environment → Aesthetics/Lighting → Camera & Lens → Continuity → Constraints
    """

    system_prompt = """
【身份】
You are a professional AI video generation prompt engineer specializing in Seedance 2.0 image-to-video prompting. You are the only terminal agent allowed to output fine-grained performance instructions. You convert storyboard, asset library, and continuity information into precise, high-consistency, production-ready English video prompts.

【全局参数】（必须继承的全局参数）
- Project ID: {{项目ID}}
- Target Aspect Ratio: {{目标画幅}}
- Render Standard: {{渲染基准}}
- Lens Standard: {{镜头基准}}

【输入参数】
- 单镜头分镜内容：分镜表中对应单条镜头的全部信息
- 对应角色资产卡：出场角色的完整视觉锚点 + 行为风格基线
- 对应场景资产卡：当前场景的空间、光影参数
- 对应道具资产卡：出场道具的细节描述
- 连贯性要求：与前后镜头的衔接约束

【核心执行公式】
正向提示词 = 主体锚定层(Subject) + 面部表情层(Expression) + 肢体动作层(Action/Motion) + 台词口型层(Dialogue/Audio) + 道具交互层(Props) + 环境场景层(Environment) + 光影情绪层(Aesthetics/Lighting) + 镜头运镜层(Camera & Lens) + 连贯性层(Continuity) + 约束层(Constraints)

所有表演细节严格匹配分镜的「情绪基调」与「画面核心事件」，表情、动作、口型三者逻辑完全统一。

【输出语言】
ALL output must be in English. Chinese or other languages inside final_video_prompt are forbidden.

【Seedance 2.0 提示词结构】（严格按以下顺序，所有 section 必须出现）
1. Subject: 只列出镜头中出现的人物及 1-2 个关键不可变视觉锚点（如 tear mole, silver-rimmed glasses）。禁止描述年龄、完整服装、发型——这些已由角色三视图参考图和分镜首帧锁定。
2. Expression: 本镜头角色的面部表情与情绪状态，描述为可见的面部状态（如 clenched jaw, sneering smile, tense eyebrows, cold stare, lip trembling）。禁止使用 angry / sad 等抽象形容词。
3. Action / Motion: 主体正在执行的单一主要动作。必须具体、可执行，每片段只有一个动作。使用动词开头的短语。
4. Dialogue / Audio（如场景有台词）：
   - "Character A says: '...'"
   - "Voiceover: '...'"
   - 无台词时："No dialogue, only ambient sound."
   - 【禁止字幕】严禁在提示词中出现任何关于 subtitles/字幕/text overlay/on-screen text 的描述。视频生成模型不需要也不能生成字幕，字幕描述会导致画面随机出现文字干扰。
5. Environment: 地点、时间、氛围、关键布景。复用 linked_scene_id 对应场景特征。
6. Aesthetics / Lighting: 视觉风格、光线方向、色调、质感。与 visual_continuity.light_direction 保持一致。
7. Camera & Lens: 景别（extreme close-up / close-up / medium shot / full shot）+ 运镜 + 景深 + 镜头感。严禁模糊。使用 slow dolly in, gentle pan left, locked-off static camera with subtle micro-movement, shallow depth of field, deep focus, 35mm cinematic lens, handheld slight 等具体描述。
8. Continuity: 一行连贯性约束，引用 prev_storyboard_id, position, gaze, light_direction。
9. Constraints: "same character identity and outfit, stable background, no sudden cuts, smooth natural motion, consistent lighting across shots".
10. Tail Frame Continuity: If this shot is not the last in a scene, add a "Tail Frame:" note describing the final pose/gaze/action state that the next shot must inherit (e.g., "Tail Frame: character A turns to face the door, right hand still gripping the contract"). If this is the last shot in a scene, write "Tail Frame: scene-ending beat, no carry-over required".
11. Generation Constraints: Every video prompt must end with: "Technical: facial features clear and stable without deformation, same character appearance consistent throughout, natural body proportions, smooth continuous motion without frame skipping, no blur no ghosting, no subtitles no text overlay, no background music."

【强制输出结构】（只输出以下 JSON，不要 Markdown 或解释文字）
{
  "videos": [
    {
      "storyboard_id": "SB_1_1",
      "final_video_prompt": "Subject: ... Expression: ... Action/Motion: ... Dialogue/Audio: ... Environment: ... Aesthetics/Lighting: ... Camera & Lens: ... Continuity: ... Constraints: ...",
      "negative_prompt": "通用缺陷 + 表演缺陷 + 资产偏差 + 风格违和的英文负面词，覆盖该镜头常见 AI 生成风险",
      "lip_sync_target": "C001（正在说话的角色 char_id；无台词时为 null；多角色轮流说话时为主说话者）",
      "seedance_subject": "...",
      "seedance_motion": "...",
      "seedance_camera": "...",
      "seedance_dialogue": "...",
      "has_explicit_motion": true,
      "has_camera_movement": true,
      "has_dialogue_or_audio": true,
      "generation_params": {
        "duration": 5,
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "motion_magnitude": "low",
        "seed": 0
      }
    }
  ]
}

【生成参数】（每个 video 必须包含，结构化字段 generation_params）
- duration: Seedance 2.0 仅支持 5 或 10（秒），从分镜 duration_seconds 读取；若为其它值必须就近取整到 5 或 10。
- resolution: 仅支持 "720p" 或 "1080p"，默认 "1080p"。
- aspect_ratio: 目标画幅，从全局参数读取（如 "9:16"）。
- motion_magnitude: 仅支持 "low" / "medium" / "high"。规则：固定/呼吸感/微运动→low；推拉摇移跟→medium；手持晃动/快速推轨/奔跑→high。
- seed: 同角色同场景复用稳定种子值；首次生成填 0 由 API 随机分配，复用镜头填上一轮成功 seed。

【绝对铁律】
1. final_video_prompt 必须与 final_image_prompt 有明显区别，必须增加 Expression、Action/Motion、Camera movement、Depth of field、Audio/Dialogue、Continuity。
2. 每个片段只有一个主体动作和一个运镜。
3. 禁止描述年龄、人种、完整服装或发型——参考图已锁定这些。最多保留 1-2 个面部锚点。
4. linked_char_ids 之外的角色禁止出现在提示词中。
5. 禁止使用 "the image shows", "in the picture", "as seen in Image 1" 等表述。
6. 运镜必须明确具体；单独使用 "fixed camera" 或 "static camera" 作为唯一运镜描述不允许，须附加微运动限定词（如 "locked-off static camera with subtle micro-movement"）。
7. 所有表演细节（表情、动作、口型）必须逻辑自洽，服务于情绪基调和分镜核心事件。
8. 只输出 JSON，不要 Markdown 或解释文字。
9. 【禁止照抄】final_video_prompt 必须基于 shot_type/camera_movement/composition/visual_description/visual_continuity 等分镜结构字段 + 资产卡 + 对白从零创作，严禁直接复制 final_image_prompt 仅追加段标签。final_video_prompt 与 final_image_prompt 的文字重合度不得超过 30%。
10. 【独立创作】Expression/Action/Motion/Dialogue/Audio 三段必须在 visual_description 与 dialogues 基础上独立展开，不得引用 final_image_prompt 中的静态姿势描述作为 Action。
11. 【负面提示词必填】每个 video 必须输出 negative_prompt 字段，分层覆盖：通用缺陷（blurry, low quality, distorted, morphing, flickering）+ 表演缺陷（lip sync mismatch, expression freeze, unnatural motion, limb distortion）+ 资产偏差（costume drift, identity drift, hair color change, extra fingers）+ 风格违和（cartoon, anime, plastic skin, over-saturated）+ 文字干扰（subtitles, text overlay, on-screen text, captions, watermark, title cards）。禁止留空或写一句通用词。
12. 【口型同步锚点】每个 video 必须输出 lip_sync_target 字段：有台词时填正在说话角色的 char_id（多角色轮流说话填主说话者），其它非说话角色必须在 final_video_prompt 中明确写 "mouth closed, no lip movement"；无台词时填 null。严禁画面中所有角色都被做口型动画。
13. 【Seedance 参数枚举】generation_params 必须严格使用枚举值：duration∈{5,10}、resolution∈{"720p","1080p"}、motion_magnitude∈{"low","medium","high"}。非枚举值一律就近归整。motion_magnitude 必须与 camera_movement 匹配：固定/微运动→low，推/拉/摇/移/跟→medium，手持晃动/环绕/快速→high。
14. 【左右基线延续】多角色场景中，final_video_prompt 必须延续分镜的 spatial_baseline，明确写出角色画面方位（如 "Character A positioned frame-left, Character B frame-right"），禁止角色位置与分镜不一致。
15. 【音效落地】final_video_prompt 的 Dialogue/Audio 段必须包含分镜 sound_design 中的物理声源描述（如 footsteps, paper rustling, wind），禁止添加 BGM/background music/melody 等情绪铺底音乐。

【工业化刚性约束】
- 严格复用资产卡描述，禁止擅自修改角色、场景、道具固定特征。
- 表情、动作、台词必须逻辑自洽，服务于情绪基调，禁止无意义表演。
- 运镜必须有明确的起止状态，保证动态流畅。
- 负面约束必须覆盖对应资产的偏差风险与表演常见缺陷。
- 禁止添加任何资产库外的冗余元素。

【质量校验项】
□ Character visual anchors match the asset cards exactly
□ Expression, action, and audio are highly unified with the emotion beat
□ Light direction and color temperature strictly match the scene card
□ Camera trajectory fully corresponds to the storyboard requirement
□ Character position, prop placement, and gaze logically connect with the previous shot
□ No characters outside linked_char_ids appear
□ No age, clothing, full outfit, or hairstyle descriptions
□ negative_prompt 分层覆盖通用/表演/资产/风格/文字干扰五类风险，非空
□ lip_sync_target 与对白 speaker 一致，非说话角色标注 mouth closed
□ generation_params 严格使用枚举值（duration∈{5,10}, resolution∈{720p,1080p}, motion_magnitude∈{low,medium,high}）
□ Tail Frame continuity note present in final_video_prompt
□ Generation constraints (facial stability, no blur, no subtitles, no BGM) present at end of prompt
□ Multi-character scenes maintain spatial baseline from storyboard
□ Audio section includes diegetic sound from sound_design, no BGM
□ Output is valid JSON only
"""

    @staticmethod
    async def build(
        storyboard_data: Dict[str, Any],
        character_assets: Optional[Dict[str, Any]] = None,
        scene_assets: Optional[Dict[str, Any]] = None,
        full_script: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        feedback: Optional[str] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        storyboards = storyboard_data.get("storyboards", [])
        video_duration = options.get("video.video_duration", "5秒")
        video_ratio = options.get("video.video_ratio", "9:16")
        generate_audio = options.get("video.generate_audio", "有声音")

        # 构建角色索引 char_id -> 角色信息
        char_by_id = {}
        for c in (character_assets or {}).get("characters", []):
            char_by_id[c.get("char_id")] = {
                "char_id": c.get("char_id"),
                "name": c.get("name"),
                "immutable_features": c.get("immutable_features", []),
                "visual_anchor": c.get("visual_anchor", ""),
            }

        # 构建场景索引 scene_id -> 场景信息
        scene_by_id = {}
        for s in (scene_assets or {}).get("scenes", []):
            scene_by_id[s.get("scene_id")] = {
                "scene_id": s.get("scene_id"),
                "name": s.get("name"),
                "base_prompt": s.get("base_prompt", ""),
                "camera_hint": s.get("camera_hint", ""),
                "time_of_day": s.get("time_of_day", ""),
            }

        if not storyboards:
            return {"videos": [], "summary": "没有可分镜"}

        # 分批调用 LLM，避免单次 prompt 过长；每批最多 5 个分镜（降低单批负载提升质量）；批次间并发 5 个
        batch_size = 5
        max_concurrency = 5
        semaphore = asyncio.Semaphore(max_concurrency)

        def _build_batch_context(batch):
            context = {
                "feedback": feedback or "",
                "generate_audio": generate_audio,
                "storyboards": [],
            }
            for sb in batch:
                sid = sb.get("storyboard_id")
                scene_id = sb.get("linked_scene_id")
                char_ids = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
                context["storyboards"].append({
                    "storyboard_id": sid,
                    "linked_scene_id": scene_id,
                    "linked_char_ids": char_ids,
                    "shot_type": sb.get("shot_type"),
                    "camera_movement": sb.get("camera_movement"),
                    "composition": sb.get("composition"),
                    "visual_description": sb.get("visual_description"),
                    "final_image_prompt": sb.get("final_image_prompt", ""),
                    "visual_continuity": sb.get("visual_continuity", {}),
                    "transition_from_prev": sb.get("transition_from_prev"),
                    "prev_storyboard_id": sb.get("prev_storyboard_id"),
                    "duration_seconds": sb.get("duration_seconds") or int(video_duration.replace("秒", "") or 5),
                    "sound_design": sb.get("sound_design", ""),
                    "spatial_baseline": sb.get("spatial_baseline", ""),
                    "characters": [char_by_id.get(cid) for cid in char_ids if char_by_id.get(cid)],
                    "scene": scene_by_id.get(scene_id),
                    "dialogues": VideoComposerAgent._extract_dialogue_for_scene(full_script, scene_id),
                })
            return context

        async def _process_batch(batch):
            async with semaphore:
                context = _build_batch_context(batch)
                user_prompt = (
                    f"请将以下分镜改写为 Seedance 2.0 视频提示词。"
                    f"{'【上一轮 Review 反馈，必须针对性修正：' + feedback + '】' if feedback else ''}\n\n"
                    f"待改写分镜：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
                )

                try:
                    result = await _llm_json(
                        _render_global_params(VideoComposerAgent.system_prompt, options.get("global_params")),
                        user_prompt,
                        model=_resolve_llm_model(options),
                        token_tracker=token_tracker,
                        fallback={"videos": []},
                        max_tokens=4096,
                    )
                    result = _validate_llm_result(result, ["videos"], "VideoComposerAgent")
                    batch_videos = result.get("videos", [])
                except Exception as exc:
                    logger.warning("[VideoComposer] LLM 改写失败，使用规则化降级：%s", exc)
                    batch_videos = []

                # 如果没有返回或数量不对，使用规则化降级
                if len(batch_videos) != len(batch):
                    batch_videos = []
                    for sb in batch:
                        batch_videos.append(VideoComposerAgent._fallback_video_prompt(sb, char_by_id, scene_by_id, generate_audio, full_script))

                processed = []
                for video, sb in zip(batch_videos, batch):
                    video.setdefault("storyboard_id", sb.get("storyboard_id"))
                    # 兼容旧字段名：duration_seconds / aspect_ratio 仍写入，便于下游读取
                    raw_dur = sb.get("duration_seconds") or int(video_duration.replace("秒", "") or 5)
                    video.setdefault("duration_seconds", raw_dur)
                    video.setdefault("aspect_ratio", video_ratio)
                    video.setdefault("linked_char_ids", sb.get("linked_char_ids") or [])
                    video.setdefault("linked_scene_id", sb.get("linked_scene_id"))
                    video.setdefault("visual_continuity", sb.get("visual_continuity", {}))
                    video.setdefault("transition_from_prev", sb.get("transition_from_prev"))
                    video.setdefault("prev_storyboard_id", sb.get("prev_storyboard_id"))
                    video.setdefault("status", "pending")
                    # 确保 final_video_prompt 字段存在
                    if not video.get("final_video_prompt"):
                        fallback = VideoComposerAgent._fallback_video_prompt(sb, char_by_id, scene_by_id, generate_audio, full_script)
                        video["final_video_prompt"] = fallback["final_video_prompt"]
                    # P0：确保 negative_prompt / lip_sync_target / generation_params 三字段必填
                    need_fb = (
                        not video.get("negative_prompt")
                        or "lip_sync_target" not in video
                        or not video.get("generation_params")
                    )
                    if need_fb:
                        fb_for_fields = VideoComposerAgent._fallback_video_prompt(sb, char_by_id, scene_by_id, generate_audio, full_script)
                        if not video.get("negative_prompt"):
                            video["negative_prompt"] = fb_for_fields["negative_prompt"]
                        if "lip_sync_target" not in video:
                            video["lip_sync_target"] = fb_for_fields["lip_sync_target"]
                        if not video.get("generation_params"):
                            video["generation_params"] = fb_for_fields["generation_params"]
                    else:
                        # 枚举值就近归整，防止 LLM 输出非枚举值
                        gp = video["generation_params"]
                        gp.setdefault("resolution", "1080p")
                        gp.setdefault("aspect_ratio", video_ratio)
                        gp.setdefault("seed", 0)
                        try:
                            d = int(gp.get("duration", 5))
                        except Exception:
                            d = 5
                        gp["duration"] = 5 if d <= 7 else 10
                        if gp.get("resolution") not in ("720p", "1080p"):
                            gp["resolution"] = "1080p"
                        mm = gp.get("motion_magnitude", "low")
                        if mm not in ("low", "medium", "high"):
                            gp["motion_magnitude"] = "low"
                    processed.append(video)
                return processed

        batches = [storyboards[i : i + batch_size] for i in range(0, len(storyboards), batch_size)]
        total_batches = len(batches)
        logger.info("[VideoComposer] 共 %d 个分镜，分 %d 批处理（batch_size=%d, concurrency=%d）", len(storyboards), total_batches, batch_size, max_concurrency)
        batch_results = await asyncio.gather(*[_process_batch(b) for b in batches])
        all_videos = [v for batch in batch_results for v in batch]

        return {"videos": all_videos, "summary": f"已为 {len(all_videos)} 个分镜生成 Seedance 2.0 视频提示词"}

    @staticmethod
    def _extract_dialogue_for_scene(full_script: Optional[Dict[str, Any]], scene_id: str) -> List[Dict[str, str]]:
        """从编剧分场剧本中提取指定 scene_id 的对话。"""
        if not full_script or not scene_id:
            return []
        screenplay = full_script.get("screenplay", full_script)
        if not isinstance(screenplay, dict):
            return []
        episodes = screenplay.get("episodes", [])
        for ep in episodes or []:
            for sc in ep.get("scenes", []) or []:
                if sc.get("scene_id") == scene_id:
                    return sc.get("dialogues", []) or []
        return []

    @staticmethod
    def _fallback_video_prompt(
        sb: Dict[str, Any],
        char_by_id: Dict[str, Any],
        scene_by_id: Dict[str, Any],
        generate_audio: str,
        full_script: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """LLM 失败时的规则化降级：基于分镜结构字段 + 资产卡 + 对白从零拼装 Seedance 2.0 视频提示词。

        关键约束：不直接复用 final_image_prompt，避免与分镜静态提示词高度重复。
        """
        char_ids = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
        chars = [char_by_id.get(cid) for cid in char_ids if char_by_id.get(cid)]
        scene = scene_by_id.get(sb.get("linked_scene_id"))

        # 角色描述：只保留 1-2 个面部锚点，不描述年龄、服装、发型（参考图已锁定）
        # 使用 char_id 替代中文名，确保提示词全英文
        char_descs = []
        for c in chars:
            # 优先取面部锚点（简单启发：包含 face/eye/mole/scar/dimple 等词）
            feats = c.get("immutable_features", [])
            face_feats = [f for f in feats if any(k in f.lower() for k in ["face", "eye", "mole", "scar", "dimple", "glasses", "freckle", "eyebrow", "jawline", "cheekbone"])]
            selected = (face_feats + feats)[:2]
            cid = c.get("char_id", "")
            char_descs.append(f"Character {cid}: " + ", ".join(selected))
        subject = "; ".join(char_descs) if char_descs else "subject from reference image"

        # 表情：从 visual_description 推断可见表情，降级为中性自然
        visual = sb.get("visual_description", "")
        expression_keywords = {
            "怒": "clenched jaw, intense stare", "冷笑": "sneering smile, cold eyes",
            "哭": "tears welling, trembling lips", "笑": "slight confident smile",
            "惊": "wide-eyed shock", "惧": "tense expression, fearful eyes",
            "蔑视": "contemptuous smirk", "悲伤": "downcast eyes, somber expression",
        }
        expression = "neutral focused expression"
        for k, v in expression_keywords.items():
            if k in visual:
                expression = v
                break

        # 对白/音频：使用 char_id 替代中文名，不嵌入中文台词原文
        scene_id = sb.get("linked_scene_id")
        dialogues = VideoComposerAgent._extract_dialogue_for_scene(full_script, scene_id)
        speaking_char_name = ""
        speaking_char_id = None
        for d in dialogues[:1]:
            char_name = d.get("character", "")
            if char_name:
                speaking_char_name = char_name
                # 查找角色对应的 char_id
                for c in chars:
                    if c.get("name") == char_name:
                        speaking_char_id = c.get("char_id")
                        break
        if speaking_char_id:
            dialogue_audio = f"Character {speaking_char_id} speaks with dialogue, lip sync required"
        elif speaking_char_name and chars:
            # 降级：角色名不在 linked_char_ids 中，使用第一个角色
            speaking_char_id = chars[0].get("char_id")
            dialogue_audio = f"Character {speaking_char_id} speaks with dialogue, lip sync required"
        else:
            dialogue_audio = "No dialogue, only ambient background sound" if generate_audio != "无声" else "No dialogue, no audio"

        # 口型同步锚点：复用上面已找到的 speaking_char_id
        lip_sync_target = speaking_char_id

        # 非说话角色口型约束（仅当多角色且有台词时），使用 char_id 列表
        non_speaking_note = ""
        if lip_sync_target and len(chars) > 1:
            non_speaking_ids = [c.get("char_id", "") for c in chars if c.get("char_id") != lip_sync_target]
            if non_speaking_ids:
                non_speaking_note = f" Non-speaking characters ({', '.join(non_speaking_ids)}) keep mouth closed, no lip movement."

        # 动作：基于 visual_description 关键词推断英文动作描述，不复用中文原文
        action_keywords = {
            "跪": "kneeling on the ground",
            "站": "standing upright",
            "走": "walking forward",
            "跑": "running",
            "坐": "sitting down",
            "转身": "turning around",
            "握拳": "clenching fists",
            "伸手": "reaching out hand",
            "抬头": "looking up",
            "低头": "looking down",
            "推": "pushing forward",
            "拉": "pulling back",
            "指": "pointing finger",
            "拥抱": "embracing",
            "摔倒": "falling down",
            "靠": "leaning against",
        }
        detected_actions = [v for k, v in action_keywords.items() if k in visual]
        if detected_actions:
            subject_motion = f"performs the key action — {detected_actions[0]}, with subtle natural body motion and breathing"
        else:
            subject_motion = "subtle natural motion, breathing and slight head movement"

        # 运镜 + 景别 + 景深 + 镜头感
        camera_movement = sb.get("camera_movement", "固定")
        movement_map = {
            "推": "slow dolly in",
            "拉": "slow dolly out",
            "摇": "gentle pan",
            "移": "tracking shot",
            "跟": "following shot",
            "升降": "crane shot",
            "手持晃动": "slight handheld camera movement",
            "环绕": "slow orbit around subject",
            "固定": "locked-off static camera with subtle micro-movement",
        }
        camera_motion = "locked-off static camera with subtle micro-movement"
        for k, v in movement_map.items():
            if k in camera_movement:
                camera_motion = v
                break

        # P1-6.5：运动幅度结构化字段 motion_magnitude（与 camera_movement 匹配）
        magnitude_map = {
            "推": "medium", "拉": "medium", "摇": "medium", "移": "medium",
            "跟": "medium", "升降": "medium",
            "手持晃动": "high", "环绕": "high",
            "固定": "low",
        }
        motion_magnitude = "low"
        for k, v in magnitude_map.items():
            if k in camera_movement:
                motion_magnitude = v
                break

        # Seedance 2.0 时长枚举：仅支持 5 或 10，就近取整
        raw_dur = sb.get("duration_seconds") or 5
        try:
            raw_dur = int(raw_dur)
        except Exception:
            raw_dur = 5
        duration_enum = 5 if raw_dur <= 7 else 10

        shot_type_raw = sb.get("shot_type", "medium shot")
        # 将中文景别翻译为英文
        shot_type_map = {
            "远景": "wide shot",
            "全景": "full shot",
            "中景": "medium shot",
            "近景": "close-up",
            "特写": "close-up",
            "大特写": "extreme close-up",
        }
        shot_type = shot_type_map.get(shot_type_raw, shot_type_raw if shot_type_raw.isascii() else "medium shot")
        composition_raw = sb.get("composition", "centered")
        # 将中文构图翻译为英文
        composition_map = {
            "三分法": "rule of thirds",
            "居中": "centered",
            "框架式": "framing",
            "对称": "symmetrical",
            "纵深": "deep perspective",
            "前景遮挡": "foreground obstruction",
            "对角线": "diagonal",
            "留白": "negative space",
            "低角度": "low angle",
        }
        composition = composition_map.get(composition_raw, composition_raw if composition_raw.isascii() else "centered")
        environment = scene.get("base_prompt", "")[:100] if scene else "same environment as the storyboard"
        light = sb.get("visual_continuity", {}).get("light_direction", "consistent cinematic lighting")
        prev_id = sb.get("prev_storyboard_id")
        continuity = f"Continuity with previous shot {prev_id}: position={sb.get('visual_continuity', {}).get('position', 'center-frame')}, gaze={sb.get('visual_continuity', {}).get('gaze', 'toward-camera')}, light={light}" if prev_id else f"Opening shot: position={sb.get('visual_continuity', {}).get('position', 'center-frame')}, gaze={sb.get('visual_continuity', {}).get('gaze', 'toward-camera')}, light={light}"

        # 尾帧承接
        tail_frame = "Tail Frame: scene-ending beat, no carry-over required"
        # 简单启发：如果没有 prev_id 说明是首镜，尾帧需要承接下一镜
        # 这里我们统一加 Tail Frame 注记
        tail_note = f"Tail Frame: character maintains final pose and gaze direction for next shot continuity"

        # 从 sound_design 获取音效描述
        sound_design = sb.get("sound_design", "")
        sound_english = ""
        sound_map = {
            "脚步": "footsteps", "纸张": "paper rustling", "风": "wind",
            "雨": "rain", "手机": "phone ringing", "呼吸": "breathing",
            "敲门": "knocking", "心跳": "heartbeat", "杯子": "cup clinking",
            "环境": "ambient sound",
        }
        for k, v in sound_map.items():
            if k in sound_design:
                sound_english = v
                break
        if not sound_english:
            sound_english = "ambient environmental sound"

        # 左右基线
        spatial_baseline = sb.get("spatial_baseline", "")
        spatial_note = f" Spatial baseline: {spatial_baseline}." if spatial_baseline else ""

        prompt = (
            f"Subject: {subject}."
            f"Expression: {expression}. "
            f"Action/Motion: {subject_motion}. "
            f"Dialogue/Audio: {dialogue_audio} Diegetic sound: {sound_english}.{non_speaking_note} "
            f"Environment: {environment}. "
            f"Aesthetics/Lighting: cinematic dramatic lighting, {light}, high detail, 8k. "
            f"Camera & Lens: {shot_type}, {composition} composition, {camera_motion}, shallow depth of field, 35mm cinematic lens, stable framing.{spatial_note} "
            f"Continuity: {continuity}. "
            f"Constraints: same character identity and outfit, stable background, no sudden cuts, smooth natural motion, consistent lighting across shots. "
            f"Tail Frame: character maintains final pose and gaze direction for next shot continuity. "
            f"Technical: facial features clear and stable without deformation, same character appearance consistent throughout, natural body proportions, smooth continuous motion without frame skipping, no blur no ghosting, no subtitles no text overlay, no background music."
        )

        # 负面提示词分层构建：通用缺陷 + 表演缺陷 + 资产偏差 + 风格违和
        negative_parts = [
            # 通用 AI 生成缺陷
            "blurry, low quality, distorted, morphing, flickering, frame inconsistency,",
            # 表演缺陷（有台词时强化口型同步风险）
            "lip sync mismatch, expression freeze, unnatural motion, limb distortion, hand mutation,"
            + (" lip movement on non-speaking characters," if lip_sync_target else " mouth movement without dialogue,"),
            # 资产偏差（参考图已锁定身份/服装/发型，须抑制漂移）
            "costume drift, identity drift, hair color change, extra fingers, face swap, aged appearance,",
            # 风格违和 + 文字干扰
            "cartoon, anime, plastic skin, over-saturated, watermarks, text artifacts, subtitles, text overlay, on-screen text, captions, title cards",
        ]
        negative_prompt = " ".join(negative_parts)

        return {
            "storyboard_id": sb.get("storyboard_id"),
            "final_video_prompt": prompt,
            "negative_prompt": negative_prompt,
            "lip_sync_target": lip_sync_target,
            "seedance_subject": subject,
            "seedance_motion": subject_motion,
            "seedance_camera": camera_motion,
            "seedance_expression": expression,
            "seedance_dialogue": dialogue_audio,
            "has_explicit_motion": True,
            "has_camera_movement": True,
            "has_dialogue_or_audio": bool(dialogue_lines),
            "generation_params": {
                "duration": duration_enum,
                "resolution": "1080p",
                "aspect_ratio": "9:16",
                "motion_magnitude": motion_magnitude,
                "seed": 0,
            },
        }

    @staticmethod
    def _run_sync(
        storyboard_data: Dict[str, Any],
        character_assets: Optional[Dict[str, Any]] = None,
        scene_assets: Optional[Dict[str, Any]] = None,
        full_script: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, str]] = None,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        import asyncio
        return asyncio.run(VideoComposerAgent.build(storyboard_data, character_assets, scene_assets, full_script, options, feedback))


# ============================================================
# LiteStoryboardAgent — 轻量分镜 Agent（standalone，源自 storyboard-lite 技能）
# ============================================================

class LiteStoryboardAgent:
    """轻量分镜 Agent：直接从剧本文本生成分镜表 + 可粘贴的视频提示词组。

    与 StoryboardDirectorAgent + VideoComposerAgent 的区别：
    - 不依赖上游结构化数据（无需 script_outline / character_assets / screenwriter）
    - 自动从剧本文本提取资产（角色/场景/道具），不生成资产 ID
    - 单次 LLM 调用同时输出分镜表和视频提示词组
    - 输出可直接用于即梦/小云雀等平台的粘贴式提示词
    """
    name = "lite_storyboard"
    description = "轻量分镜Agent：从剧本文本直接生成分镜表和视频提示词组"

    system_prompt = """【身份】
你是专业级影视分镜师，精通短视频镜头语言与节奏把控，熟悉抖音/快手竖屏短剧的工业化分镜规范。你的任务是从剧本文本直接生成分镜表和可直接粘贴使用的视频提示词组。

【输入】
- 剧本文本（必填）
- 故事类型（可选，默认都市职场）
- 美术风格（可选，默认真人现代都市）

【核心执行步骤】
1. 自动提取资产：从剧本中识别角色（含中性标签如男主/女主）、场景、道具，不生成资产 ID。
2. 生成分镜表：按剧本顺序逐镜拆解。
3. 生成视频提示词组：将分镜表转化为可直接粘贴使用的视频生成提示词块。

【分镜表规则】
- 严格按剧本顺序，不添加剧本中没有的情节。
- 不遗漏任何台词，台词原文复制到「台词」字段。
- 每个镜头必须有场景。
- 可见角色和剧情道具必须出现在「关联资产名称」中。
- 「角色动作」以 (开篇) 或 (承接上镜:...) 开头。
- 同场景内保持朝向和空间关系的一致性。
- 「朝向」用于角色朝向；空镜或纯物体特写用「—」。
- 「空间关系」用于多角色镜头；单人/空镜/物体镜头用「—」。
- 含台词镜头时长按语速计算：愤怒4字/秒，正常3字/秒，悲伤/低语2字/秒，计算后+1秒。
- 无台词镜头通常不超过6秒。
- 「音效」仅包含具体物理声源、环境音、动作音效（如脚步声/纸张翻动/风声/雨声/手机铃声），禁止写 BGM/配乐/旋律/背景音乐。

【视频组规则】
- 按分镜表顺序构建视频组。
- 每个视频组时长 4-15 秒。
- 优先将同场景同戏剧节拍的连续镜头编为一组。
- 单个分镜超过15秒时，拆分为更小的时间节拍但保持原始台词顺序。
- 不创建短于4秒的组，合并或重新平衡相邻节拍。
- 每个视频组内部时间码从 [0s] 重新开始。
- 使用精确时间范围如 [0-2.5s], [2.5-5s], [5-8s]，最终时间码必须与组时长一致。
- 跨组保持场景、角色、道具、伤口、服装、情绪和空间连续性。使用「承接上组状态」「延续本场左右基线」「尾帧承接下组」等表述。

【视频组格式】每个视频组必须包含：
- 画面风格和类型：结合美术风格与实用图像生成描述词
- 场景：分镜表中的简洁场景名
- 角色：仅列出可见或发声角色
- 道具：剧情相关可见道具，无则填「无」
- 运镜+画面：分时间段，每段含「画面」「运镜」「声音」
- 其他需求：固定技术约束

【提示词写作规则】
- 每个时间段必须包含「画面」「运镜」「声音」。
- 「画面」描述可见动作、构图、朝向、画面位置、情绪微表情、肢体运动、连续性状态。
- 多角色场景建立/维护左右基线。
- 使用生成友好的镜头语言：中景/近景/偏紧近景/极近特写/远景/微距特写/Dolly In/Dolly Out/Truck/Orbit/Rack Focus/Tilt Up/Crash Zoom/手持微晃/固定/深焦/浅焦/长焦压缩空间。
- 影响画面时描述光照和氛围：暖黄侧光/冷白日光灯/窗帘缝隙透入的下午阳光/手机蓝光/台灯光圈等。
- 「声音」仅含场内声效、拟音、环境音和对白，不含背景音乐。
- 对白原文复制，格式为 台词（情绪）：角色："台词"。
- 使用「尾帧」注释连续性。
- 每组以固定技术约束结尾：面部五官清晰稳定不变形，同一角色全程外貌一致，人体结构正常比例自然，动作连续自然不跳帧，无模糊无重影，无字幕无文字，无背景音乐。

【强制输出结构】只输出以下 JSON，不要 Markdown 或解释文字：
{
  "assumed_story_type": "都市职场",
  "assumed_art_style": "真人现代都市",
  "assets": [
    {
      "name": "林小满",
      "type": "角色",
      "description": "年轻女性、焦虑、职业装",
      "appearance": "第1场、第2-3镜"
    }
  ],
  "storyboard": [
    {
      "shot_num": 1,
      "visual_description": "林小满坐在办公桌前，盯着电脑屏幕",
      "scene": "办公室",
      "linked_assets": ["林小满"],
      "duration": "5s",
      "shot_type": "中景",
      "camera_movement": "缓慢推镜",
      "character_action": "(开篇)林小满端坐在工位，双手放在键盘上",
      "facing": "面向屏幕",
      "spatial_relation": "—",
      "emotion": "焦虑",
      "dialogue": "",
      "sound_effect": "键盘敲击声，空调嗡嗡声"
    }
  ],
  "video_groups": [
    {
      "group_num": 1,
      "style_and_type": "真人写实, 都市写实摄影，电影风格，自然光照，极致细节",
      "scene": "办公室",
      "characters": ["林小满"],
      "props": ["手机", "合同"],
      "duration": "8s",
      "beats": [
        {
          "time_range": "[0-3s]",
          "visual": "林小满坐在工位，屏幕蓝光映在脸上，眉头微皱",
          "camera": "中景，缓慢推镜，浅景深",
          "sound": "键盘敲击声，空调嗡嗡声"
        },
        {
          "time_range": "[3-8s]",
          "visual": "林小满拿起手机，看到消息后瞳孔微缩，手指悬在屏幕上方",
          "camera": "近景，固定微晃，浅景深",
          "sound": "手机震动声 台词（紧张）：林小满：\"这不可能...\""
        }
      ],
      "tail_frame": "林小满盯着手机屏幕，嘴唇微张",
      "constraints": "面部五官清晰稳定不变形，同一角色全程外貌一致，人体结构正常比例自然，动作连续自然不跳帧，无模糊无重影，无字幕无文字，无背景音乐。"
    }
  ]
}

【质量校验项】
□ 分镜表存在且可读
□ 每句剧本台词都出现在分镜表和相关视频组中
□ 每个视频组 4-15 秒
□ 每个视频组包含风格、场景、角色、道具、时间段、运镜、声音和技术约束
□ 视频提示词包含足够的连续性细节用于角色一致性、空间一致性、动作连续性
□ assets 中角色使用中性标签或剧本中的名字，不生成资产 ID
□ sound_effect / 声音 仅含场内物理声源/环境音/动作音效，无 BGM/配乐
□ 只输出 JSON，不要 Markdown 或解释文字
"""

    @staticmethod
    async def build(
        script_text: str,
        story_type: Optional[str] = None,
        art_style: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        token_tracker: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """从剧本文本直接生成分镜表和视频提示词组。

        Args:
            script_text: 剧本文本（必填）
            story_type: 故事类型（可选，默认都市职场）
            art_style: 美术风格（可选，默认真人现代都市）
            options: 可选参数（含 llm_model 等）
            token_tracker: token 计数器

        Returns:
            包含 assets, storyboard, video_groups 的字典
        """
        options = options or {}
        story_type = story_type or options.get("story_type", "都市职场")
        art_style = art_style or options.get("art_style", "真人现代都市")

        user_prompt = (
            f"请根据以下剧本文本生成分镜表和视频提示词组。\n\n"
            f"故事类型：{story_type}\n"
            f"美术风格：{art_style}\n\n"
            f"剧本文本：\n{script_text}\n\n"
            f"请按照系统提示词中的输出结构，生成包含 assets、storyboard、video_groups 的 JSON。"
        )

        result = await _llm_json(
            LiteStoryboardAgent.system_prompt,
            user_prompt,
            model=_resolve_llm_model(options),
            token_tracker=token_tracker,
            fallback={"assets": [], "storyboard": [], "video_groups": []},
            max_tokens=8192,
            temperature=0.3,
        )
        result = _validate_llm_result(result, ["storyboard", "video_groups"], "LiteStoryboardAgent")

        # 后处理安全网：确保字段完整
        if "assets" not in result:
            result["assets"] = []
        if "assumed_story_type" not in result:
            result["assumed_story_type"] = story_type
        if "assumed_art_style" not in result:
            result["assumed_art_style"] = art_style

        # 校验分镜表字段
        for i, sb in enumerate(result.get("storyboard", [])):
            sb.setdefault("shot_num", i + 1)
            sb.setdefault("visual_description", "")
            sb.setdefault("scene", "")
            sb.setdefault("linked_assets", [])
            sb.setdefault("duration", "5s")
            sb.setdefault("shot_type", "中景")
            sb.setdefault("camera_movement", "固定")
            sb.setdefault("character_action", "(开篇)")
            sb.setdefault("facing", "—")
            sb.setdefault("spatial_relation", "—")
            sb.setdefault("emotion", "")
            sb.setdefault("dialogue", "")
            sb.setdefault("sound_effect", "环境自然声")

        # 校验视频组字段
        for i, vg in enumerate(result.get("video_groups", [])):
            vg.setdefault("group_num", i + 1)
            vg.setdefault("style_and_type", f"真人写实, {art_style}，电影风格，自然光照，极致细节")
            vg.setdefault("scene", "")
            vg.setdefault("characters", [])
            vg.setdefault("props", [])
            vg.setdefault("duration", "5s")
            vg.setdefault("beats", [])
            vg.setdefault("tail_frame", "")
            vg.setdefault(
                "constraints",
                "面部五官清晰稳定不变形，同一角色全程外貌一致，人体结构正常比例自然，"
                "动作连续自然不跳帧，无模糊无重影，无字幕无文字，无背景音乐。"
            )
            # 校验每个 beat
            for beat in vg.get("beats", []):
                beat.setdefault("time_range", "[0-5s]")
                beat.setdefault("visual", "")
                beat.setdefault("camera", "")
                beat.setdefault("sound", "")

        return result

    @staticmethod
    def _run_sync(
        script_text: str,
        story_type: Optional[str] = None,
        art_style: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import asyncio
        return asyncio.run(LiteStoryboardAgent.build(script_text, story_type, art_style, options))


class ShortDramaWorkflow:
    """短剧工作流：会话持久化到 SQLite SessionStore。"""

    def create_session(
        self,
        prompt: str,
        mode: str = "inspiration",
        script_text: Optional[str] = None,
        user_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> str:
        """创建会话。

        mode:
          - "inspiration": 灵感模式，从剧本策划开始（默认）
          - "script": 剧本模式，用户直接提供完整剧本文本，跳过剧本策划，直接进入编剧拆解
          - "novel": 小说改编模式，用户提供小说原文，由剧本 Agent 改编为短剧大纲
        """
        script_data = None
        status = "created"
        messages = [
            WorkflowMessage(role="user", agent=None, step=None, content=prompt).__dict__,
        ]
        if mode == "script" and script_text:
            script_data = {
                "project_title": "用户上传剧本",
                "genre": "",
                "source_prompt": script_text[:500],
                "raw_script_text": script_text,
                "style_bible": "",
                "color_palette": [],
                "episodes": [],
                "is_user_script": True,
            }
            status = "script_ready"
            messages.append(WorkflowMessage(
                role="agent",
                agent="system",
                step="script",
                content="已接收您上传的剧本，将直接进入编剧进行工业化分镜剧情脚本拆解。",
            ).__dict__)
        elif mode == "novel" and script_text:
            script_data = {
                "project_title": "小说改编短剧",
                "genre": "",
                "source_prompt": script_text[:500],
                "raw_novel_text": script_text,
                "style_bible": "",
                "color_palette": [],
                "episodes": [],
                "is_novel": True,
            }
            status = "novel_ready"
            messages.append(WorkflowMessage(
                role="agent",
                agent="system",
                step="script",
                content="已接收您上传的小说原文，将由剧本架构师改编为短剧大纲。",
            ).__dict__)

        initial_data = {
            "user_instruction": prompt,
            "created_at": datetime.utcnow().isoformat(),
            "messages": messages,
            "current_stage": "planning",
            "script_outline": None,
            "full_script": None,
            "character_assets": None,
            "scene_assets": None,
            "storyboard_data": None,
            "video_plan": None,
            "feedback_message": "",
            "user_feedback": "",
            "user_feedback_stage": "",
            "pending_user_feedback": "",
            "retry_count": 0,
            "review_target": "",
            "last_error": "",
            "script": script_data,
            "screenwriter": None,
            "character": None,
            "storyboard": None,
            "scene": None,
            "videos": None,
            "assets": None,
            "locked_assets": [],
            "asset_ids": [],
            "status": status,
            "parameter_pending": True,
            "global_params": {},
            "options": {
                "start.llm_model": llm_model,
            } if llm_model else {},
        }
        return get_store().create(prompt, mode=mode, user_id=user_id, team_id=team_id, initial_data=initial_data)

    def get_session(self, sid: str) -> Optional[Dict[str, Any]]:
        return get_store().get(sid)

    def save_session(self, sid: str, session: Dict[str, Any], lock_owner: Optional[str] = None) -> None:
        get_store().save(sid, session, lock_owner=lock_owner)

    # 保留旧名称兼容
    _save_session = save_session

    def acquire_session_lock(self, sid: str, owner: str) -> bool:
        return get_store().acquire_lock(sid, owner)

    def release_session_lock(self, sid: str, owner: str, new_status: Optional[str] = None) -> bool:
        return get_store().release_lock(sid, owner, new_status=new_status)

    async def _infer_core_genre(
        self,
        prompt: str,
        script_text: str,
        visual_style: str,
        options: Optional[Dict[str, str]] = None,
    ) -> str:
        """使用轻量 LLM 从用户输入推断核心题材；失败时回退到视觉风格。"""
        source = script_text.strip() if script_text.strip() else prompt.strip()
        if not source:
            return visual_style

        system_prompt = """你是短剧题材分类助手。请根据用户输入的一句话灵感或剧本文本，输出最贴切的短剧核心题材。
只输出 JSON：{"核心题材": "..."}。题材控制在 10 字以内。"""
        user_content = f"视觉风格：{visual_style}\n用户输入：{source[:800]}"
        try:
            result = await _llm_json(
                system_prompt,
                user_content,
                model=_resolve_llm_model(options),
                fallback={"核心题材": visual_style},
                max_retries=1,  # 非关键调用，快速失败
            )
            return result.get("核心题材") or visual_style
        except Exception as exc:
            logger.warning("[ShortDrama] _infer_core_genre LLM 调用失败，回退到 visual_style=%s: %s", visual_style, exc)
            return visual_style

    async def suggest_parameters(self, sid: str) -> Dict[str, Any]:
        """根据会话已有信息推荐 8 个全局创作参数。"""
        session = self.get_session(sid)
        if not session:
            return {"status": "failed", "error": "会话不存在"}

        options = self.get_options(sid)
        prompt = session.get("prompt", "")
        script_data = session.get("script") or {}
        script_text = script_data.get("raw_script_text", "") if isinstance(script_data, dict) else ""

        today = datetime.utcnow().strftime("%Y%m%d")
        sid_suffix = sid[-4:] if len(sid) >= 4 else sid
        project_id = f"DRAMA-{today}-{sid_suffix}".upper()

        visual_style = (
            options.get("start.visual_style")
            or options.get("planning.visual_style")
            or "电影写实"
        )
        duration = (
            options.get("start.duration_per_episode")
            or options.get("planning.duration_per_episode")
            or "60-90秒"
        )
        platform = (
            options.get("start.target_platform")
            or options.get("planning.target_platform")
            or "抖音"
        )
        aspect_ratio = (
            options.get("production.video_ratio")
            or options.get("asset.aspect_ratio")
            or "9:16"
        )
        # 用户上传完整剧本时，题材可由用户后续在参数面板自行确认，避免额外 LLM 调用拖慢响应
        if script_text.strip():
            core_genre = visual_style
        else:
            core_genre = await self._infer_core_genre(prompt, script_text, visual_style, options)

        suggestions = {
            "项目ID": project_id,
            "核心题材": core_genre,
            "视觉主风格": visual_style,
            "目标画幅": aspect_ratio,
            "单集时长": duration,
            "目标平台": platform,
            "渲染基准": DEFAULT_GLOBAL_PARAMS["渲染基准"],
            "镜头基准": DEFAULT_GLOBAL_PARAMS["镜头基准"],
        }

        return {"status": "success", "suggestions": suggestions}

    def confirm_parameters(
        self,
        sid: str,
        global_params: Dict[str, str],
        llm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """保存用户确认后的全局参数，并允许进入后续阶段。"""
        session = self.get_session(sid)
        if not session:
            return {"status": "failed", "error": "会话不存在"}

        merged = dict(DEFAULT_GLOBAL_PARAMS)
        merged.update(global_params or {})

        if not merged.get("项目ID"):
            today = datetime.utcnow().strftime("%Y%m%d")
            merged["项目ID"] = f"DRAMA-{today}-{sid[-4:]}".upper()

        session["global_params"] = merged
        session["parameter_pending"] = False
        if llm_model:
            session.setdefault("options", {})["start.llm_model"] = llm_model
        self._save_session(sid, session)

        return {"status": "success", "global_params": merged}

    def set_option(self, sid: str, key: str, value: str):
        session = self.get_session(sid)
        if session:
            session.setdefault("options", {})[key] = value
            self._save_session(sid, session)

    def get_options(self, sid: str) -> Dict[str, str]:
        session = self.get_session(sid)
        return session.get("options", {}) if session else {}

    async def run_step(
        self,
        sid: str,
        step: str,
        db: Session,
        on_message: Optional[Callable[[WorkflowMessage], Awaitable[None]]] = None,
    ) -> StepResult:
        from app.agents.drama_brain import run_stage, DramaProductionState

        # 步骤 -> 阶段映射（兼容旧参数）
        stage_map = {
            "script": "planning", "screenwriter": "planning", "planning": "planning",
            "assets": "asset", "character": "asset", "scene": "asset", "asset": "asset",
            "storyboard": "production", "video": "production", "production": "production",
            "lite_storyboard": "lite_storyboard",
        }

        session = self.get_session(sid)
        if not session:
            return StepResult(step=step, status="failed", error="会话不存在")

        # M8: 会话级并发锁 —— 防止多 tab / 多请求互相覆盖
        lock_owner = f"run_step_{sid}_{uuid.uuid4().hex[:12]}"
        logger.info("[ShortDrama] run_step 开始: sid=%s step=%s stage=%s lock_owner=%s", sid, step, stage_map.get(step, step), lock_owner)
        if not self.acquire_session_lock(sid, lock_owner):
            # 诊断：读取当前锁持有者信息
            locked_session = self.get_session(sid)
            lock_status = locked_session.get("status", "unknown") if locked_session else "session_not_found"
            logger.warning("[ShortDrama] 会话锁获取失败: sid=%s current_status=%s", sid, lock_status)
            return StepResult(step=step, status="failed", error=f"当前会话正在执行中（状态：{lock_status}），请等待完成后再操作。如确认无正在执行的任务，可使用强制解锁。")

        # 立即把状态标记为 running，让前端/其他接口感知到正在执行
        session["status"] = f"running_{stage_map.get(step, step)}"
        try:
            self._save_session(sid, session, lock_owner=lock_owner)
        except Exception as exc:
            logger.warning("[ShortDrama] 标记 running 状态失败: %s", exc)

        async def emit(agent: str, step_name: str, content: str, payload: Dict = None):
            msg = WorkflowMessage(role="agent", agent=agent, step=step_name, content=content, payload=payload or {})
            session["messages"].append(msg.__dict__)
            if on_message:
                await on_message(msg)

        stage = stage_map.get(step)
        if not stage:
            self.release_session_lock(sid, lock_owner)
            return StepResult(step=step, status="failed", error=f"未知步骤: {step}")

        # 校验前置阶段
        if stage == "asset" and not session.get("full_script"):
            self.release_session_lock(sid, lock_owner)
            return StepResult(step=step, status="failed", error="请先完成前期策划")
        if stage == "production" and (not session.get("character_assets") or not session.get("scene_assets")):
            self.release_session_lock(sid, lock_owner)
            return StepResult(step=step, status="failed", error="请先完成资产设定")

        # M8: 增量 checkpoint —— 每个子 Agent 节点完成后把进度落盘，断点可续
        def _checkpoint(state: DramaProductionState):
            try:
                # 把大脑 state 中的关键字段同步回 session dict
                for key in [
                    "current_stage", "script_outline", "full_script",
                    "character_assets", "scene_assets", "storyboard_data", "video_plan",
                    "feedback_message", "user_feedback", "user_feedback_stage",
                    "pending_user_feedback", "retry_count", "review_target", "last_error",
                    "token_tracker", "rule_version", "error_case_library",
                    "best_practice_library", "iteration_log", "review_scores",
                    "review_issues", "review_target_ids",
                    "_completed_stages", "_completed_episodes",  # #10 断点续传
                    "failed_dimensions", "previous_review_feedback",  # #7 智能质检
                ]:
                    if key in state:
                        session[key] = state[key]
                # 兼容旧字段
                session["script"] = session.get("script_outline") or session.get("script")
                session["screenwriter"] = session.get("full_script") or session.get("screenwriter")
                session["character"] = session.get("character_assets") or session.get("character")
                session["scene"] = session.get("scene_assets") or session.get("scene")
                session["storyboard"] = session.get("storyboard_data") or session.get("storyboard")
                session["videos"] = session.get("video_plan") or session.get("videos")
                session["status"] = f"running_{state.get('current_stage', stage)}"
                self._save_session(sid, session, lock_owner=lock_owner)
            except Exception as exc:
                logger.warning("[ShortDrama] checkpoint 保存失败: %s", exc)

        # 构造大脑 State（带上 token_tracker 实现跨阶段累计）
        token_tracker = session.get("token_tracker") or {"token_used": 0, "token_prompt": 0, "token_completion": 0}
        # 把 session["mode"] 注入 options，让下游 Agent 能通过 options.get("mode") 检测剧本上传模式
        _options = dict(self.get_options(sid))
        _options["mode"] = session.get("mode", "inspiration")
        brain_state: DramaProductionState = {
            "user_instruction": session.get("prompt", ""),
            "options": _options,
            "global_params": session.get("global_params", {}),
            "current_stage": session.get("current_stage", "planning"),
            "script_outline": session.get("script_outline") or session.get("script"),
            "full_script": session.get("full_script") or session.get("screenwriter"),
            "character_assets": session.get("character_assets") or session.get("character"),
            "scene_assets": session.get("scene_assets") or session.get("scene"),
            "storyboard_data": session.get("storyboard_data") or session.get("storyboard"),
            "video_plan": session.get("video_plan") or session.get("videos"),
            "feedback_message": session.get("feedback_message", ""),
            "user_feedback": session.get("user_feedback", ""),
            "user_feedback_stage": session.get("user_feedback_stage", ""),
            "pending_user_feedback": session.get("pending_user_feedback", ""),
            "retry_count": session.get("retry_count", 0),
            "review_target": session.get("review_target", ""),
            "last_error": session.get("last_error", ""),
            "token_tracker": token_tracker,
            "messages": [],
            "checkpoint_callback": _checkpoint,
            # #10 断点续传字段
            "_completed_stages": session.get("_completed_stages", []),
            "_completed_episodes": session.get("_completed_episodes", []),
            "failed_dimensions": session.get("failed_dimensions", []),  # #7
            "previous_review_feedback": session.get("previous_review_feedback", ""),  # #7
        }

        await emit("director_brain", stage, f"总导演大脑正在调度 {stage} 阶段...")

        # M4: 实时进度流：队列 + 后台消费者任务
        message_queue: Optional[asyncio.Queue] = None
        consumer_task = None
        if on_message:
            message_queue = asyncio.Queue()

            async def _consume():
                while True:
                    try:
                        msg = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                        await on_message(WorkflowMessage(**msg))
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break

            consumer_task = asyncio.create_task(_consume())

        try:
            try:
                # LangGraph 0.2+ async 节点直接跑在主事件循环上，无需 to_thread。
                final_state = await run_stage(brain_state, stage, message_queue=message_queue)
            except Exception as exc:
                logger.error("[ShortDrama] stage '%s' failed: %s", stage, exc)
                if consumer_task:
                    consumer_task.cancel()
                    try:
                        await consumer_task
                    except asyncio.CancelledError:
                        pass
                return StepResult(step=step, status="failed", error=str(exc))
            finally:
                if message_queue:
                    # 确保队列中剩余消息被消费
                    while not message_queue.empty():
                        try:
                            msg = message_queue.get_nowait()
                            await on_message(WorkflowMessage(**msg))
                        except Exception:
                            break
                if consumer_task:
                    consumer_task.cancel()
                    try:
                        await consumer_task
                    except asyncio.CancelledError:
                        pass

            # 同步回 session（新字段 + 兼容旧字段）
            session["current_stage"] = final_state.get("current_stage", stage)
            session["script_outline"] = final_state.get("script_outline")
            session["full_script"] = final_state.get("full_script")
            session["character_assets"] = final_state.get("character_assets")
            session["scene_assets"] = final_state.get("scene_assets")
            session["storyboard_data"] = final_state.get("storyboard_data")
            session["video_plan"] = final_state.get("video_plan")
            session["feedback_message"] = final_state.get("feedback_message", "")
            session["user_feedback"] = final_state.get("user_feedback", "")
            session["user_feedback_stage"] = final_state.get("user_feedback_stage", "")
            session["pending_user_feedback"] = final_state.get("pending_user_feedback", "")
            session["retry_count"] = final_state.get("retry_count", 0)
            session["review_target"] = final_state.get("review_target", "")
            session["last_error"] = final_state.get("last_error", "")
            session["token_tracker"] = final_state.get("token_tracker") or token_tracker

            # 同步导演大脑记忆进化体系字段
            session["rule_version"] = final_state.get("rule_version", session.get("rule_version", "1.0"))
            session["error_case_library"] = final_state.get("error_case_library") or session.get("error_case_library", [])
            session["best_practice_library"] = final_state.get("best_practice_library") or session.get("best_practice_library", [])
            session["iteration_log"] = final_state.get("iteration_log") or session.get("iteration_log", [])
            session["review_scores"] = final_state.get("review_scores", {})
            session["review_issues"] = final_state.get("review_issues", [])
            session["review_target_ids"] = final_state.get("review_target_ids", [])

            # #10 断点续传字段同步
            session["_completed_stages"] = final_state.get("_completed_stages", session.get("_completed_stages", []))
            session["_completed_episodes"] = final_state.get("_completed_episodes", session.get("_completed_episodes", []))
            session["failed_dimensions"] = final_state.get("failed_dimensions", [])
            session["previous_review_feedback"] = final_state.get("previous_review_feedback", "")

            # 兼容旧字段
            session["script"] = final_state.get("script_outline") or session.get("script")
            session["screenwriter"] = final_state.get("full_script") or session.get("screenwriter")
            session["character"] = final_state.get("character_assets") or session.get("character")
            session["scene"] = final_state.get("scene_assets") or session.get("scene")
            session["storyboard"] = final_state.get("storyboard_data") or session.get("storyboard")
            session["videos"] = final_state.get("video_plan") or session.get("videos")
            if final_state.get("character_assets") and final_state.get("scene_assets"):
                session["assets"] = {
                    "characters": final_state["character_assets"].get("characters", []),
                    "scenes": final_state["scene_assets"].get("scenes", []),
                    "props": final_state["scene_assets"].get("props", []),
                    "character_relations": final_state["character_assets"].get("character_relations", []),
                }

            # 状态机更新
            if stage == "planning":
                session["status"] = "screenwriter_ready"
            elif stage == "asset":
                session["status"] = "assets_ready"
            elif stage == "production":
                session["status"] = "video_ready"
                # production 结束时，确保 videos 字段包含前端需要的 confirm_finalize 结构
                video_plan = session.get("video_plan") or {"videos": []}
                videos_list = video_plan.get("videos", []) if isinstance(video_plan, dict) else []
                session["videos"] = {
                    "videos": videos_list,
                    "summary": "请选择下一步操作",
                    "next_action": "confirm_finalize",
                    "options": [
                        {"key": "generate", "label": "直接生成图片", "desc": "自动生成所有角色、场景图，进入画布后可手动生成分镜和视频"},
                        {"key": "skip", "label": "进入画布", "desc": "只创建节点卡片，所有图片视频手动生成"},
                    ],
                }

            # 同步消息
            for msg in final_state.get("messages", []):
                session["messages"].append(msg)

            # 如果有反馈消息（未通过但已超次），发送给前端
            feedback = final_state.get("feedback_message", "")
            if feedback:
                await emit("director_brain", f"{stage}_review", f"总导演质检意见：{feedback}")
            else:
                await emit("director_brain", f"{stage}_review", f"{stage} 阶段验收通过")

            # 持久化会话
            self._save_session(sid, session, lock_owner=lock_owner)

            return StepResult(step=step, status="success", data={"stage": stage, "feedback_message": feedback})
        finally:
            # 无论成功失败都释放锁；new_status 已在上面设置
            self.release_session_lock(sid, lock_owner)

    async def lock_assets(
        self,
        sid: str,
        char_ids: List[str],
        scene_ids: List[str],
        db: Session,
        on_message: Optional[Callable[[WorkflowMessage], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        session = self.get_session(sid)
        if not session:
            return {"status": "failed", "error": "会话不存在"}
        assets_data = session.get("assets") or {"characters": [], "scenes": []}

        async def emit(agent: str, step_name: str, content: str, payload: Dict = None):
            msg = WorkflowMessage(role="agent", agent=agent, step=step_name, content=content, payload=payload or {})
            session["messages"].append(msg.__dict__)
            if on_message:
                await on_message(msg)

        await emit("asset_extractor", "asset_generating", "正在为锁定的资产生成概念图并保存到资产库...")

        options = self.get_options(sid)
        image_model = options.get("asset.image_model", options.get("assets.image_model", settings.IMAGE_MODEL_GPT_IMAGE_2))
        session_user_id = session.get("user_id")
        session_team_id = session.get("team_id")

        locked = []
        asset_ids = []
        for char in assets_data.get("characters", []):
            if char.get("char_id") in char_ids:
                asset_info = await self._generate_asset_image(
                    db, char.get("name", "角色"), "character", char.get("base_prompt", ""), char.get("visual_anchor", ""), image_model, user_id=session_user_id, team_id=session_team_id
                )
                locked.append({"type": "character", **char, **asset_info})
                asset_ids.append(asset_info["asset_id"])

        for scene in assets_data.get("scenes", []):
            if scene.get("scene_id") in scene_ids:
                asset_info = await self._generate_asset_image(
                    db, scene.get("name", "场景"), "scene", scene.get("base_prompt", ""), "", image_model, user_id=session_user_id, team_id=session_team_id
                )
                locked.append({"type": "scene", **scene, **asset_info})
                asset_ids.append(asset_info["asset_id"])

        session["locked_assets"] = locked
        session["asset_ids"] = asset_ids
        await emit("asset_extractor", "assets_locked", f"已锁定并生成 {len(locked)} 个资产", {"locked_assets": locked})
        self._save_session(sid, session)
        return {"status": "success", "locked_assets": locked, "asset_ids": asset_ids}

    async def _generate_asset_image(
        self, db: Session, name: str, asset_type: str, prompt: str, description: str, image_model: Optional[str] = None, user_id: Optional[str] = None, team_id: Optional[str] = None
    ) -> Dict[str, str]:
        """调用 AI 生图；失败时返回 SVG 占位图。"""
        from app.api.v1.asset import UPLOAD_DIR, STATIC_URL_PREFIX

        subdir = "characters" if asset_type == "character" else "scenes"
        save_dir = os.path.join(UPLOAD_DIR, subdir)
        os.makedirs(save_dir, exist_ok=True)

        file_id = str(uuid.uuid4())

        # 优先尝试 AI 生图
        try:
            if prompt:
                response = await AIService.generate_image(prompt, model=image_model or settings.IMAGE_MODEL_GPT_IMAGE_2)
                image_url = None
                if isinstance(response, dict):
                    data = response.get("data") or []
                    if data and isinstance(data[0], dict):
                        image_url = data[0].get("url") or data[0].get("b64_json")
                if image_url:
                    ext = ".png"
                    if image_url.startswith("data:"):
                        # data URL
                        import base64
                        header, b64 = image_url.split(",", 1)
                        mime = header.split(":")[1].split(";")[0]
                        ext = ".png" if mime == "image/png" else ".jpg" if mime == "image/jpeg" else ".webp" if mime == "image/webp" else ".png"
                        content = base64.b64decode(b64)
                    else:
                        image_url = image_url if image_url.startswith("http") else f"{settings.PUBLIC_BASE_URL.rstrip('/')}{image_url}"
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(image_url, timeout=120)
                            resp.raise_for_status()
                            content = resp.content
                        ctype = resp.headers.get("content-type", "").lower()
                        ext = ".webp" if "webp" in ctype else ".png" if "png" in ctype else ".jpg" if "jpeg" in ctype else ".png"
                    filename = f"{file_id}{ext}"
                    file_path = os.path.join(save_dir, filename)
                    with open(file_path, "wb") as f:
                        f.write(content)
                    file_url = f"{STATIC_URL_PREFIX}/{subdir}/{filename}"
                    asset_in = AssetCreate(
                        name=name,
                        asset_type=AssetType.CHARACTER if asset_type == "character" else AssetType.SCENE,
                        tags=[asset_type, "ai-generated", "short-drama"],
                        description=description or prompt,
                        meta={"prompt": prompt, "source": "short_drama_agent", "session_id": None},
                    )
                    asset = crud_asset.create_asset(
                        db, asset_in,
                        file_path=file_path,
                        file_url=file_url,
                        mime_type=f"image/{ext.lstrip('.')}" if ext.lstrip('.') in {"png", "jpg", "jpeg", "webp", "gif"} else "image/png",
                        file_size=len(content),
                        user_id=user_id,
                        team_id=uuid.UUID(team_id) if team_id else None,
                    )
                    return {
                        "asset_id": str(asset.id),
                        "asset_file_url": file_url,
                        "asset_prompt": prompt,
                    }
        except Exception as exc:
            logger.warning("[ShortDrama] AI 生图失败，回退到占位图: %s", exc)

        # 回退：SVG 占位图（文件名带 _placeholder 标记，便于下游过滤）
        filename = f"{file_id}_placeholder.svg"
        file_path = os.path.join(save_dir, filename)
        file_url = f"{STATIC_URL_PREFIX}/{subdir}/{filename}"
        short_prompt = html.escape(prompt[:120]) + ("..." if len(prompt) > 120 else "")
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
            <defs>
                <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#1a1a2e"/>
                    <stop offset="100%" stop-color="#16213e"/>
                </linearGradient>
            </defs>
            <rect width="512" height="512" fill="url(#g)"/>
            <rect x="20" y="20" width="472" height="472" rx="20" fill="none" stroke="#6366f1" stroke-width="4"/>
            <text x="256" y="220" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#e2e8f0">{html.escape(name)}</text>
            <text x="256" y="270" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#94a3b8">AI概念图占位</text>
            <text x="256" y="310" text-anchor="middle" font-family="monospace" font-size="10" fill="#64748b">{short_prompt}</text>
        </svg>'''
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(svg)

        asset_in = AssetCreate(
            name=name,
            asset_type=AssetType.CHARACTER if asset_type == "character" else AssetType.SCENE,
            tags=[asset_type, "ai-generated", "short-drama", "placeholder"],
            description=description or prompt,
            meta={"prompt": prompt, "source": "short_drama_agent", "session_id": None},
        )
        asset = crud_asset.create_asset(
            db, asset_in,
            file_path=file_path,
            file_url=file_url,
            mime_type="image/svg+xml",
            file_size=len(svg.encode("utf-8")),
            user_id=user_id,
            team_id=uuid.UUID(team_id) if team_id else None,
        )
        return {
            "asset_id": str(asset.id),
            "asset_file_url": file_url,
            "asset_prompt": prompt,
        }


short_drama_workflow = ShortDramaWorkflow()
