import logging
from typing import List, Dict, Any, Tuple, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.tasks import task_manager, Task, TaskStatus
from app.crud import node as crud_node
from app.crud import canvas as crud_canvas
from app.schemas.node import NodeCreate, NodeUpdate, NodeInDB, NodeAction
from app.models.node import NodeStatus, NodeType
from app.models.edge import Edge, EdgeType
from app.models.user import User
from app.api.deps import get_current_user, require_canvas_access
from app.services.credit_service import calculate_cost, deduct_credits, InsufficientCreditsError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nodes", tags=["nodes"])


def _is_valid_ref_image(url: str) -> bool:
    """过滤掉 SVG/placeholder 等占位图，确保只使用真实 AI 生成的图片作为参考。"""
    if not url:
        return False
    lower = url.lower()
    if lower.endswith(".svg"):
        return False
    if "_placeholder." in lower or "/placeholder" in lower:
        return False
    return True


def collect_storyboard_references(
    db: Session,
    node: Any,
    node_config: Dict[str, Any],
) -> Tuple[List[str], List[str], str]:
    """为分镜/视频节点收集参考图、资产 ID 和衔接前缀。

    逻辑与 node_action 中的分镜参考图收集完全一致，提取为独立函数供 generate-all 复用。

    Returns:
        (ref_images, ref_asset_ids, storyboard_continuity_prefix)
    """
    ref_images = [u for u in (node_config.get("reference_images") or []) if _is_valid_ref_image(u)]
    ref_asset_ids = list(node_config.get("reference_asset_ids") or [])
    storyboard_continuity_prefix = ""

    if node.node_type not in (NodeType.STORYBOARD, NodeType.VIDEO, NodeType.IMAGE, NodeType.CHARACTER, NodeType.SCENE):
        return ref_images, ref_asset_ids, storyboard_continuity_prefix

    canvas_nodes = crud_node.get_nodes_by_canvas(db, node.canvas_id)

    # ── 过滤掉上次生成时持久化到 config 的画布节点结果图 ──
    # （自动收集的参考图会被写回 reference_images，下次生成时残留为旧数据）
    # 只保留用户手动上传的参考图（不在画布节点 result_url 中）
    canvas_result_urls = set()
    for _n in canvas_nodes:
        if _n.id != node.id and _is_valid_ref_image(_n.result_url or ""):
            canvas_result_urls.add(_n.result_url)
    ref_images = [u for u in ref_images if u not in canvas_result_urls]

    # ── 检查是否有连线（任意类型边指向本节点） ──
    # 无连线时跳过所有自动关联（linked_chars/linked_scene/prev_storyboard），
    # 只保留用户手动上传的参考图
    has_any_edges = db.query(Edge).filter(
        Edge.target_node_id == node.id,
    ).count() > 0

    # linked_chars/linked_scene 自动关联仅适用于分镜/视频/图片节点，且需要至少有一条边
    linked_chars = []
    linked_scene = None
    if node.node_type in (NodeType.STORYBOARD, NodeType.VIDEO, NodeType.IMAGE) and has_any_edges:
        linked_chars = node_config.get("linked_char_ids") or (
            [node_config.get("linked_char_id")] if node_config.get("linked_char_id") else []
        )
        linked_scene = node_config.get("linked_scene_id")

    char_ref_images = []
    scene_ref_images = []
    char_text_anchors = []
    for n in canvas_nodes:
        cfg = n.config or {}
        if n.node_type == NodeType.CHARACTER and cfg.get("char_id") in linked_chars:
            # 优先使用 result_url（AI 生成图），兜底读取 config.reference_images（用户上传图）
            char_urls = []
            if _is_valid_ref_image(n.result_url or ""):
                char_urls.append(n.result_url)
            for fallback_url in (cfg.get("reference_images") or []):
                if _is_valid_ref_image(fallback_url) and fallback_url not in char_urls:
                    char_urls.append(fallback_url)
            for u in char_urls:
                if u not in char_ref_images:
                    char_ref_images.append(u)
            if cfg.get("asset_id") and cfg.get("asset_id") not in ref_asset_ids:
                ref_asset_ids.append(cfg.get("asset_id"))
            features = cfg.get("immutable_features") or []
            visual_anchor = cfg.get("visual_anchor")
            name = n.title or cfg.get("char_id")
            if features:
                char_text_anchors.append(f"{name}: {', '.join(features)}")
            elif visual_anchor:
                char_text_anchors.append(f"{name}: {visual_anchor}")
        if n.node_type == NodeType.SCENE and cfg.get("scene_id") == linked_scene:
            # 优先使用 result_url（AI 生成图），兜底读取 config.reference_images（用户上传图）
            scene_urls = []
            if _is_valid_ref_image(n.result_url or ""):
                scene_urls.append(n.result_url)
            for fallback_url in (cfg.get("reference_images") or []):
                if _is_valid_ref_image(fallback_url) and fallback_url not in scene_urls:
                    scene_urls.append(fallback_url)
            for u in scene_urls:
                if u not in scene_ref_images:
                    scene_ref_images.append(u)
            if cfg.get("asset_id") and cfg.get("asset_id") not in ref_asset_ids:
                ref_asset_ids.append(cfg.get("asset_id"))

    # 前一镜参考图（仅分镜/视频节点适用，且需要存在连线）
    prev_sb_ref = None
    prev_sb_id = node_config.get("prev_storyboard_id")
    if prev_sb_id and node.node_type in (NodeType.STORYBOARD, NodeType.VIDEO) and has_any_edges:
        for n in canvas_nodes:
            cfg = n.config or {}
            if n.node_type == NodeType.STORYBOARD and cfg.get("storyboard_id") == prev_sb_id:
                if _is_valid_ref_image(n.result_url):
                    prev_sb_ref = n.result_url
                break

    # 从 edge 表收集 reference 类型的角色/场景参考图
    ref_edges = db.query(Edge).filter(
        Edge.target_node_id == node.id,
        Edge.edge_type == EdgeType.REFERENCE,
    ).all()
    for e in ref_edges:
        src = next((n for n in canvas_nodes if n.id == e.source_node_id), None)
        if not src:
            continue
        src_url = src.result_url
        if not _is_valid_ref_image(src_url or ""):
            # 上传型节点可能未写入 result_url，兜底读取 config.reference_images
            # 适用于 IMAGE / CHARACTER / SCENE / STORYBOARD 等所有视觉节点类型
            if src.node_type in (NodeType.IMAGE, NodeType.CHARACTER, NodeType.SCENE, NodeType.STORYBOARD):
                src_cfg = src.config or {}
                for fallback_url in (src_cfg.get("reference_images") or []):
                    if _is_valid_ref_image(fallback_url):
                        src_url = fallback_url
                        break
        if not _is_valid_ref_image(src_url or ""):
            continue
        if src.node_type == NodeType.CHARACTER and src_url not in char_ref_images:
            char_ref_images.append(src_url)
            src_cfg = src.config or {}
            if src_cfg.get("asset_id") and src_cfg.get("asset_id") not in ref_asset_ids:
                ref_asset_ids.append(src_cfg.get("asset_id"))
            features = src_cfg.get("immutable_features") or []
            visual_anchor = src_cfg.get("visual_anchor")
            name = src.title or src_cfg.get("char_id")
            if features:
                char_text_anchors.append(f"{name}: {', '.join(features)}")
            elif visual_anchor:
                char_text_anchors.append(f"{name}: {visual_anchor}")
        elif src.node_type == NodeType.SCENE and src_url not in scene_ref_images:
            scene_ref_images.append(src_url)
            src_cfg = src.config or {}
            if src_cfg.get("asset_id") and src_cfg.get("asset_id") not in ref_asset_ids:
                ref_asset_ids.append(src_cfg.get("asset_id"))
        elif src_url not in ref_images:
            # 分镜/图片等其他视觉节点的结果图作为通用参考图
            ref_images.append(src_url)

    # 组装参考图：角色（首位）> 场景 > 前一镜 > 节点已有参考图
    assembled = list(char_ref_images)
    for u in scene_ref_images:
        if u not in assembled:
            assembled.append(u)
    if prev_sb_ref and prev_sb_ref not in assembled:
        assembled.append(prev_sb_ref)
    for u in ref_images:
        if u not in assembled:
            assembled.append(u)
    ref_images = assembled

    # 注入衔接描述前缀
    vc = node_config.get("visual_continuity") or {}
    transition = node_config.get("transition_from_prev")
    if vc or transition:
        parts = []
        if prev_sb_id:
            parts.append(f"Continuity with previous shot {prev_sb_id}")
        if vc.get("position"):
            parts.append(f"position={vc.get('position')}")
        if vc.get("gaze"):
            parts.append(f"gaze={vc.get('gaze')}")
        if vc.get("light_direction"):
            parts.append(f"light={vc.get('light_direction')}")
        if transition:
            parts.append(f"transition={transition}")
        if parts:
            storyboard_continuity_prefix = "[" + ", ".join(parts) + "] "

    # 注入角色不可变锚点文字前缀
    if char_text_anchors:
        anchor_text = "; ".join(char_text_anchors)
        storyboard_continuity_prefix = (
            f"[Character identity anchors (MUST match exactly): {anchor_text}] "
            + storyboard_continuity_prefix
        )

    logger.info(
        "[collect_refs] node=%s type=%s linked_chars=%s linked_scene=%s refs=%d asset_ids=%s",
        node.id, node.node_type.value, linked_chars, linked_scene, len(ref_images), ref_asset_ids,
    )

    return ref_images, ref_asset_ids, storyboard_continuity_prefix

NODE_TYPE_TO_TASK = {
    NodeType.IMAGE: "generate_image",
    NodeType.VIDEO: "generate_video",
    NodeType.SCRIPT: "generate_script",
    # 分镜节点点击生成时出图，便于预览画面
    NodeType.STORYBOARD: "generate_image",
    NodeType.CHARACTER: "generate_image",
    NodeType.SCENE: "generate_image",
    NodeType.AUDIO: "generate_audio",
}


def _check_node_canvas_access(node, db: Session, current_user: User):
    """校验节点所属画布的访问权限。"""
    canvas = crud_canvas.get_canvas(db, node.canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="画布不存在")
    if canvas.user_id and str(canvas.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="没有权限访问该节点")


@router.post("", response_model=NodeInDB, status_code=201)
def create_node(
    node_in: NodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    canvas = crud_canvas.get_canvas(db, node_in.canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="画布不存在")
    if canvas.user_id and str(canvas.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="没有权限访问该画布")
    return crud_node.create_node(db, node_in)


@router.get("/{node_id}", response_model=NodeInDB)
def get_node(
    node_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    node = crud_node.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_canvas_access(node, db, current_user)
    return node


@router.get("/canvas/{canvas_id}", response_model=List[NodeInDB])
def list_nodes_by_canvas(
    canvas_id: UUID,
    db: Session = Depends(get_db),
    canvas=Depends(require_canvas_access),
):
    return crud_node.get_nodes_by_canvas(db, canvas_id)


@router.patch("/{node_id}", response_model=NodeInDB)
def update_node(
    node_id: UUID,
    node_in: NodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    node = crud_node.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_canvas_access(node, db, current_user)
    return crud_node.update_node(db, node, node_in)


@router.post("/batch/positions", status_code=200)
def batch_update_positions(
    positions: List[dict],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 先校验所有节点权限
    node_ids = [UUID(p.get("id")) for p in positions if p.get("id")]
    nodes = db.query(crud_node.Node).filter(crud_node.Node.id.in_(node_ids)).all() if node_ids else []
    node_map = {str(n.id): n for n in nodes}
    for node in nodes:
        _check_node_canvas_access(node, db, current_user)
    count = crud_node.batch_update_positions(db, positions)
    return {"updated": count}


@router.post("/{node_id}/action", status_code=202)
async def node_action(
    node_id: UUID,
    action: NodeAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    node = crud_node.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_canvas_access(node, db, current_user)

    if action.action == "generate":
        if node.status == NodeStatus.PROCESSING:
            raise HTTPException(status_code=409, detail="节点正在处理中，请等待完成或取消")
        if action.prompt:
            node.prompt = action.prompt
        if action.style:
            node.style = action.style
        # 前端通过 action.config 传入最新的节点配置（含 model 等），
        # 合并到 node.config 确保后端使用用户选择的模型，避免 PATCH 竞态导致模型丢失
        if action.config:
            merged_config = dict(node.config or {})
            merged_config.update(action.config)
            node.config = merged_config
            logger.info("[node_action] node=%s action.config=%s", node_id, action.config)
        node.status = NodeStatus.PENDING
        node.progress = 0
        node.error_msg = None
        node.result_url = None
        db.add(node)
        db.commit()

        task_type = NODE_TYPE_TO_TASK.get(node.node_type, "generate_image")
        node_config = node.config or {}

        # 使用共享函数收集参考图（分镜/视频节点自动关联角色/场景）
        ref_images, ref_asset_ids, storyboard_continuity_prefix = collect_storyboard_references(
            db, node, node_config
        )
        logger.info("[node_action] node=%s type=%s node_config.reference_images=%s collected_ref_images=%s",
                    node_id, node.node_type.value, node_config.get("reference_images"), ref_images)

        # 角色/场景/图片节点：持久化收集到的参考图（有连线优先上游，无连线用用户上传）
        if node.node_type in (NodeType.CHARACTER, NodeType.SCENE, NodeType.IMAGE):
            node_config["reference_images"] = ref_images
            node_config["reference_asset_ids"] = ref_asset_ids
            node.config = node_config
            db.add(node)
            db.commit()
            logger.info("[%s_ref] node=%s refs=%s asset_ids=%s", node.node_type.value, node_id, ref_images, ref_asset_ids)

        # 分镜节点：持久化收集到的参考图 + 固定 seed
        elif node.node_type == NodeType.STORYBOARD:
            node_config["reference_images"] = ref_images
            node_config["reference_asset_ids"] = ref_asset_ids

            # 同场景分镜固定 seed：根据场景 ID + 角色 ID 哈希，保证同场景同角色细节一致
            if not node_config.get("seed"):
                import hashlib
                linked_chars = node_config.get("linked_char_ids") or (
                    [node_config.get("linked_char_id")] if node_config.get("linked_char_id") else []
                )
                linked_scene = node_config.get("linked_scene_id")
                seed_key = f"{linked_scene or 'S'}|{'-'.join(sorted(linked_chars))}"
                stable_seed = int(hashlib.md5(seed_key.encode("utf-8")).hexdigest()[:8], 16) % 999999 + 1
                node_config["seed"] = stable_seed

            node.config = node_config
            db.add(node)
            db.commit()
            logger.info("[storyboard_ref] node=%s refs=%s asset_ids=%s", node_id, ref_images, ref_asset_ids)

        # 视频节点：先收集角色/场景参考图，再额外把分镜结果图放首位作为首帧
        elif node.node_type == NodeType.VIDEO:
            # 分镜结果图作为首帧，用户上传的参考图追加在后
            sb_id = node_config.get("storyboard_id")
            canvas_nodes = crud_node.get_nodes_by_canvas(db, node.canvas_id)

            user_ref_images = list(ref_images)  # collect_storyboard_references 已收集的
            user_ref_asset_ids = list(ref_asset_ids)

            # 无连线时不自动引用分镜结果图作为首帧
            has_edge_to_video = db.query(Edge).filter(
                Edge.target_node_id == node.id,
            ).count() > 0

            sb_node = None
            if has_edge_to_video and sb_id:
                for n in canvas_nodes:
                    cfg = n.config or {}
                    if n.node_type == NodeType.STORYBOARD and cfg.get("storyboard_id") == sb_id:
                        sb_node = n
                        break
            # 分镜结果图放首位（作为首帧），已收集的角色/场景参考图和用户上传的参考图追加在后
            final_ref_images = []
            if sb_node and _is_valid_ref_image(sb_node.result_url):
                final_ref_images.append(sb_node.result_url)
            for u in user_ref_images:
                if u not in final_ref_images:
                    final_ref_images.append(u)
            ref_images = final_ref_images

            # 持久化
            node_config["reference_images"] = ref_images
            node_config["reference_asset_ids"] = ref_asset_ids
            node.config = node_config
            db.add(node)
            db.commit()
            logger.info("[video_ref] node=%s storyboard_id=%s refs=%s asset_ids=%s", node_id, sb_id, ref_images, ref_asset_ids)

        # 图片节点：持久化从边收集到的参考图
        elif node.node_type == NodeType.IMAGE:
            node_config["reference_images"] = ref_images
            node_config["reference_asset_ids"] = ref_asset_ids
            node.config = node_config
            db.add(node)
            db.commit()
            logger.info("[image_ref] node=%s refs=%s asset_ids=%s", node_id, ref_images, ref_asset_ids)

        # 音频生成暂未实现，提前拒绝（避免扣费后必定失败-退款的无效流程）
        if task_type == "generate_audio":
            raise HTTPException(status_code=501, detail="音频生成功能暂未开放")

        # 计算并扣减积分（生成任务提交前）
        # 多张出图支持：仅图片任务 count=N 时按 N×单张成本计费
        count = max(1, action.count or 1)
        if count > 20:
            raise HTTPException(status_code=400, detail="单次最多生成 20 张")
        # 视频任务不支持批量出片，强制 count=1
        if task_type != "generate_image":
            count = 1
        single_cost = calculate_cost(task_type, node_config, db=db)
        cost = single_cost * count
        # 成本为 0 的任务（如剧本生成）跳过扣费，避免 ValueError
        if cost > 0:
            try:
                deduct_credits(
                    db=db,
                    user_id=current_user.id,
                    amount=cost,
                    reason=task_type,
                    ref_id=str(node_id),
                    description=f"生成 {count} 张 {node.node_type.value} 节点",
                )
                db.commit()
            except InsufficientCreditsError as exc:
                db.rollback()
                node.status = NodeStatus.FAILED
                node.error_msg = str(exc)
                db.add(node)
                db.commit()
                raise HTTPException(status_code=402, detail=str(exc))

        task = Task(
            id=task_manager.new_task_id(),
            node_id=str(node_id),
            canvas_id=str(node.canvas_id),
            task_type=task_type,
            user_id=str(current_user.id),
            cost=cost,
            params={
                "prompt": (storyboard_continuity_prefix + (node.prompt or "")) if storyboard_continuity_prefix else (node.prompt or ""),
                "style": node.style or "realistic",
                "node_type": node.node_type.value,
                "model": node_config.get("model"),
                "aspect_ratio": node_config.get("aspect_ratio"),
                "resolution": node_config.get("resolution"),
                "durationSec": node_config.get("duration"),
                "reference_images": ref_images,
                "reference_asset_ids": ref_asset_ids,
                "reference_audio": node_config.get("reference_audio"),
                "reference_video": node_config.get("reference_video"),
                "negative_prompt": node_config.get("negative_prompt"),
                "seed": node_config.get("seed"),
                "sound": node_config.get("sound"),
                "watermark": node_config.get("watermark"),
                "count": count,
                # 局部重绘蒙版（PNG data URL，透明区域=重绘区）
                "mask_url": node_config.get("mask_data_url"),
                # P0：Seedance 2.0 结构化参数（VideoComposerAgent 产出，canvas_builder 透传）
                "lip_sync_target": node_config.get("lip_sync_target"),
                "generation_params": node_config.get("generation_params"),
            },
        )
        logger.info(
            "[node] 提交任务 node=%s type=%s model=%s config_keys=%s",
            node_id, task_type, node_config.get("model"), list(node_config.keys()),
        )
        await task_manager.submit(task)

        return {
            "task_id": task.id,
            "node_id": str(node_id),
            "status": "queued",
            "cost": cost,
            "count": count,
            "message": f"任务已提交，已扣除 {cost} 积分（{count} 张 × {single_cost}），正在排队等待AI处理"
        }

    if action.action == "cancel":
        tasks = task_manager.get_tasks_by_node(str(node_id))
        cancelled = 0
        for t in tasks:
            if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRYING, TaskStatus.PENDING):
                if await task_manager.cancel_task(t.id):
                    cancelled += 1
        # 即使没有活跃任务，也要重置卡在 PENDING/PROCESSING 的节点状态
        # 否则服务重启后任务丢失，节点永远卡住，点生图"没反应"
        if node.status in (NodeStatus.PENDING, NodeStatus.PROCESSING):
            crud_node.update_node_status(db, node_id, NodeStatus.FAILED, error_msg="用户取消")
            db.commit()
        return {"cancelled": cancelled, "message": f"已取消 {cancelled} 个任务"}

    raise HTTPException(status_code=400, detail=f"不支持的操作: {action.action}")


@router.delete("/{node_id}", status_code=204)
def delete_node(node_id: UUID, db: Session = Depends(get_db)):
    success = crud_node.delete_node(db, node_id)
    if not success:
        raise HTTPException(status_code=404, detail="节点不存在")
