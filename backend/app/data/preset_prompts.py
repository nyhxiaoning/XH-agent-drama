"""
预设功能 Prompt 模板集中管理。
包括：
  - 图片生成类：三视图、360°、九宫格、四宫格推演、高清放大、扩图、抠图
  - LLM 类：剧本解析、脚本优化、拉片分析、25宫格分镜
  - 角色特征提取：锁定角色一致性时用 LLM 分析图片特征
"""
from typing import Callable, Dict, Any, List, Tuple


# ── 图片生成类 Prompt 模板 ──
# 每个 lambda 接收 (base_prompt, style) 返回最终 prompt

IMAGE_PRESET_PROMPTS: Dict[str, Callable[[str, str], str]] = {
    "character_sheet": lambda p, s="": (
        f"Professional character design sheet, pure white background, "
        f"divided into 4 panels arranged horizontally. "
        f"All 4 panels MUST follow these strict rules: "
        f"neutral calm expression with relaxed eyes and closed mouth, "
        f"no smiling, no smirking, no eye-rolling, no raised eyebrows, no sneering, "
        f"no hand gestures, no pointing, no raised fingers, no dynamic poses, no head tilting. "
        f"Panels 1-3 are full-body character turns: "
        f"front view, side view, back view, standing straight facing forward, "
        f"arms relaxed at sides with hands open and empty. "
        f"Panel 4 is a neutral face close-up portrait: head and shoulders only, "
        f"showing these character features without any expression: {p}. "
        f"Same character consistently shown from multiple angles, "
        f"clean simple clothing, no text, no letters, no watermark, "
        f"no props, no accessories, no background elements, no weapons, "
        f"highly detailed, 8k, realistic lighting"
        f"{f', {s}' if s else ''}"
    ),
    "character_360": lambda p, s="": (
        f"Character turnaround reference sheet, 8 angles arranged in a circle: "
        f"front, 3/4 front, side profile, 3/4 back, back, 3/4 back (other side), "
        f"side profile (other side), 3/4 front (other side). "
        f"Full body, {p}, pure white background, consistent design across all angles, "
        f"neutral pose, arms at sides, looking forward. "
        f"Same clothing, same hairstyle, same body type in every angle. "
        f"No text, no watermark, concept art style, 8k, realistic lighting"
        f"{f', {s}' if s else ''}"
    ),
    "multi_angle_9": lambda p, s="": (
        f"3x3 grid layout, 9 different camera angles of the same subject, "
        f"arranged in a 3-column 3-row grid with thin white dividing lines. "
        f"Row 1: bird's eye view, high angle, eye level. "
        f"Row 2: low angle, dutch angle (tilted), over the shoulder. "
        f"Row 3: close-up, medium shot, wide shot. "
        f"Subject: {p}, consistent character design across all 9 panels. "
        f"Same person, same clothing, same hairstyle in every panel. "
        f"Pure white background, cinematic lighting, 8k, highly detailed"
        f"{f', {s}' if s else ''}"
    ),
    "story_evolution_4": lambda p, s="": (
        f"2x2 grid layout, 4 possible next scenes continuing from the current image, "
        f"arranged with thin white dividing lines. "
        f"Top-left: most likely continuation. "
        f"Top-right: alternative continuation A. "
        f"Bottom-left: alternative continuation B. "
        f"Bottom-right: dramatic twist continuation. "
        f"Scene context: {p}. "
        f"Cinematic storytelling, consistent characters across all 4 panels, "
        f"sequential narrative flow, 8k, highly detailed"
        f"{f', {s}' if s else ''}"
    ),
    "upscale": lambda p, s="": (
        f"Ultra high resolution version of the reference image, "
        f"4K quality, enhanced details, sharper focus, same composition and style. "
        f"Subject: {p}. "
        f"Maintain exact same character appearance, clothing, pose, and scene. "
        f"No new elements, no changes to the original design, only quality enhancement. "
        f"Professional photo retouching quality, 8k"
        f"{f', {s}' if s else ''}"
    ),
    "outpaint": lambda p, s="": (
        f"Extended scene, wider view of the reference image, "
        f"seamless expansion in all directions. "
        f"Original content: {p}. "
        f"Expand the background, environment, and scene naturally. "
        f"Keep the original subject exactly the same, do not alter the original composition. "
        f"Seamless blending, consistent lighting, 8k, highly detailed"
        f"{f', {s}' if s else ''}"
    ),
    "remove_bg": lambda p, s="": (
        f"Isolated subject on transparent background, clean cutout. "
        f"Subject: {p}. "
        f"Remove all background elements, keep only the main subject. "
        f"Preserve hair details, edges, and shadows naturally. "
        f"No background color, no scenery, pure transparency. "
        f"Professional product photography quality cutout, 8k"
        f"{f', {s}' if s else ''}"
    ),
}


# ── LLM 类预设 System/User Prompt ──

LLM_PRESET_PROMPTS: Dict[str, Dict[str, str]] = {
    "script_parse": {
        "system": (
            "你是一位专业的短视频剧本结构分析师。请将用户提供的文本拆分为结构化的剧本数据。\n"
            "你必须仅返回 JSON，不要包含任何解释性文字。JSON 格式如下：\n"
            "{\n"
            '  "title": "剧本标题",\n'
            '  "genre": "类型（如悬疑/爱情/搞笑/励志）",\n'
            '  "summary": "一句话概要",\n'
            '  "characters": [\n'
            '    {"char_id": "C001", "name": "角色名", "role": "主角/配角/群演", "description": "外貌和性格描述", "base_prompt": "用于AI生图的角色提示词（英文）"}\n'
            "  ],\n"
            '  "scenes": [\n'
            '    {"scene_id": "S001", "name": "场景名", "description": "场景描述", "base_prompt": "用于AI生图的场景提示词（英文）"}\n'
            "  ],\n"
            '  "storyboards": [\n'
            '    {"storyboard_id": "SB_001", "linked_char_ids": ["C001"], "linked_scene_id": "S001", "description": "画面描述", "final_image_prompt": "用于AI生图的画面提示词（英文）", "duration_seconds": 5}\n'
            "  ]\n"
            "}\n"
            "注意：所有 prompt 字段使用英文描述，适合 AI 图像生成模型。"
        ),
        "user_template": "请分析以下剧本文本并拆分为结构化数据：\n\n{content}",
    },
    "script_optimize": {
        "system": (
            "你是一位资深短视频剧本编剧和润色专家。请优化用户提供的剧本，要求：\n"
            "1. 润色对白，使其更自然、更有张力\n"
            "2. 优化节奏，确保每 5-10 秒有一个情绪转折或视觉变化\n"
            "3. 修正逻辑漏洞，确保剧情连贯\n"
            "4. 增强画面感，让文字更容易转化为视觉分镜\n"
            "5. 保持原剧本的核心创意和风格不变\n"
            "请直接返回优化后的剧本全文，不要添加任何解释性说明。"
        ),
        "user_template": "请优化以下剧本：\n\n{content}",
    },
    "film_analysis": {
        "system": (
            "你是一位专业的影视拉片分析师。请对视频进行详细的镜头语言和叙事分析。\n"
            "你必须仅返回 JSON，不要包含任何解释性文字。JSON 格式如下：\n"
            "{\n"
            '  "overall_style": "整体风格评价",\n'
            '  "shots": [\n'
            '    {"timestamp": "0:00-0:05", "shot_type": "景别（特写/近景/中景/全景/远景）", "camera_movement": "运镜（固定/推/拉/摇/移/跟）", "description": "画面描述", "narrative_function": "叙事功能"}\n'
            "  ],\n"
            '  "rhythm": {"pace": "节奏（快/中/慢）", "cuts": "剪辑次数", "avg_shot_duration": "平均镜头时长"},\n'
            '  "color": {"tone": "色调（暖/冷/中性）", "style": "色彩风格描述", "lighting": "光线描述"},\n'
            '  "editing": {"technique": "剪辑手法", "transitions": "转场方式", "highlights": "亮点"},\n'
            '  "suggestions": ["改进建议1", "改进建议2"]\n'
            "}\n"
            "注意：如果无法直接观看视频，请根据视频的描述文本和提示词进行推断分析。"
        ),
        "user_template": (
            "请分析以下视频：\n"
            "视频提示词: {content}\n"
            "视频URL: {video_url}\n"
            "请根据这些信息进行拉片分析。"
        ),
    },
    "storyboard_25": {
        "system": (
            "你是一位专业的短视频分镜师。请将用户提供的一句话或概念拆分为 25 个连续的画面分镜。\n"
            "25 个分镜按 5x5 网格排列，按从左到右、从上到下的顺序编号（1-25）。\n"
            "你必须仅返回 JSON，不要包含任何解释性文字。JSON 格式如下：\n"
            "{\n"
            '  "concept": "原始概念",\n'
            '  "panels": [\n'
            '    {"index": 1, "grid_row": 0, "grid_col": 0, "description": "画面中文描述", "prompt": "English prompt for AI image generation", "shot_type": "景别", "duration_seconds": 3}\n'
            "  ]\n"
            "}\n"
            "要求：\n"
            "1. 25 个分镜必须有清晰的叙事弧线（开端→发展→高潮→结局）\n"
            "2. 每个 prompt 必须是英文，包含具体的画面描述、光线、角度\n"
            "3. 保持角色和场景的一致性\n"
            "4. grid_row 和 grid_col 从 0 开始（0-4）\n"
            "5. 每个 duration_seconds 在 3-5 秒之间"
        ),
        "user_template": "请将以下概念拆分为 25 个分镜：\n\n{content}",
    },
}


# ── 角色特征提取 Prompt（lock_character 用）──

CHARACTER_FEATURE_EXTRACTION_PROMPT = {
    "system": (
        "你是一位角色设计师。请根据用户提供的角色描述，提取角色的不可变特征（用于保持角色一致性）。\n"
        "你必须仅返回 JSON，不要包含任何解释性文字。JSON 格式如下：\n"
        "{\n"
        '  "gender": "性别",\n'
        '  "age_range": "年龄段",\n'
        '  "body_type": "体型",\n'
        '  "height": "身高描述",\n'
        '  "hair": {"color": "发色", "style": "发型", "length": "发长"},\n'
        '  "eyes": {"color": "瞳色", "shape": "眼型"},\n'
        '  "skin": {"tone": "肤色", "texture": "肤质"},\n'
        '  "face": {"shape": "脸型", "features": "面部特征（如疤痕、痣等）"},\n'
        '  "clothing": {"top": "上装描述", "bottom": "下装描述", "accessories": "配饰", "colors": "主色调"},\n'
        '  "personality": "性格气质",\n'
        '  "distinctive_marks": "独特标识（如纹身、胎记等）",\n'
        '  "summary_en": "英文完整角色描述（用于生图）"\n'
        "}"
    ),
    "user_template": "请提取以下角色的不可变特征：\n\n角色描述：{content}\n\n风格：{style}",
}


# ── 辅助函数 ──

def get_image_preset_prompt(feature_id: str, base_prompt: str, style: str = "") -> str:
    """获取图片生成类预设的最终 prompt。"""
    fn = IMAGE_PRESET_PROMPTS.get(feature_id)
    if not fn:
        return base_prompt
    return fn(base_prompt, style)


def get_llm_preset_messages(
    feature_id: str,
    content: str,
    video_url: str = "",
    style: str = "",
) -> List[Dict[str, str]]:
    """获取 LLM 类预设的 messages 列表。"""
    config = LLM_PRESET_PROMPTS.get(feature_id)
    if not config:
        return [
            {"role": "system", "content": "你是一位短视频剧本生成专家。请根据用户要求输出剧本正文。"},
            {"role": "user", "content": content},
        ]

    user_content = config["user_template"].replace("{content}", content)
    if "{video_url}" in user_content:
        user_content = user_content.replace("{video_url}", video_url or "无")
    if "{style}" in user_content:
        user_content = user_content.replace("{style}", style or "")

    return [
        {"role": "system", "content": config["system"]},
        {"role": "user", "content": user_content},
    ]


def get_character_feature_messages(description: str, style: str = "") -> List[Dict[str, str]]:
    """获取角色特征提取的 messages 列表。"""
    config = CHARACTER_FEATURE_EXTRACTION_PROMPT
    user_content = config["user_template"].replace("{content}", description).replace("{style}", style or "")
    return [
        {"role": "system", "content": config["system"]},
        {"role": "user", "content": user_content},
    ]


# ── 预设功能配置（强制参数覆盖）──

PRESET_CONFIG_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "character_sheet": {"aspect_ratio": "1:1", "resolution": "4K"},
    "character_360": {"aspect_ratio": "1:1", "resolution": "4K"},
    "multi_angle_9": {"aspect_ratio": "1:1", "resolution": "4K"},
    "story_evolution_4": {"aspect_ratio": "1:1", "resolution": "4K"},
    "upscale": {"resolution": "4K"},
    "outpaint": {},
    "remove_bg": {},
}

# 需要引用当前节点 result_url 作为参考图的功能
PRESET_NEEDS_RESULT_REF = {"upscale", "outpaint", "remove_bg", "story_evolution_4"}

# 预设功能中文标签（用于下游节点命名）
PRESET_LABELS: Dict[str, str] = {
    "character_sheet": "角色三视图",
    "character_360": "360°角度",
    "multi_angle_9": "九宫格机位",
    "story_evolution_4": "剧情推演",
    "upscale": "高清放大",
    "outpaint": "扩图",
    "remove_bg": "抠图",
    "grid_split": "宫格切分",
    "focus_crop": "聚焦特写",
    "storyboard_25": "25宫格分镜",
    "script_parse": "剧本解析",
    "script_optimize": "脚本优化",
    "film_analysis": "拉片分析",
    "batch_generate": "批量生成",
    "lock_character": "锁定角色",
}
