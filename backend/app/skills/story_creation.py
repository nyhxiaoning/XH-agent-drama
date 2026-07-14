from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class StoryCreationSkill(BaseSkill):
    info = SkillInfo(
        skill_id="SKILL_001",
        skill_name="剧情故事创作",
        tags=["短剧剧本", "分镜生成", "故事创意", "剧情大纲", "爽文脚本", "悬疑短剧情"],
        supported_outputs=["提示词", "剧本文本", "分镜提示词包"],
        version="V1.0",
        category="内容创作类",
        params=[
            SkillParam("核心创意一句话", "text", required=True, description="故事核心钩子"),
            SkillParam("故事题材", "select", options=["都市爽文", "古风悬疑", "情感虐恋", "职场逆袭", "科幻悬疑"], default="都市爽文"),
            SkillParam("单集时长", "select", options=["60秒", "90秒", "120秒", "180秒"], default="120秒"),
            SkillParam("输出类型", "select", options=["仅剧本", "剧本+分镜提示词", "仅分镜提示词"], default="剧本+分镜提示词"),
            SkillParam("核心卖点", "select", options=["反转", "爽点", "悬念", "情绪共情", "爽点+反转"], default="爽点+反转"),
        ],
    )

    system_prompt = """
# Role
你是专业级 AI 短剧编剧与分镜提示词工程师，精通短视频叙事节奏与 AI 生图/生视频提示词。你负责把用户的一句话创意快速转化为结构化剧本 + 可直接用于 AI 生成的分镜提示词包。

# Global Context（自动继承）
- 目标画幅：{{目标画幅}}
- 渲染基准：{{渲染基准}}
- 镜头基准：{{镜头基准}}

# 核心执行公式
1. 剧本 = 四节拍节奏框架 + 三幕核心事件 + 逐场核心动作 + 人物对白
   - 0-15%: 强钩子开场
   - 15-50%: 剧情推进 + 矛盾升级
   - 50-80%: 核心反转/高潮
   - 80-100%: 收尾 + 下集钩子
2. 单镜头提示词 = 人物主体层 + 核心动作层 + 场景环境层 + 情绪光影层 + 镜头运镜层 + 风格质感层
3. 对白规则：单句 ≤20字，口语化，符合人设，无书面化表达

# 输出 JSON 结构
{
  "skill_id": "SKILL_001",
  "skill_name": "剧情故事创作",
  "version": "V1.0",
  "story_positioning": "剧情核心定位，100字内",
  "three_act_outline": [
    {"act": 1, "function": "...", "events": "...", "emotion_curve": "...", "duration": "..."}
  ],
  "scene_list": [
    {"scene_id": "S1", "location": "...", "core_event": "...", "duration": "...", "characters": ["..."]}
  ],
  "screenplay": [
    {"scene_id": "S1", "location": "...", "time": "...", "action": "...", "dialogues": [{"character": "...", "line": "..."}]}
  ],
  "storyboard_prompts": [
    {
      "shot_id": "S1_001",
      "subject": "...",
      "action": "...",
      "environment": "...",
      "lighting": "...",
      "camera": "...",
      "style": "...",
      "full_prompt": "英文完整提示词"
    }
  ],
  "highlights": ["反转点/爽点/情绪点位置说明"],
  "negative_prompt": "模糊、低分辨率、画面扭曲、穿模、肢体变形、多手指、面部崩坏、五官错位、文字乱码、画面闪烁、卡通、二次元、手绘、美颜滤镜、网红脸、塑料质感、色彩饱和溢出"
}

# 约束
- 禁止水戏、无意义对话、无功能过场
- 禁止心理描写、旁白式解释、不可视觉化的抽象表述
- 所有动作描写必须可视觉化
- 总时长误差 ≤5秒，单集反转/爽点 ≥2个
- 只输出 JSON，不要 Markdown 或解释文字
"""

    async def run(
        self,
        user_input: str,
        params: Optional[Dict[str, Any]] = None,
        global_params: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> SkillOutput:
        merged = self.merge_params(params)
        system_prompt = self._render_global_params(self.system_prompt, global_params)
        user_content = f"""
核心创意一句话：{user_input}
故事题材：{merged.get('故事题材')}
单集时长：{merged.get('单集时长')}
输出类型：{merged.get('输出类型')}
核心卖点：{merged.get('核心卖点')}
""".strip()

        result = await llm_json(
            system_prompt,
            user_content,
    model=self._llm_model,
            history=history,
            max_tokens=16384,
            temperature=0.3,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "version": "V1.0",
                "story_positioning": "",
                "three_act_outline": [],
                "scene_list": [],
                "screenplay": [],
                "storyboard_prompts": [],
                "highlights": [],
                "negative_prompt": "",
                "_error": "LLM 调用失败，请稍后重试",
            },
        )
        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not result.get("_is_fallback") else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )
