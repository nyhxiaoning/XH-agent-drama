from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.node import Node, NodeStatus
from app.schemas.node import NodeCreate, NodeUpdate


def create_node(db: Session, node_in: NodeCreate, commit: bool = True) -> Node:
    node = Node(**node_in.model_dump(exclude_unset=True))
    db.add(node)
    if commit:
        db.commit()
        db.refresh(node)
    else:
        # 事务内创建时需要 flush 才能拿到 default UUID
        db.flush()
    return node


def get_node(db: Session, node_id: UUID) -> Optional[Node]:
    return db.query(Node).filter(Node.id == node_id).first()


def get_nodes_by_canvas(db: Session, canvas_id: UUID) -> List[Node]:
    return db.query(Node).filter(Node.canvas_id == canvas_id).order_by(Node.created_at).all()


# ─── #18 批量操作优化 ──────────────────────────────────

def bulk_create_nodes(db: Session, nodes_in: List[NodeCreate], commit: bool = True) -> List[Node]:
    """#18 批量创建节点；commit=False 时由调用方统一提交。"""
    if not nodes_in:
        return []
    nodes = [Node(**n.model_dump(exclude_unset=True)) for n in nodes_in]
    db.add_all(nodes)
    if commit:
        db.commit()
        for n in nodes:
            db.refresh(n)
    else:
        db.flush()
    return nodes


def bulk_update_status(db: Session, updates: List[dict], commit: bool = True) -> int:
    """#18 批量更新节点状态。

    updates: [{ 'node_id': UUID, 'status': NodeStatus, 'progress': int, ... }]
    """
    if not updates:
        return 0
    node_ids = [u['node_id'] for u in updates]
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    node_map = {str(n.id): n for n in nodes}
    count = 0
    for u in updates:
        n = node_map.get(str(u['node_id']))
        if not n:
            continue
        if 'status' in u:
            n.status = u['status']
        if 'progress' in u:
            n.progress = u['progress']
        if 'error_msg' in u:
            n.error_msg = u['error_msg']
        if 'result_url' in u:
            n.result_url = u['result_url']
        count += 1
    if count > 0 and commit:
        db.commit()
    return count


def update_node(db: Session, node: Node, node_in: NodeUpdate) -> Node:
    update_data = node_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(node, field, value)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def update_node_status(db: Session, node_id: UUID, status: NodeStatus, progress: int = 0, error_msg: Optional[str] = None, result_url: Optional[str] = None) -> Optional[Node]:
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        return None
    changed = False
    if node.status != status:
        node.status = status
        changed = True
    if progress != node.progress:
        node.progress = progress
        changed = True
    if error_msg is not None and error_msg != node.error_msg:
        node.error_msg = error_msg
        changed = True
    if result_url is not None and result_url != node.result_url:
        node.result_url = result_url
        changed = True
    if changed:
        db.commit()
        db.refresh(node)
    return node


def delete_node(db: Session, node_id: UUID) -> bool:
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        return False
    db.delete(node)
    db.commit()
    return True


def batch_update_positions(db: Session, positions: List[dict]) -> int:
    if not positions:
        return 0
    node_ids = [pos["id"] for pos in positions]
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    node_map = {str(n.id): n for n in nodes}
    count = 0
    for pos in positions:
        n = node_map.get(pos["id"])
        if n:
            n.x = pos.get("x", n.x)
            n.y = pos.get("y", n.y)
            count += 1
    if count > 0:
        db.commit()
    return count
