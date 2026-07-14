from typing import Any, Dict, List, Optional

from app.skills.base import BaseSkill, SkillOutput
from app.skills.story_creation import StoryCreationSkill
from app.skills.shot_breakdown import ShotBreakdownSkill
from app.skills.scene_design import SceneDesignSkill
from app.skills.worldcup import WorldCupSkill
from app.skills.drone_aerial import DroneAerialSkill
from app.skills.novel_to_shortdrama import NovelToShortDramaSkill
from app.skills.storyboard_lite import StoryboardLiteSkill
from app.skills.drama_generator_pro import DramaGeneratorProSkill
from app.skills.muzi_generator import MuziGeneratorSkill
from app.skills.seedance_prompt import SeedancePromptSkill
from app.skills.xyq_short_drama import XyqShortDramaSkill
from app.skills.storyboard_director import StoryboardDirectorSkill
from app.skills.script_video_prompt_architect import ScriptVideoPromptArchitectSkill
from app.skills.novel_director import NovelDirectorSkill


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}
        self._register_defaults()

    def _register_defaults(self):
        # 新版技能（首页展示）
        self.register(NovelToShortDramaSkill())
        self.register(StoryboardLiteSkill())
        # 新接入技能（skill技能文件夹）
        self.register(DramaGeneratorProSkill())
        self.register(MuziGeneratorSkill())
        self.register(SeedancePromptSkill())
        self.register(XyqShortDramaSkill())
        self.register(StoryboardDirectorSkill())
        self.register(ScriptVideoPromptArchitectSkill())
        self.register(NovelDirectorSkill())
        # 旧版技能（保留向后兼容）
        self.register(StoryCreationSkill())
        self.register(ShotBreakdownSkill())
        self.register(SceneDesignSkill())
        self.register(WorldCupSkill())
        self.register(DroneAerialSkill())

    def register(self, skill: BaseSkill):
        self._skills[skill.info.skill_id] = skill

    def get(self, skill_id: str) -> Optional[BaseSkill]:
        return self._skills.get(skill_id)

    def list(self) -> List[BaseSkill]:
        return list(self._skills.values())

    def describe_all(self) -> List[Dict[str, Any]]:
        return [s.describe() for s in self._skills.values()]


skill_registry = SkillRegistry()


def list_skills() -> List[Dict[str, Any]]:
    return skill_registry.describe_all()


def get_skill(skill_id: str) -> Optional[BaseSkill]:
    return skill_registry.get(skill_id)


async def run_skill(
    skill_id: str,
    user_input: str,
    params: Optional[Dict[str, Any]] = None,
    global_params: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    llm_model: Optional[str] = None,
) -> SkillOutput:
    """执行指定 Skill，支持大脑注入的全局参数和多轮对话历史。"""
    skill = skill_registry.get(skill_id)
    if not skill:
        return SkillOutput(
            skill_id=skill_id,
            status="failed",
            error=f"未找到 Skill: {skill_id}",
        )
    # 将用户选择的 LLM 模型设置到 skill 实例上
    skill._llm_model = llm_model
    return await skill.run(user_input, params, global_params, history=history)
