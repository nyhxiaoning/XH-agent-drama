"""
Skill: novel-director
AI互动小说创作工具 - 导演板模式 v2.0.0（支持长篇连载）。
用户作为导演设定场景、人物、目标，AI作为演员分镜演绎，在关键节点停下请示。
支持长篇小说上下文管理、智能检索、跨Session续写。

基于 skill技能/novel-director-2.0.0/SKILL.md 实现。
模板文件位于 backend/app/data/prompts/novel_director_templates/。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


# ─── 模板文件加载 ────────────────────────────────────────
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "prompts" / "novel_director_templates"


def _load_template(filename: str) -> str:
    """加载模板文件内容，若文件不存在则返回空字符串。"""
    filepath = _TEMPLATE_DIR / filename
    try:
        return filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


_WORLD_KNOWLEDGE_TEMPLATE = _load_template("world_knowledge.json")
_CHAPTER_INDEX_TEMPLATE = _load_template("chapter_index.json")


# ─── 参数选项 ────────────────────────────────────────────
GENRE_OPTIONS = [
    "悬疑推理", "都市言情", "古风宫斗", "青春校园",
    "科幻未来", "武侠江湖", "奇幻玄幻", "恐怖惊悚",
    "喜剧幽默", "黑色幽默", "战争军事", "历史传记",
]

NARRATIVE_MODE_OPTIONS = [
    "导演板模式（回合制互动演绎）",
    "一口气模式（AI连续演绎完整章节）",
]


class NovelDirectorSkill(BaseSkill):
    info = SkillInfo(
        skill_id="novel-director",
        skill_name="AI互动小说导演板",
        tags=["小说创作", "互动叙事", "导演板", "分镜演绎", "长篇连载", "决策点"],
        supported_outputs=[
            "小说章节", "角色档案", "世界知识库", "章节索引",
            "决策点选项", "完整Markdown",
        ],
        version="2.0.0",
        category="小说创作类",
        params=[
            SkillParam("小说标题", "text", required=True, description="小说的标题"),
            SkillParam("类型题材", "select", options=GENRE_OPTIONS, default="悬疑推理",
                       description="小说的类型或题材方向"),
            SkillParam("预计章节数", "text", default="10章",
                       description="预计完成的总章节数"),
            SkillParam("主角设定", "text", required=True,
                       description="主角姓名和背景简介，如：陈明，前刑警，女儿失踪"),
            SkillParam("叙事模式", "select", options=NARRATIVE_MODE_OPTIONS,
                       default="导演板模式（回合制互动演绎）",
                       description="导演板模式为回合制（AI演绎一段后停下等用户选择），一口气模式为AI连续演绎完整章节"),
        ],
    )

    system_prompt = f"""\
# Novel Director - AI互动小说导演板 v2.0.0

## 概述

Novel Director 是一个**分镜推进式**的AI互动小说创作工具。

- **你是导演**：设定场景、人物、目标、氛围
- **AI是演员**：根据你的设定分镜演绎，在关键节点停下请示
- **你掌控走向**：在每个决策点做出选择，决定剧情方向
- **长篇连载**：智能上下文管理，支持跨Session续写

---

## 长篇小说上下文管理

### 三层架构

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: 世界知识库 (world_knowledge.json)               │
│  - 世界观设定、角色档案、关键事件时间线                    │
│  - 核心设定，长期不变                                      │
├─────────────────────────────────────────────────────────┤
│  Layer 2: 章节索引 (chapter_index.json)                   │
│  - 每章的元数据：标题、摘要、关键词、角色出场              │
│  - 快速检索，无需读取全文                                  │
├─────────────────────────────────────────────────────────┤
│  Layer 1: 工作上下文 (Working Context)                    │
│  - 当前章节原文（最近1-2章）                               │
│  - 当前场景的创作草稿                                      │
└─────────────────────────────────────────────────────────┘
```

### 世界知识库模板
```json
{_WORLD_KNOWLEDGE_TEMPLATE}
```

### 章节索引模板
```json
{_CHAPTER_INDEX_TEMPLATE}
```

---

## 核心工作流程

### 回合制循环

```
【导演指令】→ AI演绎一段 → 【决策点】→ 用户选择 → AI继续演绎 → 【决策点】...
```

### 每回合步骤

**Step 1: 导演指令（用户）**

用户提供标准化的场景设定：

```
【场景】场景描述（时间、地点、环境）
【人物A】姓名 + 性格特点 + 当前目标
【人物B】姓名 + 性格特点 + 当前目标
【冲突】核心矛盾或张力来源
【氛围】整体基调（悬疑、温情、黑色幽默等）
```

**Step 2: AI演绎**

AI根据导演指令演绎**一个分镜**（200-400字），推进剧情到下一个**决策点**。

**Step 3: 决策点**

AI在以下情况停下，标记【决策点 ⏸️】：
- 信息揭示后（重要线索/秘密刚刚揭露）
- 冲突升级前（情势即将转折）
- 人物反应点（某个角色需要做出回应）
- 路径分叉点（剧情可以往多个方向走）

**Step 4: 用户选择**

用户提供选择，可以是：
- 选A/B/C（预设选项）
- 自由输入（"让主角..."）
- 导演指令（"重来"、"改戏"等）

---

## 导演控制台

### 基础指令

| 指令 | 作用 |
|------|------|
| **"重来"** | 回到上一个决策点，重新选择 |
| **"改戏"** | 修改刚刚演绎的片段 |
| **"加人"** | 增加新角色进入场景 |
| **"换景"** | 切换到另一个并行场景 |
| **"快进到..."** | 跳过当前场景，直接到某个结果 |
| **"幕后"** | 查看当前场景的人物状态、隐藏信息 |
| **"这场戏过了"** | 结束当前场景，输出成片 |

### 长篇连载专用指令

| 指令 | 作用 |
|------|------|
| **"新建小说"** | 创建新小说项目，初始化知识库和索引 |
| **"继续写 [小说名]"** | 加载已有小说，恢复创作状态 |
| **"保存"** | 保存当前进度到文件 |
| **"导出"** | 导出完整小说为 Markdown 文件 |
| **"角色档案"** | 查看/编辑角色信息 |
| **"时间线"** | 查看故事时间线 |
| **"查找 [关键词]"** | 检索相关内容所在的章节 |
| **"上一章"** | 回顾上一章内容 |
| **"大纲"** | 查看/编辑小说大纲 |
| **"完成本章"** | 标记当前章节完成，更新索引 |

---

## 演绎规则

### 分镜长度控制
- 每段演绎控制在 **200-400字**
- 刚好一个戏剧单元的量
- 不要一次写完整个场景

### 决策点标记格式

```
【决策点 ⏸️】

这里发生了什么：
- 关键信息1
- 关键信息2

请选择：

A. 选项A描述
B. 选项B描述
C. 选项C描述
D. 【自由输入】你想怎么做？
```

### 演绎风格指南
- **小说化叙述**：使用第三人称，有环境描写、动作描写、对话
- **留白**：不要把所有信息都说完，给导演留决策空间
- **悬念**：在决策点处制造合理的悬念
- **人物一致性**：保持已设定的人物性格和目标

---

## 成片输出

当用户说"这场戏过了"或"完成本章"，AI将：
1. 整合所有分镜和选择，润色成完整章节
2. 保存到章节文件
3. **自动生成摘要**，更新章节索引
4. 更新角色状态到世界知识库

输出格式：
```
【章节标题】

（完整小说文本，融合所有选择）

---
字数：XXXX
关键事件：[事件1, 事件2]
```

---

## 输出 JSON 格式要求

你必须输出以下 JSON 结构：

```json
{{
  "skill_id": "novel-director",
  "skill_name": "AI互动小说导演板",
  "title": "小说标题",
  "genre": "类型题材",
  "total_chapters": 10,
  "current_chapter": 1,
  "narrative_mode": "导演板模式",
  "chapter_title": "当前章节标题",
  "chapter_content": "本章完整的小说文本内容",
  "word_count": 0,
  "characters": [
    {{
      "id": "char_001",
      "name": "角色姓名",
      "role": "主角/配角/反派",
      "traits": ["性格特点1", "性格特点2"],
      "background": "背景故事",
      "current_status": "当前状态"
    }}
  ],
  "decision_points": [
    {{
      "scene": "当前场景描述",
      "context": "决策点上下文信息",
      "options": [
        {{"id": "A", "description": "选项A描述"}},
        {{"id": "B", "description": "选项B描述"}},
        {{"id": "C", "description": "选项C描述"}}
      ]
    }}
  ],
  "world_knowledge": {{
    "metadata": {{
      "title": "小说标题",
      "genre": "类型",
      "total_chapters": 0,
      "current_chapter": 1
    }},
    "characters": [],
    "timeline": [],
    "locations": [],
    "mysteries": [],
    "themes": []
  }},
  "chapter_index": {{
    "chapters": [],
    "search_index": {{}},
    "character_appearances": {{}}
  }},
  "key_events": ["关键事件1", "关键事件2"],
  "cliffhanger": "悬念结尾（如有）",
  "status": "drafting"
}}
```

- `status` 可选值：`"drafting"`（创作中）、`"chapter_complete"`（章节完成）、`"novel_complete"`（全书完成）
- `chapter_content` 为当前演绎的完整文本（含分镜、对话、决策点标记）
- `decision_points` 为本章出现的所有决策点列表
- `world_knowledge` 为更新后的世界知识库
- `chapter_index` 为更新后的章节索引
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

        title = str(merged.get("小说标题", "未命名"))
        genre = str(merged.get("类型题材", "悬疑推理"))
        chapters_str = str(merged.get("预计章节数", "10章"))
        protagonist = str(merged.get("主角设定", ""))
        narrative_mode = str(merged.get("叙事模式", "导演板模式（回合制互动演绎）"))

        try:
            total_chapters = int("".join(filter(str.isdigit, chapters_str)))
        except ValueError:
            total_chapters = 10

        # 判断是否为一口气模式
        is_continuous = "一口气" in narrative_mode

        mode_instruction = (
            "请一次性演绎完整章节（1500-3000字），不需要在决策点停下。"
            if is_continuous else
            "请演绎一个分镜（200-400字），推进剧情到决策点后停下，给出选项。"
        )

        user_content = f"""\
小说标题：{title}
类型题材：{genre}
预计章节数：{total_chapters}章
主角设定：{protagonist}
叙事模式：{narrative_mode}

用户导演指令：
{user_input}

{mode_instruction}

请输出完整的 JSON 结果，包含章节内容、角色档案、世界知识库和章节索引。
如果是首轮对话，请初始化 world_knowledge 和 chapter_index。
"""

        # 注入多轮对话历史上下文
        result = await llm_json(
            system_prompt,
            user_content,
    model=self._llm_model,
            history=history,
            max_tokens=16384,
            temperature=0.7,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "title": title,
                "genre": genre,
                "total_chapters": total_chapters,
                "current_chapter": 1,
                "narrative_mode": narrative_mode,
                "chapter_title": "",
                "chapter_content": "",
                "word_count": 0,
                "characters": [],
                "decision_points": [],
                "world_knowledge": json.loads(_WORLD_KNOWLEDGE_TEMPLATE) if _WORLD_KNOWLEDGE_TEMPLATE else {},
                "chapter_index": json.loads(_CHAPTER_INDEX_TEMPLATE) if _CHAPTER_INDEX_TEMPLATE else {},
                "key_events": [],
                "cliffhanger": "",
                "status": "drafting",
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

        title = result.get("title", "未命名")
        genre = result.get("genre", "")
        chapter_title = result.get("chapter_title", "")
        current_chapter = result.get("current_chapter", 1)

        parts.append(f"# 《{title}》\n")

        if genre:
            parts.append(f"**类型**：{genre}\n")

        # 章节内容
        chapter_content = result.get("chapter_content", "")
        if chapter_content:
            parts.append(f"\n## 第{current_chapter}章 {chapter_title}\n\n")
            parts.append(chapter_content)
            parts.append("\n")

            word_count = result.get("word_count", 0)
            if word_count:
                parts.append(f"\n---\n字数：{word_count}\n")

            key_events = result.get("key_events", [])
            if key_events:
                parts.append(f"关键事件：{', '.join(key_events)}\n")

            cliffhanger = result.get("cliffhanger", "")
            if cliffhanger:
                parts.append(f"悬念：{cliffhanger}\n")

        # 决策点
        decision_points = result.get("decision_points", [])
        if decision_points:
            parts.append("\n## 决策点记录\n")
            for i, dp in enumerate(decision_points, 1):
                parts.append(f"### 决策点 {i}\n")
                scene = dp.get("scene", "")
                if scene:
                    parts.append(f"**场景**：{scene}\n\n")
                context = dp.get("context", "")
                if context:
                    parts.append(f"{context}\n\n")
                options = dp.get("options", [])
                if options:
                    for opt in options:
                        parts.append(f"**{opt.get('id', '')}**. {opt.get('description', '')}\n")
                    parts.append("\n")

        # 角色档案
        characters = result.get("characters", [])
        if characters:
            parts.append("\n## 角色档案\n")
            for ch in characters:
                parts.append(f"### {ch.get('name', '')}\n")
                parts.append(f"- **角色定位**：{ch.get('role', '')}\n")
                traits = ch.get("traits", [])
                if traits:
                    parts.append(f"- **性格特点**：{', '.join(traits)}\n")
                parts.append(f"- **背景**：{ch.get('background', '')}\n")
                parts.append(f"- **当前状态**：{ch.get('current_status', '')}\n\n")

        # 世界知识库
        world_knowledge = result.get("world_knowledge", {})
        if world_knowledge:
            parts.append("\n## 世界知识库\n")
            parts.append("```json\n")
            parts.append(json.dumps(world_knowledge, ensure_ascii=False, indent=2))
            parts.append("\n```\n")

        # 章节索引
        chapter_index = result.get("chapter_index", {})
        if chapter_index:
            parts.append("\n## 章节索引\n")
            parts.append("```json\n")
            parts.append(json.dumps(chapter_index, ensure_ascii=False, indent=2))
            parts.append("\n```\n")

        return "".join(parts)
