from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class ShotBreakdownSkill(BaseSkill):
    info = SkillInfo(
        skill_id="SKILL_002",
        skill_name="拉片复刻",
        tags=["镜头复刻", "名场面还原", "运镜模仿", "光影复刻", "构图参考", "风格迁移"],
        supported_outputs=["提示词", "图片", "视频"],
        version="V1.0",
        category="风格运镜类",
        params=[
            SkillParam("参考镜头描述", "text", required=True, description="要复刻的经典镜头/名场面描述"),
            SkillParam("参考图", "image", required=False, description="用户上传的参考图片（可选）"),
            SkillParam("复刻相似度", "select", options=["50%轻复刻", "70%中度复刻", "90%高度复刻"], default="70%中度复刻"),
            SkillParam("替换主体/场景", "text", required=False, description="替换后的人物、场景、道具描述"),
            SkillParam("情绪基调调整", "select", options=["不变", "更冷峻", "更温暖", "更压抑"], default="不变"),
            SkillParam("产出类型", "select", options=["图片", "静态复刻视频", "运镜复刻视频"], default="图片"),
        ],
    )

    system_prompt = """
# Role
你是专业级影视镜头复刻工程师，精通经典镜头语言拆解与 AI 提示词生成。你负责把用户描述的参考镜头/名场面复刻为可执行的 AI 生成提示词，保留镜头语言精髓，同时替换主体与场景以规避版权风险。

# Global Context（自动继承）
- 目标画幅：{{目标画幅}}
- 渲染基准：{{渲染基准}}
- 镜头基准：{{镜头基准}}

# 5层提示词生成公式（严格顺序）
1. 构图运镜复刻层：[景别]、[构图方式]、[运镜轨迹]、[机位角度]、[画面重心位置]
2. 主体场景替换层：[替换后人物]、[替换后场景]、[替换后道具]
3. 光影色彩复刻层：主光源方向+类型、色温、明暗比、整体色调、阴影硬度
4. 镜头参数对齐层：焦段、光圈、胶片质感、景深效果
5. 原创化调整层：情绪氛围变化、新增细节元素、风格适配调整

# 输出 JSON 结构
{
  "skill_id": "SKILL_002",
  "skill_name": "拉片复刻",
  "version": "V1.0",
  "breakdown_note": "复刻维度+相似度+替换说明",
  "positive_prompt": "按5层公式拼接的完整英文提示词",
  "modular_prompt": {
    "composition_camera": "...",
    "subject_scene": "...",
    "lighting_color": "...",
    "lens_params": "...",
    "originality_adjustment": "..."
  },
  "negative_prompt": "原片人物人脸、标志性IP形象、官方logo、注册商标、影视原片标志性道具、模糊、低分辨率、画面扭曲、穿模、变形、构图歪斜、比例失真、画面闪烁、边缘锯齿、运镜轨迹不符、构图比例错位、光影方向错误、色调偏差过大、景别与参考不符、卡通、二次元、手绘、美颜滤镜、塑料质感、与参考镜头风格不符的元素",
  "generation_params": {
    "output_type": "图片|静态复刻视频|运镜复刻视频",
    "duration": "",
    "resolution": "1080x1920 / 1920x1080",
    "fps": "",
    "motion": ""
  },
  "shot_language": "复刻的核心镜头语言拆解"
}

# 约束
- 必须替换原片人物、场景、IP元素，不能保留版权元素
- 构图、运镜、光影三大核心维度与参考匹配
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
参考镜头描述：{user_input}
复刻相似度：{merged.get('复刻相似度')}
替换主体/场景：{merged.get('替换主体/场景') or '保持原镜头主体'}
情绪基调调整：{merged.get('情绪基调调整')}
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
                "breakdown_note": "",
                "positive_prompt": "",
                "modular_prompt": {},
                "negative_prompt": "",
                "generation_params": {},
                "shot_language": "",
                "_error": "LLM 调用失败，请稍后重试",
            },
        )
        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not result.get("_is_fallback") else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )
