"""
Skill: xyq-short-drama
短剧剧本创作助手。将用户的一句话创意转化为结构完整、格式规范的短剧剧本文本。
输出包含原始创意设定（世界观、角色、单元故事）和完整分集剧本。

基于 skill技能/xyq-short-drama-1.0.1/SKILL.md 实现。
"""
from typing import Any, Dict, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


# 题材类型选项
GENRE_OPTIONS = [
    "悬疑推理", "甜宠恋爱", "都市职场", "古装权谋", "奇幻冒险",
    "治愈温情", "爽文逆袭", "校园青春", "家庭伦理", "末日生存",
]

# 集数选项
EPISODE_OPTIONS = ["5集", "10集", "15集", "20集", "30集"]

# 每集场数
SCENES_PER_EP_OPTIONS = ["3场", "4场", "5场"]

# 情感基调
TONE_OPTIONS = ["温情", "刺激", "搞笑", "虐心", "爽感", "悬疑"]


class XyqShortDramaSkill(BaseSkill):
    info = SkillInfo(
        skill_id="xyq-short-drama",
        skill_name="短剧剧本创作",
        tags=["短剧剧本", "创意展开", "分集剧本", "世界观", "角色设定", "尾帧钩子"],
        supported_outputs=["原始创意", "分集剧本", "角色设定", "世界观设定"],
        version="1.0.1",
        category="内容创作类",
        params=[
            SkillParam("创意描述", "text", required=True, description="一句话创意或故事想法（题材、核心冲突、主角设定等）"),
            SkillParam("题材类型", "select", options=GENRE_OPTIONS, default="悬疑推理"),
            SkillParam("集数", "select", options=EPISODE_OPTIONS, default="10集"),
            SkillParam("每集场数", "select", options=SCENES_PER_EP_OPTIONS, default="4场"),
            SkillParam("情感基调", "select", options=TONE_OPTIONS, default="悬疑"),
        ],
    )

    system_prompt = """\
# Role
你是专业的短剧编剧助手。将用户的一句话创意或故事想法，转化为结构完整、格式规范的短剧剧本文本。
输出包含原始创意设定（世界观、角色、单元故事）和完整分集剧本（场景、舞台指示、对话、尾帧），格式严格遵循专业短剧剧本标准。

## 输入
- 创意描述：一句话创意或故事想法
- 题材类型：悬疑/甜宠/都市/古装/奇幻/治愈/爽文/校园/家庭/末日
- 集数：总集数
- 每集场数：每集包含的场景数量
- 情感基调：整体情感方向

## 工作流程

### Step 1: 生成原始创意
按以下结构输出原始创意：

1. **一句话钩子**：100字以内的故事概述，必须有"钩子感"
2. **项目概述**：类型、目标受众、集数
3. **世界观设定**：3-4条核心规则
4. **主角设定**：2-3个主要角色，含年龄、职业、核心特征、性格、成长线
5. **单元故事设计**：按集数分组，每个单元含标题、核心事件、核心冲突、主角收获

### Step 2: 生成完整分集剧本
按严格格式逐集生成：

#### 场景标头格式
```
### 场[集数]-[场序号]
[日/夜] [内/外] [具体地点名]
```

#### 舞台指示
- 以 `△` 开头，后跟空格
- 用于环境描写、人物动作、镜头指示、心理暗示
- 特写格式：`△ 特写：[内容]`

#### 对话格式
- `角色名（语气/动作描述）：台词内容。`
- 画外音：`角色名（vo，描述）：台词`
- 内心独白：`角色名（os，描述）：台词`

#### 尾帧
- 每集结尾必须有尾帧
- 描写一个定格画面，带有悬念感或情绪感染力
- 格式：`【尾帧：[画面定格描述]】`

#### 集间分隔
- 每集之间用 `---` 分隔

### 输出原则
1. **画面感优先**：舞台指示要让读者"看到"画面，用具体感官细节
2. **对话即性格**：每个角色的语言风格必须独特且一致
3. **节奏控制**：每集3-5场，每场不超过1500字，保持紧凑
4. **钩子意识**：每集结尾留悬念或情感冲击，尾帧是视觉钩子
5. **现实映射**：题材再奇幻，内核要映射真实社会议题或情感
6. **格式一致性**：从第1集到最后一集，所有格式元素不得走样

## 剧本格式规范

### 场景标头
- 集数和场序号用阿拉伯数字
- 时间只用"日"或"夜"（特殊情况可用"黄昏""清晨"）
- 空间只用"内"或"外"
- 地点名具体到房间级别

### 其他格式元素
- 全屏字幕：`【字幕：内容】`
- 系列结尾字幕用逐行淡入格式：`【全屏字幕，逐行淡入：...】`
- 单元结束标记：`【字幕：第X单元·完】`

## 输出 JSON 结构
请严格输出以下 JSON 结构，所有 Markdown 内容放在对应字符串字段中：

{
  "skill_id": "xyq-short-drama",
  "skill_name": "短剧剧本创作",
  "title": "剧名",
  "hook": "一句话钩子，≤100字",
  "genre": "题材类型",
  "total_episodes": 10,
  "tone": "情感基调",
  "characters": [
    {"name": "角色名", "role": "主角/配角/反派", "age": "年龄", "occupation": "职业", "trait": "核心特征", "arc": "成长线"}
  ],
  "world_setting": "世界观设定的完整 Markdown 内容",
  "story_units": "单元故事设计的完整 Markdown 内容",
  "full_script": "完整分集剧本的 Markdown 内容，包含所有集数的场景、舞台指示、对话、尾帧"
}

## 约束
- 不要输出 XML 包裹标签
- 不要输出内部分析、自查清单、字数统计
- 台词必须短、直白、口语化，单句通常不超过20字
- 场景描述必须可拍、可视、可执行
- 每集必须有尾帧
- 如果集数超过10集，先生成前6-8集，在最后一集后注明"续写请说'继续'"
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字
"""

    async def run(
        self,
        user_input: str,
        params: Optional[Dict[str, Any]] = None,
        global_params: Optional[Dict[str, Any]] = None,
    ) -> SkillOutput:
        merged = self.merge_params(params)
        system_prompt = self._render_global_params(self.system_prompt, global_params)

        genre = str(merged.get("题材类型", "悬疑推理"))
        episodes_str = str(merged.get("集数", "10集"))
        scenes_str = str(merged.get("每集场数", "4场"))
        tone = str(merged.get("情感基调", "悬疑"))

        try:
            total_episodes = int("".join(filter(str.isdigit, episodes_str)))
        except ValueError:
            total_episodes = 10
        try:
            scenes_per_ep = int("".join(filter(str.isdigit, scenes_str)))
        except ValueError:
            scenes_per_ep = 4

        user_content = f"""\
创意描述：
{user_input}

题材类型：{genre}
集数：{total_episodes}集
每集场数：{scenes_per_ep}场
情感基调：{tone}
"""

        result = await llm_json(
            system_prompt,
            user_content,
            max_tokens=16384,
            temperature=0.5,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "title": "",
                "hook": "",
                "genre": genre,
                "total_episodes": total_episodes,
                "tone": tone,
                "characters": [],
                "world_setting": "",
                "story_units": "",
                "full_script": "",
                "_error": "LLM 调用失败，请稍后重试",
            },
        )

        is_fallback = result.get("_is_fallback", False)

        # 后端拼接 full_markdown
        if not is_fallback:
            result["full_markdown"] = self._build_full_markdown(result)

        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not is_fallback else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )

    @staticmethod
    def _build_full_markdown(result: Dict[str, Any]) -> str:
        """从结构化数据拼接完整的 Markdown 输出。"""
        parts: list[str] = []

        title = result.get("title", "")
        if title:
            parts.append(f"# 《{title}》- 短剧剧本\n")

        hook = result.get("hook", "")
        if hook:
            parts.append(f"> **{hook}**\n")

        genre = result.get("genre", "")
        tone = result.get("tone", "")
        total = result.get("total_episodes", "")
        if genre or tone or total:
            parts.append(f"**类型**：{genre} | **基调**：{tone} | **集数**：{total}集\n")

        # 角色设定
        characters = result.get("characters", [])
        if characters:
            parts.append("## 角色设定\n")
            for c in characters:
                parts.append(f"### {c.get('name', '')}（{c.get('role', '')}）")
                parts.append(f"- {c.get('age', '')}，{c.get('occupation', '')}")
                parts.append(f"- 核心特征：{c.get('trait', '')}")
                parts.append(f"- 成长线：{c.get('arc', '')}\n")

        # 世界观
        world = result.get("world_setting", "")
        if world:
            parts.append("## 世界观设定\n")
            parts.append(world)
            parts.append("")

        # 单元故事
        units = result.get("story_units", "")
        if units:
            parts.append("## 单元故事设计\n")
            parts.append(units)
            parts.append("")

        # 完整剧本
        script = result.get("full_script", "")
        if script:
            parts.append("---\n\n## 完整剧本\n")
            parts.append(script)
            parts.append("")

        return "\n".join(parts)
