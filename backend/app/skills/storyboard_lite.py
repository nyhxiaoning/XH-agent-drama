"""
Skill: storyboard-lite
将剧本文本生成为轻量分镜表和可直接粘贴到 AI 视频平台的视频组提示词。

基于 skill技能/video-agent-skills-main/skills/storyboard-lite/SKILL.md 实现。
"""
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class StoryboardLiteSkill(BaseSkill):
    info = SkillInfo(
        skill_id="storyboard-lite",
        skill_name="轻量分镜制作",
        tags=["分镜表", "视频提示词", "资产提取", "镜头拆解", "运镜", "AI视频生成"],
        supported_outputs=["分镜表", "视频组提示词", "资产清单"],
        version="V1.0",
        category="分镜制作类",
        params=[
            SkillParam("剧本文本", "text", required=True, description="需要拆解为分镜的剧本内容"),
            SkillParam("故事类型", "select", options=[
                "都市职场", "甜宠恋爱", "悬疑惊悚", "热血动作", "仙侠玄幻",
                "家庭温情", "喜剧幽默", "科幻末世", "历史史诗", "心理剧情",
                "恐怖超自然", "成长剧情",
            ], default="都市职场"),
            SkillParam("美术风格", "select", options=[
                "真人现代都市", "真人古装中国", "真人武侠",
                "2D 国风", "2D 日漫", "2D 扁平设计", "2D 成熟都市恋爱",
                "3D 动画", "3D 国风", "3D 国风赛博", "3D 黏土定格",
            ], default="真人现代都市"),
            SkillParam("输出格式", "select", options=["Markdown", "CSV", "JSON"], default="Markdown"),
        ],
    )

    system_prompt = """\
# Role
你是专业的分镜师和 AI 视频提示词工程师。你的任务是把剧本文本转化为实用的分镜表和一组可直接粘贴到 AI 视频平台（如即梦、小云雀）的视频组提示词。

## 输入
- 剧本文本（必需）
- 故事类型（可选，默认：都市职场）
- 美术风格（可选，默认：真人现代都市）

## 资产提取
在分镜表之前，从剧本中提取资产：
- **角色**：有名角色和明确角色别称（如男主、女主、母亲、老板）。
- **场景**：明确地点和反复出现的隐含地点（如办公室、客厅、医院走廊）。
- **道具**：与剧情相关的物件（如手机、合同、钥匙、药瓶）。

规则：
- 不要编造资产 ID。
- 只使用剧本中明确的名称或保守中性标签。
- 如果角色名未知，使用稳定中性标签如女主、男主、母亲。
- 资产提取输出列：名称、类型、描述词、出镜位置。
- 类型必须是：角色、场景、道具之一。
- 描述词应简洁，用「、」分隔，如「年轻女性、焦虑、职业装」。

## 分镜表规则
- 严格按照剧本顺序。
- 不要添加剧本中没有的剧情事件。
- 不要遗漏台词。将台词原文逐字复制到台词字段。
- 每个镜头都需要有场景。
- 可见角色和剧情相关道具必须出现在关联资产名称中。
- 角色动作应以 `(开篇)` 或 `(承接上镜:...)` 开头。
- 同一场景内保持朝向和空间关系的视觉连续性。
- 朝向用于角色面向；空镜或纯物品特写用 —。
- 空间关系用于多人镜头；单人、空镜或物品镜头用 —。
- 对话镜头时长需足够说完整台词：愤怒约4字/秒，正常约3字/秒，悲伤/低语/虚弱约2字/秒，然后加约1秒。
- 非对话镜头通常不超过6秒。
- 音效只包含具体物理声源、环境声、动作声或拟音。不要写 BGM、配乐、旋律或乐器。

## 视频组规则
分镜表之后，输出视频组列表。视频组是从分镜表派生的可直接生成的提示词块。

分组规则：
- 按分镜表顺序构建视频组。
- 每个视频组时长 4-15 秒。
- 优先将同一场景和戏剧节拍的连续镜头分为一组。
- 如果单个分镜镜头超过15秒，拆分为更小的时间节拍，保持原始台词顺序。
- 不要创建短于4秒的组。
- 每个视频组内部时间码从 [0s] 重新开始。
- 使用精确的内部时间范围，如 [0-2.5s]、[2.5-5s]、[5-8s]。
- 跨组保持场景、角色、道具、伤痕、服装、情感和空间连续性。

视频组格式：
```
### 视频组1
画面风格和类型: 真人写实, 都市写实摄影，电影风格，自然光照，极致细节

场景: 场景名称
角色：角色A、角色B
道具：道具A、道具B

运镜+画面：[0-2.5s]
画面：...
运镜：...
声音：...

[2.5-5s]
画面：...
运镜：...
声音：... 台词（情绪）：角色A："原文台词"

其他需求：面部五官清晰稳定不变形，同一角色全程外貌一致，人体结构正常比例自然，动作连续自然不跳帧，无模糊无重影，无字幕无文字，无背景音乐。
```

运镜语言：中景、近景、偏紧近景、极近特写、远景、微距特写、Dolly In、Dolly Out、Truck、Orbit、Rack Focus、Tilt Up、Crash Zoom、手持微晃、固定、深焦、浅焦、长焦压缩空间。

## 输出 JSON 结构
请严格输出以下 JSON 结构。注意：不要输出 full_markdown 字段，该字段由后端自动拼接生成。

{
  "skill_id": "storyboard-lite",
  "skill_name": "轻量分镜制作",
  "assumptions": "说明假设的故事类型和美术风格",
  "story_type": "故事类型",
  "art_style": "美术风格",
  "assets": [
    {"name": "名称", "type": "角色/场景/道具", "description": "描述词", "appearances": "出镜位置"}
  ],
  "storyboard": [
    {
      "shot_num": "序号",
      "visual_desc": "画面描述",
      "scene": "场景",
      "related_assets": "关联资产名称",
      "duration": "时长",
      "shot_type": "景别",
      "camera": "运镜",
      "action": "角色动作",
      "facing": "朝向",
      "spatial": "空间关系",
      "emotion": "情绪",
      "dialogue": "台词",
      "sfx": "音效"
    }
  ],
  "video_groups_markdown": "视频组列表的完整 Markdown 内容，每个视频组包含画面风格和类型、场景、角色、道具、分段时间码的画面/运镜/声音描述、其他需求"
}

## 约束
- 不要输出 API 响应 JSON、场景 ID、集 ID、图片 URL、视频 URL。
- 分镜表必须存在且可读。
- 每条剧本台词都出现在分镜表和相关视频组中。
- 每个视频组 4-15 秒。
- 每个视频组都有风格、场景、角色、道具、时间码节拍、运镜、声音和技术约束。
- 视频提示词需包含足够的连续性细节，确保角色一致性、空间一致性、动作连续性。
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字。
- 不要输出 full_markdown 字段，节省 token，后端会自动拼接。
"""

    @staticmethod
    def _build_full_markdown(result: Dict[str, Any]) -> str:
        """从结构化数据拼接完整的 Markdown 输出（替代让 LLM 生成，节省大量 token）。"""
        parts: list[str] = []

        # 假设说明
        assumptions = result.get("assumptions", "")
        if assumptions:
            parts.append(f"> **{assumptions}**\n")

        # 资产清单
        assets = result.get("assets", [])
        if assets:
            parts.append("## 资产清单\n")
            parts.append("| 名称 | 类型 | 描述词 | 出镜位置 |")
            parts.append("|------|------|--------|----------|")
            for a in assets:
                parts.append(
                    f"| {a.get('name', '')} | {a.get('type', '')} | "
                    f"{a.get('description', '')} | {a.get('appearances', '')} |"
                )
            parts.append("")

        # 分镜表
        storyboard = result.get("storyboard", [])
        if storyboard:
            parts.append("## 分镜表\n")
            parts.append(
                "| 序号 | 画面描述 | 场景 | 关联资产 | 时长 | 景别 | 运镜 | "
                "角色动作 | 朝向 | 空间关系 | 情绪 | 台词 | 音效 |"
            )
            parts.append(
                "|------|----------|------|----------|------|------|------|"
                "----------|------|----------|------|------|------|"
            )
            for s in storyboard:
                parts.append(
                    f"| {s.get('shot_num', '')} | {s.get('visual_desc', '')} | "
                    f"{s.get('scene', '')} | {s.get('related_assets', '')} | "
                    f"{s.get('duration', '')} | {s.get('shot_type', '')} | "
                    f"{s.get('camera', '')} | {s.get('action', '')} | "
                    f"{s.get('facing', '')} | {s.get('spatial', '')} | "
                    f"{s.get('emotion', '')} | {s.get('dialogue', '')} | "
                    f"{s.get('sfx', '')} |"
                )
            parts.append("")

        # 视频组
        video_md = result.get("video_groups_markdown", "")
        if video_md:
            parts.append("## 视频组提示词\n")
            parts.append(video_md)

        return "\n".join(parts)

    async def run(
        self,
        user_input: str,
        params: Optional[Dict[str, Any]] = None,
        global_params: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> SkillOutput:
        merged = self.merge_params(params)
        system_prompt = self._render_global_params(self.system_prompt, global_params)

        story_type = str(merged.get("故事类型", "都市职场"))
        art_style = str(merged.get("美术风格", "真人现代都市"))
        output_format = str(merged.get("输出格式", "Markdown"))

        user_content = f"""\
故事类型：{story_type}
美术风格：{art_style}
输出格式：{output_format}

剧本文本：
{user_input}
""".strip()

        # 注入多轮对话历史上下文
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
                "assumptions": f"假设：故事类型为「{story_type}」，美术风格为「{art_style}」。",
                "story_type": story_type,
                "art_style": art_style,
                "assets": [],
                "storyboard": [],
                "video_groups_markdown": "",
                "full_markdown": "",
                "_error": "LLM 调用失败，请稍后重试",
            },
        )

        # 后端自动拼接 full_markdown，避免 LLM 重复输出浪费 token
        if not result.get("_is_fallback"):
            if not result.get("full_markdown"):
                result["full_markdown"] = self._build_full_markdown(result)

        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not result.get("_is_fallback") else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )
