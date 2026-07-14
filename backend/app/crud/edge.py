from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.edge import Edge
from app.schemas.edge import EdgeCreate, EdgeUpdate


def create_edge(db: Session, edge_in: EdgeCreate, commit: bool = True) -> Edge:
    edge = Edge(**edge_in.model_dump(exclude_unset=True))
    db.add(edge)
    if commit:
        db.commit()
        db.refresh(edge)
    else:
        db.flush()
    return edge


def bulk_create_edges(db: Session, edges_in: List[EdgeCreate], commit: bool = True) -> List[Edge]:
    """批量创建边；commit=False 时由调用方统一提交。"""
    if not edges_in:
        return []
    edges = [Edge(**e.model_dump(exclude_unset=True)) for e in edges_in]
    db.add_all(edges)
    if commit:
        db.commit()
        for e in edges:
            db.refresh(e)
    else:
        # 事务内创建时需要 flush 才能拿到 default UUID
        db.flush()
    return edges


def get_edge(db: Session, edge_id: UUID) -> Optional[Edge]:
    return db.query(Edge).filter(Edge.id == edge_id).first()


def get_edges_by_canvas(db: Session, canvas_id: UUID) -> List[Edge]:
    return db.query(Edge).filter(Edge.canvas_id == canvas_id).order_by(Edge.created_at).all()


def update_edge(db: Session, edge: Edge, edge_in: EdgeUpdate) -> Edge:
    update_data = edge_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(edge, field, value)
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


def delete_edge(db: Session, edge_id: UUID) -> bool:
    edge = db.query(Edge).filter(Edge.id == edge_id).first()
    if not edge:
        return False
    db.delete(edge)
    db.commit()
    return True


def delete_edges_by_canvas(db: Session, canvas_id: UUID, exclude_default: bool = False, commit: bool = True) -> int:
    """删除指定画布的所有边（或排除 default 类型）。返回删除条数。"""
    q = db.query(Edge).filter(Edge.canvas_id == canvas_id)
    if exclude_default:
        from app.models.edge import EdgeType
        q = q.filter(Edge.edge_type != EdgeType.DEFAULT)
    count = q.count()
    q.delete(synchronize_session=False)
    if commit:
        db.commit()
    return count
