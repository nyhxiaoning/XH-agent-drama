"""
Skill: drama-generator-pro
AI漫剧全流程一键生成技能。将小说内容转化为AI动漫短剧制作所需的全套素材，
包括专业剧本、人物设定、场景设定、分镜脚本、以及最终Excel表格输出。

基于 skill技能/drama-generator-pro-1.0.0/SKILL.md 实现。
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam
from app.utils.excel_generator import generate_excel_from_skill_data

logger = logging.getLogger(__name__)

# 可选动漫风格列表
ANIME_STYLES = [
    "美式卡通", "2D古风", "3D古风", "韩漫二次元", "现代都市", "3D卡通",
    "日漫二次元", "中国工笔画", "写实风格", "彩色水墨", "厚涂古风",
    "吉卜力", "赛博朋克", "胶片质感",
]

ADAPTATION_LEVELS = ["忠实原著", "适度改编", "创意改编"]


class DramaGeneratorProSkill(BaseSkill):
    info = SkillInfo(
        skill_id="drama-generator-pro",
        skill_name="AI漫剧全流程生成",
        tags=["漫剧", "小说改编", "分镜脚本", "人物设定", "场景设计", "Excel表格", "AI短剧"],
        supported_outputs=["剧本", "人物信息表", "场景信息表", "分镜信息表", "Excel文件", "三视图提示词"],
        version="1.0.0",
        category="漫剧制作类",
        params=[
            SkillParam("小说内容", "text", required=True, description="小说原文或章节片段"),
            SkillParam("动漫风格", "select", options=ANIME_STYLES, default="现代都市", description="选择动漫的视觉风格"),
            SkillParam("改编程度", "select", options=ADAPTATION_LEVELS, default="适度改编", description="对原著的改编程度"),
        ],
    )

    system_prompt = """\
# Role
你是AI漫剧全流程生成专家，将小说内容一站式转化为AI动漫短剧制作所需的完整素材包。

## 输入
- 小说内容：完整原文或章节片段
- 动漫风格：从风格列表中选择
- 改编程度：忠实原著 / 适度改编 / 创意改编

## 全流程总览
小说输入 → 阶段1：小说转剧本 → 阶段2：剧本处理（自查→大纲→分场大纲→分场剧本）
→ 阶段3A：人物信息处理 + 阶段3B：场景信息处理
→ 阶段4：分镜脚本生成（拆分+首帧/尾帧/视频提示词）
→ 阶段5：汇总输出

## 阶段1：小说转剧本
以剧本改编专家身份执行：
1. 完整阅读小说，理解情节、人物、场景
2. 提取关键元素：场景、人物、对话、动作描述、时间地点
3. 去除文学性描述，专注可拍摄内容
4. 保留所有关键情节，对白精炼且符合人物性格
5. 适当添加拍摄指示

## 阶段2：剧本处理
### 2.1 剧本自查
- 开头15秒有钩子（悬念/反常识/冲突）
- 总时长约90-120秒/集
- 结尾有卡点
- 场景描述视觉化
- 对白自然简短

### 2.2 剧本大纲
选择合适叙事结构（费希特曲线、拯救猫咪、英雄之旅、三幕式、起承转结）

### 2.3 分场大纲
每集60-80秒，从第1集开始。

### 2.4 分场剧本格式
- 场景题头：`场号 场景名 [内/外] [日/夜]`（加粗）
- 出场人物：每集最前面列出
- 画面/动作：以"△"开头，严禁心理描写
- 对白：`**角色名**：(情绪/动作提示) 台词内容`
- 音效/字幕：`【音效】`、`【字幕】`标注
- 画外音：`(O.S.)`，内心独白：`(V.O.)`

## 阶段3A：人物信息处理
### 3A.1 人物信息提取
为每个角色提取：姓名/称呼、性别、年龄段、社会身份、性格标签(3-5个)、与主角关系、反差点、记忆点

### 3A.2 人物小传（150-200字）
多写"别人能看到的东西"（日常行为、说话方式、穿着），少写纯心理描写，突出反差点

### 3A.3 人物视觉关键词提炼
从5个维度提炼并合理夸张：
1. 外在条件：身高、体型、年龄感
2. 头部五官：发型发色、脸型、眼睛（重点）、特殊特征
3. 服装配饰：上装/下装/鞋，必须有1-2个标志性配饰
4. 色彩语言：主色调1-2个，辅助色1-2个
5. 表情姿态：标志性表情 + 标志性动作

### 3A.4 三视图提示词
框架：【画风与风格定位】+【性别年龄职业】+【身材比例】+【脸型五官】+【发型发色】+【服装配饰】+【表情气质】+【姿态】+【画面规格】
画面规格：全身三视图+面部特写，左1/3面部特写，右2/3正/侧/后视图，纯白背景，21:9横向，高精细线稿上色，无道具无他人无文字

人物按戏份排序：主角→主要配角→次要配角→功能性角色→龙套

## 阶段3B：场景信息处理
### 3B.1 场景提取
从分场剧本提取所有场景：场景编号(S001起)、场景名称、时间、空间(内/外)、出现集数、场景描述
相同场景去重，日/夜版本分别记录

### 3B.2 场景提示词
框架：【空间类型】+【时代与风格】+【主要结构与物件】+【光线与时间】+【氛围与情绪】+【是否有角色】+【画面规格】
画面规格：21:9宽幅，空镜头（无人），高精细度，8K

## 阶段4：分镜脚本生成
以20年资历的影视导演及分镜设计师身份执行。

### 4.1 8条核心切镜原则
1. 情绪转变需切镜
2. 复杂动作需切镜（准备→执行→结果）
3. 人物变化需切镜
4. 空间转场需切镜
5. 时间跳跃需切镜
6. 对话视线乒乓（说话者↔聆听者）
7. 摄影机变化需切镜
8. 视觉特效独占镜头

### 4.2 分镜表格规范
每个镜头包含：镜号、时长(1-10秒)、景别、摄法、画面内容(≥50字)、台词/音效、入镜角色、场景标识

### 4.3 画面内容8大要素
自然语言融合：视觉风格、环境设定、人物布局、动作描述、情绪与表演、光影与色调、镜头构图、特效/备注

### 4.4 首帧/尾帧提示词
框架：(主体描述)+(环境场景)+(艺术风格)+(光影与色彩)+(构图与视角)+(质量修饰词)
强调内容用()包裹，可多层嵌套

### 4.5 图生视频提示词
框架：[主体描述]+[动作描述]+[运镜描述]+[环境氛围描述]

## 重要约束
- 所有提示词必须使用中文撰写
- 动漫风格需贯穿所有输出

## 输出 JSON 结构
请严格输出以下 JSON 结构：

{
  "skill_id": "drama-generator-pro",
  "skill_name": "AI漫剧全流程生成",
  "work_title": "作品名（从原文提取或概括）",
  "anime_style": "动漫风格",
  "adaptation_level": "改编程度",
  "summary": "一句话摘要，≤50字",
  "script": "阶段1-2完整剧本的 Markdown 内容",
  "characters": [
    {
      "id": "C01",
      "name": "角色名",
      "info": "人物信息提取（性别、年龄段、社会身份、性格标签、与主角关系、反差点、记忆点）",
      "bio": "人物小传（150-200字）",
      "prompt": "三视图提示词（中文，21:9宽幅）"
    }
  ],
  "scenes": [
    {
      "id": "S001",
      "name": "场景名称",
      "prompt": "场景提示词（中文，21:9宽幅，空镜头无人）"
    }
  ],
  "storyboards": [
    {
      "episode": 1,
      "scene": 1,
      "shot": 1,
      "duration": "3s",
      "shot_size": "中景",
      "camera": "固定",
      "content": "画面内容（≥50字，融合8大要素）",
      "dialogue": "台词/音效",
      "characters": "角色A，角色B",
      "scene_label": "场景名称",
      "first_frame": "首帧提示词（中文）",
      "last_frame": "尾帧提示词（中文）",
      "video_prompt": "视频提示词（中文）"
    }
  ]
}

## 约束
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字
- 所有提示词必须使用中文
- 人物按戏份从多到少排序
- 场景相同去重，日/夜分别记录
- 每个镜头时长1-10秒
- 画面内容≥50字且包含8大要素
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

        anime_style = str(merged.get("动漫风格", "现代都市"))
        adaptation_level = str(merged.get("改编程度", "适度改编"))

        user_content = f"""\
小说内容：
{user_input}

动漫风格：{anime_style}
改编程度：{adaptation_level}
""".strip()

        # 注入多轮对话历史上下文
        result = await llm_json(
            system_prompt,
            user_content,
    model=self._llm_model,
            history=history,
            max_tokens=16384,
            temperature=0.4,
            max_retries=4,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "work_title": "",
                "anime_style": anime_style,
                "adaptation_level": adaptation_level,
                "summary": "",
                "script": "",
                "characters": [],
                "scenes": [],
                "storyboards": [],
                "_error": "LLM 调用失败，请稍后重试",
            },
        )

        is_fallback = result.get("_is_fallback", False)

        # 后端拼接 full_markdown
        if not is_fallback:
            result["full_markdown"] = self._build_full_markdown(result)

            # 尝试生成 Excel 文件
            try:
                excel_info = self._generate_excel(result)
                if excel_info:
                    result["excel_info"] = excel_info
            except Exception as exc:
                logger.warning("[DramaGeneratorPro] Excel 生成失败: %s", exc, exc_info=True)
                result["excel_error"] = str(exc)

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

        # 标题与摘要
        title = result.get("work_title", "")
        if title:
            parts.append(f"# {title}\n")
        summary = result.get("summary", "")
        if summary:
            parts.append(f"> {summary}\n")
        style = result.get("anime_style", "")
        level = result.get("adaptation_level", "")
        if style or level:
            parts.append(f"**动漫风格**：{style} | **改编程度**：{level}\n")

        # 剧本
        script = result.get("script", "")
        if script:
            parts.append("---\n\n## 剧本\n")
            parts.append(script)
            parts.append("")

        # 人物信息表
        characters = result.get("characters", [])
        if characters:
            parts.append("## 人物信息表\n")
            parts.append("| 编号 | 姓名 | 人物信息 | 人物小传 | 三视图提示词 |")
            parts.append("|------|------|----------|----------|-------------|")
            for c in characters:
                parts.append(
                    f"| {c.get('id', '')} | {c.get('name', '')} | "
                    f"{c.get('info', '')[:80]}... | "
                    f"{c.get('bio', '')[:80]}... | "
                    f"{c.get('prompt', '')[:60]}... |"
                )
            parts.append("")

        # 场景信息表
        scenes = result.get("scenes", [])
        if scenes:
            parts.append("## 场景信息表\n")
            parts.append("| 编号 | 场景名称 | 场景提示词 |")
            parts.append("|------|----------|-----------|")
            for s in scenes:
                parts.append(
                    f"| {s.get('id', '')} | {s.get('name', '')} | "
                    f"{s.get('prompt', '')[:80]}... |"
                )
            parts.append("")

        # 分镜信息表
        storyboards = result.get("storyboards", [])
        if storyboards:
            parts.append("## 分镜信息表\n")
            parts.append(
                "| 集号 | 场号 | 镜号 | 时长 | 景别 | 摄法 | "
                "画面内容 | 台词/音效 | 入镜角色 | 场景标识 |"
            )
            parts.append(
                "|------|------|------|------|------|------|"
                "----------|----------|----------|----------|"
            )
            for s in storyboards:
                content = s.get("content", "")
                if len(content) > 60:
                    content = content[:60] + "..."
                parts.append(
                    f"| {s.get('episode', '')} | {s.get('scene', '')} | "
                    f"{s.get('shot', '')} | {s.get('duration', '')} | "
                    f"{s.get('shot_size', '')} | {s.get('camera', '')} | "
                    f"{content} | {s.get('dialogue', '')} | "
                    f"{s.get('characters', '')} | {s.get('scene_label', '')} |"
                )
            parts.append("")

        return "\n".join(parts)

    @staticmethod
    def _generate_excel(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """调用 Excel 生成工具，返回文件路径信息。"""
        characters = result.get("characters", [])
        scenes = result.get("scenes", [])
        storyboards = result.get("storyboards", [])
        if not characters and not scenes and not storyboards:
            return None

        project_name = result.get("work_title", f"漫剧_{int(time.time())}")
        output_dir = os.path.join("uploads", "generated")
        os.makedirs(output_dir, exist_ok=True)

        return generate_excel_from_skill_data(
            characters=characters,
            scenes=scenes,
            storyboards=storyboards,
            output_dir=output_dir,
            project_name=project_name,
        )
