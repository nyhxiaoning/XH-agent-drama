"""
Skill: storyboard-director
分镜导演台本生成。将用户的故事/小说/剧本文本，自动拆解为专业的多宫格分镜故事板
和视频提示词。内部集成镜头语言词典（情绪基底 A–G + 类型叠加 H）、多宫格布局计算器、
风险库、画风预设库和黄金范例，实现一站式分镜导演输出。

基于 skill技能/references/ 下的 6 个参考文件实现：
  - shot-language-index.md   (常驻路由索引)
  - shot-language-detail.md  (按需明细库)
  - layout-calculator.md     (多宫格布局计算器)
  - risk-library.md          (逐帧风险注入库)
  - style-presets.md         (画风预设库)
  - golden-example.md        (完整格式范例)
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


# ─── 参考文件加载 ────────────────────────────────────────
_REF_DIR = Path(__file__).resolve().parent.parent / "data" / "prompts" / "storyboard_refs"


def _load_ref(filename: str) -> str:
    """加载参考文件内容，若文件不存在则返回空字符串。"""
    filepath = _REF_DIR / filename
    try:
        return filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# 预加载常驻文件
_SHOT_LANGUAGE_INDEX = _load_ref("shot-language-index.md")
_LAYOUT_CALCULATOR = _load_ref("layout-calculator.md")
_RISK_LIBRARY = _load_ref("risk-library.md")
_STYLE_PRESETS = _load_ref("style-presets.md")
_GOLDEN_EXAMPLE = _load_ref("golden-example.md")
_SHOT_LANGUAGE_DETAIL = _load_ref("shot-language-detail.md")


# ─── 参数选项 ────────────────────────────────────────────
STYLE_OPTIONS = [
    "写实", "电影质感现实主义", "王家卫风格", "纪录片/手持写实",
    "古风写实", "古风唯美", "古朴水墨",
    "现代都市写实", "赛博朋克", "轻奢/商业时尚",
    "胶片复古", "黑色电影Noir", "吉卜力动画", "恐怖/惊悚",
    "港式武侠动作", "现代动作/警匪枪战", "飙车/赛车片",
    "动画", "3D", "水墨国风",
]

ASPECT_OPTIONS = ["9:16竖屏", "16:9横屏", "1:1方形"]

SHOT_LIMIT_OPTIONS = ["20镜", "30镜", "50镜", "80镜", "不限"]

PLATFORM_OPTIONS = ["抖音", "快手", "B站", "小红书", "YouTube"]


class StoryboardDirectorSkill(BaseSkill):
    info = SkillInfo(
        skill_id="storyboard-director",
        skill_name="分镜导演台本",
        tags=["分镜", "导演台本", "镜头语言", "多宫格", "视频提示词", "风险注入"],
        supported_outputs=["分镜脚本设计表", "多宫格分镜故事板提示词", "视频提示词"],
        version="1.0.0",
        category="分镜制作类",
        params=[
            SkillParam("故事文本", "text", required=True, description="故事/小说/剧本片段文本"),
            SkillParam("风格", "select", options=STYLE_OPTIONS, default="写实"),
            SkillParam("画幅", "select", options=ASPECT_OPTIONS, default="9:16竖屏"),
            SkillParam("镜头数限制", "select", options=SHOT_LIMIT_OPTIONS, default="30镜"),
            SkillParam("目标平台", "select", options=PLATFORM_OPTIONS, default="抖音"),
        ],
    )

    # system_prompt 在运行时动态构建（需嵌入参考文件内容）
    # 这里提供一个基础模板，run() 方法中会拼接完整版
    system_prompt = ""

    def _build_system_prompt(self, merged: Dict[str, Any]) -> str:
        """构建包含所有参考文件知识的完整 system prompt。"""
        style = str(merged.get("风格", "写实"))
        aspect = str(merged.get("画幅", "9:16竖屏"))
        shot_limit_str = str(merged.get("镜头数限制", "30镜"))
        platform = str(merged.get("目标平台", "抖音"))

        # 解析画幅比例
        if "9:16" in aspect:
            canvas_ratio = "9:16"
        elif "16:9" in aspect:
            canvas_ratio = "16:9"
        elif "1:1" in aspect:
            canvas_ratio = "1:1"
        else:
            canvas_ratio = "9:16"

        # 解析镜头数限制
        try:
            shot_limit = int("".join(filter(str.isdigit, shot_limit_str)))
        except ValueError:
            shot_limit = 30
        if "不限" in shot_limit_str:
            shot_limit = 25  # 最大帧数

        # 从画风预设库中查找匹配的画风描述
        style_desc = self._extract_style_desc(style)

        return f"""\
# Role
你是专业分镜导演。将用户提交的故事/小说/剧本文本，拆解为专业的多宫格分镜故事板提示词和视频提示词。
你的输出必须严格遵循下方的镜头语言词典、布局计算器、风险库和黄金范例格式。

## 全局参数
- 视频比例：{canvas_ratio}
- 视频画风（仅用于视频提示词）：{style_desc}
- 镜头数限制：{shot_limit} 帧（帧数范围 2–25）
- 目标平台：{platform}

---

# 硬不变量（绝对不可违反）

1. **帧数范围**：2–25 帧
2. **总时长**：4–15 秒的整数
3. **每帧时长**：0.5 秒的倍数
4. **故事板画风固定**：手绘铅笔草稿、黑白线条、木偶小人构图，不受用户画风影响
5. **`{{STYLE}}` 仅进视频提示词**：用户画风只出现在视频【视频风格】段
6. **两个独立代码块**：分镜故事板提示词和视频提示词分置两个独立代码块
7. **禁止写入文件**：只输出到对话中

---

# STEP 1: 拆帧
读取用户故事文本，按叙事节奏拆分为 2–25 帧。每帧对应一个关键画面。
- 每帧时长 = 0.5 秒的倍数
- 总时长 = 所有帧时长之和，必须是 4–15 秒的整数
- 若帧数超过限制，合并次要帧

# STEP 2: 情绪/类型两轴查询
对每帧执行两轴查询：
- **情绪基底轴（A–G，必选）**：从下方【镜头语言词典·路由索引】中定位条目码
- **类型叠加轴（H，仅动作场景）**：武打/打斗/枪战/飙车场景叠加
- **合成规则**：类型层的景别/机位/运镜/构图作动作骨架，情绪基底的光影/表演/节奏做情绪着色
- **冲突优先级**：动作可读性 > 情绪渲染；局部冲突：焦段 > 景别 > 运镜

# STEP 3: 分镜脚本设计确认表
输出面向用户的分镜设计表，每帧包含：
- 帧号、时长、标注（序号+运镜简写+景别 | 核心内容）
- 镜头语言：景别 / 视角 / 运镜 / 焦段 / 景深
- 环境、光影、构图、表演
- 查询标注（情绪码+类型码）

# STEP 4: 多宫格布局
根据帧数和画幅，从下方【多宫格布局计算器】中查找推荐布局。
非标准帧数取最近的较大标准帧数，用空格占位。

# STEP 5: 逐帧风险注入
对每一帧，根据其镜头码和特征，从下方【风险库】中命中对应行，注入风险约束关键词。
- A库（生图风险）：注入到分镜故事板提示词
- B库（视频风险）：注入到视频提示词
- C库（组合场景）：整段属于成套场景时直接套用

# STEP 6: 字符预算
每帧提示词 ≤ 700 字符。超出则裁剪次要描述。

# STEP 7: 最终输出
输出两个独立代码块：
1. 📐 多宫格信息 + 🎬 多宫格分镜故事板提示词
2. ⏱ 视频时长 + 🎥 视频提示词

---

# 【常驻参考】镜头语言词典·路由索引

{_SHOT_LANGUAGE_INDEX}

---

# 【常驻参考】镜头语言词典·明细模块（按需查阅）

{_SHOT_LANGUAGE_DETAIL}

---

# 【常驻参考】多宫格布局计算器

{_LAYOUT_CALCULATOR}

---

# 【常驻参考】风险库

{_RISK_LIBRARY}

---

# 【常驻参考】画风预设库

{_STYLE_PRESETS}

---

# 【常驻参考】Golden Example（完整格式范例）

{_GOLDEN_EXAMPLE}

---

## 输出 JSON 结构
请严格输出以下 JSON 结构，所有提示词内容放在对应字符串字段中：

{{
  "skill_id": "storyboard-director",
  "skill_name": "分镜导演台本",
  "title": "分镜标题（从故事文本概括）",
  "aspect_ratio": "{canvas_ratio}",
  "total_frames": 6,
  "total_duration": "7秒",
  "layout": "2行×3列",
  "canvas_ratio": "4:5",
  "storyboard_prompt": "多宫格分镜故事板提示词的完整内容（包含全局规则、全局风险约束、分镜板逐帧设计、负面提示）",
  "video_prompt": "视频提示词的完整内容（包含参考图片、核心规则、视频风格、全局风险约束、视频叙事、运动约束、视频负面提示）",
  "shot_design_table": "分镜脚本设计确认表的 Markdown 内容（每帧含帧号、时长、标注、镜头语言、环境、光影、构图、表演、查询标注）",
  "characters": [
    {{"name": "角色名", "voice": "音色描述"}}
  ],
  "scenes": ["场景名"],
  "props": ["道具名"]
}}

## 约束
- 不要输出 XML 包裹标签
- 不要输出内部分析、自查清单
- 故事板画风固定为手绘铅笔草稿/木偶小人，不受用户画风影响
- 用户画风仅出现在视频提示词的【视频风格】段
- 分镜故事板提示词和视频提示词是两个独立代码块
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字
"""

    @staticmethod
    def _extract_style_desc(style_name: str) -> str:
        """从画风预设库中提取匹配的画风描述词。"""
        # 简单匹配：在预设库文本中查找风格名后最近的代码块
        lines = _STYLE_PRESETS.split("\n")
        found = False
        desc_lines: list[str] = []
        for line in lines:
            if found:
                if line.startswith("```"):
                    if desc_lines:
                        break  # 代码块结束
                    continue  # 跳过开头的 ```
                if line.startswith("情绪词") or line.startswith("---") or line.startswith("#"):
                    break
                if line.strip():
                    desc_lines.append(line.strip())
            # 匹配风格名（包含即可）
            if style_name in line and line.strip().startswith("**"):
                found = True
        if desc_lines:
            return "，".join(desc_lines)
        # 默认回退
        return f"{style_name}风格"

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

        user_content = f"""\
故事文本：
{user_input}

请按照 STEP 1–7 流程执行，输出完整的分镜脚本设计表、多宫格分镜故事板提示词和视频提示词。
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
                "title": "",
                "aspect_ratio": merged.get("画幅", "9:16竖屏"),
                "total_frames": 0,
                "total_duration": "",
                "layout": "",
                "canvas_ratio": "",
                "storyboard_prompt": "",
                "video_prompt": "",
                "shot_design_table": "",
                "characters": [],
                "scenes": [],
                "props": [],
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
            parts.append(f"# 《{title}》- 分镜导演台本\n")

        # 基本信息
        aspect = result.get("aspect_ratio", "")
        frames = result.get("total_frames", "")
        duration = result.get("total_duration", "")
        layout = result.get("layout", "")
        canvas = result.get("canvas_ratio", "")
        if any([aspect, frames, duration, layout, canvas]):
            parts.append("## 基本信息\n")
            info_parts = []
            if aspect:
                info_parts.append(f"画幅：{aspect}")
            if frames:
                info_parts.append(f"帧数：{frames}")
            if duration:
                info_parts.append(f"时长：{duration}")
            if layout:
                info_parts.append(f"布局：{layout}")
            if canvas:
                info_parts.append(f"画布比例：{canvas}")
            parts.append(" | ".join(info_parts) + "\n")

        # 角色
        characters = result.get("characters", [])
        if characters:
            parts.append("## 角色圣经\n")
            for c in characters:
                voice = c.get("voice", "")
                parts.append(f"- @{c.get('name', '')}" + (f"（音色：{voice}）" if voice else ""))
            parts.append("")

        # 场景
        scenes = result.get("scenes", [])
        if scenes:
            parts.append("### 场景")
            parts.append(" | ".join(f"@{s}" for s in scenes))
            parts.append("")

        # 道具
        props = result.get("props", [])
        if props:
            parts.append("### 道具")
            parts.append(" | ".join(f"@{p}" for p in props))
            parts.append("")

        # 分镜设计表
        shot_table = result.get("shot_design_table", "")
        if shot_table:
            parts.append("---\n\n## 分镜脚本设计确认表\n")
            parts.append(shot_table)
            parts.append("")

        # 多宫格信息 + 分镜故事板提示词
        storyboard = result.get("storyboard_prompt", "")
        if storyboard:
            parts.append("---\n\n## 📐 多宫格信息\n")
            if frames:
                parts.append(f"- 关键帧：{frames} 个")
            if layout:
                parts.append(f" | 布局：{layout}")
            if canvas:
                parts.append(f" | 画布比例：{canvas}")
            parts.append("\n")
            parts.append("### 🎬 多宫格分镜故事板提示词\n")
            parts.append(f"```text\n{storyboard}\n```")
            parts.append("")

        # 视频时长 + 视频提示词
        video = result.get("video_prompt", "")
        if video:
            parts.append("### ⏱ 视频时长\n")
            parts.append(f"**{duration}**\n")
            parts.append("### 🎥 视频提示词\n")
            parts.append(f"```text\n{video}\n```")
            parts.append("")

        return "\n".join(parts)
