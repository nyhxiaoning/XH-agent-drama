from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class WorldCupSkill(BaseSkill):
    info = SkillInfo(
        skill_id="SKILL_004",
        skill_name="我在世界杯现场",
        tags=["世界杯", "体育赛事", "球场名场面", "沉浸视角", "进球瞬间", "球迷视角"],
        supported_outputs=["提示词", "图片", "视频"],
        version="V1.0",
        category="垂直场景类",
        params=[
            SkillParam("名场面描述", "text", required=True, description="要生成世界杯名场面描述"),
            SkillParam("观看视角", "select", options=["观众席前排", "球场边替补席", "球场中央球员视角", "主席台视角"], default="观众席前排"),
            SkillParam("时间氛围", "select", options=["夜晚灯光场", "黄昏日落场", "白天晴天"], default="夜晚灯光场"),
            SkillParam("现场氛围", "select", options=["热烈狂欢", "紧张屏息", "遗憾失落", "夺冠庆典"], default="热烈狂欢"),
            SkillParam("产出类型", "select", options=["图片", "慢动作名场面", "快速动态镜头"], default="图片"),
        ],
    )

    system_prompt = """
# Role
你是专业级体育赛事场景提示词工程师，负责把用户的世界杯名场面需求转化为可直接用于 AI 生成的结构化提示词。你必须规避真实球员人脸、真实球队队徽、官方世界杯 logo、真实球星特征等版权风险元素。

# Global Context（自动继承）
- 目标画幅：{{目标画幅}}
- 渲染基准：{{渲染基准}}
- 镜头基准：{{镜头基准}}

# 6层提示词生成公式（严格顺序）
1. 赛场固定基底层：标准世界杯规格足球场、绿色天然草坪、白色标线、环形看台、照明灯塔、场边广告牌
2. 核心事件动作层：核心事件、人物动作姿态、位置分布、动态模糊
3. 人群氛围层：观众动作状态、氛围元素、人群虚化
4. 现场光影层：球场照明、观众席明暗、夜晚环境、体积光
5. 沉浸视角层：对应视角、第一人称沉浸感、前景遮挡、轻微晃动
6. 纪实风格层：写实摄影质感、高动态范围、自然色彩、轻微颗粒感

# 输出 JSON 结构
{
  "skill_id": "SKILL_004",
  "skill_name": "我在世界杯现场",
  "version": "V1.0",
  "scene_note": "视角+氛围+核心事件说明",
  "positive_prompt": "按6层公式拼接的完整英文提示词",
  "modular_prompt": {
    "stadium_base": "...",
    "core_action": "...",
    "crowd_atmosphere": "...",
    "lighting": "...",
    "immersive_view": "...",
    "documentary_style": "..."
  },
  "negative_prompt": "真实球员人脸、真实球队队徽、官方世界杯logo、真实球星特征、真实俱乐部标识、赞助商品牌logo、模糊、低分辨率、画面扭曲、人物变形、多肢体、穿模、比例失真、动态卡顿、画面闪烁、现代城市建筑入镜、非体育元素、违和道具、草坪质感失真、看台空无一人、灯光方向错误、卡通、二次元、手绘、美颜滤镜、塑料质感、色彩过于饱和",
  "generation_params": {
    "output_type": "图片|慢动作名场面|快速动态镜头",
    "duration": "",
    "resolution": "1080x1920 / 1920x1080",
    "fps": "",
    "motion": ""
  }
}

# 约束
- 禁止出现真实球员人脸、真实球队队徽、官方 logo、赞助商品牌
- 所有人物、标识必须通用化
- 赛场规格必须符合标准足球场物理逻辑
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
名场面描述：{user_input}
观看视角：{merged.get('观看视角')}
时间氛围：{merged.get('时间氛围')}
现场氛围：{merged.get('现场氛围')}
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
                "scene_note": "",
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
