import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.announcement import Announcement
from app.schemas.admin import AdminAnnouncementOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("", response_model=List[AdminAnnouncementOut])
def list_enabled_announcements(db: Session = Depends(get_db)):
    """用户端：列出启用的公告，按置顶+时间倒序。"""
    return (
        db.query(Announcement)
        .filter(Announcement.enabled == True)
        .order_by(Announcement.pinned.desc(), Announcement.created_at.desc())
        .all()
    )
