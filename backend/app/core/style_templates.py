"""
P9: 多画风/风格切换预设模板系统。

每种风格模板包含完整的视觉风格参数集：
- style_bible: 视觉风格圣经
- color_palette: 色彩方案
- rendering_standard: 渲染基准
- lens_standard: 镜头基准
- character_style: 角色风格描述
- scene_style: 场景风格描述
- negative_prompt: 通用负面提示词
- image_model_hint: 推荐的图像生成模型
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class StyleTemplate:
    """画风预设模板。"""
    template_id: str
    template_name: str
    template_name_en: str
    category: str  # realistic | anime | 3d | artistic | special
    description: str
    style_bible: str
    color_palette: List[str] = field(default_factory=list)
    rendering_standard: str = ""
    lens_standard: str = ""
    character_style: str = ""
    scene_style: str = ""
    negative_prompt: str = ""
    image_model_hint: str = ""
    icon: str = ""  # emoji or icon name for frontend
    preview_colors: List[str] = field(default_factory=list)  # gradient preview colors


# ---- 预设风格模板 ----

STYLE_TEMPLATES: Dict[str, StyleTemplate] = {
    "realistic_cinematic": StyleTemplate(
        template_id="realistic_cinematic",
        template_name="真人写实·电影感",
        template_name_en="Realistic Cinematic",
        category="realistic",
        description="写实电影质感，适合都市、情感、悬疑题材",
        style_bible="写实电影感，自然光影，浅景深，35mm胶片质感，肤色真实还原",
        color_palette=["#2C3E50", "#34495E", "#E74C3C", "#ECF0F1", "#D4A574"],
        rendering_standard="UE5离线渲染、PBR物理材质、写实电影感、SSS皮肤着色",
        lens_standard="35mm定焦镜头，f/1.8光圈，柯达5207胶片质感",
        character_style="真人写实，自然妆容，电影级皮肤质感，毛孔级细节",
        scene_style="实景拍摄质感，自然光线，大气透视，体积光",
        negative_prompt="cartoon, anime, 3d render, plastic skin, over-smoothed, beauty filter, influencer face, saturated colors, cartoon eyes",
        image_model_hint="gpt-image-2",
        icon="🎬",
        preview_colors=["#1a1a2e", "#16213e", "#0f3460"],
    ),
    "realistic_portrait": StyleTemplate(
        template_id="realistic_portrait",
        template_name="真人写实·清新",
        template_name_en="Realistic Portrait",
        category="realistic",
        description="清新自然写实风格，适合甜宠、校园、日常题材",
        style_bible="清新自然写实，柔光，明亮色调，浅景深人像",
        color_palette=["#FFB6C1", "#87CEEB", "#F0E68C", "#98FB98", "#FFE4E1"],
        rendering_standard="写实渲染，柔光箱照明，自然肤色",
        lens_standard="50mm定焦镜头，f/2.0光圈，自然柔焦",
        character_style="清新写实，淡妆，自然发型，青春气息",
        scene_style="明亮场景，自然光，清新色调",
        negative_prompt="dark, gothic, horror, over-dramatic lighting, heavy makeup, plastic skin",
        image_model_hint="gpt-image-2",
        icon="🌸",
        preview_colors=["#fce4ec", "#f8bbd0", "#f48fb1"],
    ),
    "anime_kr": StyleTemplate(
        template_id="anime_kr",
        template_name="2D韩式厚涂",
        template_name_en="Korean Webtoon",
        category="anime",
        description="韩式漫画厚涂风格，适合漫改短剧",
        style_bible="韩式webtoon厚涂风格，半写实人物比例，丰富阴影层次，鲜明色彩",
        color_palette=["#FF6B6B", "#4ECDC4", "#FFE66D", "#1A535C", "#F7FFF7"],
        rendering_standard="2D厚涂，数字绘画，韩式漫画风格",
        lens_standard="漫画构图，夸张透视，动态角度",
        character_style="韩式漫画人物，大眼，精致五官，时尚穿搭，半写实比例",
        scene_style="漫画场景，饱和色彩，简化背景",
        negative_prompt="3d render, realistic photo, photorealistic, ugly, deformed, blurry, low quality",
        image_model_hint="gemini-3.1-flash-lite-image",
        icon="🎨",
        preview_colors=["#ff6b6b", "#feca57", "#ff9ff3"],
    ),
    "anime_jp": StyleTemplate(
        template_id="anime_jp",
        template_name="日系二次元",
        template_name_en="Japanese Anime",
        category="anime",
        description="日系动漫风格，适合奇幻、冒险、热血题材",
        style_bible="日系动漫赛璐璐风格，清晰线稿，平涂上色，夸张表情",
        color_palette=["#FF9F1C", "#2EC4B6", "#E71D36", "#FDFFFC", "#011627"],
        rendering_standard="2D赛璐璐动画风格，平面着色",
        lens_standard="动画镜头语言，广角夸张，速度线",
        character_style="日系动漫人物，大眼，夸张发型，丰富表情",
        scene_style="动漫场景，渐变天空，特效光效",
        negative_prompt="realistic, 3d, photo, photorealistic, live action",
        image_model_hint="gemini-3.1-flash-lite-image",
        icon="✨",
        preview_colors=["#667eea", "#764ba2", "#f093fb"],
    ),
    "render_3d": StyleTemplate(
        template_id="render_3d",
        template_name="3D渲染·皮克斯",
        template_name_en="3D Pixar Style",
        category="3d",
        description="3D动画渲染风格，适合奇幻、童话、冒险题材",
        style_bible="3D动画电影质感，PBR材质渲染，柔和全局光照，卡通化比例",
        color_palette=["#264653", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51"],
        rendering_standard="3D渲染，PBR物理材质，全局光照，SSS次表面散射",
        lens_standard="3D动画镜头，广角，景深模糊",
        character_style="3D卡通人物，大眼，圆润造型，丰富表情",
        scene_style="3D渲染场景，体积光，大气效果",
        negative_prompt="2d, flat, anime, realistic photo, live action",
        image_model_hint="gpt-image-2",
        icon="🧊",
        preview_colors=["#5f0a87", "#a4508b", "#dbd05b"],
    ),
    "chinese_ink": StyleTemplate(
        template_id="chinese_ink",
        template_name="国风水墨",
        template_name_en="Chinese Ink Wash",
        category="artistic",
        description="中国水墨画风，适合古风、仙侠、历史题材",
        style_bible="中国传统水墨画风格，留白意境，墨色浓淡变化，工笔细节",
        color_palette=["#2C2C2C", "#8B8B8B", "#D4D4D4", "#F5F5F5", "#C04000"],
        rendering_standard="水墨画风格，宣纸纹理，毛笔笔触",
        lens_standard="国画构图，留白，散点透视",
        character_style="古风人物，汉服/古装，水墨线条，工笔面部",
        scene_style="山水水墨，留白意境，墨色渲染",
        negative_prompt="3d render, photorealistic, modern, western, neon, cyber",
        image_model_hint="gemini-3.1-flash-lite-image",
        icon="🀄",
        preview_colors=["#2c2c2c", "#8b8b8b", "#f5f5f5"],
    ),
    "cyberpunk": StyleTemplate(
        template_id="cyberpunk",
        template_name="赛博朋克",
        template_name_en="Cyberpunk",
        category="special",
        description="赛博朋克科幻风格，适合科幻、未来、悬疑题材",
        style_bible="赛博朋克美学，霓虹灯光，暗色调，未来都市，全息投影",
        color_palette=["#FF006E", "#8338EC", "#3A86FF", "#06FFA5", "#1A1A2E"],
        rendering_standard="赛博朋克渲染，霓虹辉光，雨夜反射，体积雾",
        lens_standard="广角变形镜头，f/1.4，霓虹光斑",
        character_style="赛博朋克风格，科技服饰，霓虹妆，义体改造",
        scene_style="未来都市夜景，霓虹招牌，全息广告，雨后街道",
        negative_prompt="medieval, ancient, historical, rural, natural daylight, sunny",
        image_model_hint="gpt-image-2",
        icon="🌃",
        preview_colors=["#ff006e", "#8338ec", "#3a86ff"],
    ),
    "watercolor": StyleTemplate(
        template_id="watercolor",
        template_name="水彩绘本",
        template_name_en="Watercolor Storybook",
        category="artistic",
        description="水彩绘本风格，适合治愈、童趣、温馨题材",
        style_bible="水彩绘本插画风格，柔和色彩晕染，手绘质感，温暖色调",
        color_palette=["#A8DADC", "#457B9D", "#E63946", "#F1FAEE", "#F4A261"],
        rendering_standard="水彩画风格，纸张纹理，颜色晕染",
        lens_standard="绘本构图，柔和透视",
        character_style="水彩绘本人物，柔和线条，温暖色调",
        scene_style="水彩场景，色彩晕染，温馨氛围",
        negative_prompt="3d render, photorealistic, dark, horror, cyberpunk, neon",
        image_model_hint="gemini-3.1-flash-lite-image",
        icon="🎨",
        preview_colors=["#a8dadc", "#457b9d", "#e63946"],
    ),
}


def get_style_template(template_id: str) -> Optional[StyleTemplate]:
    """获取风格模板。"""
    return STYLE_TEMPLATES.get(template_id)


def list_style_templates() -> List[Dict[str, Any]]:
    """列出所有风格模板的元数据。"""
    return [
        {
            "template_id": t.template_id,
            "template_name": t.template_name,
            "template_name_en": t.template_name_en,
            "category": t.category,
            "description": t.description,
            "icon": t.icon,
            "preview_colors": t.preview_colors,
        }
        for t in STYLE_TEMPLATES.values()
    ]


def apply_style_to_global_params(
    template_id: str,
    existing_params: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """将风格模板应用到全局参数，返回合并后的参数。"""
    template = get_style_template(template_id)
    if not template:
        return existing_params or {}

    params = dict(existing_params or {})
    params["视觉主风格"] = template.style_bible
    params["渲染基准"] = template.rendering_standard
    params["镜头基准"] = template.lens_standard
    return params


def get_style_metadata_for_script(template_id: str) -> Dict[str, Any]:
    """获取风格模板中剧本/分镜 Agent 需要的字段。"""
    template = get_style_template(template_id)
    if not template:
        return {}
    return {
        "style_bible": template.style_bible,
        "color_palette": template.color_palette,
        "character_style": template.character_style,
        "scene_style": template.scene_style,
        "negative_prompt": template.negative_prompt,
        "image_model_hint": template.image_model_hint,
    }
