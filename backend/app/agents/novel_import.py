"""
P8: 小说/长文本导入与分集功能。

NovelImportAgent 支持将小说文本自动拆分为多集短剧剧本。
"""
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.llm_utils import llm_json as _llm_json

logger = logging.getLogger(__name__)

# 长文本分块阈值（字符数）
CHUNK_SIZE = 6000
MAX_EPISODES = 30


class NovelImportAgent:
    """小说导入与分集 Agent。"""

    def __init__(self, llm_model: Optional[str] = None):
        self.llm_model = llm_model

    def preprocess_novel(self, text: str) -> str:
        """预处理小说文本：清理格式、统一标点。"""
        if not text:
            return ""
        # 移除多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 移除不可见字符
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        # 统一引号
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        return text.strip()

    def detect_chapters(self, text: str) -> List[Dict[str, str]]:
        """检测小说章节结构。"""
        chapters = []
        # 常见章节标题模式
        patterns = [
            r"^第[一二三四五六七八九十百千零\d]+[章节回卷集部篇]",
            r"^Chapter\s+\d+",
            r"^第\d+章",
            r"^【第\d+[章节回]】",
            r"^\d+[.、]\s*.{2,20}$",
        ]

        lines = text.split("\n")
        current_chapter_start = 0
        current_chapter_title = "序章"

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            for pattern in patterns:
                if re.match(pattern, line_stripped):
                    # 保存前一章
                    if i > current_chapter_start:
                        chapter_text = "\n".join(lines[current_chapter_start:i])
                        chapters.append({
                            "title": current_chapter_title,
                            "content": chapter_text,
                        })
                    current_chapter_start = i
                    current_chapter_title = line_stripped
                    break

        # 最后一章
        if current_chapter_start < len(lines):
            chapter_text = "\n".join(lines[current_chapter_start:])
            chapters.append({
                "title": current_chapter_title,
                "content": chapter_text,
            })

        return chapters

    def chunk_text(self, text: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
        """将长文本按段落边界分块。"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) > chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk += "\n\n" + para if current_chunk else para

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    async def plan_episodes(
        self,
        novel_text: str,
        target_episodes: int = 10,
        episodes_per_minute: int = 1,
        genre_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """规划分集方案。

        Args:
            novel_text: 小说全文
            target_episodes: 目标集数
            episodes_per_minute: 每集分钟数
            genre_hint: 题材提示

        Returns:
            {
                "episodes": [{"episode": 1, "title": "...", "summary": "...", "source_range": "第X-Y章", "estimated_scenes": 8}],
                "total_episodes": 10,
                "character_extraction": [...],
                "story_arc": "...",
            }
        """
        # 预处理
        cleaned = self.preprocess_novel(novel_text)

        # 检测章节
        chapters = self.detect_chapters(cleaned)

        # 分块处理长文本
        if len(cleaned) > CHUNK_SIZE * 3:
            # 大文本：先做章节摘要，再基于摘要规划分集
            logger.info("[NovelImport] 大文本检测 (%d 字)，分块摘要中...", len(cleaned))
            chunks = self.chunk_text(cleaned)
            summaries = []
            for i, chunk in enumerate(chunks):
                summary = await self._summarize_chunk(chunk, i + 1, len(chunks))
                summaries.append(summary)

            full_summary = "\n\n".join(
                f"【片段{i+1}】\n{s.get('summary', '')}" for i, s in enumerate(summaries)
            )
            # 基于摘要规划分集
            plan = await self._plan_from_summary(full_summary, target_episodes, genre_hint)
        else:
            # 小文本：直接规划
            plan = await self._plan_from_summary(cleaned[:8000], target_episodes, genre_hint)

        # 限制最大集数
        if plan.get("total_episodes", 0) > MAX_EPISODES:
            plan["episodes"] = plan["episodes"][:MAX_EPISODES]
            plan["total_episodes"] = MAX_EPISODES

        # 章节映射
        if chapters:
            plan["detected_chapters"] = [{"title": c["title"], "char_count": len(c["content"])} for c in chapters]

        return plan

    async def _summarize_chunk(self, chunk: str, index: int, total: int) -> Dict[str, Any]:
        """摘要单个文本块。"""
        system_prompt = """你是小说摘要助手。请提取文本块的关键信息。

只输出 JSON：
{
  "summary": "300字以内的剧情摘要",
  "key_events": ["关键事件1", "关键事件2"],
  "characters_mentioned": ["角色名1", "角色名2"],
  "emotional_tone": "情感基调",
  "cliffhanger": "是否有悬念结尾 true/false"
}"""

        user_content = f"这是小说的第 {index}/{total} 部分（约 {len(chunk)} 字）：\n\n{chunk[:5000]}"

        try:
            result = await _llm_json(
                system_prompt,
                user_content,
                model=self.llm_model,
                fallback={
                    "summary": chunk[:300],
                    "key_events": [],
                    "characters_mentioned": [],
                    "emotional_tone": "未知",
                    "cliffhanger": False,
                },
            )
            return result
        except Exception as e:
            logger.warning("[NovelImport] 分块摘要失败 (chunk %d): %s", index, e)
            return {
                "summary": chunk[:300],
                "key_events": [],
                "characters_mentioned": [],
                "emotional_tone": "未知",
                "cliffhanger": False,
            }

    async def _plan_from_summary(
        self,
        summary_text: str,
        target_episodes: int,
        genre_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """基于摘要规划分集。"""
        system_prompt = f"""你是短剧编剧顾问。请根据小说内容规划 {target_episodes} 集短剧的分集方案。

规则：
1. 每集 1-2 分钟，约 6-10 个分镜场景
2. 每集结尾要有钩子（悬念/反转）
3. 剧情节奏紧凑，删除冗余描写
4. 保留核心人物关系和冲突
5. 第 1 集要有强开场，最后一集要有完整结局
6. 如果原文内容不足以撑满 {target_episodes} 集，可适当减少

只输出 JSON：
{{
  "episodes": [
    {{
      "episode": 1,
      "title": "集标题",
      "summary": "本集剧情梗概(100字)",
      "key_conflict": "核心冲突",
      "cliffhanger": "结尾钩子",
      "estimated_scenes": 8,
      "priority": "high/medium/low"
    }}
  ],
  "total_episodes": {target_episodes},
  "character_extraction": [
    {{"name": "角色名", "role": "主角/配角/反派", "personality": "性格", "appearance": "外貌简述"}}
  ],
  "story_arc": "整体故事弧线描述",
  "pacing_analysis": "节奏分析"
}}"""

        genre_line = f"\n题材提示：{genre_hint}" if genre_hint else ""
        user_content = f"小说内容摘要：\n{summary_text}{genre_line}"

        try:
            result = await _llm_json(
                system_prompt,
                user_content,
                model=self.llm_model,
                fallback={
                    "episodes": [],
                    "total_episodes": 0,
                    "character_extraction": [],
                    "story_arc": "",
                    "pacing_analysis": "",
                },
            )
            return result
        except Exception as e:
            logger.warning("[NovelImport] 分集规划失败: %s", e)
            return {
                "episodes": [],
                "total_episodes": 0,
                "character_extraction": [],
                "story_arc": "",
                "pacing_analysis": "",
                "error": str(e),
            }

    async def generate_episode_script(
        self,
        episode_plan: Dict[str, Any],
        source_text: str,
        episode_num: int,
    ) -> Dict[str, Any]:
        """为单集生成详细剧本。"""
        system_prompt = """你是短剧编剧。请根据分集规划和原文素材，生成单集的详细分镜剧本。

每集包含 6-10 个分镜，每个分镜包含：
- 场景描述（地点、时间、氛围）
- 出场角色
- 对话/独白
- 动作指导
- 情绪标签
- 时长（秒）

只输出 JSON：
{
  "episode": 1,
  "title": "集标题",
  "total_duration": 90,
  "scenes": [
    {
      "scene_id": 1,
      "location": "场景地点",
      "time": "日/夜",
      "characters": ["角色A", "角色B"],
      "description": "画面描述",
      "dialogue": [{"speaker": "角色A", "line": "台词"}],
      "action": "动作指导",
      "emotion": "情绪标签",
      "duration": 12
    }
  ]
}"""

        import json
        user_content = json.dumps({
            "episode_plan": episode_plan,
            "source_text": source_text[:3000],
            "episode_num": episode_num,
        }, ensure_ascii=False, indent=2)

        try:
            result = await _llm_json(
                system_prompt,
                user_content,
                model=self.llm_model,
                fallback={"episode": episode_num, "title": "", "scenes": []},
            )
            return result
        except Exception as e:
            logger.warning("[NovelImport] 分集剧本生成失败 (ep %d): %s", episode_num, e)
            return {"episode": episode_num, "title": "", "scenes": [], "error": str(e)}


# 全局实例
_novel_agent: Optional[NovelImportAgent] = None


def get_novel_agent(llm_model: Optional[str] = None) -> NovelImportAgent:
    global _novel_agent
    if _novel_agent is None or llm_model:
        _novel_agent = NovelImportAgent(llm_model=llm_model)
    return _novel_agent
