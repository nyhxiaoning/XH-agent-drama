"""
技能对话历史 API。
提供对话的创建、列表、详情、删除，以及消息追加。
"""
import uuid
from datetime import datetime
from typing import Optional, List, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.skill_conversation import SkillConversation, SkillMessage

router = APIRouter(prefix="/skill-conversations", tags=["skill-conversations"])


# ─── Schemas ────────────────────────────────────────────

class CreateConversationReq(BaseModel):
    skill_id: str
    skill_title: Optional[str] = None
    title: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class AppendMessageReq(BaseModel):
    role: str  # user | assistant | error
    content: str
    raw_data: Optional[Dict[str, Any]] = None
    params_used: Optional[Dict[str, Any]] = None


class UpdateTitleReq(BaseModel):
    title: str


# ─── Endpoints ──────────────────────────────────────────

@router.get("")
def list_conversations(
    skill_id: Optional[str] = Query(None, description="按技能ID过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的技能对话历史。可按 skill_id 过滤。"""
    query = db.query(SkillConversation).filter(
        SkillConversation.user_id == str(current_user.id)
    )
    if skill_id:
        query = query.filter(SkillConversation.skill_id == skill_id)
    query = query.order_by(desc(SkillConversation.updated_at))
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {
        "status": "success",
        "total": total,
        "conversations": [
            {
                "id": str(c.id),
                "skill_id": c.skill_id,
                "skill_title": c.skill_title,
                "title": c.title,
                "params": c.params,
                "message_count": c.message_count,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in items
        ],
    }


@router.post("")
def create_conversation(
    req: CreateConversationReq,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建一条新的技能对话。"""
    conv = SkillConversation(
        user_id=str(current_user.id),
        skill_id=req.skill_id,
        skill_title=req.skill_title,
        title=req.title or "新对话",
        params=req.params or {},
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {
        "status": "success",
        "conversation": {
            "id": str(conv.id),
            "skill_id": conv.skill_id,
            "skill_title": conv.skill_title,
            "title": conv.title,
            "params": conv.params,
            "message_count": 0,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        },
    }


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取对话详情，包含所有消息。"""
    conv = db.query(SkillConversation).filter(
        SkillConversation.id == conversation_id,
        SkillConversation.user_id == str(current_user.id),
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = db.query(SkillMessage).filter(
        SkillMessage.conversation_id == conv.id
    ).order_by(SkillMessage.created_at.asc()).all()
    return {
        "status": "success",
        "conversation": {
            "id": str(conv.id),
            "skill_id": conv.skill_id,
            "skill_title": conv.skill_title,
            "title": conv.title,
            "params": conv.params,
            "message_count": conv.message_count,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        },
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "raw_data": m.raw_data,
                "params_used": m.params_used,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/{conversation_id}/messages")
def append_message(
    conversation_id: str,
    req: AppendMessageReq,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向对话追加一条消息（用户输入或AI回复）。"""
    conv = db.query(SkillConversation).filter(
        SkillConversation.id == conversation_id,
        SkillConversation.user_id == str(current_user.id),
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msg = SkillMessage(
        conversation_id=conv.id,
        role=req.role,
        content=req.content,
        raw_data=req.raw_data,
        params_used=req.params_used,
    )
    db.add(msg)

    # 更新对话计数和时间
    conv.message_count = (conv.message_count or 0) + 1

    # 如果是第一条用户消息且标题还是默认的，更新标题
    if req.role == "user" and conv.title in (None, "", "新对话"):
        conv.title = req.content[:40] + ("..." if len(req.content) > 40 else "")

    db.commit()
    db.refresh(msg)
    return {
        "status": "success",
        "message": {
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "raw_data": msg.raw_data,
            "params_used": msg.params_used,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }


@router.patch("/{conversation_id}/title")
def update_title(
    conversation_id: str,
    req: UpdateTitleReq,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新对话标题。"""
    conv = db.query(SkillConversation).filter(
        SkillConversation.id == conversation_id,
        SkillConversation.user_id == str(current_user.id),
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    conv.title = req.title[:200]
    db.commit()
    return {"status": "success", "title": conv.title}


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除对话及其所有消息。"""
    conv = db.query(SkillConversation).filter(
        SkillConversation.id == conversation_id,
        SkillConversation.user_id == str(current_user.id),
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    # 先删消息
    db.query(SkillMessage).filter(
        SkillMessage.conversation_id == conv.id
    ).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()
    return {"status": "success"}
