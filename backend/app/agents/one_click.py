"""
一键短剧编排器：从一句话灵感到画布全节点自动创建的全自动流水线。

核心流程：
  1. create_session   — 创建会话（复用现有逻辑）
  2. auto_params      — LLM 自动推断全局参数并直接确认（跳过用户手动确认）
  3. run_planning     — 执行 planning 阶段（剧本+编剧+质检）
  4. auto_lock        — 自动锁定所有角色和场景（不生图，只锁定结构）
  5. run_production   — 执行 production 阶段（分镜+视频参数+质检）
  6. auto_finalize    — 自动创建画布和节点（不触发生成，留待用户确认）

注意：生图和生视频不在自动流程中，需用户手动确认后触发（涉及费用）。
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Awaitable

from app.agents.short_drama import short_drama_workflow, WorkflowMessage

logger = logging.getLogger(__name__)

# ── 阶段定义 ──────────────────────────────────────────────────

STAGE_LABELS = {
    "auto_params": "参数推断",
    "planning": "剧本创作",
    "asset": "资产提取",
    "auto_lock": "资产锁定",
    "production": "分镜制作",
    "finalize": "画布创建",
}

STAGE_WEIGHTS = {
    "auto_params": 5,
    "planning": 25,
    "asset": 20,
    "auto_lock": 5,
    "production": 30,
    "finalize": 15,
}

TOTAL_WEIGHT = sum(STAGE_WEIGHTS.values())


def _build_progress_payload(
    completed_weight: int,
    stage: str,
    elapsed: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建 SSE 进度 payload。"""
    overall = int(completed_weight * 100 / TOTAL_WEIGHT)
    return {
        "overall_progress": overall,
        "current_stage": stage,
        "elapsed": elapsed,
        **(extra or {}),
    }


async def run_one_click(
    sid: str,
    db,
    user_id: str,
    on_message: Optional[Callable[[WorkflowMessage], Awaitable[None]]] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    """执行一键流水线。

    Args:
        sid: 会话 ID
        db: 数据库 Session
        user_id: 用户 ID
        on_message: SSE 消息回调
        resume: 是否断点续跑

    Returns:
        {"status": "success"|"failed", "canvas_id": ..., "error": ...}
    """
    start_time = time.time()
    session = short_drama_workflow.get_session(sid)
    if not session:
        return {"status": "failed", "error": "会话不存在"}

    # 读取已完成阶段（断点续跑）
    completed_stages: List[str] = session.get("one_click_completed_stages", []) if resume else []
    canvas_id: Optional[str] = session.get("one_click_canvas_id")

    async def emit(step: str, content: str, payload: Optional[Dict] = None):
        msg = WorkflowMessage(
            role="system",
            agent="orchestrator",
            step=step,
            content=content,
            payload=payload or {},
        )
        session["messages"].append(msg.__dict__)
        if on_message:
            await on_message(msg)

    async def emit_progress(stage: str, content: str, completed_weight: int, extra: Optional[Dict] = None):
        elapsed = int(time.time() - start_time)
        await emit(
            f"{stage}_progress",
            content,
            _build_progress_payload(completed_weight, stage, elapsed, extra),
        )

    # ── 定义阶段执行函数 ──────────────────────────────────────

    completed_weight = sum(STAGE_WEIGHTS.get(s, 0) for s in completed_stages)

    # 阶段 1：自动推断参数
    if "auto_params" not in completed_stages:
        await emit("stage_start", "🔍 正在分析灵感，自动推断创作参数...",
                   _build_progress_payload(completed_weight, "auto_params", 0))
        try:
            result = await short_drama_workflow.suggest_parameters(sid)
            if result.get("status") == "failed":
                return {"status": "failed", "error": f"参数推断失败: {result.get('error')}"}
            suggestions = result.get("suggestions", {})
            # 直接用推荐参数确认
            confirm_result = short_drama_workflow.confirm_parameters(sid, suggestions)
            if confirm_result.get("status") == "failed":
                return {"status": "failed", "error": f"参数确认失败: {confirm_result.get('error')}"}
            completed_weight += STAGE_WEIGHTS["auto_params"]
            completed_stages.append("auto_params")
            _mark_stage_complete(sid, "auto_params")
            await emit("stage_done", "✅ 参数已自动确认",
                       _build_progress_payload(completed_weight, "auto_params", int(time.time() - start_time),
                                               {"global_params": suggestions}))
        except Exception as exc:
            logger.error("[OneClick] auto_params 失败: %s", exc, exc_info=True)
            await emit("error", f"❌ 参数推断失败: {exc}")
            return {"status": "failed", "error": str(exc)}

    # 阶段 2：planning（剧本+编剧+质检）
    if "planning" not in completed_stages:
        await emit("stage_start", "🎭 正在创作剧本大纲与分场剧本...",
                   _build_progress_payload(completed_weight, "planning", 0))

        async def _planning_callback(msg: WorkflowMessage):
            # 透传 planning 阶段的子 Agent 进度
            if on_message:
                await on_message(msg)

        try:
            result = await short_drama_workflow.run_step(sid, "planning", db, on_message=_planning_callback)
            if result.status == "failed":
                return {"status": "failed", "error": f"剧本创作失败: {result.error}"}
            completed_weight += STAGE_WEIGHTS["planning"]
            completed_stages.append("planning")
            _mark_stage_complete(sid, "planning")
            await emit("stage_done", "✅ 剧本创作完成",
                       _build_progress_payload(completed_weight, "planning", int(time.time() - start_time)))
        except Exception as exc:
            logger.error("[OneClick] planning 失败: %s", exc, exc_info=True)
            await emit("error", f"❌ 剧本创作失败: {exc}")
            return {"status": "failed", "error": str(exc)}

    # 阶段 3：asset（角色/场景提取，不生图）
    if "asset" not in completed_stages:
        await emit("stage_start", "🎨 正在从剧本中提取角色与场景...",
                   _build_progress_payload(completed_weight, "asset", 0))

        async def _asset_callback(msg: WorkflowMessage):
            if on_message:
                await on_message(msg)

        try:
            result = await short_drama_workflow.run_step(sid, "asset", db, on_message=_asset_callback)
            if result.status == "failed":
                return {"status": "failed", "error": f"资产提取失败: {result.error}"}
            completed_weight += STAGE_WEIGHTS["asset"]
            completed_stages.append("asset")
            _mark_stage_complete(sid, "asset")
            # 读取提取结果统计
            session = short_drama_workflow.get_session(sid)
            char_data = session.get("character_assets") or session.get("character") or {}
            scene_data = session.get("scene_assets") or session.get("scene") or {}
            char_count = len(char_data.get("characters", []))
            scene_count = len(scene_data.get("scenes", []))
            await emit("stage_done", f"✅ 已提取 {char_count} 个角色 + {scene_count} 个场景",
                       _build_progress_payload(completed_weight, "asset", int(time.time() - start_time),
                                               {"char_count": char_count, "scene_count": scene_count}))
        except Exception as exc:
            logger.error("[OneClick] asset 失败: %s", exc, exc_info=True)
            await emit("error", f"❌ 资产提取失败: {exc}")
            return {"status": "failed", "error": str(exc)}

    # 阶段 4：自动锁定所有资产（不生图）
    if "auto_lock" not in completed_stages:
        await emit("stage_start", "🔒 正在自动锁定所有角色与场景...",
                   _build_progress_payload(completed_weight, "auto_lock", 0))
        try:
            session = short_drama_workflow.get_session(sid)
            char_data = session.get("character_assets") or session.get("character") or {}
            scene_data = session.get("scene_assets") or session.get("scene") or {}

            char_ids = [c.get("char_id", c.get("id", "")) for c in char_data.get("characters", []) if c.get("char_id") or c.get("id")]
            scene_ids = [s.get("scene_id", s.get("id", "")) for s in scene_data.get("scenes", []) if s.get("scene_id") or s.get("id")]

            # 不调用 lock_assets（那会触发 AI 生图），只做结构锁定
            session["locked_assets"] = [
                {"type": "character", **c} for c in char_data.get("characters", [])
            ] + [
                {"type": "scene", **s} for s in scene_data.get("scenes", [])
            ]
            session["asset_ids"] = []
            short_drama_workflow.save_session(sid, session)

            completed_weight += STAGE_WEIGHTS["auto_lock"]
            completed_stages.append("auto_lock")
            _mark_stage_complete(sid, "auto_lock")
            await emit("stage_done", f"✅ 已锁定 {len(char_ids)} 个角色 + {len(scene_ids)} 个场景（未生图，请在画布手动生成）",
                       _build_progress_payload(completed_weight, "auto_lock", int(time.time() - start_time),
                                               {"char_count": len(char_ids), "scene_count": len(scene_ids)}))
        except Exception as exc:
            logger.error("[OneClick] auto_lock 失败: %s", exc, exc_info=True)
            await emit("error", f"❌ 资产锁定失败: {exc}")
            return {"status": "failed", "error": str(exc)}

    # 阶段 5：production（分镜+视频参数+质检）
    if "production" not in completed_stages:
        await emit("stage_start", "🎬 正在生成分镜与视频参数...",
                   _build_progress_payload(completed_weight, "production", 0))

        async def _production_callback(msg: WorkflowMessage):
            if on_message:
                await on_message(msg)

        try:
            result = await short_drama_workflow.run_step(sid, "production", db, on_message=_production_callback)
            if result.status == "failed":
                return {"status": "failed", "error": f"分镜制作失败: {result.error}"}
            completed_weight += STAGE_WEIGHTS["production"]
            completed_stages.append("production")
            _mark_stage_complete(sid, "production")
            await emit("stage_done", "✅ 分镜与视频参数完成",
                       _build_progress_payload(completed_weight, "production", int(time.time() - start_time)))
        except Exception as exc:
            logger.error("[OneClick] production 失败: %s", exc, exc_info=True)
            await emit("error", f"❌ 分镜制作失败: {exc}")
            return {"status": "failed", "error": str(exc)}

    # 阶段 6：自动创建画布
    if "finalize" not in completed_stages:
        await emit("stage_start", "🏗️ 正在创建画布与节点...",
                   _build_progress_payload(completed_weight, "finalize", 0))
        try:
            from app.services.canvas_builder import build_canvas_from_session
            session = short_drama_workflow.get_session(sid)
            result = build_canvas_from_session(db, session, user_id=user_id)
            canvas = result["canvas"]
            db.commit()

            canvas_id = str(canvas.id)
            session["status"] = "finalized"
            session["finalized_canvas_id"] = canvas_id
            session["one_click_canvas_id"] = canvas_id
            short_drama_workflow.save_session(sid, session)

            completed_weight += STAGE_WEIGHTS["finalize"]
            completed_stages.append("finalize")
            _mark_stage_complete(sid, "finalize")
            await emit("stage_done", f"✅ 画布已创建（{result.get('node_count', 0)} 个节点）",
                       _build_progress_payload(completed_weight, "finalize", int(time.time() - start_time),
                                               {"canvas_id": canvas_id, "node_count": result.get("node_count", 0)}))
        except Exception as exc:
            logger.error("[OneClick] finalize 失败: %s", exc, exc_info=True)
            db.rollback()
            await emit("error", f"❌ 画布创建失败: {exc}")
            return {"status": "failed", "error": str(exc)}

    # 完成
    elapsed = int(time.time() - start_time)
    await emit("one_click_complete", "🎉 一键创作完成！可在画布中查看并手动生成图片/视频",
               _build_progress_payload(TOTAL_WEIGHT, "done", elapsed,
                                       {"canvas_id": canvas_id}))

    return {"status": "success", "canvas_id": canvas_id, "elapsed": elapsed}


def _mark_stage_complete(sid: str, stage: str):
    """标记阶段完成到 session（断点续跑用）。"""
    session = short_drama_workflow.get_session(sid)
    if not session:
        return
    completed = session.get("one_click_completed_stages", [])
    if stage not in completed:
        completed.append(stage)
    session["one_click_completed_stages"] = completed
    session["one_click_mode"] = True
    short_drama_workflow.save_session(sid, session)
