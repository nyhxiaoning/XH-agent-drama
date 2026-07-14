"""
P3: 角色一致性增强模块。

功能：
1. CharacterConsistencyAgent: 在角色生成后做一致性校验和修正建议
2. 面部嵌入校验: 基于 LLM 对比描述一致性
3. 交叉引用检查: 确保分镜中引用的角色与资产库匹配
4. 服装/配饰一致性追踪: 跨镜头追踪角色视觉特征
"""
import logging
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json as _llm_json

logger = logging.getLogger(__name__)


class CharacterConsistencyAgent:
    """角色一致性校验 Agent。"""

    def __init__(self, llm_model: Optional[str] = None):
        self.llm_model = llm_model

    async def verify_character_sheet(
        self,
        character_name: str,
        character_desc: str,
        reference_image_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """校验角色设定表与参考图的一致性。

        Returns:
            {
                "consistent": bool,
                "issues": List[str],
                "suggestions": List[str],
                "confidence": float,
            }
        """
        system_prompt = """你是角色一致性审核专家。请审核角色设定描述是否完整且一致。

检查维度：
1. 外貌特征：发型、发色、瞳色、肤色、体型、身高
2. 服装风格：主色调、风格类型、标志性配饰
3. 性格标签：是否与外貌协调
4. 辨识度：是否有足够独特的视觉特征让 AI 生成时保持一致

只输出 JSON：
{
  "consistent": true/false,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"],
  "confidence": 0.0-1.0
}"""

        user_content = f"角色名称：{character_name}\n角色设定：{character_desc}"
        if reference_image_url:
            user_content += f"\n参考图：{reference_image_url}"

        try:
            result = await _llm_json(
                system_prompt,
                user_content,
                model=self.llm_model,
                fallback={
                    "consistent": True,
                    "issues": [],
                    "suggestions": [],
                    "confidence": 0.5,
                },
            )
            return result
        except Exception as e:
            logger.warning("[ConsistencyAgent] 校验失败: %s", e)
            return {
                "consistent": True,
                "issues": [],
                "suggestions": [],
                "confidence": 0.0,
                "error": str(e),
            }

    async def batch_verify_characters(
        self,
        characters: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """批量校验角色列表的一致性。"""
        results = {}
        for char in characters:
            name = char.get("name", char.get("名称", "未知"))
            desc = char.get("description", char.get("描述", char.get("外貌描述", "")))
            ref_url = char.get("image_url", char.get("参考图URL"))
            results[name] = await self.verify_character_sheet(name, desc, ref_url)
        return results

    async def check_storyboard_consistency(
        self,
        storyboard: List[Dict[str, Any]],
        character_assets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """检查分镜中引用的角色是否与资产库一致。

        检查内容：
        1. 分镜中引用的角色名是否都在资产库中存在
        2. 角色描述是否有矛盾（如同一角色在不同镜头中发色不同）
        3. 服装一致性：同一场景中角色服装是否统一
        """
        # 构建 ID → 角色名 映射
        char_names = set()
        char_desc_map: Dict[str, str] = {}
        for c in character_assets:
            name = c.get("name", c.get("名称", ""))
            if name:
                char_names.add(name)
                desc = c.get("description", c.get("外貌描述", ""))
                char_desc_map[name] = desc

        # 收集分镜中引用的角色
        referenced_chars: Dict[str, List[Dict]] = {}
        missing_refs: List[str] = []
        for i, shot in enumerate(storyboard):
            shot_chars = shot.get("characters", shot.get("出场角色", []))
            if isinstance(shot_chars, str):
                shot_chars = [shot_chars]
            for char_name in shot_chars:
                if char_name not in char_names:
                    missing_refs.append(f"分镜{i+1}: 角色'{char_name}'不在资产库中")
                else:
                    if char_name not in referenced_chars:
                        referenced_chars[char_name] = []
                    referenced_chars[char_name].append({
                        "shot_index": i + 1,
                        "description": shot.get("description", shot.get("画面描述", "")),
                    })

        # 快速返回缺失引用
        if missing_refs:
            return {
                "consistent": False,
                "issues": missing_refs,
                "suggestions": ["请检查角色名称拼写或补充缺失的角色资产"],
                "confidence": 0.3,
            }

        # LLM 深度检查描述矛盾
        system_prompt = """你是角色一致性审核专家。请检查分镜中各角色的描述是否与角色设定一致。

检查维度：
1. 同一角色在不同镜头中的外貌描述是否矛盾（发色、服装、体型等）
2. 角色行为是否符合设定
3. 是否有视觉特征冲突

只输出 JSON：
{
  "consistent": true/false,
  "conflicts": [{"character": "角色名", "shot_a": "镜头号", "shot_b": "镜头号", "conflict": "冲突描述"}],
  "suggestions": ["修正建议1", "修正建议2"],
  "confidence": 0.0-1.0
}"""

        import json
        user_content = json.dumps({
            "characters": {k: v for k, v in char_desc_map.items()},
            "storyboard_refs": referenced_chars,
        }, ensure_ascii=False, indent=2)

        try:
            result = await _llm_json(
                system_prompt,
                user_content,
                model=self.llm_model,
                fallback={
                    "consistent": True,
                    "conflicts": [],
                    "suggestions": [],
                    "confidence": 0.5,
                },
            )
            return result
        except Exception as e:
            logger.warning("[ConsistencyAgent] 分镜一致性检查失败: %s", e)
            return {
                "consistent": True,
                "conflicts": [],
                "suggestions": [],
                "confidence": 0.0,
                "error": str(e),
            }

    async def generate_consistency_prompt(
        self,
        character: Dict[str, Any],
        scene_context: Optional[str] = None,
    ) -> str:
        """生成用于图像/视频生成的一致性提示词片段。

        根据角色设定生成标准化的视觉锚点描述，确保跨镜头一致。
        """
        name = character.get("name", character.get("名称", ""))
        desc = character.get("description", character.get("外貌描述", ""))
        outfit = character.get("outfit", character.get("服装", ""))
        hair = character.get("hair", character.get("发型发色", ""))
        features = character.get("features", character.get("标志性特征", ""))

        # 组装锚点
        anchors = []
        if hair:
            anchors.append(f"发型发色: {hair}")
        if desc:
            anchors.append(f"面部特征: {desc}")
        if outfit:
            anchors.append(f"服装: {outfit}")
        if features:
            anchors.append(f"标志性特征: {features}")

        anchor_str = "，".join(anchors)
        prompt = f"角色「{name}」视觉锚点：[{anchor_str}]"

        if scene_context:
            prompt += f" 场景：{scene_context}"

        return prompt


# 全局实例
_consistency_agent: Optional[CharacterConsistencyAgent] = None


def get_consistency_agent(llm_model: Optional[str] = None) -> CharacterConsistencyAgent:
    global _consistency_agent
    if _consistency_agent is None or llm_model:
        _consistency_agent = CharacterConsistencyAgent(llm_model=llm_model)
    return _consistency_agent
