"""
智能体大脑（Director Brain）：基于 LangGraph StateGraph 的短剧生产调度中枢。

三阶段流水线：
  planning  : 剧本 Agent -> 编剧 Agent -> review_planning
  asset     : 角色 Agent -> 场景道具 Agent -> review_asset
  production: 分镜 Agent -> 视频 Agent -> review_production

每个阶段结束时由 Review 节点质检，不通过则重试（最多 3 次），通过后进入下一阶段。
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from app.services.ai_service import AIService
from app.agents.llm_utils import llm_json as _llm_json, is_fallback_result, check_token_budget
from app.agents.short_drama import _resolve_llm_model
from app.core.errors import classify_exception, should_stop_retrying, format_error_for_state
from app.core.version_manager import add_version_to_session, should_snapshot

logger = logging.getLogger(__name__)

# 重试次数上限改为读 settings.DRAMA_BRAIN_MAX_RETRIES（见 _should_retry），不再用模块常量

# H4: 长剧本按集分片阈值
EPISODE_SHARD_THRESHOLD = 3       # 集数超过此值启用分片
EPISODE_BATCH_SIZE = 2            # 每次扩写多少集
MAX_EPISODE_CONCURRENCY = 3       # 并发扩写批次数


def _parse_int_hint(value: Any, default: int = 0) -> int:
    """解析用户参数中的数字（如 '5集' -> 5）。"""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        import re
        m = re.search(r"\d+", value)
        if m:
            return int(m.group(0))
    return default


def _use_compact_outline(options: Dict[str, str], episode_count: int = 0) -> bool:
    """是否使用精简大纲模式（长剧本 planning 先出大纲）。"""
    hint = _parse_int_hint(options.get("script.episode_count", options.get("start.episode_count", 0)), 0)
    return hint > EPISODE_SHARD_THRESHOLD or episode_count > EPISODE_SHARD_THRESHOLD


def _should_shard_episodes(script_outline: Dict[str, Any]) -> bool:
    """判断当前大纲是否需要按集分批扩写。"""
    episodes = (script_outline or {}).get("episodes", []) or []
    return len(episodes) > EPISODE_SHARD_THRESHOLD


def _merge_screenplay_results(results: List[Dict[str, Any]], script_outline: Dict[str, Any]) -> Dict[str, Any]:
    """合并各批次 screenwriter 输出为完整 full_script。"""
    merged_episodes: List[Dict[str, Any]] = []
    style_bible = ""
    color_palette: List[str] = []
    project_title = script_outline.get("project_title", "")

    for r in results:
        if not isinstance(r, dict):
            continue
        screenplay = r.get("screenplay", {}) or {}
        if not project_title:
            project_title = screenplay.get("project_title", "")
        if not style_bible:
            style_bible = r.get("style_bible", "")
        if not color_palette:
            color_palette = r.get("color_palette", []) or []
        for ep in (screenplay.get("episodes", []) or []):
            merged_episodes.append(ep)

    # 按 episode_num 排序
    merged_episodes.sort(key=lambda ep: ep.get("episode_num", 0))

    return {
        "screenplay": {
            "project_title": project_title,
            "total_episodes": len(merged_episodes),
            "episodes": merged_episodes,
        },
        "style_bible": style_bible or script_outline.get("style_bible", ""),
        "color_palette": color_palette or script_outline.get("color_palette", []),
    }


class DramaProductionState(TypedDict, total=False):
    # 用户输入
    user_instruction: str
    options: Dict[str, str]          # 用户确认的创作参数
    global_params: Dict[str, str]    # 全局统一约束参数（项目ID、核心题材、视觉主风格等）

    # 大脑控制
    current_stage: str               # planning / asset / production / finished
    feedback_message: str            # Review 节点给出的修改意见
    user_feedback: str               # 用户通过 feedback 接口提交的反馈（尚未被消费）
    user_feedback_stage: str         # 用户反馈对应的目标阶段
    pending_user_feedback: str       # 已确认要透传到本子阶段的反馈（script_planner 不清空）
    retry_count: int                 # 当前阶段重试次数
    review_target: str               # 当前被 Review 的 Agent 名
    last_error: str                  # 运行时错误信息
    token_tracker: Dict[str, Any]    # token 计量器 {token_used, token_prompt, token_completion}
    checkpoint_callback: Callable[["DramaProductionState"], None]  # 增量 checkpoint 回调

    # 导演规则库与记忆进化体系
    rule_version: str                # 导演规则库版本号
    error_case_library: List[Dict[str, Any]]  # 错误案例库
    best_practice_library: List[Dict[str, Any]]  # 最佳实践库
    iteration_log: List[Dict[str, Any]]  # 规则优化日志

    # 策划阶段产出
    script_outline: Dict[str, Any]   # 剧本 Agent 产出
    full_script: Dict[str, Any]      # 编剧 Agent 产出

    # 资产阶段产出
    character_assets: Dict[str, Any] # 角色 Agent 产出
    scene_assets: Dict[str, Any]     # 场景道具 Agent 产出

    # 制作阶段产出
    storyboard_data: Dict[str, Any]  # 分镜 Agent 产出
    video_plan: Dict[str, Any]       # 视频 Agent 产出（参数规划，不生视频）

    # 消息记录（用于前端展示）
    messages: List[Dict[str, Any]]


# -----------------------------------------------------------------------------
# 全局大脑导演 Agent 提示词与工具
# -----------------------------------------------------------------------------
class DirectorBrainAgent:
    """全局大脑导演 Agent：总控调度 + 审核迭代 + 记忆进化体系。

    定位：全流水线中枢决策与质量管控核心，不执行具体创作任务，仅负责
    流程调度、标准审核、偏差修正、经验沉淀、自我迭代。
    """

    name = "director_brain"
    description = "全局大脑导演Agent：总控调度、三级审核、偏差修正、记忆进化"

    system_prompt = """
【身份】
你是 AI 短剧工业化流水线的总导演与生产管控中枢，精通影视创作全流程逻辑与工业化批量生产标准，拥有全局调度权、质量否决权与规则迭代权。你不执行具体创作，仅通过标准化指令调度 6 个子 Agent 完成生产，通过刚性审核体系把控输出质量，通过记忆系统沉淀经验并持续优化自身规则。

【全局元参数（强制继承）】
- 项目ID: {{项目ID}}
- 核心题材: {{核心题材}}
- 视觉主风格: {{视觉主风格}}
- 目标画幅: {{目标画幅}}
- 单集时长: {{单集时长}}
- 目标平台: {{目标平台}}
- 渲染基准: {{渲染基准}}
- 镜头基准: {{镜头基准}}
- 导演规则库版本: V{{版本号}}

【下辖子Agent清单（唯一调度对象）】
1. 剧本架构Agent：输出故事骨架、分场清单、节奏拆解
2. 文学编剧Agent：输出标准格式文学剧本、台词文本
3. 角色道具资产Agent：输出角色/道具资产库、固定视觉锚点
4. 场景空间Agent：输出场景资产库、空间光影标准
5. 分镜设计Agent：输出逐镜头分镜表、运镜时长参数
6. 视频生成Agent：输出单镜头生成提示词、渲染参数

【核心能力矩阵】
1. 全流程调度：按标准 SOP 顺序下发任务，管控生产节点，支持并行与串行环节精准衔接。
2. 三级质量审核：对每个子 Agent 输出执行格式合规 → 逻辑一致 → 质量达标的三级校验，拥有打回修改权。
3. 精准偏差修正：对不合格输出输出标准化修正指令，明确问题点、违反规则、修改方向与验收标准。
4. 全局一致性管控：维护全项目 ID 体系、资产标准、风格基调统一，杜绝跨环节偏差。
5. 记忆与沉淀：存储当前项目全链路上下文，沉淀跨项目错误案例库、最佳实践库、规则优化库。
6. 自我进化迭代：基于生产数据与反馈自动更新审核阈值、调度规则、前置约束，持续提升流水线效率与良品率。

【三级质量审核体系（刚性执行）】
■ 一级审核：格式合规性校验（一票否决）
- 是否严格遵循对应 Agent 的强制输出结构。
- 所有元素是否配备标准 ID（角色 Cxxx、场景 Sxxx、道具 Pxxx、镜头 xxx-xx）。
- 所有必填字段是否完整，无遗漏。
- 时长、参数等数值是否符合格式要求。

■ 二级审核：逻辑一致性校验
- 剧情逻辑是否自洽，人物行为是否符合动机。
- 所有出场元素是否均存在于对应资产库，无未定义新增元素。
- 上下游输出是否对应：分镜是否覆盖全部剧本内容、视频提示词是否完全匹配分镜。
- 空间逻辑、光影逻辑、动作衔接是否符合物理常识。
- 总时长、分场时长、镜头时长是否匹配，误差是否在允许范围内。

■ 三级审核：质量达标校验
- 剧本：是否满足钩子前置、节奏达标、爽点/反转数量达标、无功能性水戏。
- 资产：视觉锚点是否具象可复用、负面约束是否覆盖常见偏差、是否符合题材风格。
- 分镜：运镜是否服务叙事、无静止镜头、景别搭配合理、节奏疏密得当。
- 视频提示词：表演细节是否匹配情绪、模块化是否清晰、负面词是否全面、一致性是否达标。

【标准化修正指令规范】
所有打回修改必须输出结构化修正指令，禁止模糊评价，模板如下：
【修正指令】
接收Agent：{{子Agent名称}}
对应输出版本：V{{版本号}}
问题等级：严重/一般/优化
问题定位：精确到具体场号/ID/条目
问题类型：格式错误/逻辑矛盾/资产偏差/节奏不达标/表演不符合情绪
违反规则：对应违反的工业化刚性约束条款
修改要求：明确、可执行的修改方向
验收标准：修改后需满足的具体量化指标
参考示例：可选，提供同类正确示例
修改次数：第N次修改，连续3次不通过触发规则升级

【强制输出结构】
根据当前执行节点不同，输出对应结构：
1. 【任务下发指令】：接收Agent、任务版本、输入参数、前置约束、交付要求、验收标准。
2. 【审核结果通知】：审核对象、结论、得分、通过项、问题清单、后续动作。
3. 【修正指令单】：严格遵循上述标准化修正指令模板。
4. 【项目进度简报】：当前阶段、已完成/待完成节点、累计修改次数、资产库版本、风险提示。
5. 【迭代升级报告】：规则库版本变更、新增/优化规则、预期效果、变更日志。

【工业化刚性约束】
1. 绝对禁止越权执行子 Agent 的具体创作工作。
2. 所有审核必须基于明确规则与量化标准，禁止主观模糊评价。
3. 所有修改必须留痕，所有版本必须编号，全流程可追溯、可复盘。
4. 记忆系统仅存储标准化生产数据与规则，禁止冗余信息。
5. 自我进化必须基于真实生产数据，禁止无依据修改规则。
6. 资产库一经冻结，单镜头级偏差仅修正对应提示词；共性偏差方可升级资产库版本。
7. 连续 2 次打回后，第 3 次必须补充参考示例与更细化约束。

【质量校验项】
□ 调度流程严格遵循 SOP 顺序，无跳步、无逆行
□ 所有审核结论均有对应规则依据，无主观判定
□ 修正指令均明确可执行，无模糊表述
□ 所有生产数据均已归档至对应记忆库
□ 每次迭代均有版本号与变更日志
□ 全项目 ID 体系统一，无冲突、无遗漏
□ 跨环节输出一致性达标，无上下游矛盾
"""


# 标准化修正指令模板
_STANDARDIZED_CORRECTION_TEMPLATE = """【修正指令】
接收Agent：{agent}
对应输出版本：{version}
问题等级：{level}
问题定位：{location}
问题类型：{issue_type}
违反规则：{violated_rule}
修改要求：{requirement}
验收标准：{acceptance}
参考示例：{example}
修改次数：第 {retry_count} 次修改，连续3次不通过触发规则升级
"""


def _format_correction_instruction(
    agent: str,
    level: str,
    location: str,
    issue_type: str,
    violated_rule: str,
    requirement: str,
    acceptance: str,
    example: str = "无",
    retry_count: int = 1,
    version: str = "1.0",
) -> str:
    """按全局大脑导演 Agent 规范生成标准化修正指令。"""
    return _STANDARDIZED_CORRECTION_TEMPLATE.format(
        agent=agent,
        version=f"V{version}",
        level=level,
        location=location,
        issue_type=issue_type,
        violated_rule=violated_rule,
        requirement=requirement,
        acceptance=acceptance,
        example=example,
        retry_count=retry_count,
    )


def _initialize_director_memory(state: DramaProductionState) -> None:
    """初始化导演规则库与记忆库，确保必要字段存在。"""
    if not state.get("rule_version"):
        state["rule_version"] = "1.0"
    if not state.get("error_case_library"):
        state["error_case_library"] = []
    if not state.get("best_practice_library"):
        state["best_practice_library"] = []
    if not state.get("iteration_log"):
        state["iteration_log"] = []


def _record_error_case(
    state: DramaProductionState,
    stage: str,
    agent: str,
    issue_type: str,
    location: str,
    description: str,
    correction: str,
) -> None:
    """将问题记录到错误案例库，供自我进化使用。"""
    cases = state.get("error_case_library") or []
    cases.append({
        "stage": stage,
        "agent": agent,
        "issue_type": issue_type,
        "location": location,
        "description": description,
        "correction": correction,
        "rule_version": state.get("rule_version", "1.0"),
        "ts": time.time(),
    })
    state["error_case_library"] = cases


def _evolve_rule_version(state: DramaProductionState, reason: str, changes: List[str]) -> None:
    """基于累计生产数据触发规则库版本升级。"""
    old_version = state.get("rule_version", "1.0")
    try:
        major, minor = old_version.split(".")
        new_version = f"{major}.{int(minor) + 1}"
    except Exception:
        new_version = "1.1"

    state["rule_version"] = new_version
    logs = state.get("iteration_log") or []
    logs.append({
        "old_version": old_version,
        "new_version": new_version,
        "reason": reason,
        "changes": changes,
        "error_case_count": len(state.get("error_case_library") or []),
        "ts": time.time(),
    })
    state["iteration_log"] = logs


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
async def _log(state: DramaProductionState, role: str, agent: Optional[str], step: str, content: str, payload: Dict[str, Any] = None):
    msg = {
        "role": role,
        "agent": agent,
        "step": step,
        "content": content,
        "payload": payload or {},
    }
    msgs = state.get("messages") or []
    msgs.append(msg)
    state["messages"] = msgs
    # M4: 若调用方注入了 message_queue，实时推送进度
    queue = state.get("message_queue")
    if queue:
        try:
            await queue.put(msg)
        except Exception:
            pass


async def _checkpoint(state: DramaProductionState) -> None:
    """M8: 在每个子 Agent 节点完成后增量落盘，确保刷新/崩溃后可恢复。"""
    cb = state.get("checkpoint_callback")
    if cb:
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(state)
            else:
                cb(state)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 6 个 Agent 节点（直接复用 short_drama.py 中的 Agent 类）
# ---------------------------------------------------------------------------
def _ensure_token_tracker(state: DramaProductionState) -> Dict[str, Any]:
    tracker = state.get("token_tracker")
    if tracker is None:
        tracker = {"token_used": 0, "token_prompt": 0, "token_completion": 0}
        state["token_tracker"] = tracker
    return tracker


def _build_outline_from_full_script(full_script: Dict[str, Any]) -> Dict[str, Any]:
    """用户上传剧本模式下，从编剧输出反推最小化剧本大纲供下游使用。"""
    screenplay = full_script.get("screenplay") or full_script or {}
    episodes = []
    for ep in (screenplay.get("episodes") or []):
        scenes = []
        for sc in (ep.get("scenes") or []):
            scenes.append({
                "scene_id": sc.get("scene_id", ""),
                "location": sc.get("location", ""),
                "time": sc.get("time", "日"),
                "characters_involved": sc.get("characters_involved", []),
                "action_summary": sc.get("action_description", "")[:120],
            })
        episodes.append({
            "episode_num": ep.get("episode_num", len(episodes) + 1),
            "logline": ep.get("logline", ""),
            "scenes": scenes,
        })
    return {
        "project_title": screenplay.get("project_title", ""),
        "genre": full_script.get("genre", ""),
        "style_bible": full_script.get("style_bible", ""),
        "color_palette": full_script.get("color_palette", []),
        "episodes": episodes,
    }


async def node_script_planner(state: DramaProductionState) -> DramaProductionState:
    from app.agents.short_drama import ScriptPlannerAgent
    options = {**state.get("options", {}), "global_params": state.get("global_params", {})}

    # 剧本上传模式：跳过剧本策划（LLM 大纲生成），直接保留原始 script_data 供编剧使用。
    # create_session 注释："剧本模式，跳过剧本策划，直接进入编剧拆解"
    # 原始 script_data 含 is_user_script=True 和 raw_script_text，ScreenwriterAgent 会直接基于原文改编。
    if options.get("mode") == "script":
        existing_outline = state.get("script_outline") or {}
        if existing_outline.get("is_user_script") and existing_outline.get("raw_script_text"):
            await _log(state, "agent", "script_planner", "planning",
                       "剧本模式：跳过大纲生成，保留原始剧本直接进入编剧拆解")
            state["feedback_message"] = ""
            state["last_error"] = ""
            await _checkpoint(state)
            return state
        # fallback：虽然 mode=script 但 script_data 缺失，走正常流程

    # 小说改编模式：使用 build_from_novel 将小说原文改编为短剧大纲
    if options.get("mode") == "novel":
        existing_outline = state.get("script_outline") or {}
        novel_text = existing_outline.get("raw_novel_text", "")
        if novel_text and not existing_outline.get("episodes"):
            await _log(state, "agent", "script_planner", "planning", "正在将小说原文改编为短剧大纲...（预计 30-90s）")
            _t0 = time.time()
            try:
                result = await ScriptPlannerAgent.build_from_novel(
                    novel_text,
                    options,
                    token_tracker=_ensure_token_tracker(state),
                )
                _elapsed = int(time.time() - _t0)
                await _log(state, "agent", "script_planner", "planning", f"LLM 调用完成，耗时 {_elapsed}s")
                # 保留 is_novel / raw_novel_text 标记
                result["is_novel"] = True
                result["raw_novel_text"] = novel_text
                state["script_outline"] = result
                state["feedback_message"] = ""
                state["last_error"] = ""
                await _log(state, "agent", "script_planner", "planning", "小说改编大纲已完成", {"project_title": result.get("project_title"), "episodes": len(result.get("episodes", []))})
                await _checkpoint(state)
            except Exception as exc:
                import traceback
                print("[NOVEL_PLANNER_FAIL]", repr(exc), traceback.format_exc(), flush=True)
                state["last_error"] = str(exc)
                await _log(state, "system", "script_planner", "planning", f"小说改编 Agent 失败: {exc}")
            return state
        elif existing_outline.get("episodes"):
            # 已有大纲，跳过
            await _log(state, "agent", "script_planner", "planning", "小说改编大纲已存在，跳过")
            state["feedback_message"] = ""
            state["last_error"] = ""
            await _checkpoint(state)
            return state

    await _log(state, "agent", "script_planner", "planning", "正在构思剧本大纲与世界观...")
    _t0 = time.time()
    try:
        # H4: 长剧本按集分片——planning 阶段先出精简大纲
        if _use_compact_outline(options):
            await _log(state, "agent", "script_planner", "planning", "集数较多，将先输出精简大纲...（预计 30-60s）")
            result = await ScriptPlannerAgent.build_compact_outline(
                state["user_instruction"],
                options,
                token_tracker=_ensure_token_tracker(state),
            )
        else:
            await _log(state, "agent", "script_planner", "planning", "正在调用 LLM 生成剧本大纲...（预计 30-90s）")
            result = await ScriptPlannerAgent.build(
                state["user_instruction"],
                options,
                token_tracker=_ensure_token_tracker(state),
            )
        _elapsed = int(time.time() - _t0)
        await _log(state, "agent", "script_planner", "planning", f"LLM 调用完成，耗时 {_elapsed}s")
        state["script_outline"] = result
        state["feedback_message"] = ""
        state["last_error"] = ""
        await _log(state, "agent", "script_planner", "planning", "剧本大纲已完成", {"project_title": result.get("project_title"), "episodes": len(result.get("episodes", []))})
        await _checkpoint(state)
    except Exception as exc:
        import traceback
        print("[SCRIPT_PLANNER_FAIL]", repr(exc), traceback.format_exc(), flush=True)
        state["last_error"] = str(exc)
        await _log(state, "system", "script_planner", "planning", f"剧本 Agent 失败: {exc}")
    return state


async def node_screenwriter(state: DramaProductionState) -> DramaProductionState:
    from app.agents.short_drama import ScreenwriterAgent
    script_outline = state.get("script_outline") or {}
    options = {**state.get("options", {}), "global_params": state.get("global_params", {})}

    # H4: 长剧本按集分片——screenwriter 按集分批并发扩写
    if _should_shard_episodes(script_outline):
        await _log(state, "agent", "screenwriter", "planning", f"集数较多，将按每 {EPISODE_BATCH_SIZE} 集分批扩写...")
        try:
            episodes = script_outline.get("episodes", []) or []
            episode_nums = [ep.get("episode_num", i + 1) for i, ep in enumerate(episodes)]
            batches = [episode_nums[i : i + EPISODE_BATCH_SIZE] for i in range(0, len(episode_nums), EPISODE_BATCH_SIZE)]
            semaphore = asyncio.Semaphore(MAX_EPISODE_CONCURRENCY)

            async def _process_batch(batch: List[int]) -> Dict[str, Any]:
                async with semaphore:
                    return await ScreenwriterAgent.build_episode_batch(
                        script_outline,
                        batch,
                        options,
                        token_tracker=_ensure_token_tracker(state),
                    )

            batch_results = await asyncio.gather(*[_process_batch(b) for b in batches])
            # 整体回滚机制：任一批次返回 fallback 数据或空 episodes，则视为整次扩写失败，
            # 不做 _merge，避免拼出半部剧本。让上游 Review 判失败并触发重试。
            failed_batches = []
            for idx, r in enumerate(batch_results):
                is_fallback = isinstance(r, dict) and r.get("_is_fallback")
                screenplay = (r or {}).get("screenplay", {}) or {}
                empty_episodes = not (screenplay.get("episodes") or [])
                if is_fallback or empty_episodes:
                    failed_batches.append({"batch": batches[idx], "is_fallback": is_fallback, "empty": empty_episodes})
            if failed_batches:
                detail = json.dumps(failed_batches, ensure_ascii=False)
                state["last_error"] = f"分片扩写有 {len(failed_batches)} 批失败，已整体回滚不合并半部剧本：{detail}"
                state["full_script"] = {"_is_fallback": True, "screenplay": {"episodes": []}, "detail": detail}
                await _log(state, "system", "screenwriter", "planning", state["last_error"])
                return state
            merged = _merge_screenplay_results(batch_results, script_outline)
            state["full_script"] = merged
            state["feedback_message"] = ""
            state["last_error"] = ""
            await _log(state, "agent", "screenwriter", "planning", f"分场剧本已完成（分片扩写 {len(batches)} 批，共 {len(merged.get('screenplay', {}).get('episodes', []))} 集）")
            await _checkpoint(state)
        except Exception as exc:
            state["last_error"] = str(exc)
            await _log(state, "system", "screenwriter", "planning", f"编剧 Agent 失败: {exc}")
        return state

    await _log(state, "agent", "screenwriter", "planning", "正在将大纲细化为分场剧本...")
    _t0 = time.time()
    try:
        # 优先透传用户反馈，其次使用 Reviewer 的修正意见
        screenwriter_feedback = state.get("pending_user_feedback") or state.get("feedback_message")
        await _log(state, "agent", "screenwriter", "planning", "正在调用 LLM 生成分场剧本...（预计 30-90s）")
        result = await ScreenwriterAgent.build(
            script_outline,
            options,
            token_tracker=_ensure_token_tracker(state),
            feedback=screenwriter_feedback,
        )
        _elapsed = int(time.time() - _t0)
        await _log(state, "agent", "screenwriter", "planning", f"LLM 调用完成，耗时 {_elapsed}s")
        state["full_script"] = result
        state["feedback_message"] = ""
        state["last_error"] = ""

        # 剧本上传模式：编剧完成后，从 full_script 反推结构化大纲供下游 Agent 使用。
        # 否则下游 Agent（角色/场景/分镜）拿到的 script_outline 仍是空 episodes 的原始剧本数据。
        if options.get("mode") == "script" and result:
            derived_outline = _build_outline_from_full_script(result)
            if derived_outline.get("episodes"):
                # 保留原始 is_user_script / raw_script_text 标记，但用反推的 episodes 替换空列表
                existing = state.get("script_outline") or {}
                derived_outline["is_user_script"] = existing.get("is_user_script", True)
                derived_outline["raw_script_text"] = existing.get("raw_script_text", "")
                state["script_outline"] = derived_outline
                await _log(state, "agent", "screenwriter", "planning",
                           f"剧本模式：已从编剧输出反推结构化大纲（{len(derived_outline['episodes'])} 集）供下游使用")

        await _log(state, "agent", "screenwriter", "planning", "分场剧本已完成")
        await _checkpoint(state)
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "screenwriter", "planning", f"编剧 Agent 失败: {exc}")
    return state


async def node_character_designer(state: DramaProductionState) -> DramaProductionState:
    from app.agents.short_drama import CharacterDesignerAgent
    await _log(state, "agent", "character_designer", "asset", "正在提取角色并设计视觉锚点...（预计 20-40s）")
    _t0 = time.time()
    try:
        agent_options = {**state.get("options", {}), "global_params": state.get("global_params", {})}
        result = await CharacterDesignerAgent.build(
            state.get("script_outline", {}),
            state.get("full_script"),
            agent_options,
            token_tracker=_ensure_token_tracker(state),
        )
        state["character_assets"] = result
        state["feedback_message"] = ""
        state["last_error"] = ""
        _elapsed = int(time.time() - _t0)
        await _log(state, "agent", "character_designer", "asset", f"已设计 {len(result.get('characters', []))} 个角色（耗时 {_elapsed}s）")
        await _checkpoint(state)
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "character_designer", "asset", f"角色 Agent 失败: {exc}")
    return state


async def node_scene_prop_designer(state: DramaProductionState) -> DramaProductionState:
    from app.agents.short_drama import ScenePropDesignerAgent
    await _log(state, "agent", "scene_prop_designer", "asset", "正在提取场景与道具...（预计 20-40s）")
    _t0 = time.time()
    try:
        agent_options = {**state.get("options", {}), "global_params": state.get("global_params", {})}
        result = await ScenePropDesignerAgent.build(
            state.get("script_outline", {}),
            state.get("full_script"),
            state.get("storyboard_data"),
            agent_options,
            token_tracker=_ensure_token_tracker(state),
            feedback=state.get("feedback_message") or state.get("pending_user_feedback"),
        )
        state["scene_assets"] = result
        state["feedback_message"] = ""
        state["last_error"] = ""
        _elapsed = int(time.time() - _t0)
        await _log(state, "agent", "scene_prop_designer", "asset", f"已设计 {len(result.get('scenes', []))} 个场景（耗时 {_elapsed}s）")
        await _checkpoint(state)
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "scene_prop_designer", "asset", f"场景 Agent 失败: {exc}")
    return state


async def node_character_designer_partial(state: DramaProductionState, target_char_ids: List[str]) -> None:
    """M2: 局部重生成问题角色（不返回 state，直接修改）。"""
    from app.agents.short_drama import CharacterDesignerAgent
    await _log(state, "agent", "character_designer", "asset", f"局部修复角色：{target_char_ids}")
    existing = (state.get("character_assets") or {}).get("characters", []) or []
    agent_options = {**state.get("options", {}), "global_params": state.get("global_params", {})}
    result = await CharacterDesignerAgent.build_partial(
        target_char_ids,
        existing,
        state.get("script_outline", {}),
        state.get("full_script"),
        agent_options,
        token_tracker=_ensure_token_tracker(state),
    )
    state["character_assets"] = result
    await _log(state, "agent", "character_designer", "asset", f"已局部修复 {len(target_char_ids)} 个角色")
    await _checkpoint(state)


async def node_scene_prop_designer_partial(state: DramaProductionState, target_scene_ids: List[str]) -> None:
    """M2: 局部重生成问题场景（不返回 state，直接修改）。"""
    from app.agents.short_drama import ScenePropDesignerAgent
    await _log(state, "agent", "scene_prop_designer", "asset", f"局部修复场景：{target_scene_ids}")
    existing = (state.get("scene_assets") or {}).get("scenes", []) or []
    agent_options = {**state.get("options", {}), "global_params": state.get("global_params", {})}
    result = await ScenePropDesignerAgent.build_partial(
        target_scene_ids,
        existing,
        state.get("script_outline", {}),
        state.get("full_script"),
        state.get("storyboard_data"),
        agent_options,
        token_tracker=_ensure_token_tracker(state),
        feedback=state.get("feedback_message") or state.get("pending_user_feedback"),
    )
    state["scene_assets"] = result
    await _log(state, "agent", "scene_prop_designer", "asset", f"已局部修复 {len(target_scene_ids)} 个场景")
    await _checkpoint(state)


async def node_asset_parallel(state: DramaProductionState) -> DramaProductionState:
    """资产阶段：角色与场景设计无数据依赖，并发执行；支持基于 review_issues 局部重跑。"""
    # M2: 根据上次 Review 的问题维度做局部路由
    review_issues = state.get("review_issues") or []
    char_failed = any(i.get("dimension") == "character" for i in review_issues)
    scene_failed = any(i.get("dimension") == "scene" for i in review_issues)

    target_char_ids = list(set(
        cid
        for i in review_issues
        if i.get("dimension") == "character"
        for cid in (i.get("target_ids") or [])
    ))
    target_scene_ids = list(set(
        sid
        for i in review_issues
        if i.get("dimension") == "scene"
        for sid in (i.get("target_ids") or [])
    ))

    try:
        if not char_failed and not scene_failed:
            # 首次运行或没有具体问题：全量并发
            await _log(state, "agent", "asset_parallel", "asset", "并发提取角色与场景...")
            await asyncio.gather(
                node_character_designer(state),
                node_scene_prop_designer(state),
            )
            await _log(state, "agent", "asset_parallel", "asset", "角色与场景并发提取完成")
        else:
            # 局部重试：只 rerun 失败维度，且尽量只 rerun 问题 ID
            tasks = []
            if char_failed:
                if target_char_ids:
                    tasks.append(node_character_designer_partial(state, target_char_ids))
                else:
                    await _log(state, "agent", "asset_parallel", "asset", "角色维度未通过但无具体 target_id，全量重跑角色")
                    tasks.append(node_character_designer(state))
            if scene_failed:
                if target_scene_ids:
                    tasks.append(node_scene_prop_designer_partial(state, target_scene_ids))
                else:
                    await _log(state, "agent", "asset_parallel", "asset", "场景维度未通过但无具体 target_id，全量重跑场景")
                    tasks.append(node_scene_prop_designer(state))
            if tasks:
                await asyncio.gather(*tasks)
            await _log(state, "agent", "asset_parallel", "asset", "资产局部修复完成")
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "asset_parallel", "asset", f"并发资产 Agent 失败: {exc}")
    return state


async def node_storyboard_director(state: DramaProductionState) -> DramaProductionState:
    from app.agents.short_drama import StoryboardDirectorAgent
    await _log(state, "agent", "storyboard_director", "production", "正在拆解分镜并组装提示词...（预计 30-60s）")
    _t0 = time.time()
    try:
        agent_options = {**state.get("options", {}), "global_params": state.get("global_params", {})}
        result = await StoryboardDirectorAgent.build(
            state.get("script_outline", {}),
            state.get("character_assets", {}),
            state.get("full_script"),
            agent_options,
            token_tracker=_ensure_token_tracker(state),
        )
        state["storyboard_data"] = result
        state["feedback_message"] = ""
        state["last_error"] = ""
        _elapsed = int(time.time() - _t0)
        await _log(state, "agent", "storyboard_director", "production", f"已拆解 {len(result.get('storyboards', []))} 个分镜（耗时 {_elapsed}s）")
        await _checkpoint(state)
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "storyboard_director", "production", f"分镜 Agent 失败: {exc}")
    return state


async def node_video_composer(state: DramaProductionState) -> DramaProductionState:
    from app.agents.short_drama import VideoComposerAgent
    sb_count = len((state.get("storyboard_data") or {}).get("storyboards", []) or [])
    await _log(state, "agent", "video_composer", "production", f"正在按 Seedance 2.0 标准重写 {sb_count} 个分镜的视频提示词...（预计 20-40s）")
    _t0 = time.time()
    try:
        agent_options = {**state.get("options", {}), "global_params": state.get("global_params", {})}
        # 优先透传用户反馈，其次使用 Reviewer 的修正意见
        composer_feedback = state.get("pending_user_feedback") or state.get("feedback_message") or None
        result = await VideoComposerAgent.build(
            state.get("storyboard_data", {}),
            character_assets=state.get("character_assets", {}),
            scene_assets=state.get("scene_assets", {}),
            full_script=state.get("full_script"),
            options=agent_options,
            feedback=composer_feedback,
            token_tracker=_ensure_token_tracker(state),
        )
        state["video_plan"] = result
        state["feedback_message"] = ""
        state["last_error"] = ""
        _elapsed = int(time.time() - _t0)
        await _log(state, "agent", "video_composer", "production", f"已为 {len(result.get('videos', []))} 个分镜生成视频提示词（耗时 {_elapsed}s）")
        await _checkpoint(state)
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "video_composer", "production", f"视频 Agent 失败: {exc}")
    return state


# ---------------------------------------------------------------------------
# Lite Storyboard 节点（轻量分镜，standalone，不依赖上游结构化数据）
# ---------------------------------------------------------------------------

async def node_lite_storyboard(state: DramaProductionState) -> DramaProductionState:
    """轻量分镜节点：直接从剧本文本生成分镜表 + 视频提示词组。

    与 node_storyboard_director + node_video_composer 的区别：
    - 不依赖 script_outline / character_assets / full_script
    - 从 options 或 script_outline 中获取原始剧本文本
    - 单次 LLM 调用同时输出分镜表和视频提示词组
    """
    from app.agents.short_drama import LiteStoryboardAgent

    # 从 state 中获取剧本文本
    options = state.get("options", {})
    script_text = options.get("script_text", "")

    # 如果 options 中没有，尝试从 script_outline 中获取
    if not script_text:
        outline = state.get("script_outline") or {}
        script_text = (
            outline.get("raw_script_text")
            or outline.get("raw_novel_text")
            or outline.get("source_prompt", "")
        )

    if not script_text:
        state["last_error"] = "轻量分镜需要剧本文本，但未在 options 或 script_outline 中找到"
        await _log(state, "system", "lite_storyboard", "lite_storyboard", "缺少剧本文本，无法执行轻量分镜")
        return state

    story_type = options.get("story_type", "都市职场")
    art_style = options.get("art_style", "真人现代都市")

    await _log(
        state, "agent", "lite_storyboard", "lite_storyboard",
        f"正在从剧本文本生成分镜表和视频提示词组...（预计 30-60s）"
    )
    _t0 = time.time()
    try:
        agent_options = {**options, "global_params": state.get("global_params", {})}
        result = await LiteStoryboardAgent.build(
            script_text,
            story_type=story_type,
            art_style=art_style,
            options=agent_options,
            token_tracker=_ensure_token_tracker(state),
        )
        # 存入 storyboard_data（兼容现有序列化逻辑）
        state["storyboard_data"] = result
        state["video_plan"] = {"videos": result.get("video_groups", [])}
        state["feedback_message"] = ""
        state["last_error"] = ""
        _elapsed = int(time.time() - _t0)
        sb_count = len(result.get("storyboard", []))
        vg_count = len(result.get("video_groups", []))
        await _log(
            state, "agent", "lite_storyboard", "lite_storyboard",
            f"已生成 {sb_count} 个分镜、{vg_count} 个视频组（耗时 {_elapsed}s）"
        )
        await _checkpoint(state)
    except Exception as exc:
        state["last_error"] = str(exc)
        await _log(state, "system", "lite_storyboard", "lite_storyboard", f"轻量分镜 Agent 失败: {exc}")
    return state


# ---------------------------------------------------------------------------
# 3 个 Review 质检节点
# ---------------------------------------------------------------------------
_REVIEW_SYSTEM_PROMPT = """
你是一位严厉的 AI 短剧总导演，负责执行三级质量审核（格式合规 → 逻辑一致 → 质量达标）。

请按以下三级审核体系检查输入数据，并输出 JSON：
{
  "passed": true/false,
  "score": 0-100,
  "feedback_message": "如果 passed=false，必须按标准化修正指令模板写出具体修改意见；如果 passed=true，写空字符串",
  "level1_format": {"passed": true/false, "issues": ["格式问题1", ...]},
  "level2_logic": {"passed": true/false, "issues": ["逻辑问题1", ...]},
  "level3_quality": {"passed": true/false, "issues": ["质量问题1", ...]},
  "target_ids": ["有问题的 ID"],
  "suggestions": ["建议1", "建议2"]
}

评分权重：
- 格式合规（level1_format）：一票否决，若未通过则总评不通过。
- 逻辑一致（level2_logic）：占 40%。
- 质量达标（level3_quality）：占 60%。
- score = level2 * 0.4 + level3 * 0.6；score ≥ 70 且 level1 通过才算 passed。

检查规则：
"""

_REVIEW_PLANNING_RULES = """
【一级：格式合规性】
1. script_outline 必须包含 project_title、genre、style_bible、color_palette、episodes 结构。
2. full_script 必须包含 screenplay.episodes.scenes，每个 scene 必须有 scene_id、location、time、characters_involved、action_description、duration、dialogues、emotion_beat、transition_hint；每个 episode 必须有 total_duration；screenplay 必须有 total_duration。
3. 每个 episode 必须包含 episode_num、logline、scenes。

【二级：逻辑一致性】
1. 【角色一致性】script_outline 与 full_script 中每个 scene 的 characters_involved 角色名称必须完全一致。
2. 【剧情连贯性】相邻场次之间必须有清晰因果转场，上一场结局能自然推动下一场开始。
3. 【时长一致性】累计总时长误差 ≤ 3 秒，分场时长精确到秒。
4. 【集数对齐】full_script 集数与 script_outline 集数必须一致。

【三级：质量达标性】
1. 【情绪曲线】每集情绪强度必须有起伏，高潮场次明确标注。
2. 【可拍摄性】action_description 禁止抽象形容词，必须转化为可拍摄动作或视觉符号。
3. 【戏剧功能】每场次必须承担推进剧情/塑造人物/铺垫反转之一。
4. 【对白口语化】单句对白不超过 20 字，符合人设，禁止全员统一话术。
"""

_REVIEW_ASSET_RULES = """
【一级：格式合规性】
1. character_assets.characters 中每个角色必须有 char_id、name、role、visual_anchor、immutable_features、base_prompt、negative_prompt、style_preset。
2. scene_assets.scenes 中每个场景必须有 scene_id、name、space_type、base_prompt、camera_hint、time_of_day、negative_prompt。
3. props 中每个道具必须有 prop_id、name、base_prompt、negative_prompt。

【二级：逻辑一致性】
1. scene_assets.scenes 必须覆盖 full_script 中出现的所有 scene_id，不得遗漏。
2. 每个场景的 time_of_day 必须与 full_script 中对应 scene 的 time 字段一致（日/夜/黄昏）。
3. 角色 char_id/name 在 full_script 各 scene 的 characters_involved 中保持一致。
4. 道具 ID 与名称在剧本/分镜中保持一致，禁止未定义新增。

【三级：质量达标性】
1. 每个核心角色必须有 3-5 个 immutable_features，且至少 1 个面部锚点。
2. base_prompt 必须为中性表情（包含 neutral expression / neutral calm / neutral standing / neutral pose 等任一表述即可），无表情/动作词，按 [immutable_features] + [clothing] + [pose: neutral standing] 组织。
3. 场景 base_prompt/negative_prompt 必须包含 no people / no human / no face / no silhouette / no hands / no feet 等无人关键词。
4. 视觉锚点必须具象可复用，禁止「帅气」「美丽」等模糊形容词。
"""

_REVIEW_PRODUCTION_RULES = """
【一级：格式合规性】
1. storyboard_data.storyboards 中每个分镜必须有 storyboard_id、prev_storyboard_id、linked_scene_id、linked_char_ids、shot_type、camera_movement、composition、visual_description、final_image_prompt、visual_continuity、transition_from_prev、duration_seconds。
2. video_plan.videos 中每个视频必须有 storyboard_id、final_video_prompt、seedance_subject、seedance_motion、seedance_camera、seedance_dialogue、has_explicit_motion、has_camera_movement、has_dialogue_or_audio。
3. video_plan.videos 必须与 storyboard_data.storyboards 一一对应（按 storyboard_id）。

【二级：逻辑一致性】
1. 【角色隔离】每个分镜的 linked_char_ids 必须等于编剧分场中对应 scene_id 的 characters_involved。final_image_prompt/final_video_prompt 中不能出现未在 linked_char_ids 中的角色。
2. 【视觉锚点落地】每个分镜的 final_image_prompt 必须包含其 linked_char_ids 对应角色的 immutable_features 中的至少 2 个关键视觉锚点。
3. 【分镜连贯性】同一场景内相邻分镜的 light_direction、角色站位（position）、视线方向（gaze）必须保持一致或给出合理过渡；transition_from_prev 必须与 visual_continuity 不矛盾。
4. 【时长匹配】分镜 duration_seconds 之和与每集预期时长大致匹配，误差 ≤ 2 秒。

【三级：质量达标性】
1. 【构图变化】相邻分镜 shot_type/composition 不能完全相同，必须形成视觉节奏变化。
2. 【无静止镜头】所有分镜必须有微运动或明确运镜，禁止纯静态画面。
3. 【视频提示词质量】final_video_prompt 必须与 final_image_prompt 有明显区别，包含明确 Motion、Camera、Expression、Continuity 段落，符合 Seedance 2.0 结构。
4. 【禁用表达】final_video_prompt 中禁止出现 the image shows / in the picture / as seen in image 等表述。禁止单独使用 static camera 或 fixed camera 作为唯一运镜描述（须附加微运动限定词）。
"""


# M5: 视频提示词禁用短语与段落标题检查
_VIDEO_BANNED_PHRASES = [
    "the image shows",
    "in the picture",
    "as seen in image",
    "as shown in",
    "no motion",
    "still image",
    "the scene begins with",  # 叙事性描述，非动作指令
]
# M5: 视频提示词必备段落标题（每个段落支持多个可接受变体，兼容 LLM 不同输出格式）
_VIDEO_REQUIRED_SECTIONS = [
    ("subject:", ["subject:"]),
    ("expression:", ["expression:"]),
    ("action/motion:", ["action/motion:", "motion:", "action:"]),
    ("camera & lens:", ["camera & lens:", "camera:", "camera/lens:"]),
    ("continuity:", ["continuity:"]),
]
# P14: 允许的运镜指令白名单（提示词中至少出现一个）
_VIDEO_CAMERA_MOVES = [
    "pan", "tilt", "dolly", "tracking", "push in", "pull back",
    "crane", "handheld", "steadicam", "orbit", "zoom", "static",
    "fixed", "aerial", "drone", "gimbal", "follow",
]
# P14: 允许的视频时长档位（秒）
_VIDEO_DURATION_OPTIONS = {5, 6, 8, 10, 12, 15, 20, 30}
_VIDEO_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "shall", "can", "need", "dare", "ought", "used", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
}


def _tokenize_words(text: str) -> List[str]:
    """简单英文分词，保留字母数字，转小写。"""
    import re
    return [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", text or "") if len(w) > 1]


def _jaccard_similarity(a: str, b: str) -> float:
    """去掉 stop words 后的 Jaccard 相似度。"""
    words_a = set(_tokenize_words(a)) - _VIDEO_STOP_WORDS
    words_b = set(_tokenize_words(b)) - _VIDEO_STOP_WORDS
    if not words_a or not words_b:
        return 0.0
    inter = words_a & words_b
    union = words_a | words_b
    return len(inter) / len(union) if union else 0.0


def _video_prompt_pre_check(state: DramaProductionState) -> Optional[str]:
    """P14: 增强版视频提示词确定性预检。

    检查项：
    1. Jaccard 相似度（与图像提示词雷同度）
    2. 禁用短语
    3. 必备段落标题
    4. P14-NEW: 角色锚点一致性 — 视频提示词引用的角色特征须与角色资产库匹配
    5. P14-NEW: 运镜指令白名单 — camera & lens 段须包含至少一个运镜关键词
    6. P14-NEW: 时长档位 — duration 须为允许的标准值
    7. P14-NEW: 负面提示词覆盖 — 须包含基本负面词（flicker, morph, distortion）
    """
    storyboards = (state.get("storyboard_data") or {}).get("storyboards", [])
    videos = (state.get("video_plan") or {}).get("videos", [])
    if not storyboards or not videos:
        return None

    sb_by_id = {sb.get("storyboard_id"): sb for sb in storyboards}
    # P14: 构建角色锚点映射
    char_assets = state.get("character_assets") or {}
    char_anchors: Dict[str, str] = {}  # char_id -> name
    for c in (char_assets.get("characters", []) or []):
        cid = c.get("char_id", "")
        name = c.get("name", "")
        if cid:
            char_anchors[cid] = name

    issues = []

    for v in videos:
        vid = v.get("storyboard_id")
        sb = sb_by_id.get(vid)
        if not sb:
            issues.append(f"{vid}: video 找不到对应分镜")
            continue
        img_prompt = (sb.get("final_image_prompt") or "").lower().strip()
        vid_prompt = (v.get("final_video_prompt") or "").lower().strip()
        if not vid_prompt:
            issues.append(f"{vid}: final_video_prompt 为空")
            continue

        # 1. Jaccard 相似度（去 stop words）
        jaccard = _jaccard_similarity(img_prompt, vid_prompt)
        if jaccard > 0.75:
            issues.append(f"{vid}: final_video_prompt 与 final_image_prompt 高度雷同（Jaccard {jaccard:.0%}），缺少 Motion/Camera 描述")

        # 2. 禁用短语
        for phrase in _VIDEO_BANNED_PHRASES:
            if phrase in vid_prompt:
                issues.append(f"{vid}: final_video_prompt 包含禁用短语 '{phrase}'")

        # 3. 必备段落标题（支持多变体匹配）
        for section_name, variants in _VIDEO_REQUIRED_SECTIONS:
            if not any(v in vid_prompt for v in variants):
                issues.append(f"{vid}: final_video_prompt 缺少段落标题 '{section_name}'")

        # 4. P14-NEW: 角色锚点一致性
        # 视频提示词为全英文，不应检查中文名；改为检查 char_id 或角色的 immutable_features 关键词
        linked_chars = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
        for cid in linked_chars:
            char_name = char_anchors.get(cid, "")
            # 检查 char_id 是否出现在提示词中
            if cid.lower() not in vid_prompt:
                # 再检查角色的 immutable_features 是否有任一关键词出现在提示词中
                char_data = None
                for c in (char_assets.get("characters", []) or []):
                    if c.get("char_id") == cid:
                        char_data = c
                        break
                if char_data:
                    feats = char_data.get("immutable_features", []) or []
                    anchor = char_data.get("visual_anchor", "") or ""
                    all_anchors = [f.lower() for f in feats] + [anchor.lower()]
                    # 取每个锚点的前 2 个英文单词作为匹配关键词
                    match_keywords = []
                    for a in all_anchors:
                        words = [w for w in a.split() if len(w) > 2 and w.isascii()]
                        match_keywords.extend(words[:2])
                    found = any(kw in vid_prompt for kw in match_keywords)
                    if not found:
                        issues.append(f"{vid}: final_video_prompt 未引用角色 {cid} 的视觉锚点")
                else:
                    issues.append(f"{vid}: final_video_prompt 未引用角色 {cid} 的视觉锚点")

        # 5. P14-NEW: 运镜指令白名单
        camera_section = ""
        for cam_header in ["camera & lens:", "camera:", "camera/lens:"]:
            if cam_header in vid_prompt:
                cam_start = vid_prompt.index(cam_header)
                cam_end = vid_prompt.find("\n", cam_start)
                if cam_end == -1:
                    cam_end = len(vid_prompt)
                camera_section = vid_prompt[cam_start:cam_end]
                break
        has_camera_move = any(move in camera_section or move in vid_prompt[:500] for move in _VIDEO_CAMERA_MOVES)
        if not has_camera_move:
            issues.append(f"{vid}: final_video_prompt 缺少运镜指令（须包含 pan/tilt/dolly/tracking/push in/pull back 等之一）")

        # 6. P14-NEW: 时长档位
        duration = v.get("duration") or v.get("duration_seconds") or 0
        try:
            duration_int = int(duration)
        except (TypeError, ValueError):
            duration_int = 0
        if duration_int and duration_int not in _VIDEO_DURATION_OPTIONS:
            nearest = min(_VIDEO_DURATION_OPTIONS, key=lambda x: abs(x - duration_int))
            issues.append(f"{vid}: duration={duration_int}s 不在标准档位 {_VIDEO_DURATION_OPTIONS}，最接近的是 {nearest}s")

        # 7. P14-NEW: 负面提示词覆盖
        negative = (v.get("negative_prompt") or v.get("final_negative_prompt") or "").lower()
        required_neg = ["flicker", "morph", "distortion"]
        missing_neg = [n for n in required_neg if n not in negative]
        if missing_neg:
            issues.append(f"{vid}: negative_prompt 缺少必备负面词 {missing_neg}（flicker/morph/distortion）")

    if issues:
        return "视频提示词预检未通过：\n- " + "\n- ".join(issues)
    return None


def _planning_pre_check(state: DramaProductionState) -> Optional[str]:
    """M1: planning 阶段确定性预检（结构完整性、角色对齐、时长估算）。"""
    script_outline = state.get("script_outline") or {}
    full_script = state.get("full_script") or {}
    issues = []

    # 判断是否为「用户直接上传原始剧本」模式
    is_user_script = isinstance(script_outline, dict) and bool(script_outline.get("is_user_script"))
    is_novel = isinstance(script_outline, dict) and bool(script_outline.get("is_novel"))

    # 用户上传剧本或小说模式下，script_outline.episodes 为空是正常的（剧本模式），
    # 小说模式大纲已生成，episodes 不应为空
    if not is_user_script and not is_novel:
        # 结构完整性
        if not script_outline.get("episodes"):
            issues.append("script_outline 缺少 episodes")
        else:
            for i, ep in enumerate(script_outline["episodes"]):
                if not ep.get("logline"):
                    issues.append(f"第 {ep.get('episode_num', i+1)} 集缺少 logline")
                if not ep.get("scenes"):
                    issues.append(f"第 {ep.get('episode_num', i+1)} 集缺少 scenes")

        # full_script 与 outline 集数对齐
        outline_eps = {ep.get("episode_num") for ep in (script_outline.get("episodes", []) or [])}
        full_eps = {ep.get("episode_num") for ep in ((full_script.get("screenplay", {}).get("episodes", [])) if isinstance(full_script, dict) else [])}
        if full_script and full_eps != outline_eps:
            issues.append(f"full_script 集数 {sorted(full_eps)} 与 script_outline 集数 {sorted(outline_eps)} 不一致")

        # 角色名集合对齐
        outline_chars = set()
        for ep in (script_outline.get("episodes", []) or []):
            for sc in ep.get("scenes", []):
                for c in sc.get("characters_involved", []):
                    if isinstance(c, dict):
                        outline_chars.add(c.get("name"))
                    elif isinstance(c, str):
                        outline_chars.add(c)
        full_chars = set()
        if isinstance(full_script, dict):
            for ep in (full_script.get("screenplay", {}).get("episodes", []) or []):
                for sc in ep.get("scenes", []):
                    for c in sc.get("characters_involved", []):
                        if isinstance(c, dict):
                            full_chars.add(c.get("name"))
                        elif isinstance(c, str):
                            full_chars.add(c)
        if full_script and outline_chars != full_chars:
            missing_in_full = outline_chars - full_chars
            missing_in_outline = full_chars - outline_chars
            if missing_in_full:
                issues.append(f"script_outline 角色 {missing_in_full} 未在 full_script 出现")
            if missing_in_outline:
                issues.append(f"full_script 角色 {missing_in_outline} 未在 script_outline 出现")

    # 对用户上传剧本和普通大纲都校验 full_script 基本结构
    if isinstance(full_script, dict):
        screenplay = full_script.get("screenplay") or {}
        if not screenplay.get("episodes"):
            issues.append("full_script.screenplay 缺少 episodes")
        else:
            for i, ep in enumerate(screenplay["episodes"]):
                ep_num = ep.get("episode_num", i + 1)
                if not ep.get("scenes"):
                    issues.append(f"第 {ep_num} 集缺少 scenes")
                total_duration = ep.get("total_duration")
                if total_duration is None:
                    issues.append(f"第 {ep_num} 集缺少 total_duration")
                scene_duration_sum = sum((s.get("duration") or 0) for s in ep.get("scenes", []) if isinstance(s, dict))
                if total_duration is not None and scene_duration_sum != total_duration:
                    issues.append(f"第 {ep_num} 集 total_duration({total_duration}) 与 scene duration 之和({scene_duration_sum}) 不一致")

        # 用户上传剧本模式：检查忠实度校验警告（角色名篡改、场景遗漏、场景地点更换）
        fidelity_warnings = full_script.get("_fidelity_warnings")
        if fidelity_warnings and isinstance(fidelity_warnings, list):
            for w in fidelity_warnings:
                issues.append(f"剧本忠实度校验：{w}")

    if issues:
        return "Planning 预检未通过：\n- " + "\n- ".join(issues)
    return None


def _asset_pre_check(state: DramaProductionState) -> Optional[str]:
    """M1: asset 阶段确定性预检（角色/场景 ID 对齐、场景无人关键词、场景覆盖）。"""
    character_assets = state.get("character_assets") or {}
    scene_assets = state.get("scene_assets") or {}
    full_script = state.get("full_script") or {}
    issues = []
    review_issues: List[Dict[str, Any]] = []

    chars = character_assets.get("characters", []) or []
    scenes = scene_assets.get("scenes", []) or []

    # 角色必须有 char_id 与 immutable_features
    char_ids = set()
    bad_char_ids: List[str] = []
    for c in chars:
        cid = c.get("char_id")
        if not cid:
            issues.append(f"角色 {c.get('name', '?')} 缺少 char_id")
            continue
        char_ids.add(cid)
        if len(c.get("immutable_features", []) or []) < 3:
            issues.append(f"角色 {cid}/{c.get('name', '?')} 的 immutable_features 少于 3 个")
            bad_char_ids.append(cid)
    if bad_char_ids:
        review_issues.append({"dimension": "character", "target_ids": bad_char_ids})

    # 场景必须有 scene_id、base_prompt、time_of_day，且必须包含无人关键词
    no_people_keywords = ["no people", "no human", "no face", "no silhouette", "no hands", "no feet"]
    scene_ids = set()
    bad_scene_ids: List[str] = []
    for s in scenes:
        sid = s.get("scene_id")
        if not sid:
            issues.append(f"场景 {s.get('name', '?')} 缺少 scene_id")
            continue
        scene_ids.add(sid)
        base = (s.get("base_prompt") or "").lower()
        negative = (s.get("negative_prompt") or "").lower()
        combined = base + " " + negative
        missing = [k for k in no_people_keywords if k not in combined]
        if missing:
            issues.append(f"场景 {sid}/{s.get('name', '?')} 缺少无人关键词：{missing}")
            bad_scene_ids.append(sid)
        if not s.get("time_of_day"):
            issues.append(f"场景 {sid}/{s.get('name', '?')} 缺少 time_of_day")
            if sid not in bad_scene_ids:
                bad_scene_ids.append(sid)

    # 场景覆盖 full_script 中所有 scene_id
    if isinstance(full_script, dict):
        required_scene_ids = set()
        for ep in (full_script.get("screenplay", {}).get("episodes", []) or []):
            for sc in ep.get("scenes", []):
                if sc.get("scene_id"):
                    required_scene_ids.add(sc.get("scene_id"))
        missing_scenes = required_scene_ids - scene_ids
        if missing_scenes:
            issues.append(f"场景资产遗漏编剧分场中的 scene_id：{sorted(missing_scenes)}")
            review_issues.append({"dimension": "scene", "target_ids": sorted(missing_scenes)})

    state["review_issues"] = review_issues
    if issues:
        return "Asset 预检未通过：\n- " + "\n- ".join(issues)
    return None


def _production_pre_check(state: DramaProductionState) -> Optional[str]:
    """M1: production 阶段确定性预检（分镜对齐、时长、视频提示词）。"""
    storyboards = (state.get("storyboard_data") or {}).get("storyboards", []) or []
    videos = (state.get("video_plan") or {}).get("videos", []) or []
    full_script = state.get("full_script") or {}
    character_assets = state.get("character_assets") or {}
    scene_assets = state.get("scene_assets") or {}
    issues = []

    if not storyboards:
        issues.append("storyboard_data 为空")
    if not videos:
        issues.append("video_plan 为空")

    # 分镜与编剧 scene_id 对齐
    char_by_id = {c.get("char_id"): c for c in (character_assets.get("characters", []) or [])}
    scene_ids = {s.get("scene_id") for s in (scene_assets.get("scenes", []) or []) if s.get("scene_id")}
    full_scene_chars: Dict[str, List[str]] = {}
    if isinstance(full_script, dict):
        for ep in (full_script.get("screenplay", {}).get("episodes", []) or []):
            for sc in ep.get("scenes", []):
                sid = sc.get("scene_id")
                if sid:
                    names = []
                    for c in sc.get("characters_involved", []):
                        if isinstance(c, dict):
                            names.append(c.get("name", ""))
                        elif isinstance(c, str):
                            names.append(c)
                    full_scene_chars[sid] = [n for n in names if n and not _is_non_character_item(n)]

    sb_ids = set()
    for sb in storyboards:
        sbid = sb.get("storyboard_id")
        sb_ids.add(sbid)
        sid = sb.get("linked_scene_id")
        if sid and sid not in scene_ids:
            issues.append(f"分镜 {sbid} 引用了不存在的场景 {sid}")
        # linked_char_ids 对齐
        linked_chars = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
        for cid in linked_chars:
            if cid and cid not in char_by_id:
                issues.append(f"分镜 {sbid} 引用了不存在的角色 {cid}")
        # 角色名对齐
        if sid and sid in full_scene_chars:
            allowed_names = set(full_scene_chars[sid])
            for cid in linked_chars:
                char = char_by_id.get(cid) or {}
                if char.get("name") and char.get("name") not in allowed_names:
                    issues.append(f"分镜 {sbid} 的角色 {cid}/{char.get('name')} 不在场景 {sid} 的出场角色 {allowed_names} 中")

    # video 与 storyboard 一一对应
    video_sb_ids = {v.get("storyboard_id") for v in videos if v.get("storyboard_id")}
    missing_videos = sb_ids - video_sb_ids
    extra_videos = video_sb_ids - sb_ids
    if missing_videos:
        issues.append(f"缺少对应视频的分镜：{sorted(missing_videos)}")
    if extra_videos:
        issues.append(f"存在多余视频（无对应分镜）：{sorted(extra_videos)}")

    # 视频提示词质量预检
    video_feedback = _video_prompt_pre_check(state)
    if video_feedback:
        issues.append(video_feedback)

    if issues:
        return "Production 预检未通过：\n- " + "\n- ".join(issues)
    return None


# M1: 细粒度 Reviewer 系统提示（小 prompt、各自打分）
_REVIEWER_CHARACTER_SYSTEM_PROMPT = """
你是一位角色一致性审核员。只检查角色一致性，输出 JSON：
{
  "score": 0-100,
  "passed": true/false,
  "feedback_message": "问题描述，无问题写空字符串",
  "target_ids": ["有问题的 char_id"]
}

检查项：
1. character_assets.characters 中每个主角有至少 3 个 immutable_features，至少 1 个面部锚点。
2. 角色 char_id/name 在 full_script 各 scene 的 characters_involved 中保持一致。
3. base_prompt 为中性表情，无表情/动作词。
"""

_REVIEWER_SCENE_SYSTEM_PROMPT = """
你是一位场景审核员。只检查场景资产质量，输出 JSON：
{
  "score": 0-100,
  "passed": true/false,
  "feedback_message": "问题描述，无问题写空字符串",
  "target_ids": ["有问题的 scene_id"]
}

检查项：
1. scene_assets.scenes 覆盖 full_script 中所有 scene_id。
2. 每个场景 base_prompt/negative_prompt 包含 no people, no human, no face 等无人关键词。
3. time_of_day 与 full_script 对应 scene 的 time 一致。
"""

_REVIEWER_STORYBOARD_SYSTEM_PROMPT = """
你是一位分镜节奏审核员。只检查分镜质量，输出 JSON：
{
  "score": 0-100,
  "passed": true/false,
  "feedback_message": "问题描述，无问题写空字符串",
  "target_ids": ["有问题的 storyboard_id"]
}

检查项：
1. 每个分镜 linked_char_ids 与对应 scene 的 characters_involved 一致。
2. 相邻分镜 shot_type/composition 有变化，不雷同。
3. 同一场景内 continuity（position/gaze/light）一致或合理过渡。
4. 分镜时长之和与每集预期时长大致匹配。
"""

_REVIEWER_VIDEO_SYSTEM_PROMPT = """
你是一位视频提示词审核员。只检查 video_plan 质量，输出 JSON：
{
  "score": 0-100,
  "passed": true/false,
  "feedback_message": "问题描述，无问题写空字符串",
  "target_ids": ["有问题的 storyboard_id"]
}

检查项：
1. final_video_prompt 与对应 final_image_prompt 有明显区别，不雷同。
2. 包含 Subject/Expression/Action/Motion/Camera/Continuity 段落。
3. 不含 the image shows / in the picture / as seen in image 等禁用表达。禁止单独使用 static camera 或 fixed camera 作为唯一运镜描述（须附加微运动限定词如 subtle micro-movement）。
4. 镜头运镜具体明确。
"""


# LLM 可能在 characters_involved 中混入的非角色项关键词
_NON_CHARACTER_KEYWORDS = {
    "分镜", "脚本", "剧本", "基调", "影片", "大纲", "旁白", "画外音",
    "style", "bible", "storyboard", "script", "outline", "palette",
    "tone", "theme", "narrator", "voiceover",
}


def _is_non_character_item(name: str) -> bool:
    """判断一个名称是否为非角色项（如'分镜脚本'、'影片基调'等被误放入 characters_involved 的项）。"""
    if not name or not isinstance(name, str):
        return True
    name_lower = name.strip().lower()
    if not name_lower:
        return True
    # 纯数字或纯标点
    import re
    if re.match(r"^[\d\W_]+$", name_lower):
        return True
    # 包含非角色关键词
    return any(kw in name_lower for kw in _NON_CHARACTER_KEYWORDS)


def _build_reviewer_context(state: DramaProductionState, dimension: str) -> Dict[str, Any]:
    """为每个细粒度 reviewer 构造最小上下文。"""
    if dimension == "character":
        character_assets = state.get("character_assets") or {}
        full_script = state.get("full_script") or {}
        return {
            "characters": [
                {
                    "char_id": c.get("char_id"),
                    "name": c.get("name"),
                    "immutable_features": c.get("immutable_features", []),
                    "base_prompt_neutral": any(
                        kw in (c.get("base_prompt", "") or "").lower()
                        for kw in ["neutral expression", "neutral calm", "neutral standing",
                                   "neutral face", "expressionless", "calm expression",
                                   "neutral pose", "pose: neutral"]
                    ),
                }
                for c in character_assets.get("characters", [])
            ],
            "full_script_characters_per_scene": [
                {
                    "scene_id": sc.get("scene_id"),
                    "characters": [
                        name for name in (
                            (c.get("name") if isinstance(c, dict) else c)
                            for c in sc.get("characters_involved", [])
                        )
                        if name and not _is_non_character_item(name)
                    ],
                }
                for ep in (full_script.get("screenplay", {}).get("episodes", []) if isinstance(full_script, dict) else [])
                for sc in ep.get("scenes", [])
            ],
        }
    elif dimension == "scene":
        scene_assets = state.get("scene_assets") or {}
        full_script = state.get("full_script") or {}
        return {
            "scenes": [
                {
                    "scene_id": s.get("scene_id"),
                    "name": s.get("name"),
                    "time_of_day": s.get("time_of_day"),
                    "has_no_people_keywords": all(
                        k in ((s.get("base_prompt", "") or "") + " " + (s.get("negative_prompt", "") or "")).lower()
                        for k in ["no people", "no human", "no face"]
                    ),
                }
                for s in scene_assets.get("scenes", [])
            ],
            "full_script_scenes": [
                {"scene_id": sc.get("scene_id"), "time": sc.get("time")}
                for ep in (full_script.get("screenplay", {}).get("episodes", []) if isinstance(full_script, dict) else [])
                for sc in ep.get("scenes", [])
            ],
        }
    elif dimension == "storyboard":
        storyboards = (state.get("storyboard_data") or {}).get("storyboards", []) or []
        full_script = state.get("full_script") or {}
        return {
            "storyboards": [
                {
                    "storyboard_id": sb.get("storyboard_id"),
                    "linked_scene_id": sb.get("linked_scene_id"),
                    "linked_char_ids": sb.get("linked_char_ids") or [sb.get("linked_char_id")],
                    "shot_type": sb.get("shot_type"),
                    "composition": sb.get("composition"),
                    "duration_seconds": sb.get("duration_seconds"),
                }
                for sb in storyboards
            ],
            "full_script_scenes": [
                {
                    "scene_id": sc.get("scene_id"),
                    "characters": [
                        (c.get("name") if isinstance(c, dict) else c)
                        for c in sc.get("characters_involved", [])
                    ],
                }
                for ep in (full_script.get("screenplay", {}).get("episodes", []) if isinstance(full_script, dict) else [])
                for sc in ep.get("scenes", [])
            ],
        }
    elif dimension == "video":
        storyboards = (state.get("storyboard_data") or {}).get("storyboards", []) or []
        videos = (state.get("video_plan") or {}).get("videos", []) or []
        sb_by_id = {sb.get("storyboard_id"): sb for sb in storyboards}
        return {
            "videos": [
                {
                    "storyboard_id": v.get("storyboard_id"),
                    "final_video_prompt": v.get("final_video_prompt", ""),
                    "image_prompt": (sb_by_id.get(v.get("storyboard_id")) or {}).get("final_image_prompt", ""),
                }
                for v in videos
            ],
        }
    return {}


async def _run_reviewer(
    state: DramaProductionState,
    dimension: str,
    system_prompt: str,
) -> Dict[str, Any]:
    """运行单个维度 reviewer，返回评分与反馈。"""
    context = _build_reviewer_context(state, dimension)
    if not context:
        return {"dimension": dimension, "score": 100, "passed": True, "feedback_message": "", "target_ids": []}

    user_feedback = state.get("pending_user_feedback", "")
    user_feedback_hint = ""
    if user_feedback:
        user_feedback_hint = f"\n\n【用户重点关注】本次运行用户额外提出以下修改要求，请在验收时重点关注这些要求是否被满足：\n{user_feedback}"
    user_content = f"请对 {dimension} 维度进行验收。\n\n待验收数据：\n{json.dumps(context, ensure_ascii=False, indent=2)}{user_feedback_hint}"
    try:
        result = await _llm_json(
            system_prompt,
            user_content,
            model=_resolve_llm_model(state.get("options", {})),
            fallback={"score": 0, "passed": False, "feedback_message": f"{dimension} reviewer LLM 调用失败", "target_ids": []},
            token_tracker=state.get("token_tracker"),
            max_tokens=1024,
        )
        if is_fallback_result(result):
            return {
                "dimension": dimension,
                "score": 0,
                "passed": False,
                "feedback_message": f"{dimension} reviewer 返回 fallback：{result.get('_fallback_error', '')}",
                "target_ids": [],
                "_is_fallback": True,
            }
        return {
            "dimension": dimension,
            "score": int(result.get("score", 0)),
            "passed": bool(result.get("passed", False)),
            "feedback_message": result.get("feedback_message", "") or "",
            "target_ids": result.get("target_ids", []) or [],
        }
    except Exception as exc:
        return {
            "dimension": dimension,
            "score": 0,
            "passed": False,
            "feedback_message": f"{dimension} reviewer 异常：{exc}",
            "target_ids": [],
        }


# 阶段 -> reviewer 维度映射
_STAGE_REVIEWERS = {
    "asset": [
        ("character", _REVIEWER_CHARACTER_SYSTEM_PROMPT),
        ("scene", _REVIEWER_SCENE_SYSTEM_PROMPT),
    ],
    "production": [
        ("storyboard", _REVIEWER_STORYBOARD_SYSTEM_PROMPT),
        ("video", _REVIEWER_VIDEO_SYSTEM_PROMPT),
    ],
}

# reviewer 权重
_REVIEWER_WEIGHTS = {
    "character": 1.0,
    "scene": 1.0,
    "storyboard": 1.0,
    "video": 1.2,  # 视频提示词质量权重略高
}

_REVIEW_PASS_THRESHOLD = 70  # 加权平均分低于 70 判未通过


async def _review_node(state: DramaProductionState, stage: str, rules: str, target_agent: str) -> DramaProductionState:
    # 初始化导演记忆体系
    _initialize_director_memory(state)

    # 用户直接上传原始剧本或小说改编时，planning 阶段放宽时长一致性，优先保证原文完整
    _outline = state.get("script_outline") or {}
    _is_user_script = isinstance(_outline, dict) and bool(_outline.get("is_user_script"))
    _is_novel = isinstance(_outline, dict) and bool(_outline.get("is_novel"))
    if stage == "planning" and (_is_user_script or _is_novel):
        rules = rules.replace(
            "3. 【时长一致性】累计总时长误差 ≤ 3 秒，分场时长精确到秒。",
            "3. 【时长一致性】用户直接上传的原始剧本允许按原文篇幅拆分为多集，总时长可超出单集限制，严禁为凑单集时长而删减原文；分场时长仍需精确到秒。",
        )

    state["review_target"] = target_agent
    await _log(state, "system", "director_brain", stage, f"正在验收 {stage} 阶段产出...")

    # 1) 如果上游 Agent 运行时出错，直接把它转成质检反馈，避免 Review 默认通过导致无限循环
    runtime_error = state.get("last_error", "")
    if runtime_error:
        # 检测是否为 LLM 服务连接/超时类错误，这类错误需要退避后重试
        is_llm_service_error = _is_llm_service_error(runtime_error)
        retry_count = (state.get("retry_count") or 0) + 1
        from app.core.config import settings as _settings
        max_retries = _settings.DRAMA_BRAIN_MAX_RETRIES

        if is_llm_service_error:
            # LLM 服务错误：重试前等待退避时间，避免立即重试再次失败
            backoff = min(5 * retry_count, 15)
            await _log(
                state, "system", "director_brain", stage,
                f"检测到 LLM 服务异常（连接/超时），等待 {backoff}s 后重试...（第 {retry_count}/{max_retries} 次）"
            )
            await asyncio.sleep(backoff)

        correction = _format_correction_instruction(
            agent=target_agent,
            level="严重",
            location=f"{stage} 阶段运行时",
            issue_type="运行时错误" if not is_llm_service_error else "LLM 服务异常",
            violated_rule="子 Agent 必须稳定返回结构化输出，禁止抛异常",
            requirement="修复运行时报错并重新执行任务，确保输出符合强制 JSON 结构",
            acceptance="无异常退出，输出可被下游正常解析",
            retry_count=retry_count,
            version=state.get("rule_version", "1.0"),
        )
        state["feedback_message"] = f"运行时错误：{runtime_error}\n\n{correction}"
        state["retry_count"] = retry_count
        state["last_error"] = ""
        _record_error_case(state, stage, target_agent, "运行时错误", f"{stage} 阶段", runtime_error, "修复异常并重新执行")
        await _log(state, "system", "director_brain", stage, f"{stage} 阶段 Agent 报错，等待重试：{runtime_error}")
        return state

    # M3: 上游 Agent 返回了 fallback 兜底数据，Review 必须直接判失败，避免 mock 产物通过验收
    fallback_targets = _collect_fallback_targets(state)
    if fallback_targets:
        fb_msg = f"上游 LLM 调用失败并返回了 fallback 数据：{', '.join(fallback_targets)}，无法验收。"
        retry_count = (state.get("retry_count") or 0) + 1
        from app.core.config import settings as _settings
        max_retries = _settings.DRAMA_BRAIN_MAX_RETRIES

        # fallback 通常也是 LLM 服务异常导致，重试前退避等待
        backoff = min(5 * retry_count, 15)
        await _log(
            state, "system", "director_brain", stage,
            f"LLM 返回 fallback 数据，等待 {backoff}s 后重试...（第 {retry_count}/{max_retries} 次）"
        )
        await asyncio.sleep(backoff)

        correction = _format_correction_instruction(
            agent=target_agent,
            level="严重",
            location=f"{stage} 阶段 fallback 字段：{', '.join(fallback_targets)}",
            issue_type="LLM fallback 兜底",
            violated_rule="上游 Agent 必须调用 LLM 成功并返回有效结构化数据",
            requirement="检查 LLM 服务可用性后重试，或降低输出复杂度后重试",
            acceptance="所有字段返回有效非 fallback 数据",
            retry_count=retry_count,
            version=state.get("rule_version", "1.0"),
        )
        state["feedback_message"] = f"{fb_msg}\n\n{correction}"
        state["retry_count"] = retry_count
        _record_error_case(state, stage, target_agent, "LLM fallback", f"{stage} 阶段", fb_msg, "检查 LLM 服务并重试")
        await _log(state, "system", "director_brain", stage, fb_msg)
        return state

    # 2) 阶段确定性预检（先跑规则化硬检查，不消耗 LLM token）
    pre_check_map = {
        "planning": _planning_pre_check,
        "asset": _asset_pre_check,
        "production": _production_pre_check,
    }
    pre_check_fn = pre_check_map.get(stage)
    if pre_check_fn:
        pre_check_feedback = pre_check_fn(state)
        if pre_check_feedback:
            correction = _format_correction_instruction(
                agent=target_agent,
                level="严重",
                location=f"{stage} 阶段确定性预检",
                issue_type="预检未通过",
                violated_rule="阶段输出必须通过规则化硬检查（格式、ID、必填字段、跨环节对齐）",
                requirement=f"按以下预检反馈逐项修复：\n{pre_check_feedback}",
                acceptance="重新预检无问题，所有硬规则检查项全部通过",
                retry_count=(state.get("retry_count") or 0) + 1,
                version=state.get("rule_version", "1.0"),
            )
            state["feedback_message"] = correction
            state["retry_count"] = (state.get("retry_count") or 0) + 1
            state["review_target"] = target_agent
            _record_error_case(state, stage, target_agent, "预检未通过", f"{stage} 阶段", pre_check_feedback, "按预检反馈逐项修复")
            await _log(state, "system", "director_brain", stage, f"{stage} 阶段预检未通过")
            return state

    # M1: 细粒度 reviewer 并发评分（planning 仍用单 reviewer，asset/production 拆维度）
    reviewers = _STAGE_REVIEWERS.get(stage, [])
    review_results: List[Dict[str, Any]] = []

    # 用户直接上传原始剧本或小说改编时，planning 阶段预检通过即可跳过 LLM reviewer，显著缩短等待时间
    is_user_script = state.get("options", {}).get("mode") in ("script", "novel")
    # production 阶段首次通过预检时跳过 LLM reviewer，节省 2 次 LLM 调用（~30-60s）；
    # 重试时仍跑 reviewer 以确保质量问题被捕获
    is_production_first_pass = stage == "production" and (state.get("retry_count") or 0) == 0

    # P13: 边缘分数强制 LLM 审核 — 即使首次预检通过，如果预检中存在 warning 级别问题也强制跑 reviewer
    pre_check_warnings = state.get("_pre_check_warnings", [])
    force_llm_review = bool(pre_check_warnings) and stage in ("asset", "production")

    if stage == "planning" and is_user_script and not force_llm_review:
        await _log(state, "system", "director_brain", stage, "用户上传剧本模式，planning 阶段预检通过，跳过 LLM reviewer")
        review_results = [{"dimension": "planning", "score": 100, "passed": True, "feedback_message": "", "target_ids": []}]
    elif is_production_first_pass and not force_llm_review:
        await _log(state, "system", "director_brain", stage, "production 阶段首次预检通过，跳过 LLM reviewer（重试时仍会执行）")
        review_results = [
            {"dimension": "storyboard", "score": 100, "passed": True, "feedback_message": "", "target_ids": []},
            {"dimension": "video", "score": 100, "passed": True, "feedback_message": "", "target_ids": []},
        ]
    elif reviewers:
        await _log(state, "system", "director_brain", stage, f"启动 {len(reviewers)} 个细粒度 reviewer...")
        review_results = await asyncio.gather(*[
            _run_reviewer(state, dim, prompt) for dim, prompt in reviewers
        ])
    else:
        # planning 阶段：使用三级审核体系 reviewer
        context = {
            "script_outline": state.get("script_outline"),
            "full_script": state.get("full_script"),
        }
        user_feedback = state.get("pending_user_feedback", "")
        user_feedback_hint = ""
        if user_feedback:
            user_feedback_hint = f"\n\n【用户重点关注】本次运行用户额外提出以下修改要求，请在验收时重点关注这些要求是否被满足：\n{user_feedback}"
        user_content = f"请按三级审核体系验收 planning 阶段产出。\n\n{_REVIEW_PLANNING_RULES}\n\n待验收数据：\n{json.dumps(context, ensure_ascii=False, indent=2)}{user_feedback_hint}"
        try:
            result = await _llm_json(
                _REVIEW_SYSTEM_PROMPT + _REVIEW_PLANNING_RULES,
                user_content,
                model=_resolve_llm_model(state.get("options", {})),
                fallback={"score": 0, "passed": False, "feedback_message": "Planning reviewer LLM 调用失败", "target_ids": []},
                token_tracker=state.get("token_tracker"),
                max_tokens=1024,
            )
            if is_fallback_result(result):
                review_results = [{"dimension": "planning", "score": 0, "passed": False, "feedback_message": result.get("_fallback_error", ""), "target_ids": [], "_is_fallback": True}]
            else:
                review_results = [{
                    "dimension": "planning",
                    "score": int(result.get("score", 100) if result.get("passed") else 0),
                    "passed": bool(result.get("passed", False)),
                    "feedback_message": result.get("feedback_message", "") or "",
                    "target_ids": result.get("target_ids", []) or [],
                }]
        except Exception as exc:
            review_results = [{"dimension": "planning", "score": 0, "passed": False, "feedback_message": f"Planning reviewer 异常：{exc}", "target_ids": []}]

    # 汇总评分
    total_weight = 0.0
    weighted_score = 0.0
    failed_dimensions = []
    fallback_dimensions = []
    all_target_ids: List[str] = []
    feedback_parts = []

    for r in review_results:
        dim = r.get("dimension", "unknown")
        weight = _REVIEWER_WEIGHTS.get(dim, 1.0)
        score = r.get("score", 0)
        total_weight += weight
        weighted_score += score * weight
        if not r.get("passed"):
            failed_dimensions.append(dim)
        if r.get("_is_fallback"):
            fallback_dimensions.append(dim)
        if r.get("feedback_message"):
            feedback_parts.append(f"[{dim}] {r['feedback_message']}")
        all_target_ids.extend(r.get("target_ids", []) or [])

    aggregate_score = int(weighted_score / total_weight) if total_weight else 0
    passed = aggregate_score >= _REVIEW_PASS_THRESHOLD and not fallback_dimensions

    # 记录各维度评分到 state，供前端展示与局部重试使用
    state["review_scores"] = {r.get("dimension"): r.get("score") for r in review_results}
    state["review_issues"] = [
        {"dimension": r.get("dimension"), "target_ids": r.get("target_ids", [])}
        for r in review_results if not r.get("passed")
    ]
    state["review_target_ids"] = list(set(all_target_ids))

    if fallback_dimensions:
        correction = _format_correction_instruction(
            agent="reviewer",
            level="严重",
            location=f"{stage} 阶段 reviewer",
            issue_type="Reviewer LLM fallback",
            violated_rule="Reviewer 必须正常返回评分 JSON，禁止 fallback",
            requirement="检查 LLM 服务可用性后重试，或缩短 reviewer 上下文后重试",
            acceptance="所有 reviewer 正常返回评分与反馈",
            retry_count=(state.get("retry_count") or 0) + 1,
            version=state.get("rule_version", "1.0"),
        )
        state["feedback_message"] = f"以下 reviewer 返回 fallback，无法完成验收：{', '.join(fallback_dimensions)}。请检查 LLM 服务。\n\n{correction}"
        state["retry_count"] = (state.get("retry_count") or 0) + 1
        _record_error_case(state, stage, "reviewer", "Reviewer fallback", f"{stage} 阶段", f"fallback 维度：{fallback_dimensions}", "检查 LLM 服务并重试")
        await _log(state, "system", "director_brain", stage, f"{stage} 阶段 reviewer fallback，按未通过处理")
        return state

    if passed:
        state["feedback_message"] = ""
        state["retry_count"] = 0
        state["last_error"] = ""

        # P6: 验收通过时创建版本快照
        snapshot_stage_map = {
            "planning": "script_ready",
            "asset": "character_scene_done",
            "production": "storyboard_video_done",
        }
        snapshot_stage = snapshot_stage_map.get(stage, stage)
        if should_snapshot(snapshot_stage):
            try:
                add_version_to_session(state, snapshot_stage, label=f"{stage} 验收通过")
            except Exception as vs_err:
                logger.warning("[VersionManager] 快照创建失败: %s", vs_err)

        # P7: Token 预算检查
        budget_warning = check_token_budget(state.get("token_tracker"))
        if budget_warning:
            await _log(state, "system", "director_brain", stage, f"Token 预算警告: {budget_warning}")

        await _log(state, "system", "director_brain", stage, f"{stage} 阶段验收通过（综合得分 {aggregate_score}）", {"scores": state.get("review_scores")})
    else:
        feedback = "\n".join(feedback_parts)
        correction = _format_correction_instruction(
            agent=target_agent,
            level="一般" if aggregate_score >= 50 else "严重",
            location=f"{stage} 阶段：{', '.join(failed_dimensions)}",
            issue_type="三级审核未通过",
            violated_rule=f"综合得分 {aggregate_score} 低于阈值 {_REVIEW_PASS_THRESHOLD}，或存在未通过维度",
            requirement=f"按以下 feedback 逐项修复：\n{feedback}",
            acceptance=f"重新验收综合得分 ≥ {_REVIEW_PASS_THRESHOLD}，且所有维度均通过",
            retry_count=(state.get("retry_count") or 0) + 1,
            version=state.get("rule_version", "1.0"),
        )
        state["feedback_message"] = correction
        state["retry_count"] = (state.get("retry_count") or 0) + 1
        state["last_error"] = ""
        _record_error_case(state, stage, target_agent, "三级审核未通过", f"{stage} 阶段", feedback, "按 feedback 逐项修复")

        # 自我进化：连续 3 次未通过触发规则库版本升级
        retry = state.get("retry_count") or 0
        if retry >= 3:
            _evolve_rule_version(
                state,
                reason=f"{stage} 阶段连续 {retry} 次未通过，触发规则强化",
                changes=[f"针对 {failed_dimensions} 维度增补前置约束", "提升对应 reviewer 审核严格度", "记录错误案例到长期记忆库"],
            )
            await _log(state, "system", "director_brain", stage, f"规则库升级至 V{state.get('rule_version')}，原因：{stage} 连续 {retry} 次未通过")

        await _log(state, "system", "director_brain", stage, f"{stage} 阶段验收未通过（综合得分 {aggregate_score}）", {"scores": state.get("review_scores")})
    return state


async def review_planning(state: DramaProductionState) -> DramaProductionState:
    state["current_stage"] = "planning"
    return await _review_node(state, "planning", _REVIEW_PLANNING_RULES, "screenwriter")


async def review_asset(state: DramaProductionState) -> DramaProductionState:
    state["current_stage"] = "asset"
    return await _review_node(state, "asset", _REVIEW_ASSET_RULES, "scene_prop_designer")


async def review_production(state: DramaProductionState) -> DramaProductionState:
    state["current_stage"] = "production"
    return await _review_node(state, "production", _REVIEW_PRODUCTION_RULES, "storyboard_director")


# ---------------------------------------------------------------------------
# 条件边
# ---------------------------------------------------------------------------
def _should_retry(state: DramaProductionState) -> bool:
    # 只要还有质检反馈/运行时错误，并且重试次数未超，就回到对应节点重试
    from app.core.config import settings
    max_retries = settings.DRAMA_BRAIN_MAX_RETRIES
    retry_count = state.get("retry_count") or 0
    has_feedback = bool(state.get("feedback_message"))

    if not has_feedback:
        return False

    # P15: 检查上次错误是否为致命错误（致命错误不重试）
    last_error = state.get("last_error", "")
    if last_error:
        try:
            exc = Exception(last_error)
            if should_stop_retrying(exc, retry_count, max_retries):
                return False
        except Exception:
            pass

    return retry_count < max_retries


def _collect_fallback_targets(state: DramaProductionState) -> List[str]:
    """检查 state 中各阶段产物是否为 fallback 兜底数据，返回有问题的字段名。"""
    targets = []
    key_map = {
        "script_outline": "剧本大纲",
        "full_script": "分场剧本",
        "character_assets": "角色资产",
        "scene_assets": "场景资产",
        "storyboard_data": "分镜脚本",
        "video_plan": "视频规划",
    }
    for key, label in key_map.items():
        value = state.get(key)
        if isinstance(value, dict) and value.get("_is_fallback"):
            targets.append(f"{label}({key})")
    return targets


def _is_video_prompt_feedback(feedback: str) -> bool:
    """判断质检反馈是否主要指向视频提示词问题，应路由到 video_composer 重写。"""
    if not feedback:
        return False
    keywords = [
        "video", "final_video_prompt", "seedance", "motion", "camera", "audio",
        "视频提示词", "视频", "运镜", "动作", "seedance", "identical to image",
        " identical", " lacks ", "缺少动作", "缺少运镜", "和分镜一样",
    ]
    low = feedback.lower()
    return any(k.lower() in low for k in keywords)


def _is_llm_service_error(error_msg: str) -> bool:
    """判断错误是否为 LLM 服务连接/超时类错误（而非剧本质量问题）。

    这类错误重试前需要退避等待，且应路由回阶段开头重新执行。
    """
    msg = error_msg.lower()
    signals = [
        "连接失败", "connecterror", "connection", "网络",
        "超时", "timeout", "timed out",
        "ai 服务请求", "ai 服务连接", "ai 服务请求超时",
        "ai 服务 http",
        "runtimeerror",
        "fallback", "兜底",
        "readtimeout", "connecttimeout", "writetimeout", "pooltimeout",
        "networkerror", "protocolerror",
    ]
    return any(s in msg for s in signals)


def _identify_planning_retry_target(state: DramaProductionState) -> str:
    """根据 feedback 内容判断 planning 阶段应路由回 script_planner 还是 screenwriter。

    规则：
    - 如果 feedback 中提到 script_outline / 大纲 / 分场清单 / scene 缺少 emotion_beat /
      transition_hint / duration 等字段，说明问题在 script_planner 产出，应路由回 script_planner。
    - 如果 feedback 中提到 full_script / 分场剧本 / 对白 / action_description / 时长误差
      / 角色不一致等，说明问题在 screenwriter 产出，应路由回 screenwriter。
    """
    feedback = (state.get("feedback_message") or "").lower()
    if not feedback:
        return "screenwriter"

    # script_planner 相关关键词
    script_planner_signals = [
        "script_outline", "大纲", "分场清单", "episode", "scene 缺少", "scenes 缺少",
        "emotion_beat", "transition_hint", "缺少字段", "color_palette", "style_bible",
        "logline", "episodes", "scene_id",
    ]
    # screenwriter 相关关键词
    screenwriter_signals = [
        "full_script", "分场剧本", "对白", "action_description", "dialogues",
        "characters_involved", "角色不一致", "剧情连贯性", "情绪曲线", "可拍摄性",
        "单句对白", "口语化", "时长误差",
    ]

    sp_score = sum(1 for k in script_planner_signals if k.lower() in feedback)
    sw_score = sum(1 for k in screenwriter_signals if k.lower() in feedback)

    # 如果 feedback 明确指向 script_outline 问题，优先回 script_planner
    if sp_score > sw_score:
        return "script_planner"
    return "screenwriter"


def route_after_review_planning(state: DramaProductionState) -> str:
    if _should_retry(state):
        # 如果是 LLM 服务异常，路由回阶段开头（script_planner）重新执行整个阶段
        feedback = state.get("feedback_message") or ""
        if _is_llm_service_error(feedback):
            state["script_outline"] = {}
            return "script_planner"
        target = _identify_planning_retry_target(state)
        # 如果要回 script_planner，清除旧 script_outline 强制重生成（screenwriter 会基于新大纲重写）
        if target == "script_planner":
            state["script_outline"] = {}
        return target
    return "character_designer"


def route_after_review_asset(state: DramaProductionState) -> str:
    # 资产阶段任一环节未通过，都回到角色设计师重新开始该阶段，以保证角色/场景一致性
    if _should_retry(state):
        return "character_designer"
    return "storyboard_director"


def route_after_review_production(state: DramaProductionState) -> str:
    if not _should_retry(state):
        return END
    # 如果反馈明显指向视频提示词问题，只让 video_composer 重写，避免重新生成分镜
    if _is_video_prompt_feedback(state.get("feedback_message", "")):
        return "video_composer"
    # 否则回到分镜导演整体重拆
    return "storyboard_director"


# ---------------------------------------------------------------------------
# 分阶段子图
# ---------------------------------------------------------------------------
def build_planning_graph() -> StateGraph:
    g = StateGraph(DramaProductionState)
    g.add_node("script_planner", node_script_planner)
    g.add_node("screenwriter", node_screenwriter)
    g.add_node("review_planning", review_planning)
    g.set_entry_point("script_planner")
    g.add_edge("script_planner", "screenwriter")
    g.add_edge("screenwriter", "review_planning")
    g.add_conditional_edges(
        "review_planning",
        route_after_review_planning,
        {"screenwriter": "screenwriter", "character_designer": "__end__"},
    )
    return g.compile()


def build_asset_graph() -> StateGraph:
    g = StateGraph(DramaProductionState)
    g.add_node("asset_parallel", node_asset_parallel)
    g.add_node("review_asset", review_asset)
    g.set_entry_point("asset_parallel")
    g.add_edge("asset_parallel", "review_asset")
    g.add_conditional_edges(
        "review_asset",
        route_after_review_asset,
        {"character_designer": "asset_parallel", "storyboard_director": "__end__"},
    )
    return g.compile()


def build_production_graph() -> StateGraph:
    g = StateGraph(DramaProductionState)
    g.add_node("storyboard_director", node_storyboard_director)
    g.add_node("video_composer", node_video_composer)
    g.add_node("review_production", review_production)
    g.set_entry_point("storyboard_director")
    g.add_edge("storyboard_director", "video_composer")
    g.add_edge("video_composer", "review_production")
    g.add_conditional_edges(
        "review_production",
        route_after_review_production,
        {"storyboard_director": "storyboard_director", "video_composer": "video_composer", END: END},
    )
    return g.compile()


def build_lite_storyboard_graph() -> StateGraph:
    """轻量分镜子图：单节点，直接从剧本文本生成分镜表 + 视频提示词组。"""
    g = StateGraph(DramaProductionState)
    g.add_node("lite_storyboard", node_lite_storyboard)
    g.set_entry_point("lite_storyboard")
    g.add_edge("lite_storyboard", END)
    return g.compile()


_STAGE_GRAPHS = {
    "planning": build_planning_graph,
    "asset": build_asset_graph,
    "production": build_production_graph,
    "lite_storyboard": build_lite_storyboard_graph,
}


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
async def run_stage(
    state: DramaProductionState,
    stage: str,
    message_queue: Optional[asyncio.Queue] = None,
) -> DramaProductionState:
    """运行单个阶段，返回更新后的 State。"""
    # 确保导演记忆体系已初始化
    _initialize_director_memory(state)

    builder = _STAGE_GRAPHS.get(stage)
    if not builder:
        raise ValueError(f"未知阶段: {stage}")
    graph = builder()
    state["current_stage"] = stage
    # 如果用户通过 feedback 接口提交了针对本阶段的反馈，保存到 pending_user_feedback
    # 该字段专门用于透传给子 Agent，不会被 script_planner 等节点清空
    user_feedback = state.get("user_feedback", "")
    user_feedback_stage = state.get("user_feedback_stage", "")
    if user_feedback and user_feedback_stage == stage:
        state["pending_user_feedback"] = user_feedback
        state["user_feedback"] = ""
        state["user_feedback_stage"] = ""
        await _log(state, "system", "director_brain", stage, f"已接收用户反馈，将在本次 {stage} 阶段执行时透传给子 Agent")
    else:
        state["pending_user_feedback"] = ""
    # feedback_message 保留 Reviewer 的修正意见，用于重试路由
    state["feedback_message"] = ""
    state["last_error"] = ""
    state["review_target"] = ""
    state["retry_count"] = 0  # 每个阶段独立计算重试次数
    state["message_queue"] = message_queue
    final_state = await graph.ainvoke(state, {"recursion_limit": 100})
    # 阶段结束时，如果还有反馈消息说明未通过但已超次，保留给前端展示
    if not final_state.get("feedback_message"):
        final_state["feedback_message"] = ""
    final_state.pop("message_queue", None)
    return final_state


async def run_drama_brain(user_instruction: str, options: Optional[Dict[str, str]] = None) -> DramaProductionState:
    """一次性跑完全部阶段（测试用）。"""
    state: DramaProductionState = {
        "user_instruction": user_instruction,
        "options": options or {},
        "current_stage": "planning",
        "feedback_message": "",
        "user_feedback": "",
        "user_feedback_stage": "",
        "retry_count": 0,
        "review_target": "",
        "last_error": "",
        "messages": [],
        "rule_version": "1.0",
        "error_case_library": [],
        "best_practice_library": [],
        "iteration_log": [],
    }
    for stage in ["planning", "asset", "production"]:
        state = await run_stage(state, stage)
    state["current_stage"] = "finished"
    return state
