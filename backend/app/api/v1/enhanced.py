"""
P3/P6/P8/P9/P10/P11: 新功能统一 API 路由。

涵盖：
- P3: 角色一致性校验
- P6: 会话版本管理
- P8: 小说导入与分集
- P9: 风格模板列表
- P10: 多人协作
- P11: IP 资产库
"""
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.core.style_templates import list_style_templates, get_style_metadata_for_script, apply_style_to_global_params
from app.core.version_manager import list_versions, restore_version, diff_versions
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enhanced", tags=["enhanced"])


# =========================================================================
# P9: 风格模板
# =========================================================================

@router.get("/style-templates")
async def get_style_templates_api():
    """获取所有可用的画风预设模板。"""
    return {"templates": list_style_templates()}


class ApplyStyleRequest(BaseModel):
    template_id: str
    existing_params: Optional[Dict[str, str]] = None


@router.post("/style-templates/apply")
async def apply_style_template_api(req: ApplyStyleRequest):
    """应用风格模板到全局参数。"""
    params = apply_style_to_global_params(req.template_id, req.existing_params)
    metadata = get_style_metadata_for_script(req.template_id)
    return {"global_params": params, "style_metadata": metadata}


# =========================================================================
# P6: 会话版本管理
# =========================================================================

class RestoreVersionRequest(BaseModel):
    version_id: str


@router.get("/sessions/{sid}/versions")
async def list_session_versions(sid: str):
    """列出会话的所有版本快照。"""
    from app.agents.short_drama import short_drama_workflow
    session = short_drama_workflow.get_session(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    versions = list_versions(session)
    return {"versions": versions}


@router.post("/sessions/{sid}/versions/restore")
async def restore_session_version(sid: str, req: RestoreVersionRequest):
    """回退到指定版本。"""
    from app.agents.short_drama import short_drama_workflow
    session = short_drama_workflow.get_session(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    restored = restore_version(session, req.version_id)
    if restored is None:
        raise HTTPException(status_code=404, detail="版本不存在")

    short_drama_workflow.save_session(sid, restored)
    return {"status": "ok", "message": f"已回退到版本 {req.version_id}"}


@router.get("/sessions/{sid}/versions/diff")
async def diff_session_versions(
    sid: str,
    version_a: str = Query(...),
    version_b: str = Query(...),
):
    """对比两个版本的差异。"""
    from app.agents.short_drama import short_drama_workflow
    session = short_drama_workflow.get_session(sid)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    diff = diff_versions(session, version_a, version_b)
    return {"diff": diff}


# =========================================================================
# P8: 小说导入与分集
# =========================================================================

class NovelImportRequest(BaseModel):
    novel_text: str
    target_episodes: int = 10
    genre_hint: Optional[str] = None
    llm_model: Optional[str] = None


class GenerateEpisodeScriptRequest(BaseModel):
    episode_plan: Dict[str, Any]
    source_text: str
    episode_num: int
    llm_model: Optional[str] = None


@router.post("/novel-import/plan")
async def novel_import_plan(req: NovelImportRequest):
    """规划小说分集方案。"""
    from app.agents.novel_import import get_novel_agent
    agent = get_novel_agent(req.llm_model)
    plan = await agent.plan_episodes(
        novel_text=req.novel_text,
        target_episodes=req.target_episodes,
        genre_hint=req.genre_hint,
    )
    return {"plan": plan}


@router.post("/novel-import/episode-script")
async def generate_episode_script(req: GenerateEpisodeScriptRequest):
    """为单集生成详细剧本。"""
    from app.agents.novel_import import get_novel_agent
    agent = get_novel_agent(req.llm_model)
    script = await agent.generate_episode_script(
        episode_plan=req.episode_plan,
        source_text=req.source_text,
        episode_num=req.episode_num,
    )
    return {"script": script}


# =========================================================================
# P3: 角色一致性校验
# =========================================================================

class VerifyCharacterRequest(BaseModel):
    character_name: str
    character_desc: str
    reference_image_url: Optional[str] = None
    llm_model: Optional[str] = None


class BatchVerifyCharactersRequest(BaseModel):
    characters: List[Dict[str, Any]]
    llm_model: Optional[str] = None


class StoryboardConsistencyRequest(BaseModel):
    storyboard: List[Dict[str, Any]]
    character_assets: List[Dict[str, Any]]
    llm_model: Optional[str] = None


@router.post("/consistency/verify-character")
async def verify_character(req: VerifyCharacterRequest):
    """校验角色设定一致性。"""
    from app.agents.consistency import get_consistency_agent
    agent = get_consistency_agent(req.llm_model)
    result = await agent.verify_character_sheet(
        character_name=req.character_name,
        character_desc=req.character_desc,
        reference_image_url=req.reference_image_url,
    )
    return {"result": result}


@router.post("/consistency/batch-verify")
async def batch_verify_characters(req: BatchVerifyCharactersRequest):
    """批量校验角色列表。"""
    from app.agents.consistency import get_consistency_agent
    agent = get_consistency_agent(req.llm_model)
    results = await agent.batch_verify_characters(req.characters)
    return {"results": results}


@router.post("/consistency/storyboard-check")
async def check_storyboard_consistency(req: StoryboardConsistencyRequest):
    """检查分镜角色一致性。"""
    from app.agents.consistency import get_consistency_agent
    agent = get_consistency_agent(req.llm_model)
    result = await agent.check_storyboard_consistency(
        storyboard=req.storyboard,
        character_assets=req.character_assets,
    )
    return {"result": result}


# =========================================================================
# P11: IP 资产库
# =========================================================================

class IPAssetCreate(BaseModel):
    asset_type: str  # character | scene | prop
    name: str
    description: Optional[str] = None
    appearance_desc: Optional[str] = None
    outfit_desc: Optional[str] = None
    immutable_features: Optional[List[str]] = None
    visual_anchors: Optional[List[str]] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    style_tags: Optional[List[str]] = None
    genre_tags: Optional[List[str]] = None
    color_palette: Optional[List[str]] = None
    source_canvas_id: Optional[str] = None
    source_project_name: Optional[str] = None
    is_public: bool = False
    tags: Optional[List[str]] = None


@router.get("/ip-assets")
async def list_ip_assets(
    asset_type: Optional[str] = Query(None),
    style_tag: Optional[str] = Query(None),
    genre_tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    is_public: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """检索 IP 资产库。"""
    from app.models.ip_asset import IPAsset
    from sqlalchemy import or_

    query = db.query(IPAsset)
    # 用户只能看到自己的资产和公开资产
    query = query.filter(
        or_(
            IPAsset.user_id == str(user.id),
            IPAsset.is_public == True,
        )
    )
    if asset_type:
        query = query.filter(IPAsset.asset_type == asset_type)
    if is_public is not None:
        query = query.filter(IPAsset.is_public == is_public)
    if search:
        query = query.filter(IPAsset.name.ilike(f"%{search}%"))

    total = query.count()
    items = query.order_by(IPAsset.updated_at.desc()).offset(offset).limit(limit).all()

    # 内存中过滤标签（SQLite JSON 查询不方便）
    results = []
    for item in items:
        if style_tag and style_tag not in (item.style_tags or []):
            continue
        if genre_tag and genre_tag not in (item.genre_tags or []):
            continue
        results.append({
            "id": str(item.id),
            "asset_type": item.asset_type,
            "name": item.name,
            "description": item.description,
            "appearance_desc": item.appearance_desc,
            "outfit_desc": item.outfit_desc,
            "immutable_features": item.immutable_features or [],
            "visual_anchors": item.visual_anchors or [],
            "image_url": item.image_url,
            "thumbnail_url": item.thumbnail_url,
            "style_tags": item.style_tags or [],
            "genre_tags": item.genre_tags or [],
            "color_palette": item.color_palette or [],
            "reuse_count": item.reuse_count,
            "is_public": item.is_public,
            "tags": item.tags or [],
        })

    return {"items": results, "total": total, "limit": limit, "offset": offset}


@router.post("/ip-assets")
async def create_ip_asset(
    req: IPAssetCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建 IP 资产。"""
    from app.models.ip_asset import IPAsset

    asset = IPAsset(
        user_id=str(user.id),
        asset_type=req.asset_type,
        name=req.name,
        description=req.description,
        appearance_desc=req.appearance_desc,
        outfit_desc=req.outfit_desc,
        immutable_features=req.immutable_features or [],
        visual_anchors=req.visual_anchors or [],
        image_url=req.image_url,
        thumbnail_url=req.thumbnail_url,
        style_tags=req.style_tags or [],
        genre_tags=req.genre_tags or [],
        color_palette=req.color_palette or [],
        source_canvas_id=req.source_canvas_id,
        source_project_name=req.source_project_name,
        is_public=req.is_public,
        tags=req.tags or [],
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"id": str(asset.id), "status": "created"}


@router.post("/ip-assets/{asset_id}/reuse")
async def reuse_ip_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """复用 IP 资产（增加复用计数）。"""
    from app.models.ip_asset import IPAsset
    from sqlalchemy import or_

    asset = db.query(IPAsset).filter(
        IPAsset.id == asset_id,
        or_(
            IPAsset.user_id == str(user.id),
            IPAsset.is_public == True,
        )
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="IP 资产不存在")

    asset.reuse_count = (asset.reuse_count or 0) + 1
    db.commit()

    return {
        "id": str(asset.id),
        "asset_type": asset.asset_type,
        "name": asset.name,
        "appearance_desc": asset.appearance_desc,
        "outfit_desc": asset.outfit_desc,
        "immutable_features": asset.immutable_features or [],
        "visual_anchors": asset.visual_anchors or [],
        "image_url": asset.image_url,
        "color_palette": asset.color_palette or [],
        "reuse_count": asset.reuse_count,
    }


# =========================================================================
# P10: 多人协作
# =========================================================================

class InviteCollaboratorRequest(BaseModel):
    canvas_id: str
    username: str
    role: str = "viewer"  # editor | viewer | commenter


class UpdateCollaboratorRequest(BaseModel):
    role: str


@router.get("/collaboration/{canvas_id}/collaborators")
async def list_collaborators(
    canvas_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """列出画布的协作者。"""
    from app.models.collaboration import CanvasCollaborator
    collabs = db.query(CanvasCollaborator).filter(
        CanvasCollaborator.canvas_id == canvas_id
    ).all()
    return {
        "collaborators": [
            {
                "id": str(c.id),
                "user_id": c.user_id,
                "username": c.username,
                "role": c.role.value if hasattr(c.role, 'value') else str(c.role),
                "invite_status": c.invite_status,
            }
            for c in collabs
        ]
    }


@router.post("/collaboration/invite")
async def invite_collaborator(
    req: InviteCollaboratorRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """邀请协作者。"""
    from app.models.collaboration import CanvasCollaborator, CollaboratorRole
    from app.models.user import User

    # 查找被邀请用户
    target_user = db.query(User).filter(User.username == req.username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 检查是否已存在
    existing = db.query(CanvasCollaborator).filter(
        CanvasCollaborator.canvas_id == req.canvas_id,
        CanvasCollaborator.user_id == str(target_user.id),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该用户已是协作者")

    role_map = {
        "editor": CollaboratorRole.EDITOR,
        "viewer": CollaboratorRole.VIEWER,
        "commenter": CollaboratorRole.COMMENTER,
    }
    role = role_map.get(req.role, CollaboratorRole.VIEWER)

    collab = CanvasCollaborator(
        canvas_id=req.canvas_id,
        user_id=str(target_user.id),
        username=target_user.username,
        role=role,
        invited_by=str(user.id),
        invite_status="accepted",  # 简化：直接接受
    )
    db.add(collab)
    db.commit()
    return {"status": "ok", "message": f"已邀请 {req.username} 作为 {req.role}"}


@router.put("/collaboration/{collab_id}/role")
async def update_collaborator_role(
    collab_id: str,
    req: UpdateCollaboratorRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """更新协作者角色。"""
    from app.models.collaboration import CanvasCollaborator, CollaboratorRole

    collab = db.query(CanvasCollaborator).filter(CanvasCollaborator.id == collab_id).first()
    if not collab:
        raise HTTPException(status_code=404, detail="协作者关系不存在")

    role_map = {
        "editor": CollaboratorRole.EDITOR,
        "viewer": CollaboratorRole.VIEWER,
        "commenter": CollaboratorRole.COMMENTER,
    }
    collab.role = role_map.get(req.role, CollaboratorRole.VIEWER)
    db.commit()
    return {"status": "ok"}


@router.delete("/collaboration/{collab_id}")
async def remove_collaborator(
    collab_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """移除协作者。"""
    from app.models.collaboration import CanvasCollaborator

    collab = db.query(CanvasCollaborator).filter(CanvasCollaborator.id == collab_id).first()
    if not collab:
        raise HTTPException(status_code=404, detail="协作者关系不存在")

    db.delete(collab)
    db.commit()
    return {"status": "ok"}


# =========================================================================
# P5: WebSocket 连接状态查询
# =========================================================================

@router.get("/ws/status")
async def ws_status():
    """查询 WebSocket 连接状态。"""
    from app.core.ws import ws_manager
    return {
        "connection_count": ws_manager.get_connection_count(),
        "canvases": list(ws_manager._connections.keys()),
    }
