"""
预设功能 API
提供角色三视图、360度角度、多机位九宫格、25宫格分镜、剧情推演、
宫格切分、聚焦特写、高清放大、扩图、抠图、剧本解析、脚本优化、拉片分析等预设功能。
"""
import logging
import uuid
from typing import List, Dict, Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.crud import node as crud_node
from app.crud import canvas as crud_canvas
from app.crud import edge as crud_edge
from app.models.node import NodeStatus, NodeType
from app.models.edge import EdgeType
from app.models.user import User
from app.api.deps import get_current_user, require_canvas_access
from app.services.credit_service import calculate_cost, deduct_credits, InsufficientCreditsError
from app.core.tasks import task_manager, Task
from app.data.preset_prompts import (
    get_image_preset_prompt,
    get_character_feature_messages,
    PRESET_CONFIG_OVERRIDES,
    PRESET_NEEDS_RESULT_REF,
    PRESET_LABELS,
)
from app.schemas.node import NodeCreate
from app.schemas.edge import EdgeCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["presets"])


# ── 请求模型 ──

class PresetRequest(BaseModel):
    feature_id: str
    node_id: Optional[str] = None
    canvas_id: Optional[str] = None
    prompt: Optional[str] = None
    style: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    # 宫格切分参数
    grid_rows: Optional[int] = None
    grid_cols: Optional[int] = None
    # 聚焦特写参数
    crop_region: Optional[Dict[str, int]] = None  # {x, y, w, h} 百分比


class PresetResponse(BaseModel):
    task_ids: List[str] = []
    node_ids: List[str] = []
    status: str = "queued"
    cost: int = 0
    message: str = ""


def _check_node_access(node, db: Session, current_user: User):
    """检查节点访问权限"""
    canvas = crud_canvas.get_canvas(db, node.canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="画布不存在")
    # canvas.user_id 是 String(255)，current_user.id 是 UUID 对象，必须统一转 str 比较
    if not canvas.user_id or str(canvas.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问此画布")


@router.post("/preset", response_model=PresetResponse)
async def execute_preset(
    req: PresetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行预设功能"""
    feature_id = req.feature_id

    # ── 宫格切分 / 聚焦特写：后端图像处理 ──
    if feature_id in ("grid_split", "focus_crop"):
        return await _handle_image_edit(feature_id, req, db, current_user)

    # ── 需要 LLM 处理的功能（剧本解析、脚本优化、拉片分析、25宫格分镜） ──
    if feature_id in ("script_parse", "script_optimize", "film_analysis", "storyboard_25"):
        return await _handle_llm_preset(feature_id, req, db, current_user)

    # ── 需要生成图片的功能 ──
    if feature_id in PRESET_CONFIG_OVERRIDES:
        return await _handle_generate_preset(feature_id, req, db, current_user)

    # ── 批量生成 ──
    if feature_id == "batch_generate":
        return await _handle_batch_generate(req, db, current_user)

    # ── 锁定角色一致性 ──
    if feature_id == "lock_character":
        return await _handle_lock_character(req, db, current_user)

    raise HTTPException(status_code=400, detail=f"不支持的预设功能: {feature_id}")


async def _handle_generate_preset(
    feature_id: str,
    req: PresetRequest,
    db: Session,
    current_user: User,
) -> PresetResponse:
    """处理需要生成图片的预设功能（三视图、360度、九宫格、四宫格推演、高清、扩图、抠图）

    核心逻辑：在原图节点下游创建新节点，连线，任务结果写入新节点，不覆盖原图。
    """
    if not req.node_id:
        raise HTTPException(status_code=400, detail="缺少 node_id")

    node = crud_node.get_node(db, UUID(req.node_id))
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_access(node, db, current_user)

    # 保留原始 prompt（未套模板的），让 worker 应用预设模板
    original_prompt = req.prompt or node.prompt or ""
    style = req.style or node.style or ""

    # 构建配置
    node_config = dict(node.config or {})
    if req.config:
        node_config.update(req.config)

    # 应用预设强制配置覆盖（aspect_ratio, resolution 等）
    overrides = PRESET_CONFIG_OVERRIDES.get(feature_id, {})
    for k, v in overrides.items():
        node_config[k] = v

    # 需要引用当前节点 result_url 作为参考图的功能
    if feature_id in PRESET_NEEDS_RESULT_REF and node.result_url:
        ref_images = list(node_config.get("reference_images") or [])
        if node.result_url not in ref_images:
            ref_images.insert(0, node.result_url)
        node_config["reference_images"] = ref_images

    # 标记预设来源
    node_config["preset_source"] = feature_id
    node_config["source_node_id"] = str(node.id)

    # 计算成本
    task_type = "generate_image"
    cost = calculate_cost(task_type, node_config, db=db)

    if cost > 0:
        try:
            deduct_credits(
                db=db,
                user_id=current_user.id,
                amount=cost,
                reason=f"preset_{feature_id}",
                ref_id=str(node.id),
                description=f"预设功能: {feature_id}",
            )
            db.commit()
        except InsufficientCreditsError as exc:
            db.rollback()
            raise HTTPException(status_code=402, detail=str(exc))

    # ── 创建下游新节点（不覆盖原节点）──
    preset_label = PRESET_LABELS.get(feature_id, feature_id)
    new_node = crud_node.create_node(db, NodeCreate(
        canvas_id=node.canvas_id,
        node_type=NodeType.IMAGE,
        title=f"{node.title} - {preset_label}",
        prompt=original_prompt,
        style=style or "realistic",
        x=node.x + (node.width or 240) + 40,
        y=node.y,
        config=node_config,
    ), commit=False)
    db.commit()

    # 创建连线：原节点 → 新节点
    crud_edge.create_edge(db, EdgeCreate(
        canvas_id=node.canvas_id,
        source_node_id=node.id,
        target_node_id=new_node.id,
        edge_type=EdgeType.REFERENCE,
        label=preset_label,
    ), commit=False)
    db.commit()

    # 提交任务：使用新节点 ID，结果将写入新节点
    task = Task(
        id=task_manager.new_task_id(),
        node_id=str(new_node.id),
        canvas_id=str(node.canvas_id),
        task_type=task_type,
        user_id=str(current_user.id),
        cost=cost,
        params={
            "prompt": original_prompt,
            "_original_prompt": original_prompt,
            "style": style or "realistic",
            "node_type": node.node_type.value,
            "model": node_config.get("model"),
            "aspect_ratio": node_config.get("aspect_ratio", "1:1"),
            "resolution": node_config.get("resolution"),
            "reference_images": node_config.get("reference_images", []),
            "reference_asset_ids": node_config.get("reference_asset_ids", []),
            "count": 1,
            "preset_feature": feature_id,
        },
    )
    await task_manager.submit(task)

    # 更新新节点状态为 PENDING
    new_node.status = NodeStatus.PENDING
    new_node.progress = 0
    db.add(new_node)
    db.commit()

    return PresetResponse(
        task_ids=[task.id],
        node_ids=[str(new_node.id)],
        status="queued",
        cost=cost,
        message=f"预设功能 {preset_label} 已提交，已创建下游节点",
    )


async def _handle_llm_preset(
    feature_id: str,
    req: PresetRequest,
    db: Session,
    current_user: User,
) -> PresetResponse:
    """处理需要 LLM 的预设功能（剧本解析、脚本优化、拉片分析、25宫格分镜）

    核心逻辑：在原节点下游创建新节点，连线，LLM 结果写入新节点，不覆盖原节点。
    storyboard_25 完成后还会自动创建 25 个分镜子节点。
    """
    if not req.node_id:
        raise HTTPException(status_code=400, detail="缺少 node_id")

    node = crud_node.get_node(db, UUID(req.node_id))
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_access(node, db, current_user)

    # 提交 LLM 任务
    task_type = "generate_script"
    node_config = dict(node.config or {})
    node_config["preset_feature"] = feature_id
    node_config["preset_source"] = feature_id
    node_config["source_node_id"] = str(node.id)

    cost = calculate_cost(task_type, node_config, db=db)

    if cost > 0:
        try:
            deduct_credits(
                db=db,
                user_id=current_user.id,
                amount=cost,
                reason=f"preset_{feature_id}",
                ref_id=str(node.id),
                description=f"预设功能: {feature_id}",
            )
            db.commit()
        except InsufficientCreditsError as exc:
            db.rollback()
            raise HTTPException(status_code=402, detail=str(exc))

    content = req.prompt or node.prompt or ""
    video_url = node.result_url or ""

    # ── 创建下游新节点（不覆盖原节点）──
    preset_label = PRESET_LABELS.get(feature_id, feature_id)
    # storyboard_25 下游节点保持 SCRIPT 类型；其他也用 SCRIPT
    new_node = crud_node.create_node(db, NodeCreate(
        canvas_id=node.canvas_id,
        node_type=NodeType.SCRIPT,
        title=f"{node.title} - {preset_label}",
        prompt=content,
        x=node.x + (node.width or 240) + 40,
        y=node.y,
        config=node_config,
    ), commit=False)
    db.commit()

    # 创建连线：原节点 → 新节点
    crud_edge.create_edge(db, EdgeCreate(
        canvas_id=node.canvas_id,
        source_node_id=node.id,
        target_node_id=new_node.id,
        edge_type=EdgeType.REFERENCE,
        label=preset_label,
    ), commit=False)
    db.commit()

    # 提交任务：使用新节点 ID
    task = Task(
        id=task_manager.new_task_id(),
        node_id=str(new_node.id),
        canvas_id=str(node.canvas_id),
        task_type=task_type,
        user_id=str(current_user.id),
        cost=cost,
        params={
            "prompt": content,
            "node_type": node.node_type.value,
            "preset_feature": feature_id,
            "model": node_config.get("model"),
            "result_url": video_url,
            "style": node.style or "",
        },
    )
    await task_manager.submit(task)

    # 更新新节点状态为 PENDING
    new_node.status = NodeStatus.PENDING
    new_node.progress = 0
    db.add(new_node)
    db.commit()

    return PresetResponse(
        task_ids=[task.id],
        node_ids=[str(new_node.id)],
        status="queued",
        cost=cost,
        message=f"预设功能 {preset_label} 已提交，已创建下游节点",
    )


async def _handle_image_edit(
    feature_id: str,
    req: PresetRequest,
    db: Session,
    current_user: User,
) -> PresetResponse:
    """处理宫格切分和聚焦特写：使用 Pillow 进行本地图像处理。"""
    if not req.node_id:
        raise HTTPException(status_code=400, detail="缺少 node_id")

    node = crud_node.get_node(db, UUID(req.node_id))
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_access(node, db, current_user)

    if not node.result_url:
        raise HTTPException(status_code=400, detail="节点没有已生成的图片，无法执行此操作")

    # 延迟导入避免 Pillow 未安装时启动报错
    try:
        from app.services.image_processor import split_image, crop_image
    except ImportError:
        raise HTTPException(status_code=500, detail="图像处理服务不可用（Pillow 未安装）")

    # 获取原图路径
    # preset.py 位于 app/api/v1/preset.py，需要 3 层 dirname 才能到 app/
    import os
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
    image_url = node.result_url

    # 解析本地文件路径
    local_path: Optional[str] = None
    if image_url.startswith("/static/"):
        local_path = os.path.join(upload_dir, image_url[len("/static/"):])
    elif image_url.startswith("/uploads/"):
        local_path = os.path.join(upload_dir, image_url[len("/uploads/"):])
    elif image_url.startswith("/api/uploads/"):
        local_path = os.path.join(upload_dir, image_url[len("/api/uploads/"):])
    elif image_url.startswith(("http://", "https://")):
        local_path = None  # 需要下载
    else:
        local_path = image_url

    created_node_ids: List[str] = []

    if feature_id == "grid_split":
        rows = req.grid_rows or 3
        cols = req.grid_cols or 3
        if rows < 2 or rows > 5 or cols < 2 or cols > 5:
            raise HTTPException(status_code=400, detail="宫格行列数必须在 2-5 之间")

        try:
            sub_images = await split_image(
                image_url=image_url,
                local_path=local_path,
                rows=rows,
                cols=cols,
                upload_dir=upload_dir,
            )
        except Exception as exc:
            logger.error("[preset] grid_split 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"宫格切分失败: {exc}")

        # 在画布上创建子图节点
        base_x = node.x + (node.width or 240) + 40
        base_y = node.y
        for i, sub in enumerate(sub_images):
            row = i // cols
            col = i % cols
            sub_node = crud_node.create_node(db, NodeCreate(
                canvas_id=node.canvas_id,
                node_type=NodeType.IMAGE,
                title=f"{node.title} - 切分 {row + 1}-{col + 1}",
                prompt=node.prompt or "",
                result_url=sub["url"],
                thumbnail_url=sub["url"],
                x=base_x + col * 260,
                y=base_y + row * 200,
                config={
                    "preset_source": "grid_split",
                    "source_node_id": str(node.id),
                    "grid_row": row,
                    "grid_col": col,
                },
            ), commit=False)
            # 图像已处理完成，直接标记为 SUCCESS
            sub_node.status = NodeStatus.SUCCESS
            sub_node.progress = 100
            created_node_ids.append(str(sub_node.id))

        db.commit()

        # 创建 REFERENCE 边：原图 → 子图
        for nid in created_node_ids:
            crud_edge.create_edge(db, EdgeCreate(
                canvas_id=node.canvas_id,
                source_node_id=node.id,
                target_node_id=UUID(nid),
                edge_type=EdgeType.REFERENCE,
                label="切分",
            ), commit=False)
        db.commit()

        return PresetResponse(
            node_ids=created_node_ids,
            status="completed",
            message=f"宫格切分完成，已创建 {len(created_node_ids)} 个子图节点",
        )

    elif feature_id == "focus_crop":
        if not req.crop_region:
            raise HTTPException(status_code=400, detail="缺少 crop_region 参数")

        region = req.crop_region
        for key in ("x", "y", "w", "h"):
            if key not in region or not (0 <= region[key] <= 100):
                raise HTTPException(status_code=400, detail=f"crop_region.{key} 必须在 0-100 之间")

        try:
            cropped = await crop_image(
                image_url=image_url,
                local_path=local_path,
                region=region,
                upload_dir=upload_dir,
            )
        except Exception as exc:
            logger.error("[preset] focus_crop 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"聚焦裁剪失败: {exc}")

        # 创建裁剪结果节点
        crop_node = crud_node.create_node(db, NodeCreate(
            canvas_id=node.canvas_id,
            node_type=NodeType.IMAGE,
            title=f"{node.title} - 特写",
            prompt=node.prompt or "",
            result_url=cropped["url"],
            thumbnail_url=cropped["url"],
            x=node.x + (node.width or 240) + 40,
            y=node.y,
            config={
                "preset_source": "focus_crop",
                "source_node_id": str(node.id),
                "crop_region": region,
            },
        ), commit=False)
        # 图像已处理完成，直接标记为 SUCCESS
        crop_node.status = NodeStatus.SUCCESS
        crop_node.progress = 100
        created_node_ids.append(str(crop_node.id))
        db.commit()

        # 创建边
        crud_edge.create_edge(db, EdgeCreate(
            canvas_id=node.canvas_id,
            source_node_id=node.id,
            target_node_id=crop_node.id,
            edge_type=EdgeType.REFERENCE,
            label="特写",
        ), commit=False)
        db.commit()

        return PresetResponse(
            node_ids=created_node_ids,
            status="completed",
            message="聚焦特写完成，已创建裁剪节点",
        )

    return PresetResponse(status="error", message="未知的图像编辑功能")


async def _handle_batch_generate(
    req: PresetRequest,
    db: Session,
    current_user: User,
) -> PresetResponse:
    """批量生成：对画布上所有 storyboard/image/video 节点批量触发生成"""
    if not req.canvas_id:
        raise HTTPException(status_code=400, detail="缺少 canvas_id")

    canvas = crud_canvas.get_canvas(db, UUID(req.canvas_id))
    if not canvas or not canvas.user_id or str(canvas.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问此画布")

    nodes = crud_node.get_nodes_by_canvas(db, UUID(req.canvas_id))
    # 过滤出可生成的节点
    target_types = {NodeType.STORYBOARD, NodeType.IMAGE, NodeType.VIDEO}
    target_nodes = [n for n in nodes if n.node_type in target_types and n.status != NodeStatus.PROCESSING]

    if not target_nodes:
        return PresetResponse(status="empty", message="没有可生成的节点")

    task_ids = []
    node_ids = []
    total_cost = 0

    for node in target_nodes:
        node_config = dict(node.config or {})
        task_type = "generate_image" if node.node_type != NodeType.VIDEO else "generate_video"

        single_cost = calculate_cost(task_type, node_config, db=db)
        total_cost += single_cost

        if single_cost > 0:
            try:
                deduct_credits(
                    db=db,
                    user_id=current_user.id,
                    amount=single_cost,
                    reason=f"batch_generate",
                    ref_id=str(node.id),
                    description=f"批量生成: {node.title}",
                )
            except InsufficientCreditsError as exc:
                db.rollback()
                raise HTTPException(status_code=402, detail=f"积分不足，已生成 {len(task_ids)} 个节点。{exc}")

        task = Task(
            id=task_manager.new_task_id(),
            node_id=str(node.id),
            canvas_id=str(node.canvas_id),
            task_type=task_type,
            user_id=str(current_user.id),
            cost=single_cost,
            params={
                "prompt": node.prompt or "",
                "style": node.style or "realistic",
                "node_type": node.node_type.value,
                "model": node_config.get("model"),
                "aspect_ratio": node_config.get("aspect_ratio"),
                "resolution": node_config.get("resolution"),
                "durationSec": node_config.get("duration"),
                "reference_images": node_config.get("reference_images", []),
                "reference_asset_ids": node_config.get("reference_asset_ids", []),
                "count": 1,
            },
        )
        await task_manager.submit(task)
        task_ids.append(task.id)
        node_ids.append(str(node.id))

        node.status = NodeStatus.PENDING
        node.progress = 0
        db.add(node)

    db.commit()

    return PresetResponse(
        task_ids=task_ids,
        node_ids=node_ids,
        status="queued",
        cost=total_cost,
        message=f"批量生成已提交 {len(task_ids)} 个节点",
    )


async def _handle_lock_character(
    req: PresetRequest,
    db: Session,
    current_user: User,
) -> PresetResponse:
    """锁定角色一致性：提取角色特征并存入 config。

    增强版：使用 LLM 提取角色不可变特征（发色、瞳色、服装等），
    而非仅存储原始 prompt。
    """
    if not req.node_id:
        raise HTTPException(status_code=400, detail="缺少 node_id")

    node = crud_node.get_node(db, UUID(req.node_id))
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_access(node, db, current_user)

    if node.node_type != NodeType.CHARACTER:
        raise HTTPException(status_code=400, detail="仅角色节点可锁定一致性")

    node_config = dict(node.config or {})

    if not node.result_url:
        raise HTTPException(status_code=400, detail="请先生成角色图片再锁定")

    # 生成角色唯一 ID
    char_id = node_config.get("character_id") or f"char_{uuid.uuid4().hex[:8]}"
    node_config["character_id"] = char_id
    node_config["is_locked"] = True
    node_config["locked_result_url"] = node.result_url

    # 基础特征（即时存储）
    node_config["immutable_features"] = {
        "description": node.prompt or "",
        "style": node.style or "",
        "reference_url": node.result_url,
    }

    # 尝试用 LLM 提取详细特征（非阻塞，失败时使用基础特征）
    try:
        from app.services.ai_service import AIService

        messages = get_character_feature_messages(node.prompt or "", node.style or "")
        response = await AIService.chat(messages, model=None, max_tokens=4096, temperature=0.1)

        if isinstance(response, dict) and isinstance(response.get("choices"), list):
            content = response["choices"][0].get("message", {}).get("content", "")
            # 尝试解析 JSON
            import json
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content, re.IGNORECASE)
            if m:
                content = m.group(1).strip()
            start = content.find("{")
            if start != -1:
                depth = 0
                for i in range(start, len(content)):
                    if content[i] == "{":
                        depth += 1
                    elif content[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                features = json.loads(content[start:i + 1])
                                node_config["immutable_features"] = {
                                    **node_config["immutable_features"],
                                    **features,
                                }
                                logger.info("[preset] 角色特征提取成功 char=%s", char_id)
                            except json.JSONDecodeError:
                                logger.warning("[preset] 角色特征 JSON 解析失败，使用基础特征")
                            break
    except Exception as exc:
        logger.warning("[preset] LLM 角色特征提取失败，使用基础特征: %s", exc)

    node.config = node_config
    db.add(node)
    db.commit()

    return PresetResponse(
        node_ids=[str(node.id)],
        status="locked",
        message=f"角色已锁定，ID: {char_id}",
    )


@router.post("/preset/storyboard_25/create_nodes")
async def create_storyboard_25_nodes(
    req: PresetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """25宫格分镜任务完成后，在画布上批量创建分镜节点。

    前端在检测到 storyboard_25 任务完成后，调用此端点创建节点。
    """
    if not req.node_id:
        raise HTTPException(status_code=400, detail="缺少 node_id")

    node = crud_node.get_node(db, UUID(req.node_id))
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    _check_node_access(node, db, current_user)

    # 从 config 中获取 LLM 生成的 panels
    node_config = dict(node.config or {})
    panels = node_config.get("storyboard_25_panels") or []
    if not panels:
        raise HTTPException(status_code=400, detail="没有可用的分镜数据，请先执行 25 宫格分镜")

    # 在画布上创建分镜节点（5x5 网格布局）
    base_x = node.x + (node.width or 240) + 60
    base_y = node.y
    col_gap = 280
    row_gap = 220

    created_node_ids: List[str] = []

    for panel in panels:
        idx = panel.get("index", 0)
        grid_row = panel.get("grid_row", (idx - 1) // 5)
        grid_col = panel.get("grid_col", (idx - 1) % 5)

        sb_node = crud_node.create_node(db, NodeCreate(
            canvas_id=node.canvas_id,
            node_type=NodeType.STORYBOARD,
            title=f"分镜 {idx}",
            prompt=panel.get("prompt") or panel.get("description", ""),
            x=base_x + grid_col * col_gap,
            y=base_y + grid_row * row_gap,
            config={
                "storyboard_id": f"SB_25_{idx:03d}",
                "panel_index": idx,
                "grid_row": grid_row,
                "grid_col": grid_col,
                "description": panel.get("description", ""),
                "shot_type": panel.get("shot_type", ""),
                "duration_seconds": panel.get("duration_seconds", 3),
                "source_node_id": str(node.id),
                "preset_source": "storyboard_25",
            },
        ), commit=False)
        created_node_ids.append(str(sb_node.id))

    db.commit()

    # 创建边：源节点 → 每个分镜
    for nid in created_node_ids:
        crud_edge.create_edge(db, EdgeCreate(
            canvas_id=node.canvas_id,
            source_node_id=node.id,
            target_node_id=UUID(nid),
            edge_type=EdgeType.REFERENCE,
            label="分镜",
        ), commit=False)
    db.commit()

    # 创建相邻分镜的 SEQUENCE 边
    for i in range(1, len(created_node_ids)):
        crud_edge.create_edge(db, EdgeCreate(
            canvas_id=node.canvas_id,
            source_node_id=UUID(created_node_ids[i - 1]),
            target_node_id=UUID(created_node_ids[i]),
            edge_type=EdgeType.SEQUENCE,
            label="下一镜",
        ), commit=False)
    db.commit()

    return {
        "status": "completed",
        "node_ids": created_node_ids,
        "count": len(created_node_ids),
        "message": f"已创建 {len(created_node_ids)} 个分镜节点",
    }
