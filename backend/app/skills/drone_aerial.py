from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class DroneAerialSkill(BaseSkill):
    info = SkillInfo(
        skill_id="SKILL_005",
        skill_name="无人机航拍",
        tags=["上帝视角", "航拍运镜", "大场景全景", "城市航拍", "自然地貌", "建筑全景"],
        supported_outputs=["提示词", "图片", "视频"],
        version="V1.0",
        category="视角运镜类",
        params=[
            SkillParam("拍摄主体描述", "text", required=True, description="要航拍的核心主体"),
            SkillParam("运镜模式", "select", options=["环绕拉升", "前进俯冲", "高空推远", "旋转下降", "横向平移"], default="环绕拉升"),
            SkillParam("飞行高度", "select", options=["低空30米", "中空100米", "高空300米"], default="中空100米"),
            SkillParam("时间天气", "select", options=["正午晴天", "黄昏夕阳", "雨夜", "薄雾清晨"], default="正午晴天"),
            SkillParam("产出类型", "select", options=["航拍全景图", "缓慢运镜视频", "冲击力运镜"], default="航拍全景图"),
        ],
    )

    system_prompt = """
# Role
你是专业级航拍摄影提示词工程师，负责把用户的航拍需求转化为可直接用于 AI 生成的结构化提示词。你精通无人机视角、大场景构图、环境地貌与运镜轨迹描述。

# Global Context（自动继承）
- 目标画幅：{{目标画幅}}
- 渲染基准：{{渲染基准}}
- 镜头基准：{{镜头基准}}

# 5层提示词生成公式（严格顺序）
1. 航拍主体层：核心拍摄主体、画面位置、主体细节特征、整体比例协调
2. 环境地貌层：主体周围环境地貌、远景天际线、近景细节、空间层次
3. 天气光线层：时间天气、光线方向、光影效果、大气氛围
4. 无人机运镜层：运镜模式、起始高度、结束高度、运动速度、镜头锁定
5. 航拍摄影质感层：高空航拍视角、大景深、宽画幅视野、高清细节、自然色彩

# 输出 JSON 结构
{
  "skill_id": "SKILL_005",
  "skill_name": "无人机航拍",
  "version": "V1.0",
  "drone_shot_note": "运镜模式+轨迹描述+起止状态",
  "positive_prompt": "按5层公式拼接的完整英文提示词",
  "modular_prompt": {
    "aerial_subject": "...",
    "environment_landscape": "...",
    "weather_light": "...",
    "drone_movement": "...",
    "aerial_texture": "..."
  },
  "negative_prompt": "模糊、低分辨率、画面扭曲、比例失真、地平线歪斜、穿模、地面细节崩坏、画面闪烁、无人机入镜、运镜卡顿、速度忽快忽慢、主体偏离画面中心、地平线倾斜、空间比例失调、地面物体悬浮、卡通、二次元、手绘、塑料质感、色彩饱和溢出、美颜滤镜、不真实的光影",
  "generation_params": {
    "output_type": "航拍全景图|缓慢运镜视频|冲击力运镜",
    "duration": "",
    "resolution": "1920x1080",
    "fps": "",
    "motion": ""
  }
}

# 约束
- 必须是高空航拍上帝视角，禁止无人机本体入镜
- 地平线必须水平，不能倾斜
- 运镜轨迹必须有明确起止状态和运动速度
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
拍摄主体描述：{user_input}
运镜模式：{merged.get('运镜模式')}
飞行高度：{merged.get('飞行高度')}
时间天气：{merged.get('时间天气')}
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
                "drone_shot_note": "",
                "positive_prompt": "",
                "modular_prompt": {},
                "negative_prompt": "",
                "generation_params": {},
                "_error": "LLM 调用失败，请稍后重试",
            },
        )
        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not result.get("_is_fallback") else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )
