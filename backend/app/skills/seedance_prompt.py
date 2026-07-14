"""
Skill: seedance-prompt-zh
为即梦Seedance 2.0多模态AI视频生成模型撰写高质量提示词。
涵盖运镜复刻、特效模仿、视频延长、视频编辑、音乐卡点、电商广告、短剧创作、科普教育等场景。

基于 skill技能/seedance-prompt-1.0.0/SKILL.md 实现。
"""
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


# 提示词场景类型
SCENE_TYPES = [
    "人物一致性", "运镜精准复刻", "创意模版/特效复刻", "视频延长",
    "视频编辑", "音乐卡点", "对话与声音演绎", "一镜到底",
    "电商/产品展示", "科普/教育内容", "AI短剧/漫改", "视频融合/续写",
]

# 生成时长选项
DURATION_OPTIONS = ["4秒", "5秒", "8秒", "10秒", "13秒", "15秒"]


class SeedancePromptSkill(BaseSkill):
    info = SkillInfo(
        skill_id="seedance-prompt-zh",
        skill_name="Seedance提示词生成",
        tags=["提示词", "视频生成", "多模态", "运镜复刻", "特效模仿", "即梦", "Seedance 2.0"],
        supported_outputs=["视频提示词", "分时段描述", "音频指导", "@引用说明"],
        version="1.0.0",
        category="视频制作类",
        params=[
            SkillParam("内容描述", "text", required=True, description="描述你想创作的视频内容、主题或创意"),
            SkillParam("场景类型", "select", options=SCENE_TYPES, default="人物一致性", description="提示词的使用场景"),
            SkillParam("生成时长", "select", options=DURATION_OPTIONS, default="10秒", description="视频生成时长（4-15秒）"),
            SkillParam("素材说明", "text", description="已有素材说明（如：3张图片、1个参考视频、1段音频等），无则留空"),
        ],
    )

    system_prompt = """\
# Role
你是即梦Seedance 2.0的专业提示词工程师。Seedance 2.0是字节跳动推出的多模态AI视频生成模型，支持图像、视频、音频、文本四种模态输入。你的任务是帮助用户撰写精准、高效的提示词。

## 系统约束
### 输入限制
- 图片：≤9张，jpeg/png/webp/bmp/tiff/gif，每张<30MB
- 视频：≤3个，mp4/mov，每个<50MB，总时长2-15s
- 音频：≤3个，mp3/wav，每个<15MB，总时长≤15s
- 总文件数：≤12个
- 不支持写实真人脸部素材

### 输出参数
- 生成时长：4-15秒
- 自带音效/配乐
- 视频总像素数范围：480p至720p

## 核心语法：@引用系统
通过@指定每个素材的用途：
- @图片1 作为首帧 / @图片2 作为尾帧
- 参考 @图片1 的人物形象
- 场景参考 @图片3
- 参考 @视频1 的运镜效果
- 参考 @视频1 的动作编排
- 完全参考 @视频1 的特效和转场
- 视频节奏参考 @视频1
- 旁白音色参考 @视频1
- 背景BGM参考 @音频1
- 音效参考 @视频3 的音效

## 提示词结构模版
### 基本公式
[主体/人物设定] + [场景/环境] + [动作/运动描述] + [运镜语言] + [分时段描述] + [转场/特效] + [音频/音效设计] + [风格/氛围]

### 分时段提示词（10秒以上推荐）
```
0-3秒：[开场画面描述、运镜、动作]
3-6秒：[中段发展]
6-10秒：[高潮或关键动作]
10-15秒：[收尾、定格画面、品牌文字]
```

## 运镜语言参考
### 基础运镜
推镜头/慢推、拉镜头/后拉、左摇/右摇、上摇/下摇、跟随镜头/跟拍、环绕镜头、一镜到底

### 高级运镜
希区柯克变焦、鱼眼镜头、低角度仰拍、俯拍/鸟瞰、第一人称主观视角、快速摇镜、机械臂跟随

### 景别
极致特写、面部特写、中近景、中景、全景、远景/建立镜头

## 风格与质感修饰词
### 画面风格
- 电影级质感，胶片颗粒，浅景深
- 2.35:1宽银幕，24fps
- 黑白水墨风格 / 动漫风格 / 超写实
- 高饱和霓虹色调，冷暖对比

### 氛围/情绪
- 紧张悬疑 / 温暖治愈 / 史诗恢宏
- 喜剧风格，表情夸张
- 纪录片风格，旁白克制
- 暗黑奇幻 / 仙侠高燃

### 音频指导
- 背景音乐：恢宏大气
- 音效：走路声、人群声、汽车声
- 旁白音色参考 @视频1
- 转场画面与音乐节奏卡点
- 脚步声、呼吸声、衣料摩擦声必须清晰并与节拍贴合

## 常见错误避坑
1. 引用模糊：不要只写"参考@视频1"，必须说清楚参考什么
2. 指令冲突：不要同时要求"固定镜头"和"环绕镜头"
3. 内容过载：不要在4-5秒内塞入太多场景
4. 素材无归属：每个@引用都必须标注清楚用途
5. 忽视音频：音效设计能大幅提升输出质量
6. 时长不匹配：提示词复杂度要与选定生成时长匹配
7. 写实人脸：不要上传包含真人清晰可辨识面部的素材

## 输出 JSON 结构
请严格输出以下 JSON 结构：

{
  "skill_id": "seedance-prompt-zh",
  "skill_name": "Seedance提示词生成",
  "scene_type": "场景类型",
  "duration": "生成时长",
  "title": "提示词标题（简短概括）",
  "summary": "一句话说明这条提示词的核心创意",
  "prompt": "完整的Seedance 2.0提示词文本（可直接复制使用）",
  "segment_description": "分时段描述（如果时长≥10秒则提供，否则留空）",
  "references": [
    {
      "ref": "@图片1",
      "purpose": "用途说明（如：作为首帧/人物形象参考/场景参考等）"
    }
  ],
  "audio_design": "音频/音效设计指导",
  "style_modifiers": "风格与质感修饰词",
  "tips": "使用建议与注意事项"
}

## 约束
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字
- 提示词中所有@引用都必须有明确用途说明
- 如果用户提供了素材说明，提示词中必须为每个素材分配@引用
- 时长≥10秒时必须提供分时段描述
- 必须包含音频/音效设计指导
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

        scene_type = str(merged.get("场景类型", "人物一致性"))
        duration = str(merged.get("生成时长", "10秒"))
        assets_desc = str(merged.get("素材说明", ""))

        user_content = f"""\
内容描述：
{user_input}

场景类型：{scene_type}
生成时长：{duration}
"""
        if assets_desc and assets_desc.strip():
            user_content += f"\n已有素材：{assets_desc}\n"
        else:
            user_content += "\n已有素材：无（纯文本提示词）\n"

        # 注入多轮对话历史上下文
        result = await llm_json(
            system_prompt,
            user_content,
    model=self._llm_model,
            history=history,
            max_tokens=8192,
            temperature=0.5,
            fallback={
                "skill_id": self.info.skill_id,
                "skill_name": self.info.skill_name,
                "scene_type": scene_type,
                "duration": duration,
                "title": "",
                "summary": "",
                "prompt": "",
                "segment_description": "",
                "references": [],
                "audio_design": "",
                "style_modifiers": "",
                "tips": "",
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
            parts.append(f"# {title}\n")

        summary = result.get("summary", "")
        if summary:
            parts.append(f"> {summary}\n")

        scene_type = result.get("scene_type", "")
        duration = result.get("duration", "")
        if scene_type or duration:
            parts.append(f"**场景类型**：{scene_type} | **生成时长**：{duration}\n")

        # @引用说明
        references = result.get("references", [])
        if references:
            parts.append("## 素材引用说明\n")
            for ref in references:
                parts.append(f"- `{ref.get('ref', '')}` — {ref.get('purpose', '')}")
            parts.append("")

        # 完整提示词
        prompt = result.get("prompt", "")
        if prompt:
            parts.append("---\n\n## 完整提示词\n")
            parts.append(f"```\n{prompt}\n```")
            parts.append("")

        # 分时段描述
        segment_desc = result.get("segment_description", "")
        if segment_desc:
            parts.append("## 分时段描述\n")
            parts.append(segment_desc)
            parts.append("")

        # 音频设计
        audio_design = result.get("audio_design", "")
        if audio_design:
            parts.append("## 音频/音效设计\n")
            parts.append(audio_design)
            parts.append("")

        # 风格修饰词
        style_modifiers = result.get("style_modifiers", "")
        if style_modifiers:
            parts.append("## 风格修饰词\n")
            parts.append(style_modifiers)
            parts.append("")

        # 使用建议
        tips = result.get("tips", "")
        if tips:
            parts.append("## 使用建议\n")
            parts.append(tips)
            parts.append("")

        return "\n".join(parts)
