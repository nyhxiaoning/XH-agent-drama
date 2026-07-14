from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.models.node import NodeType, NodeStatus


class NodeBase(BaseModel):
    node_type: NodeType = NodeType.SCRIPT
    title: Optional[str] = ""
    x: float = 0.0
    y: float = 0.0
    width: Optional[float] = 240.0
    height: Optional[float] = 160.0
    prompt: Optional[str] = None
    style: Optional[str] = None
    config: Optional[Dict[str, Any]] = {}
    result_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


class NodeCreate(NodeBase):
    canvas_id: UUID


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    node_type: Optional[NodeType] = None
    status: Optional[NodeStatus] = None
    progress: Optional[int] = None
    prompt: Optional[str] = None
    style: Optional[str] = None
    result_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    error_msg: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class NodeInDB(NodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    canvas_id: UUID
    status: NodeStatus
    progress: int
    result_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    error_msg: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class NodeAction(BaseModel):
    action: str = "generate"
    prompt: Optional[str] = None
    style: Optional[str] = None
    count: Optional[int] = 1
    config: Optional[Dict[str, Any]] = None
