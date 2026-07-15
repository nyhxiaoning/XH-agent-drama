import os
import uuid
import logging
import mimetypes
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.core.permissions import can_access_canvas
from app.crud import asset as crud_asset
from app.crud import team as team_crud
from app.crud import canvas as crud_canvas
from app.schemas.asset import AssetCreate, AssetUpdate, AssetInDB, AssetType
from app.models.asset import Asset
from app.api.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assets", tags=["assets"])

# 本地目录仅在 COS 未配置时作为降级方案
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
STATIC_URL_PREFIX = "/static"

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
MAX_FILE_SIZE = 100 * 1024 * 1024


def _get_subdir(asset_type: str) -> str:
    mapping = {
        "image": "images",
        "video": "videos",
        "audio": "audio",
        "character": "images",
        "scene": "images",
        "other": "images",
    }
    return mapping.get(asset_type, "images")


def _check_asset_access(asset: Asset, current_user: User, db: Session):
    """校验当前用户是否有权访问/修改该资产。"""
    user_id = str(current_user.id)
    if asset.user_id and asset.user_id == user_id:
        return
    if asset.team_id:
        if team_crud.is_team_member(db, user_id=user_id, team_id=asset.team_id):
            return
    raise HTTPException(status_code=403, detail="没有权限访问该资产")


def _ext_for_mime(content_type: str) -> str:
    """根据 mime_type 获取文件扩展名（不含点）。"""
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
    if ext:
        return ext.lstrip(".")
    mapping = {
        "video/mp4": "mp4",
        "video/webm": "webm",
        "image/webp": "webp",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/gif": "gif",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/ogg": "ogg",
        "application/octet-stream": "bin",
    }
    return mapping.get(content_type.lower().split(";")[0].strip(), "bin")


def _cos_configured() -> bool:
    """检查腾讯云 COS 是否已配置。"""
    return bool(
        settings.TENCENT_COS_SECRET_ID
        and settings.TENCENT_COS_SECRET_KEY
        and settings.TENCENT_COS_BUCKET
        and settings.TENCENT_COS_REGION
    )


@router.post("/upload", response_model=AssetInDB, status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form("未命名资产"),
    asset_type: AssetType = Form(AssetType.IMAGE),
    tags: str = Form(""),
    description: str = Form(None),
    canvas_id: Optional[str] = Form(None),
    team_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        if file.content_type and file.content_type.startswith("image/") and file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的图片格式: {file.content_type}")
        if file.content_type and file.content_type.startswith("video/") and file.content_type not in ALLOWED_VIDEO_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持的视频格式: {file.content_type}")

        subdir = _get_subdir(asset_type.value)
        content = await file.read()
        file_size = len(content)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="文件大小超过限制(100MB)")

        mime_type = file.content_type or "application/octet-stream"
        ext = _ext_for_mime(mime_type)
        file_id = str(uuid.uuid4())
        cos_key = f"uploads/{subdir}/{file_id}.{ext}"

        if _cos_configured():
            # 直传腾讯云 COS
            from app.services.cos_service import upload_to_cos
            file_url = upload_to_cos(content, cos_key, mime_type, file_size)
            file_path = cos_key  # 存储 COS key 作为路径
            logger.info("[upload] 文件已上传至 COS: %s (%d bytes)", file_url, file_size)
        else:
            # 降级：存到本地磁盘
            save_dir = os.path.join(UPLOAD_DIR, subdir)
            os.makedirs(save_dir, exist_ok=True)
            local_filename = f"{file_id}.{ext}"
            file_path = os.path.join(save_dir, local_filename)
            file_url = f"{STATIC_URL_PREFIX}/{subdir}/{local_filename}"
            with open(file_path, "wb") as f:
                f.write(content)
            logger.info("[upload] COS 未配置，文件已存至本地: %s (%d bytes)", file_path, file_size)

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        canvas_uuid = None
        if canvas_id:
            try:
                canvas_uuid = UUID(canvas_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="canvas_id 格式错误")
            canvas = crud_canvas.get_canvas(db, canvas_uuid)
            if not canvas or not can_access_canvas(db, str(current_user.id), canvas):
                raise HTTPException(status_code=403, detail="没有权限上传资产到该画布")

        team_uuid = None
        if team_id:
            try:
                team_uuid = UUID(team_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="team_id 格式错误")
            if not team_crud.is_team_member(db, user_id=str(current_user.id), team_id=team_uuid):
                raise HTTPException(status_code=403, detail="你不是该团队成员")

        asset_in = AssetCreate(
            name=name or file.filename or "未命名资产",
            asset_type=asset_type,
            tags=tag_list,
            description=description,
            canvas_id=canvas_uuid,
        )

        asset = crud_asset.create_asset(
            db, asset_in,
            file_path=file_path,
            file_url=file_url,
            mime_type=mime_type,
            file_size=file_size,
            user_id=str(current_user.id),
            team_id=team_uuid,
        )
        return asset
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[upload] 上传失败: %s", e)
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.get("", response_model=List[AssetInDB])
def list_assets(
    asset_type: AssetType = None,
    canvas_id: Optional[str] = None,
    team_id: Optional[str] = None,
    q: str = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    canvas_uuid = None
    if canvas_id:
        try:
            canvas_uuid = UUID(canvas_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="canvas_id 格式错误")
    user_id = str(current_user.id)
    teams = team_crud.get_user_teams(db, user_id=user_id)
    team_ids = [t.id for t in teams]

    # 如果指定了 team_id，仅返回该团队的资产（校验成员身份）
    if team_id:
        try:
            team_uuid = UUID(team_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="team_id 格式错误")
        if team_uuid not in team_ids:
            raise HTTPException(status_code=403, detail="你不是该团队成员")
        return crud_asset.get_assets(
            db,
            user_id=None,
            team_ids=[team_uuid],
            canvas_id=canvas_uuid,
            asset_type=asset_type,
            query=q,
            skip=skip,
            limit=limit,
        )

    return crud_asset.get_assets(
        db,
        user_id=user_id,
        team_ids=team_ids,
        canvas_id=canvas_uuid,
        asset_type=asset_type,
        query=q,
        skip=skip,
        limit=limit,
    )


@router.get("/{asset_id}", response_model=AssetInDB)
def get_asset(asset_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    asset = crud_asset.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    _check_asset_access(asset, current_user, db)
    return asset


@router.patch("/{asset_id}", response_model=AssetInDB)
def update_asset(asset_id: UUID, asset_in: AssetUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    asset = crud_asset.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    _check_asset_access(asset, current_user, db)
    return crud_asset.update_asset(db, asset, asset_in)


@router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    asset = crud_asset.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    _check_asset_access(asset, current_user, db)
    crud_asset.delete_asset(db, asset_id)


@router.get("/search/suggest")
def suggest_assets(q: str = Query(..., min_length=1), limit: int = 10, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_id = str(current_user.id)
    teams = team_crud.get_user_teams(db, user_id=user_id)
    team_ids = [t.id for t in teams]
    assets = crud_asset.get_assets(db, user_id=user_id, team_ids=team_ids, query=q, limit=limit)
    return [
        {"id": str(a.id), "name": a.name, "type": a.asset_type.value, "url": a.file_url, "thumbnail": a.thumbnail_url}
        for a in assets
    ]
