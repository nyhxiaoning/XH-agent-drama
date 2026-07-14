from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_current_active_user, require_canvas_access
from app.core.database import get_db
from app.crud import snapshot as crud_snapshot
from app.crud import canvas as crud_canvas, node as crud_node, edge as crud_edge
from app.models.snapshot import CanvasSnapshot
from app.models.user import User
from app import models

router = APIRouter(prefix="/canvases", tags=["snapshots"])


def _serialize_canvas(db: Session, canvas_id: UUID) -> dict:
    canvas = crud_canvas.get_canvas(db, canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="画布不存在")
    nodes = crud_node.get_nodes_by_canvas(db, canvas_id)
    edges = crud_edge.get_edges_by_canvas(db, canvas_id)
    return {
        "canvas": {
            "name": canvas.name,
            "description": canvas.description,
            "meta": canvas.meta,
        },
        "nodes": [
            {
                "id": str(n.id), "node_type": n.node_type.value, "title": n.title,
                "x": n.x, "y": n.y, "width": n.width, "height": n.height,
                "prompt": n.prompt, "style": n.style, "config": n.config,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": str(e.id), "source_node_id": str(e.source_node_id),
                "target_node_id": str(e.target_node_id), "edge_type": e.edge_type.value,
                "label": e.label, "config": e.config,
            }
            for e in edges
        ],
    }


@router.post("/{canvas_id}/snapshots", status_code=201)
def create_snapshot(
    canvas_id: UUID,
    label: str = "",
    db: Session = Depends(get_db),
    canvas=Depends(require_canvas_access),
):
    data = _serialize_canvas(db, canvas_id)
    snap = crud_snapshot.create_snapshot(db, canvas_id, data, label=label)
    return {"id": str(snap.id), "canvas_id": str(snap.canvas_id), "label": snap.label, "created_at": snap.created_at}


@router.get("/{canvas_id}/snapshots")
def list_snapshots(
    canvas_id: UUID,
    limit: int = 20,
    db: Session = Depends(get_db),
    canvas=Depends(require_canvas_access),
):
    snaps = crud_snapshot.get_snapshots_by_canvas(db, canvas_id, limit=limit)
    return [
        {"id": str(s.id), "label": s.label, "created_at": s.created_at}
        for s in snaps
    ]


@router.post("/{canvas_id}/snapshots/{snapshot_id}/restore", status_code=200)
def restore_snapshot(
    canvas_id: UUID,
    snapshot_id: UUID,
    db: Session = Depends(get_db),
    canvas=Depends(require_canvas_access),
):
    snap = crud_snapshot.get_snapshot(db, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="快照不存在")
    if str(snap.canvas_id) != str(canvas_id):
        raise HTTPException(status_code=400, detail="快照不属于该画布")

    data = snap.data
    nodes = crud_node.get_nodes_by_canvas(db, canvas_id)
    edges = crud_edge.get_edges_by_canvas(db, canvas_id)
    for e in edges:
        db.delete(e)
    for n in nodes:
        db.delete(n)

    canvas = crud_canvas.get_canvas(db, canvas_id)
    c_data = data.get("canvas", {})
    if "name" in c_data:
        canvas.name = c_data["name"]
    if "description" in c_data:
        canvas.description = c_data["description"]
    if "meta" in c_data:
        canvas.meta = c_data["meta"]
    db.add(canvas)

    id_map = {}
    for n_data in data.get("nodes", []):
        old_id = n_data.pop("id", None)
        from app.models.node import Node, NodeType, NodeStatus
        node = Node(canvas_id=canvas_id)
        for k, v in n_data.items():
            if k == "node_type":
                try:
                    v = NodeType(v)
                except Exception:
                    v = NodeType.SCRIPT
            setattr(node, k, v)
        node.status = NodeStatus.PENDING
        db.add(node)
        db.flush()
        if old_id:
            id_map[old_id] = str(node.id)

    for e_data in data.get("edges", []):
        e_data.pop("id", None)
        from app.models.edge import Edge, EdgeType
        edge = Edge(canvas_id=canvas_id)
        src_old = str(e_data.pop("source_node_id", ""))
        tgt_old = str(e_data.pop("target_node_id", ""))
        edge.source_node_id = id_map.get(src_old, src_old)
        edge.target_node_id = id_map.get(tgt_old, tgt_old)
        for k, v in e_data.items():
            if k == "edge_type":
                try:
                    v = EdgeType(v)
                except Exception:
                    v = EdgeType.DEFAULT
            setattr(edge, k, v)
        db.add(edge)

    db.commit()
    return {"message": "画布已恢复", "snapshot_id": str(snapshot_id)}


@router.delete("/{canvas_id}/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(
    canvas_id: UUID,
    snapshot_id: UUID,
    db: Session = Depends(get_db),
    canvas=Depends(require_canvas_access),
):
    snap = crud_snapshot.get_snapshot(db, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="快照不存在")
    if str(snap.canvas_id) != str(canvas_id):
        raise HTTPException(status_code=400, detail="快照不属于该画布")
    crud_snapshot.delete_snapshot(db, snapshot_id)
    return None
