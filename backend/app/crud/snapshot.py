import json
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.snapshot import CanvasSnapshot


def create_snapshot(db: Session, canvas_id: uuid.UUID, data: dict, label: str = "") -> CanvasSnapshot:
    snapshot = CanvasSnapshot(canvas_id=canvas_id, data=data, label=label)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_snapshot(db: Session, snapshot_id: uuid.UUID) -> Optional[CanvasSnapshot]:
    return db.query(CanvasSnapshot).filter(CanvasSnapshot.id == snapshot_id).first()


def get_snapshots_by_canvas(db: Session, canvas_id: uuid.UUID, limit: int = 20) -> List[CanvasSnapshot]:
    return db.query(CanvasSnapshot).filter(
        CanvasSnapshot.canvas_id == canvas_id
    ).order_by(CanvasSnapshot.created_at.desc()).limit(limit).all()


def delete_snapshot(db: Session, snapshot_id: uuid.UUID) -> bool:
    snap = db.query(CanvasSnapshot).filter(CanvasSnapshot.id == snapshot_id).first()
    if not snap:
        return False
    db.delete(snap)
    db.commit()
    return True
