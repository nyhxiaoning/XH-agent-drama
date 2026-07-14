"""
#2 #4 统一 Agent 注册表 + 角色化消息

将所有 Agent（DramaBrain 子 Agent + PlatformBrain + Skill）统一注册，
附带角色元数据（显示名、图标、描述、阶段、模型分级），供：
  - 前端 SSE 消息展示角色化头像和标签
  - 后端模型分级自动选择
  - Agent 注册发现
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.model_tiers import TaskTier


@dataclass
class AgentMeta:
    """Agent 元数据。"""
    agent_id: str                    # 唯一标识
    display_name: str                # 前端显示名
    icon: str                        # 图标名（对应 lucide-react 图标）
    description: str                 # 一句话描述
    stage: str                       # 所属阶段: planning / asset / production / routing / system
    tier: TaskTier = TaskTier.STANDARD  # 模型分级
    color: str = "teal"              # 前端主题色
    sort_order: int = 99             # 排序权重


# ── 统一注册表 ──────────────────────────────────────

_REGISTRY: Dict[str, AgentMeta] = {}


def register_agent(meta: AgentMeta) -> None:
    """注册一个 Agent。"""
    _REGISTRY[meta.agent_id] = meta


def get_agent_meta(agent_id: str) -> Optional[AgentMeta]:
    """获取 Agent 元数据。"""
    return _REGISTRY.get(agent_id)


def get_agent_display_name(agent_id: str) -> str:
    """获取 Agent 显示名，未注册则返回 agent_id。"""
    meta = _REGISTRY.get(agent_id)
    return meta.display_name if meta else agent_id


def get_agent_icon(agent_id: str) -> str:
    """获取 Agent 图标名。"""
    meta = _REGISTRY.get(agent_id)
    return meta.icon if meta else "Brain"


def list_all_agents() -> List[AgentMeta]:
    """列出所有已注册 Agent，按 sort_order 排序。"""
    return sorted(_REGISTRY.values(), key=lambda a: a.sort_order)


def list_agents_by_stage(stage: str) -> List[AgentMeta]:
    """列出指定阶段的 Agent。"""
    return [a for a in list_all_agents() if a.stage == stage]


# ── 内置 Agent 注册 ──────────────────────────────────

# 系统级
register_agent(AgentMeta(
    agent_id="platform_brain",
    display_name="智能体调度",
    icon="Brain",
    description="分析用户需求，路由到对应技能或短剧流水线",
    stage="routing",
    tier=TaskTier.LITE,
    color="teal",
    sort_order=0,
))

register_agent(AgentMeta(
    agent_id="param_extractor",
    display_name="参数提取",
    icon="Settings2",
    description="从用户输入中提取技能所需参数",
    stage="routing",
    tier=TaskTier.LITE,
    color="cyan",
    sort_order=1,
))

register_agent(AgentMeta(
    agent_id="director_brain",
    display_name="总导演智能体",
    icon="Clapperboard",
    description="全流程调度、三级审核、偏差修正、记忆进化",
    stage="planning",
    tier=TaskTier.STANDARD,
    color="purple",
    sort_order=2,
))

# Planning 阶段
register_agent(AgentMeta(
    agent_id="script_planner",
    display_name="剧本架构师",
    icon="BookOpen",
    description="将灵感转化为结构化故事骨架",
    stage="planning",
    tier=TaskTier.CREATIVE,
    color="blue",
    sort_order=10,
))

register_agent(AgentMeta(
    agent_id="screenwriter",
    display_name="文学编剧",
    icon="BookText",
    description="将大纲细化为标准可拍摄文学剧本",
    stage="planning",
    tier=TaskTier.CREATIVE,
    color="indigo",
    sort_order=11,
))

# Asset 阶段
register_agent(AgentMeta(
    agent_id="character_designer",
    display_name="角色设计师",
    icon="User",
    description="设计角色视觉锚点与生图提示词",
    stage="asset",
    tier=TaskTier.CREATIVE,
    color="amber",
    sort_order=20,
))

register_agent(AgentMeta(
    agent_id="scene_prop_designer",
    display_name="场景设计师",
    icon="LayoutGrid",
    description="设计场景空间参数与道具规范",
    stage="asset",
    tier=TaskTier.CREATIVE,
    color="orange",
    sort_order=21,
))

register_agent(AgentMeta(
    agent_id="asset_extractor",
    display_name="资产提取师",
    icon="Package",
    description="将剧本元素转化为工业级生图提示词",
    stage="asset",
    tier=TaskTier.STANDARD,
    color="yellow",
    sort_order=22,
))

register_agent(AgentMeta(
    agent_id="asset_parallel",
    display_name="资产调度",
    icon="Layers",
    description="并行调度角色与场景资产设计",
    stage="asset",
    tier=TaskTier.STANDARD,
    color="amber",
    sort_order=23,
))

# Production 阶段
register_agent(AgentMeta(
    agent_id="storyboard_director",
    display_name="分镜导演",
    icon="Film",
    description="将文学剧本转化为逐镜头分镜表",
    stage="production",
    tier=TaskTier.CREATIVE,
    color="rose",
    sort_order=30,
))

register_agent(AgentMeta(
    agent_id="video_composer",
    display_name="视频作曲",
    icon="Video",
    description="生成分镜对应的视频生成提示词",
    stage="production",
    tier=TaskTier.STANDARD,
    color="red",
    sort_order=31,
))

register_agent(AgentMeta(
    agent_id="lite_storyboard",
    display_name="轻量分镜",
    icon="Film",
    description="直接从剧本文本生成分镜表",
    stage="production",
    tier=TaskTier.STANDARD,
    color="pink",
    sort_order=32,
))

# 审核节点
register_agent(AgentMeta(
    agent_id="reviewer",
    display_name="质检审核",
    icon="CheckCircle",
    description="三级质量审核：格式合规→逻辑一致→质量达标",
    stage="planning",
    tier=TaskTier.STANDARD,
    color="green",
    sort_order=5,
))

# 系统
register_agent(AgentMeta(
    agent_id="system",
    display_name="系统",
    icon="AlertCircle",
    description="系统消息",
    stage="system",
    tier=TaskTier.LITE,
    color="gray",
    sort_order=99,
))


def get_agent_meta_dict(agent_id: str) -> Dict[str, str]:
    """获取 Agent 元数据字典（用于 SSE 消息注入）。"""
    meta = _REGISTRY.get(agent_id)
    if not meta:
        return {"agent_id": agent_id, "display_name": agent_id, "icon": "Brain", "color": "teal", "stage": "system"}
    return {
        "agent_id": meta.agent_id,
        "display_name": meta.display_name,
        "icon": meta.icon,
        "color": meta.color,
        "stage": meta.stage,
        "description": meta.description,
    }
