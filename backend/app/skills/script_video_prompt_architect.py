"""
Skill: script-video-prompt-architect
短剧视频提示词架构师。基于用户提交的短剧/微短剧剧本，进行导演思维的分镜拆解
与分镜脚本设计，最终输出适配 Seedance 2.0 的视频生成提示词。

基于 skill技能/script-video-prompt-architect-1.0.2/SKILL.md 实现。
参考文件位于 backend/app/data/prompts/script_video_refs/。
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


# ─── 参考文件加载 ────────────────────────────────────────
_REF_DIR = Path(__file__).resolve().parent.parent / "data" / "prompts" / "script_video_refs"


def _load_ref(filename: str) -> str:
    """加载参考文件内容，若文件不存在则返回空字符串。"""
    filepath = _REF_DIR / filename
    try:
        return filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# 预加载全部参考文件
_SHOT_BREAKDOWN_GUIDE = _load_ref("shot-breakdown-guide.md")
_SHOT_SCRIPT_GUIDE = _load_ref("shot-script-guide.md")
_MERGE_RULES = _load_ref("merge-rules.md")
_CROSS_SHOT_CONTINUITY = _load_ref("cross-shot-continuity.md")
_STYLE_GUIDE = _load_ref("style-guide.md")
_VOICE_DESIGN = _load_ref("voice-design.md")
_VIDEO_CONTENT_GUIDE = _load_ref("video-content-guide.md")
_OUTPUT_EXAMPLES = _load_ref("output-examples.md")


# ─── 参数选项 ────────────────────────────────────────────
STYLE_PRESETS = [
    "真人写实", "古装真人写实", "现代都市写实", "悬疑暗黑写实",
    "甜宠轻喜写实", "奇幻玄幻写实",
    "2D动漫", "赛博朋克", "水墨国风", "复古胶片",
]

ASPECT_OPTIONS = ["9:16竖屏", "16:9横屏", "1:1方形"]


class ScriptVideoPromptArchitectSkill(BaseSkill):
    info = SkillInfo(
        skill_id="script-video-prompt-architect",
        skill_name="短剧视频提示词架构师",
        tags=["剧本转视频", "分镜拆解", "分镜脚本", "Seedance 2.0", "视频提示词", "短剧"],
        supported_outputs=[
            "角色音色清单", "场景道具清单", "分镜合并表",
            "分镜脚本设计", "Seedance视频提示词", "完整Markdown",
        ],
        version="1.0.2",
        category="视频制作类",
        params=[
            SkillParam("剧本内容", "text", required=True, description="完整一集或片段的短剧剧本原文"),
            SkillParam("视频画风", "select", options=STYLE_PRESETS, default="真人写实",
                       description="基础画面风格大类（对所有视频单元通用）"),
            SkillParam("画幅比例", "select", options=ASPECT_OPTIONS, default="9:16竖屏",
                       description="默认竖屏9:16，适用于短剧"),
            SkillParam("集数编号", "text", default="第1集",
                       description="当前处理的集数编号（用于提示词标题）"),
        ],
    )

    def _build_system_prompt(self, merged: Dict[str, Any]) -> str:
        """构建包含全部参考文件知识的完整 system prompt。"""
        style = str(merged.get("视频画风", "真人写实"))
        aspect = str(merged.get("画幅比例", "9:16竖屏"))
        episode = str(merged.get("集数编号", "第1集"))

        # 解析画幅
        if "9:16" in aspect:
            canvas_ratio = "9:16"
        elif "16:9" in aspect:
            canvas_ratio = "16:9"
        elif "1:1" in aspect:
            canvas_ratio = "1:1"
        else:
            canvas_ratio = "9:16"

        return f"""\
# 短剧视频提示词架构师

你是基于用户提交的短剧/微短剧剧本，进行导演思维的分镜拆解与分镜脚本设计，
最终输出适配 Seedance 2.0 的视频生成提示词的专业架构师。

## 全局参数
- 画幅比例：{canvas_ratio}（竖屏短剧默认）
- 视频画风：{style}
- 当前集数：{episode}

## 前提条件
- **默认竖屏 9:16**：本流程产出默认用于竖屏短剧。
- **用户已备好参考图**：Seedance 2.0 出视频要求用户提前准备角色/场景/道具的参考图（定妆照素材）。
  提示词中一律以 `@素材名` 引用，**绝不在提示词中描写角色外观**。
- **无独立负向字段**：Seedance 2.0 没有独立的 negative prompt 字段，
  所有内容（含负向约束）统一写入提示词正文的【视频约束】段。

## 核心约束
1. **忠于剧本原文**：不添加剧本原文没有的动作、台词、情节。
2. **逐层对应**：分镜→合并→分镜脚本→提示词，每层严格映射剧本原文，不丢不增。
3. **不描述角色外观**：角色外观统一由用户准备的参考图承载。
4. **针对性约束**：每条 prompt 的约束段应根据视频内容定制，而非套用固定模板。
5. **基础风格通用可复用**：基础视频风格描述必须是对全剧所有视频单元都适用的通用描述，
   不得包含受时间段（白天/夜晚）、室内外、特定天气等因素制约的描述。
6. **分镜脚本是提示词唯一依据**：阶段③生成提示词时，必须严格按照阶段②产出的分镜脚本来设计。

## 编号体系
三层编号，逐层映射，全程一致：
- 分镜层：`镜1、镜2、镜3…`
- 视频单元层：`视频单元1、视频单元2…`
- 提示词层：`【{episode}-NN】`（视频单元N → {episode}-0N）

---

## 三阶段处理流程

### 阶段①：剧本分析 → 确认清单 → 确认风格 → 分镜拆解 + 智能合并

1. **剧本分析**（内部）：逐场提取场次信息、人物、动作台词顺序、特殊标记。
2. **角色音色设计**（内部）：为每个有台词/OS的角色设计音色（性别、年龄感、核心特质2-3个词）。
3. **输出角色/场景/道具清单**。
4. **确认风格**：基础画面风格描述（对所有视频单元通用）。
5. **分镜拆解**（内部）：以导演思维将每场拆为独立镜头序列。
6. **智能合并 → 输出合并后分镜详情表**。

#### 分镜拆解原则（参考下方参考文件）
{_SHOT_BREAKDOWN_GUIDE}

#### 合并规则（参考下方参考文件）
{_MERGE_RULES}

#### 音色设计（参考下方参考文件）
{_VOICE_DESIGN}

#### 画面风格设计（参考下方参考文件）
{_STYLE_GUIDE}

---

### 阶段②：逐镜头设计分镜脚本

严格按照合并后的分镜详情，逐镜头设计完整的分镜脚本。每个镜头的设计必须严格基于
该镜头对应的剧本原文，不增不减。

#### 分镜脚本设计标准（参考下方参考文件）
{_SHOT_SCRIPT_GUIDE}

#### 相邻镜头连贯性检查（参考下方参考文件）
{_CROSS_SHOT_CONTINUITY}

---

### 阶段③：Seedance 2.0 提示词生成

严格按照分镜脚本，将每个视频单元转为一条 Seedance prompt。

#### 视频内容写作规范（参考下方参考文件）
{_VIDEO_CONTENT_GUIDE}

#### 各步骤输出范例（参考下方参考文件）
{_OUTPUT_EXAMPLES}

---

## 提示词固定结构（唯一权威格式）

每个视频单元输出一条提示词，结构如下：
```
【{episode}-NN | 总时长Xs】
【参考素材】
@角色A；
@场景B；
@道具C；

【视频风格】
[基础风格：对所有视频单元通用的画面风格描述]
- 时间：[白天/夜晚/黄昏/凌晨]
- 光源：主光源为[...]
- 色温：[描述+大约色温值]
- 动态元素：[如有则描述]
- 氛围：[情绪氛围关键词]
- 微细节：[如有则描述]

【视频内容】
[一段自然连贯的叙事段落，严格基于分镜脚本按时间先后串联所有镜头]

视频约束：
无字幕、无水印、无背景音乐。[定制化约束内容]
```

---

## 边界情况
- 用户提交多集剧本：仅处理第一集
- 剧本只有台词无动作描述：按台词节奏拆分镜头
- 合并后视频单元 >15s：必须拆为多个视频单元
- 未被合并的 <4s 独立镜头：补充空镜头扩充到至少 4s

---

## 输出 JSON 格式要求

你必须输出以下 JSON 结构：

```json
{{
  "skill_id": "script-video-prompt-architect",
  "skill_name": "短剧视频提示词架构师",
  "episode": "{episode}",
  "style": "{style}",
  "aspect_ratio": "{canvas_ratio}",
  "characters": [
    {{"name": "角色名", "gender": "性别", "age": "年龄感", "voice_traits": "音色核心特质"}}
  ],
  "scenes": [
    {{"name": "场景名", "description": "描述", "time": "时间", "interior_exterior": "内/外"}}
  ],
  "props": [
    {{"name": "道具名", "scene": "所属场景", "note": "说明"}}
  ],
  "video_units": [
    {{
      "unit_number": 1,
      "prompt_title": "{episode}-01",
      "duration_seconds": 8,
      "shots": ["镜1", "镜2"],
      "reference_materials": ["@角色A", "@场景B"],
      "style_base": "基础风格描述",
      "style_scene_specific": "场景特定风格描述",
      "video_content": "完整视频内容叙事段落",
      "video_constraints": "约束内容",
      "full_prompt": "完整的提示词文本（含所有段落）"
    }}
  ],
  "shot_script_details": [
    {{
      "unit_number": 1,
      "shot_number": "镜1",
      "script_excerpt": "剧本原文",
      "shot_type": "景别",
      "angle": "视角",
      "movement": "运镜",
      "composition": "构图",
      "lighting": "光影",
      "performance": "表演与动作",
      "dialogue": "台词",
      "sound_effect": "音效",
      "continuity_check": "连贯性检查"
    }}
  ],
  "merge_table": [
    {{"unit": "视频单元1", "shot": "镜1", "script": "剧本原文"}}
  ],
  "total_units": 0,
  "total_duration": ""
}}
```
"""

    system_prompt = ""

    async def run(
        self,
        user_input: str,
        params: Optional[Dict[str, Any]] = None,
        global_params: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> SkillOutput:
        merged = self.merge_params(params)
        system_prompt = self._build_system_prompt(merged)
        system_prompt = self._render_global_params(system_prompt, global_params)

        episode = str(merged.get("集数编号", "第1集"))
        style = str(merged.get("视频画风", "真人写实"))
        aspect = str(merged.get("画幅比例", "9:16竖屏"))

        user_content = f"""\
剧本原文：
{user_input}

请按照三阶段流程执行：
1. 剧本分析 → 输出角色音色清单、场景道具清单
2. 分镜拆解 + 智能合并 → 输出合并后分镜详情
3. 逐镜头设计分镜脚本 → 生成 Seedance 2.0 视频提示词

集数：{episode}
画风：{style}
画幅：{aspect}

请直接输出完整的 JSON 结果。
"""

        # 注入多轮对话历史上下文
        result = await llm_json(
            system_prompt,
            user_content,
    model=self._llm_model,
            history=history,
            max_tokens=16384,
            temperature=0.4,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "episode": episode,
                "style": style,
                "aspect_ratio": aspect,
                "characters": [],
                "scenes": [],
                "props": [],
                "video_units": [],
                "shot_script_details": [],
                "merge_table": [],
                "total_units": 0,
                "total_duration": "",
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

        episode = result.get("episode", "")
        style = result.get("style", "")
        aspect = result.get("aspect_ratio", "")

        parts.append(f"# {episode} 视频提示词架构\n")

        # 基本信息
        info_parts = []
        if style:
            info_parts.append(f"画风：{style}")
        if aspect:
            info_parts.append(f"画幅：{aspect}")
        total_units = result.get("total_units", 0)
        if total_units:
            info_parts.append(f"视频单元：{total_units}个")
        total_duration = result.get("total_duration", "")
        if total_duration:
            info_parts.append(f"总时长：{total_duration}")
        if info_parts:
            parts.append("## 基本信息\n")
            parts.append(" | ".join(info_parts) + "\n")

        # 角色音色清单
        characters = result.get("characters", [])
        if characters:
            parts.append("## 角色与音色清单\n")
            parts.append("| 角色名 | 性别 | 年龄感 | 音色核心特质 |\n")
            parts.append("|--------|------|--------|-------------|\n")
            for ch in characters:
                parts.append(f"| {ch.get('name', '')} | {ch.get('gender', '')} | "
                             f"{ch.get('age', '')} | {ch.get('voice_traits', '')} |\n")
            parts.append("\n")

        # 场景清单
        scenes = result.get("scenes", [])
        if scenes:
            parts.append("## 场景清单\n")
            parts.append("| 场景 | 描述 | 时间 | 内/外 |\n")
            parts.append("|------|------|------|-------|\n")
            for sc in scenes:
                parts.append(f"| {sc.get('name', '')} | {sc.get('description', '')} | "
                             f"{sc.get('time', '')} | {sc.get('interior_exterior', '')} |\n")
            parts.append("\n")

        # 道具清单
        props = result.get("props", [])
        if props:
            parts.append("## 道具清单\n")
            parts.append("| 道具 | 所属场景 | 说明 |\n")
            parts.append("|------|----------|------|\n")
            for pr in props:
                parts.append(f"| {pr.get('name', '')} | {pr.get('scene', '')} | "
                             f"{pr.get('note', '')} |\n")
            parts.append("\n")

        # 合并后分镜详情
        merge_table = result.get("merge_table", [])
        if merge_table:
            parts.append("## 合并后分镜详情\n")
            parts.append("| 视频单元 | 分镜号 | 剧本原文 |\n")
            parts.append("|---------|--------|----------|\n")
            for row in merge_table:
                parts.append(f"| {row.get('unit', '')} | {row.get('shot', '')} | "
                             f"{row.get('script', '')} |\n")
            parts.append("\n")

        # 分镜脚本设计
        shot_details = result.get("shot_script_details", [])
        if shot_details:
            parts.append("## 详细分镜脚本\n")
            for shot in shot_details:
                parts.append(f"### {shot.get('unit_number', '')}·{shot.get('shot_number', '')}"
                             f"（{shot.get('shot_type', '')}）\n")
                parts.append(f"- 剧本原文：{shot.get('script_excerpt', '')}\n")
                parts.append(f"- 景别：{shot.get('shot_type', '')}\n")
                parts.append(f"- 视角：{shot.get('angle', '')}\n")
                parts.append(f"- 运镜：{shot.get('movement', '')}\n")
                parts.append(f"- 构图：{shot.get('composition', '')}\n")
                parts.append(f"- 光影：{shot.get('lighting', '')}\n")
                parts.append(f"- 表演与动作：{shot.get('performance', '')}\n")
                parts.append(f"- 台词：{shot.get('dialogue', '')}\n")
                parts.append(f"- 音效：{shot.get('sound_effect', '')}\n")
                parts.append(f"- 连贯性检查：{shot.get('continuity_check', '')}\n\n")

        # 视频提示词
        video_units = result.get("video_units", [])
        if video_units:
            parts.append(f"# {episode} 视频提示词\n")
            parts.append(f"> 本集概况：共 {len(video_units)} 个视频单元\n\n")
            for unit in video_units:
                parts.append(f"## {unit.get('prompt_title', '')} | "
                             f"{unit.get('duration_seconds', '')}s\n\n")
                full_prompt = unit.get("full_prompt", "")
                if full_prompt:
                    parts.append(f"```\n{full_prompt}\n```\n\n")
                else:
                    # 逐步拼接
                    parts.append("【参考素材】\n")
                    for ref in unit.get("reference_materials", []):
                        parts.append(f"{ref}；\n")
                    parts.append("\n【视频风格】\n")
                    parts.append(f"{unit.get('style_base', '')}\n")
                    style_scene = unit.get("style_scene_specific", "")
                    if style_scene:
                        parts.append(f"{style_scene}\n")
                    parts.append("\n【视频内容】\n")
                    parts.append(f"{unit.get('video_content', '')}\n")
                    parts.append("\n视频约束：\n")
                    parts.append(f"{unit.get('video_constraints', '')}\n\n")
                parts.append("---\n\n")

        return "".join(parts)
