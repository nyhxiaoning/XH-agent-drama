import json
import asyncio
import logging
import time
import uuid
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.memory import memory_cache
from app.api.deps import get_current_user
from app.agents.short_drama import short_drama_workflow, WorkflowMessage
from app.schemas.asset import AgentRequest
from app.schemas.canvas import CanvasCreate
from app.schemas.node import NodeCreate
from app.schemas.edge import EdgeCreate
from app.models.node import Node, NodeType, NodeStatus
from app.models.edge import Edge
from app.models.asset import Asset
from app.models.user import User
from app.models.model_config import ModelConfig
from app.crud import canvas as crud_canvas
from app.crud import node as crud_node
from app.crud import edge as crud_edge
from app.crud import asset as crud_asset
from app.services.credit_service import calculate_cost, deduct_credits, InsufficientCreditsError
from app.skills import list_skills, run_skill
from app.agents.platform_brain import platform_brain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/context/{node_id}")
def get_node_context(node_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    source_edges = db.query(Edge).filter(Edge.source_node_id == node_id).all()
    target_edges = db.query(Edge).filter(Edge.target_node_id == node_id).all()

    connected_node_ids = set()
    for e in source_edges:
        connected_node_ids.add(str(e.target_node_id))
    for e in target_edges:
        connected_node_ids.add(str(e.source_node_id))

    # #18: 批量查询关联节点，避免 N+1 问题
    connected_nodes = []
    if connected_node_ids:
        nodes = db.query(Node).filter(Node.id.in_([UUID(nid) for nid in connected_node_ids])).all()
        connected_nodes = [
            {
                "id": str(n.id),
                "title": n.title,
                "node_type": n.node_type.value,
                "status": n.status.value,
            }
            for n in nodes
        ]

    related_assets = db.query(Asset).filter(
        Asset.asset_type.in_(["image", "video", "character", "scene"])
    ).order_by(Asset.created_at.desc()).limit(5).all()

    chat_history = memory_cache.get_chat_history(str(node_id))

    context = {
        "node_id": str(node_id),
        "node": {
            "id": str(node.id),
            "title": node.title,
            "node_type": node.node_type.value,
            "status": node.status.value,
            "prompt": node.prompt,
            "style": node.style,
            "result_url": node.result_url,
            "config": node.config,
        },
        "chat_history": chat_history,
        "connected_nodes": connected_nodes,
        "related_assets": [
            {"id": str(a.id), "name": a.name, "type": a.asset_type.value, "url": a.file_url, "thumbnail": a.thumbnail_url}
            for a in related_assets
        ],
    }

    memory_cache.set_node_context(str(node_id), context)
    return context


class LlmModelOut(BaseModel):
    model_id: str
    name: str
    description: Optional[str] = None


@router.get("/llm-models")
def list_llm_models(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """返回所有已启用的语言大模型配置，供前端在开始 Agent 前选择。"""
    models = (
        db.query(ModelConfig)
        .filter(ModelConfig.type == "llm", ModelConfig.enabled == True)
        .order_by(ModelConfig.order.asc())
        .all()
    )
    return [
        {
            "model_id": m.model_id,
            "name": m.name,
            "description": m.description,
        }
        for m in models
    ]


class ShortDramaStartReq(BaseModel):
    prompt: str
    mode: str = "inspiration"  # inspiration | script | novel
    script_text: Optional[str] = None  # 剧本模式下用户上传/粘贴的剧本文本；novel 模式下为小说原文
    llm_model: Optional[str] = None  # 用户选择的语言大模型


class ShortDramaStepReq(BaseModel):
    session_id: str
    step: str  # script | screenwriter | character | storyboard | scene | video | assets(legacy)


class ShortDramaLockReq(BaseModel):
    session_id: str
    char_ids: List[str] = []
    scene_ids: List[str] = []


class ShortDramaOptionReq(BaseModel):
    session_id: str
    key: str
    value: str


class ShortDramaFinalizeReq(BaseModel):
    session_id: str
    canvas_id: Optional[str] = None
    auto_generate: bool = False


class ShortDramaSyncReq(BaseModel):
    session_id: str
    canvas_id: str


class ShortDramaFeedbackReq(BaseModel):
    session_id: str
    feedback: str
    target_stage: Optional[str] = None  # planning | asset | production，默认取当前会话阶段


class ShortDramaSuggestParamsReq(BaseModel):
    session_id: str


class ShortDramaConfirmParamsReq(BaseModel):
    session_id: str
    global_params: Dict[str, str]
    llm_model: Optional[str] = None  # 用户选择的语言大模型


def _serialize_session(session: dict) -> dict:
    return {
        "id": session["id"],
        "status": session["status"],
        "prompt": session["prompt"],
        "parameter_pending": session.get("parameter_pending", False),
        "global_params": session.get("global_params", {}),
        # 三阶段大脑状态
        "current_stage": session.get("current_stage", "planning"),
        "script_outline": session.get("script_outline"),
        "full_script": session.get("full_script"),
        "character_assets": session.get("character_assets"),
        "scene_assets": session.get("scene_assets"),
        "storyboard_data": session.get("storyboard_data"),
        "video_plan": session.get("video_plan"),
        "feedback_message": session.get("feedback_message", ""),
        "user_feedback": session.get("user_feedback", ""),
        "user_feedback_stage": session.get("user_feedback_stage", ""),
        "pending_user_feedback": session.get("pending_user_feedback", ""),
        "retry_count": session.get("retry_count", 0),
        "review_target": session.get("review_target", ""),
        "review_scores": session.get("review_scores", {}),
        "review_issues": session.get("review_issues", []),
        "review_target_ids": session.get("review_target_ids", []),
        "last_error": session.get("last_error", ""),
        "token_tracker": session.get("token_tracker", {"token_used": 0, "token_prompt": 0, "token_completion": 0}),
        # 导演大脑记忆进化体系
        "rule_version": session.get("rule_version", "1.0"),
        "error_case_library": session.get("error_case_library", []),
        "best_practice_library": session.get("best_practice_library", []),
        "iteration_log": session.get("iteration_log", []),
        # 兼容旧字段
        "script": session.get("script"),
        "screenwriter": session.get("screenwriter"),
        "character": session.get("character"),
        "storyboard": session.get("storyboard"),
        "scene": session.get("scene"),
        "videos": session.get("videos"),
        "assets": session.get("assets"),
        "locked_assets": session.get("locked_assets", []),
        "asset_ids": session.get("asset_ids", []),
        # #13: 画布关联 ID（用于增量同步）
        "finalized_canvas_id": session.get("finalized_canvas_id"),
        "one_click_canvas_id": session.get("one_click_canvas_id"),
        "messages": session.get("messages", []),
        "options": session.get("options", {}),
    }


def _verify_session_ownership(session_id: str, current_user: User):
    """校验会话属于当前登录用户。"""
    session = short_drama_workflow.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.get("user_id") and session.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session


@router.post("/short-drama/start")
async def short_drama_start(req: ShortDramaStartReq, current_user: User = Depends(get_current_user)):
    sid = short_drama_workflow.create_session(
        req.prompt,
        mode=req.mode,
        script_text=req.script_text,
        user_id=str(current_user.id),
        llm_model=req.llm_model,
    )
    return {"status": "success", "session_id": sid, "session": _serialize_session(short_drama_workflow.get_session(sid))}


@router.post("/short-drama/parameters/suggest")
async def short_drama_suggest_params(
    req: ShortDramaSuggestParamsReq,
    current_user: User = Depends(get_current_user),
):
    _verify_session_ownership(req.session_id, current_user)
    result = await short_drama_workflow.suggest_parameters(req.session_id)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/short-drama/parameters/confirm")
async def short_drama_confirm_params(
    req: ShortDramaConfirmParamsReq,
    current_user: User = Depends(get_current_user),
):
    _verify_session_ownership(req.session_id, current_user)
    result = short_drama_workflow.confirm_parameters(req.session_id, req.global_params, llm_model=req.llm_model)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    session = short_drama_workflow.get_session(req.session_id)
    return {
        "status": "success",
        "global_params": result["global_params"],
        "session": _serialize_session(session),
    }


@router.post("/short-drama/step")
async def short_drama_step(req: ShortDramaStepReq, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _verify_session_ownership(req.session_id, current_user)
    result = await short_drama_workflow.run_step(req.session_id, req.step, db)
    if result.status == "failed":
        raise HTTPException(status_code=400, detail=result.error)
    session = short_drama_workflow.get_session(req.session_id)
    return {"status": "success", "step": result.step, "data": result.data, "session": _serialize_session(session)}


@router.get("/short-drama/step/stream")
async def short_drama_step_stream(
    session_id: str,
    step: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """M4: Server-Sent Events 实时流式返回阶段内 Agent 进度。"""
    _verify_session_ownership(session_id, current_user)
    from fastapi.responses import StreamingResponse
    from app.agents.short_drama import WorkflowMessage
    from app.core.sse_utils import sse_event_stream

    queue: asyncio.Queue = asyncio.Queue()
    last_agent = {"name": None}

    async def on_message(msg: WorkflowMessage):
        last_agent["name"] = msg.agent or last_agent["name"]
        await queue.put(msg)

    async def run():
        try:
            result = await short_drama_workflow.run_step(session_id, step, db, on_message=on_message)
            if result.status == "failed":
                await queue.put(WorkflowMessage(role="system", agent="director_brain", step="error", content=result.error or "阶段执行失败"))
            else:
                await queue.put(WorkflowMessage(role="system", agent="director_brain", step=f"{step}_done", content="阶段执行完成"))
        except Exception as exc:
            await queue.put(WorkflowMessage(role="system", agent="director_brain", step="error", content=str(exc)))
        finally:
            await queue.put(None)

    def _heartbeat(elapsed: int) -> WorkflowMessage:
        agent_name = last_agent["name"] or "director_brain"
        return WorkflowMessage(
            role="system",
            agent=agent_name,
            step="heartbeat",
            content=f"⏳ {agent_name} 仍在工作中...（已耗时 {elapsed}s）",
            payload={"elapsed": elapsed, "agent": agent_name},
        )

    return StreamingResponse(
        sse_event_stream(run, on_message, queue, heartbeat_fn=_heartbeat),
        media_type="text/event-stream",
    )


# ================= 一键创作模式 =================

class OneClickStartReq(BaseModel):
    prompt: str
    mode: str = "inspiration"
    script_text: Optional[str] = None  # 剧本模式或小说模式下的原文文本
    llm_model: Optional[str] = None


@router.post("/short-drama/one-click")
async def short_drama_one_click(req: OneClickStartReq, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """一键启动全自动流水线。

    创建会话后通过 SSE 流式返回全程进度。
    自动完成：参数推断 → planning → 资产锁定 → production → 画布创建。
    生图/生视频不在自动流程中，需用户在画布中手动触发。
    """
    sid = short_drama_workflow.create_session(
        req.prompt,
        mode=req.mode,
        script_text=req.script_text,
        user_id=str(current_user.id),
        llm_model=req.llm_model,
    )
    # 标记为一键模式
    session = short_drama_workflow.get_session(sid)
    if session:
        session["one_click_mode"] = True
        session["one_click_completed_stages"] = []
        short_drama_workflow.save_session(sid, session)

    return {"status": "success", "session_id": sid, "session": _serialize_session(session)}


@router.get("/short-drama/one-click/stream")
async def short_drama_one_click_stream(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一键流水线 SSE 流式进度。"""
    _verify_session_ownership(session_id, current_user)
    from fastapi.responses import StreamingResponse
    from app.agents.one_click import run_one_click
    from app.core.sse_utils import sse_event_stream

    queue: asyncio.Queue = asyncio.Queue()
    last_agent = {"name": "orchestrator"}

    async def on_message(msg: WorkflowMessage):
        last_agent["name"] = msg.agent or last_agent["name"]
        await queue.put(msg)

    async def run():
        try:
            result = await run_one_click(
                session_id, db, str(current_user.id),
                on_message=on_message,
                resume=True,
            )
            if result.get("status") == "failed":
                await queue.put(WorkflowMessage(
                    role="system", agent="orchestrator", step="error",
                    content=result.get("error", "一键创作失败"),
                ))
            else:
                await queue.put(WorkflowMessage(
                    role="system", agent="orchestrator", step="one_click_done",
                    content="🎉 一键创作完成！",
                    payload={"canvas_id": result.get("canvas_id")},
                ))
        except Exception as exc:
            logger.error("[OneClick] 流水线异常: %s", exc, exc_info=True)
            await queue.put(WorkflowMessage(
                role="system", agent="orchestrator", step="error",
                content=str(exc),
            ))
        finally:
            await queue.put(None)

    def _heartbeat(elapsed: int) -> WorkflowMessage:
        agent_name = last_agent["name"] or "orchestrator"
        return WorkflowMessage(
            role="system",
            agent=agent_name,
            step="heartbeat",
            content=f"⏳ {agent_name} 仍在工作中...（已耗时 {elapsed}s）",
            payload={"elapsed": elapsed, "agent": agent_name},
        )

    return StreamingResponse(
        sse_event_stream(run, on_message, queue, heartbeat_fn=_heartbeat),
        media_type="text/event-stream",
    )


# ================= 轻量分镜模式 =================

class LiteStoryboardReq(BaseModel):
    script_text: str                           # 剧本文本（必填）
    story_type: Optional[str] = None           # 故事类型（可选）
    art_style: Optional[str] = None            # 美术风格（可选）
    llm_model: Optional[str] = None            # 用户选择的语言大模型


@router.post("/short-drama/lite-storyboard")
async def short_drama_lite_storyboard(req: LiteStoryboardReq, current_user: User = Depends(get_current_user)):
    """轻量分镜：直接从剧本文本生成分镜表 + 视频提示词组。

    不经过剧本策划/编剧/角色/场景等上游阶段，适合快速预览分镜效果。
    创建会话后通过 SSE 流式返回进度。
    """
    prompt = req.script_text.strip()[:80] + ("..." if len(req.script_text.strip()) > 80 else "")
    sid = short_drama_workflow.create_session(
        prompt,
        mode="inspiration",
        script_text=req.script_text,
        user_id=str(current_user.id),
        llm_model=req.llm_model,
    )
    # 将 lite 参数写入 session options
    session = short_drama_workflow.get_session(sid)
    if session:
        opts = session.get("options") or {}
        opts["script_text"] = req.script_text
        if req.story_type:
            opts["story_type"] = req.story_type
        if req.art_style:
            opts["art_style"] = req.art_style
        if req.llm_model:
            opts["start.llm_model"] = req.llm_model
        session["options"] = opts
        session["status"] = "created"
        short_drama_workflow.save_session(sid, session)

    return {"status": "success", "session_id": sid, "session": _serialize_session(session)}


@router.get("/short-drama/lite-storyboard/stream")
async def short_drama_lite_storyboard_stream(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """轻量分镜 SSE 流式进度。"""
    _verify_session_ownership(session_id, current_user)
    from fastapi.responses import StreamingResponse
    from app.core.sse_utils import sse_event_stream

    queue: asyncio.Queue = asyncio.Queue()
    last_agent = {"name": "lite_storyboard"}

    async def on_message(msg: WorkflowMessage):
        last_agent["name"] = msg.agent or last_agent["name"]
        await queue.put(msg)

    async def run():
        try:
            result = await short_drama_workflow.run_step(session_id, "lite_storyboard", db, on_message=on_message)
            if result.status == "failed":
                await queue.put(WorkflowMessage(role="system", agent="director_brain", step="error", content=result.error or "轻量分镜执行失败"))
            else:
                await queue.put(WorkflowMessage(role="system", agent="director_brain", step="lite_storyboard_done", content="轻量分镜生成完成"))
        except Exception as exc:
            await queue.put(WorkflowMessage(role="system", agent="director_brain", step="error", content=str(exc)))
        finally:
            await queue.put(None)

    def _heartbeat(elapsed: int) -> WorkflowMessage:
        agent_name = last_agent["name"] or "lite_storyboard"
        return WorkflowMessage(
            role="system",
            agent=agent_name,
            step="heartbeat",
            content=f"⏳ {agent_name} 仍在工作中...（已耗时 {elapsed}s）",
            payload={"elapsed": elapsed, "agent": agent_name},
        )

    return StreamingResponse(
        sse_event_stream(run, on_message, queue, heartbeat_fn=_heartbeat),
        media_type="text/event-stream",
    )


@router.post("/short-drama/lock-assets")
async def short_drama_lock_assets(req: ShortDramaLockReq, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _verify_session_ownership(req.session_id, current_user)
    result = await short_drama_workflow.lock_assets(req.session_id, req.char_ids, req.scene_ids, db)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    session = short_drama_workflow.get_session(req.session_id)
    return {"status": "success", **result, "session": _serialize_session(session)}


@router.get("/short-drama/session/{session_id}")
def short_drama_get_session(session_id: str, current_user: User = Depends(get_current_user)):
    session = _verify_session_ownership(session_id, current_user)
    return {"status": "success", "session": _serialize_session(session)}


@router.post("/short-drama/force-unlock")
async def short_drama_force_unlock(session_id: str, current_user: User = Depends(get_current_user)):
    """强制释放会话锁（诊断/恢复用）。

    当会话因进程崩溃等原因锁未释放时，可用此端点强制解锁。
    注意：如果当前有正在执行的 run_step，强制解锁可能导致数据不一致。
    """
    _verify_session_ownership(session_id, current_user)
    # 直接在 store 层面清除锁
    from app.services.session_store import get_store
    store = get_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 用 release_lock 尝试以任意 owner 解锁（store 层面直接清除）
    # SQLitePersistentSessionStore.release_lock 需要 owner 匹配，这里直接操作
    db_session = store._session()
    try:
        from app.models.session import AgentSession
        from datetime import datetime
        db_session.query(AgentSession).filter(
            AgentSession.session_id == session_id
        ).update({
            "lock_version": None,
            "updated_at": datetime.utcnow(),
        }, synchronize_session=False)
        db_session.commit()
        logger.info("[force-unlock] 会话 %s 锁已强制释放 (by user=%s)", session_id, current_user.id)
    finally:
        db_session.close()
    session = short_drama_workflow.get_session(session_id)
    return {"status": "success", "message": "会话锁已强制释放", "session": _serialize_session(session)}


@router.post("/short-drama/option")
async def short_drama_option(req: ShortDramaOptionReq, current_user: User = Depends(get_current_user)):
    _verify_session_ownership(req.session_id, current_user)
    short_drama_workflow.set_option(req.session_id, req.key, req.value)
    session = short_drama_workflow.get_session(req.session_id)
    return {"status": "success", "session": _serialize_session(session)}


@router.post("/short-drama/feedback")
async def short_drama_feedback(req: ShortDramaFeedbackReq, current_user: User = Depends(get_current_user)):
    """接收用户对当前阶段的反馈，保存到会话并在下一次运行对应阶段时透传给子 Agent。"""
    session = _verify_session_ownership(req.session_id, current_user)
    feedback = req.feedback.strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="反馈内容不能为空")

    target_stage = req.target_stage or session.get("current_stage", "planning")
    # 只允许透传到实际存在的阶段
    valid_stages = {"planning", "asset", "production"}
    if target_stage not in valid_stages:
        target_stage = session.get("current_stage", "planning")
        if target_stage not in valid_stages:
            target_stage = "planning"

    # M8: 反馈也可能和正在执行的 run_step 竞态，需要加锁后再改
    lock_owner = f"feedback_{current_user.id}_{uuid.uuid4().hex[:8]}"
    if not short_drama_workflow.acquire_session_lock(req.session_id, lock_owner):
        raise HTTPException(status_code=409, detail="当前会话正在执行中，请等待完成后再提交反馈")
    try:
        # 重新读取，避免拿到加锁前的旧缓存
        session = short_drama_workflow.get_session(req.session_id)
        session["user_feedback"] = feedback
        session["user_feedback_stage"] = target_stage

        # 记录到消息历史，方便前端左侧对话框展示
        messages = session.get("messages") or []
        messages.append({
            "role": "user",
            "agent": None,
            "step": target_stage,
            "content": feedback,
            "payload": {"type": "user_feedback", "target_stage": target_stage},
            "ts": time.time(),
        })
        session["messages"] = messages
        short_drama_workflow.save_session(req.session_id, session, lock_owner=lock_owner)
    finally:
        short_drama_workflow.release_session_lock(req.session_id, lock_owner)

    return {"status": "success", "session": _serialize_session(session)}


@router.post("/short-drama/sync-canvas")
async def short_drama_sync_canvas(req: ShortDramaSyncReq, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """#13 增量同步会话数据到已有画布。

    当用户在已有画布后重新执行某个阶段（如重试策划/资产/制作），
    调用此接口以 upsert 方式更新画布节点，避免重复创建。
    """
    session = _verify_session_ownership(req.session_id, current_user)
    from app.services.canvas_builder import sync_session_to_canvas

    try:
        result = sync_session_to_canvas(db, session, UUID(req.canvas_id))
        db.commit()
        logger.info(
            "[sync-canvas] canvas=%s updated=%d created=%d edges=%d",
            result.get("canvas_id"), result.get("updated_count", 0),
            result.get("created_count", 0), result.get("edge_count", 0),
        )
        return {"status": "success", **result}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        logger.error("[sync-canvas] 同步失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"画布同步失败: {exc}")


@router.post("/short-drama/finalize")
async def short_drama_finalize(req: ShortDramaFinalizeReq, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = _verify_session_ownership(req.session_id, current_user)
    if not session.get("script"):
        raise HTTPException(status_code=400, detail="请先完成剧本策划")

    from app.services.canvas_builder import build_canvas_from_session, sync_session_to_canvas

    # #13: 如果提供了 canvas_id 且画布已存在，使用增量同步避免重复创建节点
    use_sync = False
    if req.canvas_id:
        existing_canvas = crud_canvas.get_canvas(db, UUID(req.canvas_id))
        if existing_canvas:
            use_sync = True

    try:
        if use_sync:
            result = sync_session_to_canvas(db, session, UUID(req.canvas_id))
            canvas = crud_canvas.get_canvas(db, UUID(req.canvas_id))
            result["canvas"] = canvas
            result["node_id_map"] = result.get("node_id_map", {})
            result.setdefault("node_count", result.get("updated_count", 0) + result.get("created_count", 0))
            result.setdefault("edge_count", result.get("edge_count", 0))
            result.setdefault("storyboard_nodes", [])
            result.setdefault("video_nodes", [])
        else:
            result = build_canvas_from_session(
                db,
                session,
                canvas_id=UUID(req.canvas_id) if req.canvas_id else None,
                user_id=str(current_user.id),
            )
        canvas = result["canvas"]
        db.commit()

        # 事务外：更新会话状态并持久化
        session["status"] = "finalized"
        session["finalized_canvas_id"] = str(canvas.id)
        short_drama_workflow.save_session(req.session_id, session)
    except Exception as exc:
        db.rollback()
        logger.error("[short_drama_finalize] 创建画布失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建画布失败: {exc}")

    logger.info(
        "[short_drama_finalize] created_nodes=%s edges=%s storyboards=%s videos=%s",
        result.get("node_count", 0),
        result.get("edge_count", 0),
        len(result.get("storyboard_nodes", [])),
        len(result.get("video_nodes", [])),
    )
    return {
        "status": "success",
        "canvas_id": str(canvas.id),
        "node_count": result.get("node_count", 0),
        "edge_count": result.get("edge_count", 0),
        "storyboard_count": len(result.get("storyboard_nodes", [])),
        "video_count": len(result.get("video_nodes", [])),
        "auto_generated": False,
        "auto_generated_node_ids": [],
        "node_ids": {
            k: str(v) for k, v in result.get("node_id_map", {}).items()
        },
        "session": _serialize_session(session),
    }


class ShortDramaGenerateAllReq(BaseModel):
    canvas_id: str
    node_types: Optional[List[str]] = None  # character, scene, storyboard, video; 默认全部


@router.post("/short-drama/generate-all")
async def short_drama_generate_all(req: ShortDramaGenerateAllReq, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """为画布上指定类型的节点批量提交生成任务（结构创建与生成触发分离）。"""
    from app.core.tasks import task_manager, Task
    from app.models.node import NodeStatus

    try:
        canvas = crud_canvas.get_canvas(db, UUID(req.canvas_id))
    except Exception:
        canvas = None
    if not canvas:
        raise HTTPException(status_code=404, detail="画布不存在")

    allowed_types = set(req.node_types or ["character", "scene", "storyboard", "video"])
    nodes = crud_node.get_nodes_by_canvas(db, canvas.id)

    # 第一阶段：确定需要提交的节点并计算总积分
    to_submit: List[tuple] = []
    total_cost = 0
    for n in nodes:
        nt = n.node_type.value
        if nt not in allowed_types:
            continue
        node_config = n.config or {}
        task_type = "generate_image"
        if nt == NodeType.VIDEO.value:
            task_type = "generate_video"
        elif nt == NodeType.STORYBOARD.value:
            task_type = "generate_image"

        # 跳过已完成或进行中的节点
        if n.status in (NodeStatus.SUCCESS, NodeStatus.PROCESSING, NodeStatus.PENDING):
            continue

        cost = calculate_cost(task_type, node_config, db=db)
        to_submit.append((n, task_type, cost))
        total_cost += cost

    # 按优先级排序：角色/场景 → 分镜 → 视频
    # 确保角色/场景先提交生成，分镜后续可收集到角色 result_url 作为参考图
    _type_priority = {
        NodeType.CHARACTER.value: 0,
        NodeType.SCENE.value: 0,
        NodeType.STORYBOARD.value: 1,
        NodeType.VIDEO.value: 2,
    }
    to_submit.sort(key=lambda x: _type_priority.get(x[0].node_type.value, 9))

    # 第二阶段：构建任务对象（不提交，用于确认参数合法）
    # 导入共享的参考图收集函数
    from app.api.v1.node import collect_storyboard_references

    tasks_to_submit: List[Task] = []
    for n, task_type, cost in to_submit:
        node_config = n.config or {}

        # 分镜/视频/图片节点：动态收集角色/场景参考图（与 node_action 完全一致）
        if n.node_type in (NodeType.STORYBOARD, NodeType.VIDEO, NodeType.IMAGE):
            ref_images, ref_asset_ids, continuity_prefix = collect_storyboard_references(
                db, n, node_config
            )
            # 持久化到 node.config
            node_config["reference_images"] = ref_images
            node_config["reference_asset_ids"] = ref_asset_ids
            n.config = node_config
            db.add(n)
            # 拼接衔接前缀到 prompt
            prompt = (continuity_prefix + (n.prompt or "")) if continuity_prefix else (n.prompt or "")
        else:
            ref_images = node_config.get("reference_images", [])
            ref_asset_ids = node_config.get("reference_asset_ids", [])
            prompt = n.prompt or ""

        params = {
            "prompt": prompt,
            "style": n.style or "realistic",
            "node_type": n.node_type.value,
            "model": node_config.get("model"),
            "aspect_ratio": node_config.get("aspect_ratio", "1:1"),
            "reference_images": ref_images,
            "reference_asset_ids": ref_asset_ids,
            "cost": cost,
        }
        if n.node_type.value == NodeType.VIDEO.value:
            params["final_video_prompt"] = node_config.get("final_video_prompt", n.prompt or "")
            params["duration_seconds"] = node_config.get("duration_seconds", 5)

        task = Task(
            id=task_manager.new_task_id(),
            node_id=str(n.id),
            canvas_id=str(n.canvas_id),
            task_type=task_type,
            params=params,
            user_id=str(current_user.id),
            cost=cost,
        )
        logger.info(
            "[generate_all] 提交任务 node=%s type=%s model=%s",
            n.id, task_type, node_config.get("model"),
        )
        tasks_to_submit.append(task)

    # 确保第二阶段对 node.config 的修改被 flush 到数据库（即使 total_cost==0 也不丢失）
    db.flush()

    # 第三阶段：统一扣费（总成本为 0 时跳过扣费）
    if tasks_to_submit and total_cost > 0:
        try:
            deduct_credits(
                db=db,
                user_id=current_user.id,
                amount=total_cost,
                reason="batch_generate",
                ref_id=str(canvas.id),
                description=f"批量生成 {len(tasks_to_submit)} 个节点",
            )
            db.commit()
        except InsufficientCreditsError as exc:
            db.rollback()
            raise HTTPException(
                status_code=402,
                detail={
                    "error": str(exc),
                    "required": exc.required,
                    "balance": exc.balance,
                    "pending_count": len(tasks_to_submit),
                },
            )

    # 第四阶段：提交任务并批量更新节点状态
    submitted: List[str] = []
    for task in tasks_to_submit:
        await task_manager.submit(task)
        submitted.append(task.node_id)

    # #18: 批量更新节点状态，减少数据库往返
    if submitted:
        crud_node.bulk_update_status(db, [
            {"node_id": nid, "status": NodeStatus.PENDING, "progress": 0}
            for nid in submitted
        ], commit=True)

    return {
        "status": "success",
        "canvas_id": str(canvas.id),
        "submitted_count": len(submitted),
        "submitted_node_ids": submitted,
        "total_cost": total_cost,
    }


# ================= Skill 平台级技能入口 =================

class SkillRunReq(BaseModel):
    skill_id: str
    prompt: str
    params: Optional[Dict[str, Any]] = None
    global_params: Optional[Dict[str, Any]] = None
    llm_model: Optional[str] = None


@router.get("/skills")
def list_skill_definitions(current_user: User = Depends(get_current_user)):
    """返回所有可用 Skill 的元数据定义。"""
    return {"status": "success", "skills": list_skills()}


@router.post("/skills/run")
async def run_skill_endpoint(req: SkillRunReq, current_user: User = Depends(get_current_user)):
    """通过大脑执行单个 Skill：参数提取 → 全局参数注入 → 执行。"""
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    try:
        from app.agents.platform_brain import platform_brain
        result = await platform_brain.execute_skill_through_brain(
            skill_id=req.skill_id,
            user_input=req.prompt,
            params=req.params or {},
            global_params=req.global_params,
            llm_model=req.llm_model,
        )
    except Exception as exc:
        logger.error("[Skill] 执行异常 skill_id=%s: %s [%s]", req.skill_id, exc, type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=400, detail=f"技能执行异常: {exc}")
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error") or "Skill 执行失败")
    return {
        "status": "success",
        "skill_id": result.get("skill_id"),
        "params": result.get("params", {}),
        "data": result.get("data", {}),
    }


class SkillRunStreamReq(BaseModel):
    skill_id: str
    prompt: str
    params: Optional[Dict[str, Any]] = None
    global_params: Optional[Dict[str, Any]] = None
    conversation_id: Optional[str] = None
    llm_model: Optional[str] = None


@router.post("/skills/run/stream")
async def run_skill_stream_endpoint(req: SkillRunStreamReq, current_user: User = Depends(get_current_user)):
    """通过大脑执行单个 Skill（SSE 流式版）：实时推送参数提取和执行进度。"""
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    from fastapi.responses import StreamingResponse
    from app.agents.platform_brain import platform_brain, BrainMessage

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        start_time = time.time()

        async def on_message(msg: BrainMessage):
            await queue.put(msg)

        async def run():
            try:
                await platform_brain.execute_skill_through_brain(
                    skill_id=req.skill_id,
                    user_input=req.prompt,
                    params=req.params or {},
                    global_params=req.global_params,
                    on_message=on_message,
                    conversation_id=req.conversation_id,
                    llm_model=req.llm_model,
                )
            except Exception as exc:
                await queue.put(BrainMessage("error", f"执行异常: {exc}"))
            finally:
                await queue.put(None)  # sentinel

        runner = asyncio.create_task(run())
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    elapsed = int(time.time() - start_time)
                    hb = BrainMessage("heartbeat", f"⏳ 仍在工作中...（已耗时 {elapsed}s）")
                    yield hb.to_sse()
                    continue
                if msg is None:
                    break
                yield msg.to_sse()
        finally:
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ================= LLM 诊断 =================

@router.get("/llm-ping")
async def llm_ping(current_user: User = Depends(get_current_user)):
    """诊断端点：快速测试 LLM API 连通性，返回配置信息和调用结果。

    用于排查"卡住无请求记录"问题：
    1. 检查 API key 是否已配置
    2. 检查 API endpoint 是否可达
    3. 检查模型名是否有效
    4. 记录完整调用耗时
    """
    import time as _time
    from app.services.ai_service import AIService
    from app.core.config import settings as _settings

    # 收集配置信息（脱敏）
    config_info = {
        "llm_provider": _settings.LLM_PROVIDER,
        "llm_model_name": _settings.LLM_MODEL_NAME,
        "ark_api_base_url": _settings.VOLCENGINE_ARK_API_BASE_URL,
        "ark_api_key_configured": bool(_settings.VOLCENGINE_ARK_API_KEY) and "YOUR_" not in _settings.VOLCENGINE_ARK_API_KEY,
        "api91_base_url": _settings.API91_BASE_URL,
        "api91_api_key_configured": bool(_settings.API91_API_KEY) and "YOUR_" not in _settings.API91_API_KEY,
        "dashscope_api_key_configured": bool(_settings.DASHSCOPE_API_KEY) and "YOUR_" not in _settings.DASHSCOPE_API_KEY,
    }

    # 尝试调用 LLM
    test_messages = [{"role": "user", "content": "请回复 JSON：{\"status\": \"ok\"}"}]
    t0 = _time.time()
    try:
        response = await AIService.chat(test_messages, model=_settings.LLM_MODEL_NAME, max_tokens=50, temperature=0.0)
        elapsed = round(_time.time() - t0, 2)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = response.get("usage", {})
        return {
            "status": "success",
            "elapsed_seconds": elapsed,
            "config": config_info,
            "response_preview": content[:200],
            "usage": usage,
            "model_used": _settings.LLM_MODEL_NAME,
            "provider_used": _settings.LLM_PROVIDER,
        }
    except Exception as exc:
        elapsed = round(_time.time() - t0, 2)
        return {
            "status": "failed",
            "elapsed_seconds": elapsed,
            "config": config_info,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "hint": "如果 elapsed < 1s 且 error 包含 'ConnectError'，说明服务器无法连接到 LLM API。"
                    "如果 error 包含 '401' 或 '403'，说明 API key 无效。"
                    "如果 error 包含 '404' 或 '400'，说明模型名可能无效。",
        }


class PlatformBrainReq(BaseModel):
    prompt: str
    global_params: Optional[Dict[str, Any]] = None


@router.post("/platform/run")
async def platform_brain_run(req: PlatformBrainReq, current_user: User = Depends(get_current_user)):
    """平台级总控大脑入口：自然语言需求 → 路由到 Skill 或短剧流水线。"""
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    try:
        result = await platform_brain.execute(req.prompt, global_params=req.global_params)
    except Exception as exc:
        logger.error("[PlatformBrain] 执行异常: %s [%s]", exc, type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=400, detail=f"大脑执行异常: {exc}")
    return {
        "status": result.get("status", "success"),
        "decision": result.get("decision", "single_skill"),
        "reasoning": result.get("reasoning", ""),
        "skill_plan": result.get("skill_plan", []),
        "params": result.get("params", {}),
        "data": result.get("data", {}),
        "results": result.get("results", []),
        "short_drama_params": result.get("short_drama_params"),
        "error": result.get("error"),
    }


class PlatformBrainStreamReq(BaseModel):
    prompt: str
    global_params: Optional[Dict[str, Any]] = None


@router.post("/platform/run/stream")
async def platform_brain_run_stream(req: PlatformBrainStreamReq, current_user: User = Depends(get_current_user)):
    """平台级总控大脑（SSE 流式版）：实时推送路由、参数提取、技能执行进度。"""
    if not req.prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    from fastapi.responses import StreamingResponse
    from app.agents.platform_brain import BrainMessage

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        start_time = time.time()

        async def on_message(msg: BrainMessage):
            await queue.put(msg)

        async def run():
            try:
                await platform_brain.execute_stream(
                    req.prompt,
                    global_params=req.global_params,
                    on_message=on_message,
                )
            except Exception as exc:
                await queue.put(BrainMessage("error", f"大脑执行异常: {exc}"))
            finally:
                await queue.put(None)

        runner = asyncio.create_task(run())
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    elapsed = int(time.time() - start_time)
                    hb = BrainMessage("heartbeat", f"⏳ 大脑仍在思考...（已耗时 {elapsed}s）")
                    yield hb.to_sse()
                    continue
                if msg is None:
                    break
                yield msg.to_sse()
        finally:
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")
