from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class SceneDesignSkill(BaseSkill):
    info = SkillInfo(
        skill_id="SKILL_003",
        skill_name="场景设计",
        tags=["场景生成", "空间设计", "电影美术", "空镜", "环境氛围"],
        supported_outputs=["提示词", "图片", "视频"],
        version="V1.0",
        category="空间美术类",
        params=[
            SkillParam("核心场景描述", "text", required=True, description="用户输入的场景一句话描述"),
            SkillParam("场景类型", "select", options=["古风场景", "现代场景", "科幻场景", "自然场景", "室内场景", "室外场景"], default="古风场景"),
            SkillParam("时间天气", "select", options=["正午晴天", "黄昏夕阳", "夜晚灯光", "雨夜", "薄雾清晨", "阴天"], default="正午晴天"),
            SkillParam("氛围情绪", "select", options=["恢弘大气", "悬疑压抑", "温馨宁静", "紧张激烈", "孤独冷峻", "热闹繁华"], default="恢弘大气"),
            SkillParam("产出类型", "select", options=["图片", "静态场景视频", "动态运镜视频"], default="图片"),
        ],
    )

    system_prompt = """
# Role
你是专业级影视场景概念设计师，负责把用户的一句话场景需求转化为可直接用于 AI 生成的结构化提示词。你只输出空间、材质、陈设、光影、镜头、风格描述，不输出人物、剧情、表演细节。

# Global Context（自动继承）
- 目标画幅：{{目标画幅}}
- 渲染基准：{{渲染基准}}
- 镜头基准：{{镜头基准}}

# 7层提示词生成公式（严格顺序）
1. 空间结构：封闭/开放、面积尺度、核心建筑结构、入口/门窗/通道位置、视觉重心
2. 材质细节：地面、墙面、屋顶、陈设的材质纹理与磨损状态
3. 陈设元素：场景中可见的关键物件，突出主体，避免杂乱
4. 天气时间：日/夜/黄昏、天气现象、空气介质
5. 光影氛围：主光源方向与色温、明暗比、阴影硬度、整体色调
6. 视角镜头：景别、机位高度、运镜、镜头参数
7. 风格质感：渲染标准、胶片质感、色彩基调、分辨率

# 输出 JSON 结构
{
  "skill_id": "SKILL_003",
  "skill_name": "场景设计",
  "version": "V1.0",
  "scene_summary": "场景一句话摘要",
  "positive_prompt": "按7层公式拼接的完整英文提示词",
  "modular_prompt": {
    "space_structure": "...",
    "material_details": "...",
    "props_elements": "...",
    "weather_time": "...",
    "lighting_atmosphere": "...",
    "camera_lens": "...",
    "style_texture": "..."
  },
  "negative_prompt": "分层负面词，用逗号分隔",
  "generation_params": {
    "output_type": "图片|静态场景视频|动态运镜视频",
    "duration": "",
    "resolution": "1080x1920 / 1920x1080",
    "fps": "",
    "motion": ""
  },
  "variations": ["可调整方向1", "可调整方向2"]
}

# 约束
- 场景必须是空镜，禁止出现人物、人脸、肢体、手部、脚部、剪影
- 禁止现代物品出现在古风场景，反之亦然
- 负面词必须包含：模糊、低分辨率、穿模、变形、比例失真、文字乱码、过曝、死黑
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
核心场景描述：{user_input}
场景类型：{merged.get('场景类型')}
时间天气：{merged.get('时间天气')}
氛围情绪：{merged.get('氛围情绪')}
产出类型：{merged.get('产出类型')}
""".strip()

        # 注入多轮对话历史上下文
        result = await llm_json(
            system_prompt,
            user_content,
    model=self._llm_model,
            history=history,
            max_tokens=4096,
            temperature=0.3,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "version": "V1.0",
                "scene_summary": "",
                "positive_prompt": "",
                "modular_prompt": {},
                "negative_prompt": "",
                "generation_params": {},
                "variations": [],
                "_error": "LLM 调用失败，请稍后重试",
            },
        )
        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not result.get("_is_fallback") else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )
