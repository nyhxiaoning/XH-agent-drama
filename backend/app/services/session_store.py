"""
SessionStore: AI 创作会话存储抽象。

当前默认实现：SQLitePersistentSessionStore（复用 xiaoyunque.db）。
未来可无缝替换为 RedisSessionStore。
"""
import json
import uuid
import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session, sessionmaker

from app.models.session import AgentSession

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 24 * 3600  # 24h
CLEANUP_EVERY_SECONDS = 3600
LOCK_TIMEOUT_SECONDS = 300  # 会话锁自动超时时间：5 分钟


class SessionStore(ABC):
    """会话存储接口。"""

    @abstractmethod
    def create(
        self,
        prompt: str,
        mode: str = "inspiration",
        user_id: Optional[str] = None,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """创建会话，返回 session_id。"""
        ...

    @abstractmethod
    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """读取完整会话字典。"""
        ...

    @abstractmethod
    def acquire_lock(self, session_id: str, owner: str) -> bool:
        """原子加锁：仅当会话未被锁定时成功，返回 True。"""
        ...

    @abstractmethod
    def release_lock(self, session_id: str, owner: str, new_status: Optional[str] = None) -> bool:
        """原子释放锁：仅当锁属于 owner 时成功。"""
        ...

    @abstractmethod
    def save(self, session_id: str, data: Dict[str, Any], lock_owner: Optional[str] = None) -> None:
        """保存完整会话字典。若提供 lock_owner，仅在锁匹配时写入。"""
        ...

    @abstractmethod
    def delete(self, session_id: str) -> None:
        """删除会话。"""
        ...

    @abstractmethod
    def cleanup_expired(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
        """清理过期会话，返回删除数量。"""
        ...


class InMemorySessionStore(SessionStore):
    """内存实现，仅用于测试或单进程无持久化场景。"""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._updated_at: Dict[str, datetime] = {}

    def create(
        self,
        prompt: str,
        mode: str = "inspiration",
        user_id: Optional[str] = None,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        sid = hashlib.sha256(f"{datetime.utcnow().isoformat()}-{uuid.uuid4()}".encode()).hexdigest()[:16]
        data = dict(initial_data or {})
        data.update({
            "id": sid,
            "prompt": prompt,
            "mode": mode,
            "status": "planning",
            "user_id": user_id,
        })
        data.setdefault("messages", [])
        data.setdefault("options", {})
        self._data[sid] = data
        self._updated_at[sid] = datetime.utcnow()
        return sid

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._data.get(session_id)

    def acquire_lock(self, session_id: str, owner: str) -> bool:
        rec = self._data.get(session_id)
        if not rec:
            return False
        if rec.get("_lock_owner") and rec["_lock_owner"] != owner:
            return False
        rec["_lock_owner"] = owner
        self._updated_at[session_id] = datetime.utcnow()
        return True

    def release_lock(self, session_id: str, owner: str, new_status: Optional[str] = None) -> bool:
        rec = self._data.get(session_id)
        if not rec or rec.get("_lock_owner") != owner:
            return False
        rec.pop("_lock_owner", None)
        if new_status:
            rec["status"] = new_status
        self._updated_at[session_id] = datetime.utcnow()
        return True

    def save(self, session_id: str, data: Dict[str, Any], lock_owner: Optional[str] = None) -> None:
        rec = self._data.get(session_id)
        if lock_owner and (not rec or rec.get("_lock_owner") != lock_owner):
            raise RuntimeError(f"会话 {session_id} 锁冲突或已丢失，保存被拒绝")
        self._data[session_id] = dict(data)
        if rec and rec.get("_lock_owner"):
            self._data[session_id]["_lock_owner"] = rec["_lock_owner"]
        self._updated_at[session_id] = datetime.utcnow()

    def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._updated_at.pop(session_id, None)

    def cleanup_expired(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
        cutoff = datetime.utcnow() - timedelta(seconds=ttl_seconds)
        expired = [sid for sid, t in self._updated_at.items() if t < cutoff]
        for sid in expired:
            self.delete(sid)
        return len(expired)


class SQLitePersistentSessionStore(SessionStore):
    """SQLite 持久化实现，每个操作新建一个 DB Session（线程安全）。"""

    def __init__(self, session_factory: sessionmaker):
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def create(
        self,
        prompt: str,
        mode: str = "inspiration",
        user_id: Optional[str] = None,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        sid = hashlib.sha256(f"{datetime.utcnow().isoformat()}-{uuid.uuid4()}".encode()).hexdigest()[:16]
        data = dict(initial_data or {})
        data.update({
            "id": sid,
            "prompt": prompt,
            "mode": mode,
            "status": "planning",
            "user_id": user_id,
        })
        db = self._session()
        try:
            record = AgentSession(
                session_id=sid,
                user_id=user_id,
                status=data.get("status", "planning"),
                prompt=prompt,
                mode=mode,
                data=data,
            )
            db.add(record)
            db.commit()
            return sid
        finally:
            db.close()

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        db = self._session()
        try:
            record = db.query(AgentSession).filter(AgentSession.session_id == session_id).first()
            if not record:
                return None
            # 刷新 updated_at（读也视为活跃）
            record.updated_at = datetime.utcnow()
            db.commit()
            return dict(record.data)
        finally:
            db.close()

    def acquire_lock(self, session_id: str, owner: str) -> bool:
        db = self._session()
        try:
            # 先清理过期锁：lock_version 非空且 updated_at 超过 LOCK_TIMEOUT_SECONDS 的视为僵死锁
            cutoff = datetime.utcnow() - timedelta(seconds=LOCK_TIMEOUT_SECONDS)
            db.query(AgentSession).filter(
                AgentSession.lock_version.isnot(None),
                AgentSession.updated_at < cutoff,
            ).update({"lock_version": None}, synchronize_session=False)

            # 原子加锁：仅当 lock_version 为空或等于 owner 时成功
            updated = db.query(AgentSession).filter(
                AgentSession.session_id == session_id,
                (AgentSession.lock_version.is_(None)) | (AgentSession.lock_version == owner),
            ).update({
                "lock_version": owner,
                "updated_at": datetime.utcnow(),
            }, synchronize_session=False)
            db.commit()
            return updated > 0
        finally:
            db.close()

    def release_lock(self, session_id: str, owner: str, new_status: Optional[str] = None) -> bool:
        db = self._session()
        try:
            values: Dict[str, Any] = {
                "lock_version": None,
                "updated_at": datetime.utcnow(),
            }
            if new_status:
                values["status"] = new_status
            updated = db.query(AgentSession).filter(
                AgentSession.session_id == session_id,
                AgentSession.lock_version == owner,
            ).update(values, synchronize_session=False)
            db.commit()
            return updated > 0
        finally:
            db.close()

    def save(self, session_id: str, data: Dict[str, Any], lock_owner: Optional[str] = None) -> None:
        db = self._session()
        try:
            record = db.query(AgentSession).filter(AgentSession.session_id == session_id).first()
            if not record:
                logger.warning("[SessionStore] save 时未找到会话 %s，尝试创建", session_id)
                record = AgentSession(session_id=session_id)
                db.add(record)
            if lock_owner and record.lock_version != lock_owner:
                raise RuntimeError(f"会话 {session_id} 锁冲突或已丢失，保存被拒绝")
            clean_data = dict(data)
            clean_data.pop("_lock_owner", None)
            record.data = clean_data
            record.status = data.get("status", record.status or "planning")
            record.prompt = data.get("prompt", record.prompt)
            record.mode = data.get("mode", record.mode or "inspiration")
            record.user_id = data.get("user_id", record.user_id)
            record.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

    def delete(self, session_id: str) -> None:
        db = self._session()
        try:
            db.query(AgentSession).filter(AgentSession.session_id == session_id).delete()
            db.commit()
        finally:
            db.close()

    def cleanup_expired(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
        db = self._session()
        try:
            cutoff = datetime.utcnow() - timedelta(seconds=ttl_seconds)
            count = db.query(AgentSession).filter(AgentSession.updated_at < cutoff).delete()
            db.commit()
            return count
        finally:
            db.close()

    def list_recent(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        db = self._session()
        try:
            q = db.query(AgentSession)
            if user_id:
                q = q.filter(AgentSession.user_id == user_id)
            return [dict(r.data) for r in q.order_by(AgentSession.updated_at.desc()).limit(limit).all()]
        finally:
            db.close()


# 全局单例占位，在应用启动时注入具体实现
_store_instance: Optional[SessionStore] = None


def set_store(store: SessionStore) -> None:
    global _store_instance
    _store_instance = store


def get_store() -> SessionStore:
    if _store_instance is None:
        raise RuntimeError("SessionStore 未初始化，请先调用 set_store()")
    return _store_instance
