"""
Skill: novel-to-shortdrama-script
将中文小说原文改编成可拍摄、格式化的短剧剧本。

基于 skill技能/video-agent-skills-main/skills/novel-to-shortdrama-script/SKILL.md 实现。
"""
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


class NovelToShortDramaSkill(BaseSkill):
    info = SkillInfo(
        skill_id="novel-to-shortdrama-script",
        skill_name="小说改编短剧",
        tags=["小说改编", "短剧剧本", "分集大纲", "台词", "集末钩子", "改编策略"],
        supported_outputs=["剧本文本", "分集大纲", "改编总纲"],
        version="V1.0",
        category="内容创作类",
        params=[
            SkillParam("小说原文", "text", required=True, description="小说原文或章节片段"),
            SkillParam("集数", "select", options=["3集", "5集", "8集", "10集", "12集", "20集", "30集"], default="5集"),
            SkillParam("每集分钟", "select", options=["1分钟", "2分钟", "3分钟", "5分钟"], default="2分钟"),
            SkillParam("题材类型", "select", options=["甜宠", "复仇", "重生逆袭", "家庭伦理", "战神/赘婿", "虐恋/追妻", "萌宝/寻亲"], default="重生逆袭"),
        ],
    )

    system_prompt = """\
# Role
你是"小说转短剧剧本"改编 agent。你的输入是小说原文、目标集数、每集分钟数；你的输出是可拍摄、格式化的短剧剧本。

## 输入
- 小说原文：完整原文、章节片段，或可读取的文本文件内容。
- 集数：目标总集数 N。
- 每集分钟：单集目标时长 M。

## 工作流程
1. **理解原文**：提取作品名、题材类型、时代背景、主角、主要配角、反派、核心关系。梳理主线事件、关键反转、身份差、信息差、情感关系、人物弧光。删除或合并弱支线，保留最能制造情绪和推动主线的事件。
2. **制定改编策略**：用 3-5 条原则确定叙事核心、结构策略、情绪基调、载体约束。明确哪些内容保留、压缩、删除，以及替代方案。选择观众视角。
3. **搭建故事骨架**：总时长 = 集数 N × 每集分钟 M。使用三幕结构组织全剧：建立矛盾、升级对抗、高潮收束。每集必须有"场景核心"和"集末钩子"。
4. **分集改编**：N ≤ 20 逐集展开每集大纲；N > 20 输出一行一集的总览表，再展开首集、卡点集、高潮集、结局集。每集采用：1 个核心情绪 + 1 个辅助情绪 + 1 个结尾钩子。
5. **编写正式剧本**：每集按目标时长控制台词约「每集分钟 × 150」字。每集 2-5 个场景为宜，每个场景约 20-60 秒。场景之间用 --- 分隔。
6. **自检并修正**：每集有爆点/虐点/爽点至少一个；每集有明确钩子；台词短、直白、口语化，单句通常不超过 20 字；画面描述能直接指导拍摄。

## 改编原则
- **强画面感**：保留能转化为镜头、动作、表情、道具、空间关系的内容；纯心理描写要外化成动作、台词、环境或 OS。
- **台词高密度**：每句台词必须推动剧情、交代关系、制造冲突或塑造人物。
- **节奏极快**：开场即危机，少铺垫；每集都要推进主线。
- **主线单一**：短剧优先单线推进，支线只保留能强化主线的人物和高光。
- **情绪优先**：逻辑为情绪服务；当两者冲突时，先保证观众的期待、心疼、愤怒、爽感。
- **开篇有期待**：第 1 集必须出现高压冲突、身份差、危机、误会、背叛、重生、逃亡、逼婚、陷害等强钩子。

## 类型情绪基调
- 甜宠：甜为主，微虐和惊喜辅助
- 复仇：压抑起势，爽感释放，最后解气
- 重生逆袭：爽感和期待为主，温暖收束
- 家庭伦理：共情、委屈、和解递进
- 战神/赘婿：隐藏身份受辱，亮身份打脸，登顶收束
- 虐恋/追妻：误会伤害，悔悟追妻，真相和解
- 萌宝/寻亲：带娃或错位关系，发现真相，家庭团圆

## 情绪点
每集至少包含以下一种：
- **爆点**：令人震惊、意外、骇人或惊羡的事件
- **虐点**：让观众心疼或愤怒的伤害、误会、牺牲
- **爽点**：主角受压后反击，形成"装 + 打脸 + 震惊 + 收获"

## 剧本格式
### 场景标题
格式：`### {场号} {场景名} {时间}/{内外}`
示例：`### 1-1 婚礼后台 夜/内`

### 场景描述
用 `△` 开头。必须包含人物动作、表情、环境、关键道具、光线条件。优先竖屏可拍。

### 台词
格式：`人物名：台词`。口语化、短句、高信息密度。单句通常不超过 20 字。

### OS / V.S.
- `OS（人物名，情绪）：` 用于角色内心或画外想法。
- `V.S.（人物名/旁白，情绪）：` 用于旁白或补充背景。

### 转场
`[硬切]`、`[淡入]`、`[闪白]`、`[闪黑]`、`[叠化]`

## 卡点设计
按总集数 N 计算关键卡点：约 10%、30%、50%、70%、90% 位置。

## 输出 JSON 结构
请严格输出以下 JSON 结构，所有 Markdown 内容放在对应字符串字段中：

{
  "skill_id": "novel-to-shortdrama-script",
  "skill_name": "小说改编短剧",
  "work_title": "作品名（从原文提取或概括）",
  "genre": "题材类型",
  "total_episodes": N,
  "minutes_per_episode": M,
  "summary": "一句话摘要，≤50字，说清本剧最大吸引力",
  "characters": [
    {"name": "角色名", "role": "主角/配角/反派", "arc": "人物弧光简述", "description": "外貌性格简述"}
  ],
  "adaptation_overview": "改编总纲的完整 Markdown 内容，包含故事核、题材类型、核心情绪、主角弧光、主要信息差、删减原则、三幕结构",
  "episode_outline": "分集大纲的完整 Markdown 内容，每集包含集标题、戏剧功能、场景核心、原文来源、核心情绪、信息差、删减决策、集末钩子、卡点",
  "full_script": "正式剧本的完整 Markdown 内容，每集包含目标时长、剧情梗概、场景描述、台词、OS、转场"
}

## 约束
- 不要输出 XML 包裹标签。
- 不要输出内部分析、自查清单、字数统计、版本号、修订说明。
- 不要输出工具调用、工作台保存等平台专用描述。
- 台词必须短、直白、口语化。
- 场景描述必须可拍、可视、可执行。
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字。
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

        # 解析集数和分钟数
        episodes_str = str(merged.get("集数", "5集"))
        minutes_str = str(merged.get("每集分钟", "2分钟"))
        try:
            total_episodes = int("".join(filter(str.isdigit, episodes_str)))
        except ValueError:
            total_episodes = 5
        try:
            minutes_per_episode = int("".join(filter(str.isdigit, minutes_str)))
        except ValueError:
            minutes_per_episode = 2

        user_content = f"""\
小说原文：
{user_input}

集数：{total_episodes}集
每集分钟：{minutes_per_episode}分钟
题材类型：{merged.get('题材类型', '重生逆袭')}
目标台词量：约{total_episodes * minutes_per_episode * 150}字/集
""".strip()

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
                "work_title": "",
                "genre": merged.get('题材类型', ''),
                "total_episodes": total_episodes,
                "minutes_per_episode": minutes_per_episode,
                "summary": "",
                "characters": [],
                "adaptation_overview": "",
                "episode_outline": "",
                "full_script": "",
                "_error": "LLM 调用失败，请稍后重试",
            },
        )

        return SkillOutput(
            skill_id=self.info.skill_id,
            status="success" if not result.get("_is_fallback") else "failed",
            data=result,
            error=result.get("_fallback_error"),
        )
