"""
平台级总控大脑 Agent（PlatformBrain）

三层架构的核心编排层：
  用户自然语言 → 大脑路由决策 → Skill 执行 / Agent 流水线

职责：
1. 意图识别：判断用户需求应该走哪个 Skill 或 Agent
2. 参数提取：从自然语言中提取 Skill 需要的参数
3. 全局参数注入：统一画幅、渲染基准、镜头基准等
4. 多 Skill 串联：novel-to-shortdrama → storyboard-lite 链式执行
5. 流式反馈：SSE 实时推送执行进度
"""
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Awaitable

from app.agents.llm_utils import llm_json, llm_json_stream
from app.skills import list_skills, run_skill
from app.skills.base import SkillOutput, DEFAULT_GLOBAL_PARAMS
from app.core.model_tiers import TaskTier
from app.core.prompt_loader import load_prompt_or
from app.core.agent_registry import get_agent_meta_dict

logger = logging.getLogger(__name__)

# SSE 消息类型
MSG_ROUTING = "routing"
MSG_ROUTING_THINKING = "routing_thinking"   # #1 流式推理 token
MSG_ROUTING_DONE = "routing_done"
MSG_TOOL_CALL = "tool_call"                  # #1 工具调用决策
MSG_TOOL_RESULT = "tool_result"              # #1 工具执行结果
MSG_PARAM_EXTRACTION = "param_extraction"
MSG_PARAM_EXTRACTION_THINKING = "param_extraction_thinking"  # #1 流式参数提取
MSG_PARAM_EXTRACTION_DONE = "param_extraction_done"
MSG_SKILL_START = "skill_start"
MSG_SKILL_DONE = "skill_done"
MSG_SKILL_FAILED = "skill_failed"
MSG_COMPLETE = "complete"
MSG_ERROR = "error"
MSG_HEARTBEAT = "heartbeat"


class BrainMessage:
    """大脑 SSE 消息。"""
    def __init__(self, msg_type: str, content: str = "", agent: str = "", **extra):
        self.type = msg_type
        self.content = content
        self.agent = agent
        self.extra = extra
        # #4 角色化消息：自动注入 Agent 元数据
        if agent:
            self.extra["agent_meta"] = get_agent_meta_dict(agent)

    def to_dict(self) -> Dict[str, Any]:
        d = {"type": self.type, "content": self.content}
        if self.agent:
            d["agent"] = self.agent
        d.update(self.extra)
        return d

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False, default=str)}\n\n"


# ─── #1 工具定义（模拟 tool-calling schema） ────────────────────────

ROUTING_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "route_to_skill",
        "description": "路由到单个技能执行。用户意图明确属于某个 Skill 时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "技能 ID"},
                "prompt": {"type": "string", "description": "传递给该 Skill 的核心用户输入"},
                "params": {"type": "object", "description": "技能参数"},
            },
            "required": ["skill_id", "prompt"],
        },
    },
    {
        "name": "route_to_multi_skill",
        "description": "路由到多技能串联执行。用户需求需要连续调用多个 Skill 时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill_id": {"type": "string"},
                            "prompt": {"type": "string"},
                            "params": {"type": "object"},
                        },
                    },
                    "description": "按顺序执行的技能计划",
                },
            },
            "required": ["skill_plan"],
        },
    },
    {
        "name": "route_to_short_drama",
        "description": "路由到短剧全流程制作。用户需要创作完整短剧时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "核心创意一句话"},
            },
            "required": ["prompt"],
        },
    },
]


class PlatformBrainAgent:
    """平台级总控大脑 Agent：统一入口，解析自然语言需求并路由到 Skill 或短剧流水线。

    #1 升级为流式 tool-calling 决策 Agent：
    - 路由决策使用流式 LLM 输出，逐 token 推送推理过程
    - 模拟 tool-calling：定义工具 schema，LLM 输出 tool_call JSON
    - 参数提取也支持流式输出
    """

    name = "platform_brain"
    description = "平台级总控大脑：解析用户需求并路由到对应 Skill 或短剧流水线"

    # ─── 路由提示词（#5 外置化到 data/prompts/platform_brain_routing.md）───
    ROUTING_PROMPT = load_prompt_or("platform_brain_routing", """\
# Role
你是星河创作平台的总控大脑 Agent，负责解析用户的自然语言需求，并决定最合适的执行路径。

# 可用工具（tool-calling）
你拥有以下三个工具，必须选择其中一个调用来完成路由决策：

1. route_to_skill：路由到单个技能执行
   - 参数：skill_id（技能ID）、prompt（用户输入核心内容）、params（技能参数，可选）
   - 适用场景：用户意图明确属于某个具体 Skill

2. route_to_multi_skill：路由到多技能串联执行
   - 参数：skill_plan（技能执行计划数组，每个元素含 skill_id、prompt、params）
   - 适用场景：用户需求需要连续调用多个 Skill（如先改小说再做分镜）

3. route_to_short_drama：路由到短剧全流程制作
   - 参数：prompt（核心创意一句话）
   - 适用场景：用户需要创作完整短剧，涉及剧本→角色→场景→分镜→视频全流程

# 可用 Skill 清单
{{SKILL_LIST}}

# 路由规则
- 用户说"改编小说/小说转剧本" → route_to_skill: novel-to-shortdrama-script
- 用户说"做分镜/分镜表/视频提示词" → route_to_skill: storyboard-lite
- 用户说"小说改编+分镜/小说到视频全流程" → route_to_multi_skill: [novel-to-shortdrama-script, storyboard-lite]
- 用户说"创作短剧/完整短剧/全流程制作" → route_to_short_drama
- 用户说"漫剧生成/AI漫剧/小说转漫剧/漫剧全流程/Excel表格/人物设定+场景设定+分镜" → route_to_skill: drama-generator-pro
- 用户说"3D漫剧/精品漫剧/3D分镜/角色生图提示词/场景生图提示词/即梦角色图" → route_to_skill: muzi-3d-generator
- 用户说"即梦提示词/Seedance/视频提示词/运镜复刻/视频延长/视频编辑/音乐卡点/电商广告视频" → route_to_skill: seedance-prompt-zh
- 用户说"场景设计/生成场景" → route_to_skill: SKILL_003
- 用户说"拉片/复刻镜头" → route_to_skill: SKILL_002
- 用户说"世界杯/赛事" → route_to_skill: SKILL_004
- 用户说"航拍/无人机" → route_to_skill: SKILL_005
- 模糊需求（如"帮我做一个视频"）→ route_to_short_drama

# 输出 JSON 结构
{
  "tool_call": "route_to_skill | route_to_multi_skill | route_to_short_drama",
  "reasoning": "决策推理过程，简要说明为什么选择这个工具",
  "skill_plan": [
    {
      "skill_id": "novel-to-shortdrama-script",
      "prompt": "传递给该 Skill 的核心用户输入",
      "params": {"参数名": "参数值"}
    }
  ],
  "short_drama_params": {
    "prompt": "如果走短剧流水线，核心创意一句话"
  }
}

# 约束
- 必须选择一个工具调用（tool_call 字段必填）
- skill_plan 中的 prompt 必须是原始用户输入的核心内容，不要改写
- params 只填 Skill 定义中存在的参数名，不确定的留空让 Skill 用默认值
- route_to_short_drama 时 short_drama_params.prompt 必填
- route_to_skill 时 skill_plan 必须恰好包含一个元素
- route_to_multi_skill 时 skill_plan 必须包含至少两个元素
- 只输出 JSON，不要 Markdown 或解释文字
""")

    # ─── 参数提取提示词（#5 外置化到 data/prompts/platform_brain_param_extraction.md）───
    PARAM_EXTRACTION_PROMPT = load_prompt_or("platform_brain_param_extraction", """\
# Role
你是参数提取助手。从用户的自然语言输入中，提取指定 Skill 需要的参数。

# Skill 信息
- skill_id: {skill_id}
- skill_name: {skill_name}
- 可选参数: {param_schema}

# 用户输入
{user_input}

# 用户已提供的参数（前端传入，优先级高于提取结果）
{existing_params}

# 输出 JSON 结构
输出一个 JSON 对象，key 为参数名，value 为提取到的参数值。
只输出在可选参数列表中存在的参数名。
如果无法从输入中提取某个参数，不要包含该 key（让 Skill 使用默认值）。
只输出 JSON，不要解释文字。
""")

    # ─── 路由 ───

    @staticmethod
    def _build_routing_prompt() -> str:
        skills = list_skills()
        skill_list = "\n".join(
            f"- {s['skill_id']}: {s['skill_name']} — {', '.join(s['tags'])}"
            for s in skills
        )
        return PlatformBrainAgent.ROUTING_PROMPT.replace("{{SKILL_LIST}}", skill_list)

    @staticmethod
    def _normalize_route_result(result: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """规范化路由结果：将 tool_call 转换为 decision 等内部字段。

        #1 兼容旧格式（decision 字段）和新格式（tool_call 字段）。
        """
        # 优先使用新格式 tool_call
        tool_call = result.get("tool_call", "")
        if tool_call:
            decision_map = {
                "route_to_skill": "single_skill",
                "route_to_multi_skill": "multi_skill",
                "route_to_short_drama": "short_drama",
            }
            result["decision"] = decision_map.get(tool_call, "short_drama")
        # 兼容旧格式：直接使用 decision 字段
        if "decision" not in result:
            result["decision"] = "short_drama"
        # 兜底：short_drama_params
        if result.get("decision") == "short_drama" and not result.get("short_drama_params"):
            result["short_drama_params"] = {"prompt": user_input}
        # 兜底：skill_plan
        if result.get("decision") in ("single_skill", "multi_skill") and not result.get("skill_plan"):
            result["skill_plan"] = []
        return result

    @staticmethod
    async def route(user_input: str) -> Dict[str, Any]:
        """解析用户需求并返回路由决策（非流式）。"""
        prompt = PlatformBrainAgent._build_routing_prompt()
        result = await llm_json(
            prompt,
            f"用户需求：{user_input}\n请输出路由决策 JSON。",
            max_tokens=1024,
            temperature=0.1,
            tier=TaskTier.LITE,
            agent_name="platform_brain",
            fallback={
                "tool_call": "route_to_short_drama",
                "decision": "short_drama",
                "reasoning": "LLM 解析失败，默认走短剧全流程",
                "skill_plan": [],
                "short_drama_params": {"prompt": user_input},
            },
        )
        return PlatformBrainAgent._normalize_route_result(result, user_input)

    @staticmethod
    async def route_stream(
        user_input: str,
        on_message: Optional[Callable[["BrainMessage"], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """#1 流式路由决策：逐 token 推送推理过程到前端。

        使用 llm_json_stream 实现流式输出，前端可实时看到大脑的推理过程。
        最终返回与 route() 相同格式的路由决策 JSON。
        """
        prompt = PlatformBrainAgent._build_routing_prompt()

        # #1 流式回调：逐 token 推送推理过程
        async def on_token(token: str):
            if on_message:
                await on_message(BrainMessage(
                    MSG_ROUTING_THINKING,
                    token,
                    agent="platform_brain",
                ))

        result = await llm_json_stream(
            prompt,
            f"用户需求：{user_input}\n请输出路由决策 JSON。",
            max_tokens=1024,
            temperature=0.1,
            tier=TaskTier.LITE,
            agent_name="platform_brain",
            on_token=on_token,
            fallback={
                "tool_call": "route_to_short_drama",
                "decision": "short_drama",
                "reasoning": "LLM 流式解析失败，默认走短剧全流程",
                "skill_plan": [],
                "short_drama_params": {"prompt": user_input},
            },
        )
        return PlatformBrainAgent._normalize_route_result(result, user_input)

    # ─── 参数提取 ───

    @staticmethod
    def _get_skill_info(skill_id: str) -> Optional[Dict[str, Any]]:
        """获取 Skill 的元数据。"""
        for s in list_skills():
            if s["skill_id"] == skill_id:
                return s
        return None

    @staticmethod
    async def extract_params(
        user_input: str,
        skill_id: str,
        existing_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """从用户输入中提取 Skill 参数，与已有参数合并（非流式）。"""
        return await PlatformBrainAgent._extract_params_impl(
            user_input, skill_id, existing_params, on_message=None,
        )

    @staticmethod
    async def extract_params_stream(
        user_input: str,
        skill_id: str,
        existing_params: Optional[Dict[str, Any]] = None,
        on_message: Optional[Callable[["BrainMessage"], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """#1 流式参数提取：逐 token 推送推理过程到前端。"""
        return await PlatformBrainAgent._extract_params_impl(
            user_input, skill_id, existing_params, on_message=on_message,
        )

    @staticmethod
    async def _extract_params_impl(
        user_input: str,
        skill_id: str,
        existing_params: Optional[Dict[str, Any]] = None,
        on_message: Optional[Callable[["BrainMessage"], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """参数提取内部实现，支持流式和非流式两种模式。"""
        skill_info = PlatformBrainAgent._get_skill_info(skill_id)
        if not skill_info:
            return existing_params or {}

        # 构建参数 schema 描述
        param_schema = []
        for p in skill_info.get("params", []):
            options_str = f" (选项: {', '.join(p.get('options', []))})" if p.get("options") else ""
            default_str = f" [默认: {p.get('default')}]" if p.get("default") else ""
            param_schema.append(f"{p['name']}: {p.get('description', '')}{options_str}{default_str}")

        prompt = PlatformBrainAgent.PARAM_EXTRACTION_PROMPT.format(
            skill_id=skill_id,
            skill_name=skill_info.get("skill_name", ""),
            param_schema="\n".join(param_schema) or "无可选参数",
            user_input=user_input[:2000],
            existing_params=json.dumps(existing_params or {}, ensure_ascii=False),
        )

        if on_message:
            # #1 流式模式
            async def on_token(token: str):
                if on_message:
                    await on_message(BrainMessage(
                        MSG_PARAM_EXTRACTION_THINKING,
                        token,
                        agent="param_extractor",
                    ))

            result = await llm_json_stream(
                "你是参数提取助手，只输出 JSON。",
                prompt,
                max_tokens=512,
                temperature=0.1,
                tier=TaskTier.LITE,
                agent_name="param_extractor",
                on_token=on_token,
                fallback={},
            )
        else:
            # 非流式模式
            result = await llm_json(
                "你是参数提取助手，只输出 JSON。",
                prompt,
                max_tokens=512,
                temperature=0.1,
                tier=TaskTier.LITE,
                agent_name="param_extractor",
                fallback={},
            )

        # 合并：提取结果覆盖已有参数（提取到的才覆盖）
        merged = dict(existing_params or {})
        if isinstance(result, dict):
            for k, v in result.items():
                if v is not None and str(v).strip():
                    merged[k] = v
        return merged

    # ─── 单 Skill 执行 ───

    @staticmethod
    async def execute_skill(
        skill_id: str,
        user_input: str,
        params: Optional[Dict[str, Any]] = None,
        global_params: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        llm_model: Optional[str] = None,
    ) -> SkillOutput:
        """执行单个 Skill，注入全局参数和多轮对话历史。"""
        gp = {**DEFAULT_GLOBAL_PARAMS, **(global_params or {})}
        return await run_skill(skill_id, user_input, params, gp, history=history, llm_model=llm_model)

    # ─── 多 Skill 串联执行 ───

    @staticmethod
    async def execute_multi_skill(
        skill_plan: List[Dict[str, Any]],
        global_params: Optional[Dict[str, Any]] = None,
        on_message: Optional[Callable[[BrainMessage], Awaitable[None]]] = None,
        llm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按顺序执行多个 Skill，前一个的输出可作为后一个的输入。"""
        gp = {**DEFAULT_GLOBAL_PARAMS, **(global_params or {})}
        results: List[Dict[str, Any]] = []
        total = len(skill_plan)

        for idx, step in enumerate(skill_plan):
            skill_id = step.get("skill_id", "")
            prompt = step.get("prompt", "")
            params = step.get("params", {})

            # 多 Skill 链：第二个起，把前一个的输出注入 prompt
            if idx > 0 and results:
                prev = results[-1]
                prev_data = prev.get("data", {})
                # 提取前一个 Skill 的核心文本输出
                prev_text = (
                    prev_data.get("full_script") or
                    prev_data.get("full_markdown") or
                    prev_data.get("episode_outline") or
                    prev_data.get("adaptation_overview") or
                    json.dumps(prev_data, ensure_ascii=False)[:2000]
                )
                prompt = f"{prompt}\n\n--- 上一步输出 ---\n{prev_text}"

            skill_info = PlatformBrainAgent._get_skill_info(skill_id)
            skill_name = skill_info.get("skill_name", skill_id) if skill_info else skill_id

            if on_message:
                await on_message(BrainMessage(
                    MSG_SKILL_START,
                    f"正在执行技能：{skill_name}（第 {idx + 1}/{total} 步）",
                    skill_id=skill_id,
                    skill_name=skill_name,
                    step=idx + 1,
                    total=total,
                ))

            try:
                output = await run_skill(skill_id, prompt, params, gp, llm_model=llm_model)
                result_entry = {
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "status": output.status,
                    "data": output.data,
                    "error": output.error,
                    "step": idx + 1,
                }
                results.append(result_entry)

                if on_message:
                    await on_message(BrainMessage(
                        MSG_SKILL_DONE if output.status == "success" else MSG_SKILL_FAILED,
                        f"技能 {skill_name} 执行{'完成' if output.status == 'success' else '失败'}",
                        skill_id=skill_id,
                        skill_name=skill_name,
                        step=idx + 1,
                        total=total,
                        data=output.data,
                        error=output.error,
                    ))

                if output.status != "success":
                    # 某步失败，停止链式执行
                    break

            except Exception as exc:
                logger.error("[PlatformBrain] multi_skill step %d failed: %s", idx + 1, exc, exc_info=True)
                result_entry = {
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "status": "failed",
                    "data": {},
                    "error": str(exc),
                    "step": idx + 1,
                }
                results.append(result_entry)
                if on_message:
                    await on_message(BrainMessage(
                        MSG_SKILL_FAILED,
                        f"技能 {skill_name} 执行异常: {exc}",
                        skill_id=skill_id,
                        skill_name=skill_name,
                        step=idx + 1,
                        error=str(exc),
                    ))
                break

        return {
            "status": "success" if all(r["status"] == "success" for r in results) else "partial_failed",
            "decision": "multi_skill",
            "results": results,
        }

    # ─── 完整执行（非流式） ───

    @staticmethod
    async def execute(
        user_input: str,
        global_params: Optional[Dict[str, Any]] = None,
        llm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """总控入口：先路由，再执行对应的 Skill 或返回短剧流水线参数。"""
        route_result = await PlatformBrainAgent.route(user_input)
        decision = route_result.get("decision", "single_skill")

        if decision == "short_drama":
            return {
                "status": "routed_to_short_drama",
                "decision": decision,
                "reasoning": route_result.get("reasoning", ""),
                "short_drama_params": route_result.get("short_drama_params", {"prompt": user_input}),
            }

        skill_plan = route_result.get("skill_plan", [])
        if not skill_plan:
            # 兜底：走短剧全流程
            return {
                "status": "routed_to_short_drama",
                "decision": "short_drama",
                "reasoning": "无法识别具体 Skill，走短剧全流程",
                "short_drama_params": {"prompt": user_input},
            }

        if decision == "multi_skill":
            return await PlatformBrainAgent.execute_multi_skill(skill_plan, global_params, llm_model=llm_model)

        # single_skill
        first_skill = skill_plan[0]
        skill_id = first_skill.get("skill_id", "")
        prompt = first_skill.get("prompt", user_input)
        params = first_skill.get("params", {})

        # 参数提取
        params = await PlatformBrainAgent.extract_params(user_input, skill_id, params)

        output = await PlatformBrainAgent.execute_skill(skill_id, prompt, params, global_params, llm_model=llm_model)

        return {
            "status": "success" if output.status == "success" else "failed",
            "decision": decision,
            "reasoning": route_result.get("reasoning", ""),
            "skill_id": output.skill_id,
            "skill_plan": skill_plan,
            "data": output.data,
            "error": output.error,
        }

    # ─── 完整执行（流式 SSE） ───

    @staticmethod
    async def execute_stream(
        user_input: str,
        global_params: Optional[Dict[str, Any]] = None,
        on_message: Optional[Callable[[BrainMessage], Awaitable[None]]] = None,
        llm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """#1 流式总控入口：实时推送路由推理、工具调用决策、技能执行进度。

        升级点：
        - 使用 route_stream 流式输出路由推理 token
        - 发送 MSG_TOOL_CALL 工具调用决策消息
        - 使用 extract_params_stream 流式参数提取
        """
        start_time = time.time()

        # 1. 流式路由决策
        if on_message:
            await on_message(BrainMessage(MSG_ROUTING, "正在分析您的需求...", agent="platform_brain"))

        route_result = await PlatformBrainAgent.route_stream(user_input, on_message=on_message)
        decision = route_result.get("decision", "single_skill")
        reasoning = route_result.get("reasoning", "")
        tool_call = route_result.get("tool_call", f"route_to_{decision}")

        # #1 发送工具调用决策消息
        if on_message:
            await on_message(BrainMessage(
                MSG_TOOL_CALL,
                f"🔧 调用工具：{tool_call}",
                agent="platform_brain",
                tool_name=tool_call,
                decision=decision,
                reasoning=reasoning,
                skill_plan=route_result.get("skill_plan", []),
                short_drama_params=route_result.get("short_drama_params"),
            ))

        if on_message:
            await on_message(BrainMessage(
                MSG_ROUTING_DONE,
                f"需求分析完成：{reasoning}",
                decision=decision,
                reasoning=reasoning,
            ))

        # 2. 路由到短剧全流程
        if decision == "short_drama":
            sd_params = route_result.get("short_drama_params", {"prompt": user_input})
            if on_message:
                await on_message(BrainMessage(
                    MSG_TOOL_RESULT,
                    f"路由结果：短剧全流程制作",
                    agent="platform_brain",
                    tool_name=tool_call,
                    result="routed_to_short_drama",
                ))
                await on_message(BrainMessage(
                    MSG_COMPLETE,
                    "建议走短剧全流程制作，正在为您准备...",
                    decision=decision,
                    short_drama_params=sd_params,
                ))
            return {
                "status": "routed_to_short_drama",
                "decision": decision,
                "reasoning": reasoning,
                "short_drama_params": sd_params,
            }

        skill_plan = route_result.get("skill_plan", [])
        if not skill_plan:
            sd_params = {"prompt": user_input}
            if on_message:
                await on_message(BrainMessage(
                    MSG_TOOL_RESULT,
                    f"路由结果：无法识别具体技能，回退到短剧全流程",
                    agent="platform_brain",
                    tool_name=tool_call,
                    result="fallback_to_short_drama",
                ))
                await on_message(BrainMessage(
                    MSG_COMPLETE,
                    "无法识别具体技能，建议走短剧全流程制作",
                    decision="short_drama",
                    short_drama_params=sd_params,
                ))
            return {
                "status": "routed_to_short_drama",
                "decision": "short_drama",
                "reasoning": "无法识别具体 Skill",
                "short_drama_params": sd_params,
            }

        # 3. 多 Skill 串联
        if decision == "multi_skill":
            if on_message:
                await on_message(BrainMessage(
                    MSG_TOOL_RESULT,
                    f"路由结果：多技能串联（{len(skill_plan)}个技能）",
                    agent="platform_brain",
                    tool_name=tool_call,
                    result="multi_skill",
                    skill_plan=skill_plan,
                ))
            result = await PlatformBrainAgent.execute_multi_skill(skill_plan, global_params, on_message)
            if on_message:
                elapsed = round(time.time() - start_time, 1)
                await on_message(BrainMessage(
                    MSG_COMPLETE,
                    f"全部技能执行完成（耗时 {elapsed}s）",
                    decision="multi_skill",
                    results=result.get("results", []),
                ))
            return result

        # 4. 单 Skill 执行
        first_skill = skill_plan[0]
        skill_id = first_skill.get("skill_id", "")
        prompt = first_skill.get("prompt", user_input)
        params = first_skill.get("params", {})

        skill_info = PlatformBrainAgent._get_skill_info(skill_id)
        skill_name = skill_info.get("skill_name", skill_id) if skill_info else skill_id

        if on_message:
            await on_message(BrainMessage(
                MSG_TOOL_RESULT,
                f"路由结果：{skill_name}（{skill_id}）",
                agent="platform_brain",
                tool_name=tool_call,
                result="single_skill",
                skill_id=skill_id,
            ))

        # 4a. 流式参数提取
        if on_message:
            await on_message(BrainMessage(MSG_PARAM_EXTRACTION, f"正在为「{skill_name}」提取参数...", agent="param_extractor"))
        params = await PlatformBrainAgent.extract_params_stream(user_input, skill_id, params, on_message=on_message)
        if on_message:
            await on_message(BrainMessage(
                MSG_PARAM_EXTRACTION_DONE,
                f"参数提取完成",
                params=params,
            ))

        # 4b. 执行 Skill
        if on_message:
            await on_message(BrainMessage(
                MSG_SKILL_START,
                f"正在执行技能：{skill_name}",
                skill_id=skill_id,
                skill_name=skill_name,
                step=1,
                total=1,
            ))

        try:
            output = await PlatformBrainAgent.execute_skill(skill_id, prompt, params, global_params, llm_model=llm_model)
            if on_message:
                await on_message(BrainMessage(
                    MSG_SKILL_DONE if output.status == "success" else MSG_SKILL_FAILED,
                    f"技能 {skill_name} 执行{'完成' if output.status == 'success' else '失败'}",
                    skill_id=skill_id,
                    skill_name=skill_name,
                    step=1,
                    total=1,
                    data=output.data,
                    error=output.error,
                ))
        except Exception as exc:
            logger.error("[PlatformBrain] execute_stream skill failed: %s", exc, exc_info=True)
            output = SkillOutput(skill_id=skill_id, status="failed", error=str(exc))
            if on_message:
                await on_message(BrainMessage(
                    MSG_SKILL_FAILED,
                    f"技能 {skill_name} 执行异常: {exc}",
                    skill_id=skill_id,
                    error=str(exc),
                ))

        elapsed = round(time.time() - start_time, 1)
        if on_message:
            await on_message(BrainMessage(
                MSG_COMPLETE,
                f"执行完成（耗时 {elapsed}s）",
                decision="single_skill",
                skill_id=skill_id,
                data=output.data,
                error=output.error,
            ))

        return {
            "status": "success" if output.status == "success" else "failed",
            "decision": "single_skill",
            "reasoning": reasoning,
            "skill_id": skill_id,
            "skill_plan": skill_plan,
            "params": params,
            "data": output.data,
            "error": output.error,
        }

    # ─── 指定 Skill 执行（用户明确选了某个技能卡片） ───

    @staticmethod
    async def execute_skill_through_brain(
        skill_id: str,
        user_input: str,
        params: Optional[Dict[str, Any]] = None,
        global_params: Optional[Dict[str, Any]] = None,
        on_message: Optional[Callable[[BrainMessage], Awaitable[None]]] = None,
        conversation_id: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """用户明确选择某个 Skill 后，大脑增强执行：
        1. #1 流式参数提取（从用户输入中补全缺失参数）
        2. 全局参数注入
        3. 执行 Skill（传入多轮对话历史）
        """
        start_time = time.time()
        skill_info = PlatformBrainAgent._get_skill_info(skill_id)
        skill_name = skill_info.get("skill_name", skill_id) if skill_info else skill_id

        # 0. 从数据库加载对话历史（多轮上下文）
        history: Optional[List[Dict[str, Any]]] = None
        if conversation_id:
            try:
                from app.core.database import SessionLocal
                from app.models.skill_conversation import SkillMessage
                db = SessionLocal()
                try:
                    msgs = db.query(SkillMessage).filter(
                        SkillMessage.conversation_id == conversation_id
                    ).order_by(SkillMessage.created_at.asc()).all()
                    if msgs:
                        history = [
                            {"role": m.role, "content": m.content}
                            for m in msgs
                            if m.role in ("user", "assistant") and m.content
                        ]
                        logger.info("[PlatformBrain] 加载对话历史 %d 条 conversation=%s", len(history), conversation_id)
                finally:
                    db.close()
            except Exception as exc:
                logger.warning("[PlatformBrain] 加载对话历史失败 conversation=%s: %s", conversation_id, exc)

        # 1. 流式参数提取
        if on_message:
            await on_message(BrainMessage(MSG_PARAM_EXTRACTION, f"正在为「{skill_name}」提取参数...", agent="param_extractor"))
        enhanced_params = await PlatformBrainAgent.extract_params_stream(user_input, skill_id, params, on_message=on_message)
        if on_message:
            await on_message(BrainMessage(
                MSG_PARAM_EXTRACTION_DONE,
                "参数提取完成",
                params=enhanced_params,
            ))

        # 2. 执行 Skill
        if on_message:
            await on_message(BrainMessage(
                MSG_SKILL_START,
                f"正在执行技能：{skill_name}",
                skill_id=skill_id,
                skill_name=skill_name,
                step=1,
                total=1,
            ))

        try:
            output = await PlatformBrainAgent.execute_skill(skill_id, user_input, enhanced_params, global_params, history=history, llm_model=llm_model)
            if on_message:
                await on_message(BrainMessage(
                    MSG_SKILL_DONE if output.status == "success" else MSG_SKILL_FAILED,
                    f"技能 {skill_name} 执行{'完成' if output.status == 'success' else '失败'}",
                    skill_id=skill_id,
                    skill_name=skill_name,
                    step=1,
                    total=1,
                    data=output.data,
                    error=output.error,
                ))
        except Exception as exc:
            logger.error("[PlatformBrain] execute_skill_through_brain failed: %s", exc, exc_info=True)
            output = SkillOutput(skill_id=skill_id, status="failed", error=str(exc))
            if on_message:
                await on_message(BrainMessage(
                    MSG_SKILL_FAILED,
                    f"技能 {skill_name} 执行异常: {exc}",
                    skill_id=skill_id,
                    error=str(exc),
                ))

        elapsed = round(time.time() - start_time, 1)
        if on_message:
            await on_message(BrainMessage(
                MSG_COMPLETE,
                f"执行完成（耗时 {elapsed}s）",
                decision="single_skill",
                skill_id=skill_id,
                data=output.data,
                error=output.error,
            ))

        return {
            "status": "success" if output.status == "success" else "failed",
            "decision": "single_skill",
            "skill_id": skill_id,
            "params": enhanced_params,
            "data": output.data,
            "error": output.error,
        }


platform_brain = PlatformBrainAgent()
