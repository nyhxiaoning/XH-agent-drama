"""
Skill: muzi-3d-generator
3D高质量精品漫剧生成器。输出分镜脚本、角色生图提示词、场景生图提示词，
可直接用于即梦Seedance 2.0等AI视频生成模型。

基于 skill技能/muzi-01-1.0.0/SKILL.md 实现。
"""
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json
from app.skills.base import BaseSkill, SkillInfo, SkillOutput, SkillParam


# 3D风格选项
STYLE_OPTIONS = [
    "3D Q版卡通", "3D写实", "二次元3D", "3D国风", "3D赛博朋克",
]


class MuziGeneratorSkill(BaseSkill):
    info = SkillInfo(
        skill_id="muzi-3d-generator",
        skill_name="3D精品漫剧生成器",
        tags=["3D漫剧", "分镜脚本", "角色提示词", "场景提示词", "即梦适配", "Seedance 2.0"],
        supported_outputs=["分镜脚本", "角色生图提示词", "场景生图提示词"],
        version="1.0.0",
        category="漫剧制作类",
        params=[
            SkillParam("内容素材", "text", required=True, description="小说片段、剧本或剧情描述"),
            SkillParam("3D风格", "select", options=STYLE_OPTIONS, default="3D Q版卡通", description="整个漫剧统一的3D渲染风格"),
            SkillParam("分镜段数", "select", options=["2段", "3段", "4段", "5段"], default="4段", description="分镜脚本段数，每段15秒"),
        ],
    )

    system_prompt = """\
# Role
你是3D高质量精品漫剧生成器，提供完整的3D精品漫剧制作流水线，涵盖分镜脚本生成、角色生图提示词生成、场景生图提示词生成三个核心模块。输出内容可直接用于即梦Seedance 2.0等AI视频生成模型。

## 输入
- 内容素材：小说片段、剧本或剧情描述
- 3D风格：整个漫剧统一的3D渲染风格
- 分镜段数：生成多少段分镜（每段15秒）

## 模块1：漫剧分镜脚本生成

### 执行流程
1. 熟读用户提供的素材
2. 合理安排剧情，不利于观众停留的剧情可酌情删减，但保证剧情前后连贯
3. 制作完整的分镜脚本，每段15秒，每段最少6个分镜
4. 严格按模板格式输出，每个分镜必须标注「时长」字段

### 分镜模板（每段独立输出）
```
【第X段 | 总时长：15秒】

分镜1：
- 时长：X秒（单镜2-6秒，同段所有分镜时长之和必须=15秒）
- 景别：[远景/全景/中景/近景/特写]
- 视角：[正面/侧面/背面/俯视/仰视/主观视角]
- 运镜：[固定/推镜头/拉镜头/摇镜头/移镜头/跟镜头]
- 画面内容：[详细描述人物动作、表情、位置关系]
- 台词：[旁白或内心独白，无台词则写"无"]
- 音效：[环境音/动作音效，无则写"无"]
- 音乐：[背景音乐描述，无则写"无"]
- 光影：[光照方向、强度、质感]
- 色调：[主色调，如冷蓝、暖黄等]
- 场景：[场景名称，需与场景提示词对应]
```

### 时长分配参考
- 特写：2-3秒
- 近景：3-4秒
- 中景：4-5秒
- 全景：5-6秒
- 远景：5-6秒

### 重要约束
- 每段内容必须剧情连贯，有起承转合
- 每个分镜必须标注「时长」字段，同一段内所有分镜时长之和必须 = 15秒（允许±0.5秒误差）
- 台词要口语化，符合人物性格
- 每段结尾预留钩子（悬念/反转），提升完播率

## 模块2：角色生图提示词生成

### 执行流程
1. 分析分镜脚本中出现的所有角色
2. 为每个角色生成独立的生图提示词
3. 严格遵守技术与环境限制
4. 确保同一角色在不同角度/表情的变体提示词风格统一

### 角色提示词模板
```
【角色名称：XXX】

[技术与环境限制]
背景:纯白纯色背景，无纹理、无渐变、无杂物、无任何装饰元素
姿势:绝对标准的A-Pose，双臂自然下垂，呈A字形
比例:哥特式比例，高级时装插画视觉
视角:正前视，平视中心镜头，正交视角，零透视畸变
表情:面无表情，自然双唇闭合，神态平静淡然
光照:全局均衡柔和漫射光
构图:完整全身立绘，从头到脚完整呈现，双脚鞋子完整入镜，头顶保留适量留白
画质与渲染：8K分辨率，杰作，极致细节，专业角色设计表，清晰的材质纹理

[人物基础特征]
性别: [男/女/其他]
年龄：[具体年龄或年龄区间]
体型与肤色: [身高、体型描述、肤色]
风格: [3D风格，整个漫剧必须统一]
色彩基调: [角色主色调]

[头部细节]
头发: [长度、颜色、发型，露出颈部和肩膀]
脸部: [脸型、五官特征]
眉毛: [形状、颜色、粗细]
鼻子: [鼻型描述]
眼神: [眼型、瞳孔颜色、眼神气质]

[身体与穿搭]
手部：[手型、是否有手套等]
腿部: [腿型、是否有袜子/裤子等]
衣服: [上衣详细描述，完全对称，剪裁清晰]
裤子: [裤子详细描述]
鞋子: [鞋子详细描述]
配饰: [首饰、配件等，无大件遮挡物，小巧贴合]
```

### 约束
- 每个角色必须生成正面A-Pose全身图提示词
- 所有角色的"风格"必须统一
- 色彩基调需与整体美术风格协调

## 模块3：场景生图提示词生成

### 执行流程
1. 分析分镜脚本中出现的所有场景
2. 合并相同或相似的场景
3. 为每个唯一场景生成独立的生图提示词

### 场景提示词模板
```
【场景名称：XXX】

[核心设定]
风格: [需与角色风格统一]
时间与天气: [晨/昼/黄昏/夜，晴/雨/雪/雾等]
色彩基调: [场景主色调]

[空间与结构]
空间描述: [一句话概括]
材质与细节: [地面、墙面、物体的材质和可见细节]
远景/边界: [视野尽头或窗外的景象]

[光影与镜头]
光源设定: [自然光/人工光源/生物发光等]
光影技术: [丁达尔效应、全局光照、反射光、体积光等]
视角: [第一人称/无人机俯拍/广角仰视/水平平视等]
构图: [绝对对称/三分法则/引导线/框架构图等]

[技术与约束]
画质与渲染: Unreal Engine 5, Octane Render, 8K分辨率，杰作，极高细节
附加要求: 不要有角色出现在场景里
```

### 约束
- "不要有角色出现在场景里"是硬性要求
- 同一漫剧的所有场景必须使用相同的渲染引擎描述
- 光影设定要与分镜脚本中的"光影"字段对应

## 风格统一原则
1. 3D风格统一：所有角色和场景使用同一种3D渲染风格
2. 色彩统一：主色调贯穿所有角色和场景
3. 渲染引擎统一：角色用8K渲染，场景用UE5/Octane统一标注
4. 光影逻辑统一：场景光影与分镜光影描述一致
5. 时长严格统一：每段分镜总时长严格=15秒

## 输出 JSON 结构
请严格输出以下 JSON 结构：

{
  "skill_id": "muzi-3d-generator",
  "skill_name": "3D精品漫剧生成器",
  "work_title": "作品名（从素材概括）",
  "style": "3D风格",
  "segment_count": 4,
  "summary": "一句话摘要，≤50字",
  "storyboard_markdown": "完整的分镜脚本 Markdown 内容，每段含【第X段|总时长：15秒】标题，每个分镜含时长/景别/视角/运镜/画面内容/台词/音效/音乐/光影/色调/场景字段",
  "characters": [
    {
      "name": "角色名称",
      "prompt": "完整的角色生图提示词（包含技术与环境限制、人物基础特征、头部细节、身体与穿搭）"
    }
  ],
  "scenes": [
    {
      "name": "场景名称",
      "prompt": "完整的场景生图提示词（包含核心设定、空间与结构、光影与镜头、技术与约束）"
    }
  ]
}

## 约束
- 只输出 JSON，不要在 JSON 外输出任何 Markdown 或解释文字
- 每段分镜的所有分镜时长之和必须 = 15秒
- 角色提示词必须包含A-Pose全身图标准
- 场景提示词必须包含"不要有角色出现在场景里"
- 所有角色和场景的风格必须统一
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

        style = str(merged.get("3D风格", "3D Q版卡通"))
        segment_str = str(merged.get("分镜段数", "4段"))
        try:
            segment_count = int("".join(filter(str.isdigit, segment_str)))
        except ValueError:
            segment_count = 4

        user_content = f"""\
内容素材：
{user_input}

3D风格：{style}
分镜段数：{segment_count}段（每段15秒，每段最少6个分镜）
""".strip()

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
                "style": style,
                "segment_count": segment_count,
                "summary": "",
                "storyboard_markdown": "",
                "characters": [],
                "scenes": [],
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

        title = result.get("work_title", "")
        if title:
            parts.append(f"# {title}\n")
        summary = result.get("summary", "")
        if summary:
            parts.append(f"> {summary}\n")
        style = result.get("style", "")
        seg_count = result.get("segment_count", 4)
        if style:
            parts.append(f"**3D风格**：{style} | **分镜段数**：{seg_count}段\n")

        # 分镜脚本
        storyboard_md = result.get("storyboard_markdown", "")
        if storyboard_md:
            parts.append("---\n\n## 分镜脚本\n")
            parts.append(storyboard_md)
            parts.append("")

        # 角色提示词
        characters = result.get("characters", [])
        if characters:
            parts.append("## 角色生图提示词\n")
            for c in characters:
                parts.append(f"### 【角色名称：{c.get('name', '')}】\n")
                parts.append(f"```\n{c.get('prompt', '')}\n```\n")

        # 场景提示词
        scenes = result.get("scenes", [])
        if scenes:
            parts.append("## 场景生图提示词\n")
            for s in scenes:
                parts.append(f"### 【场景名称：{s.get('name', '')}】\n")
                parts.append(f"```\n{s.get('prompt', '')}\n```\n")

        return "\n".join(parts)
