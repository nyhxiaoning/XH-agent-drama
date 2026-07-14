from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.models.edge import EdgeType


class EdgeBase(BaseModel):
    source_node_id: UUID
    target_node_id: UUID
    edge_type: EdgeType = EdgeType.DEFAULT
    label: Optional[str] = None
    config: Optional[Dict[str, Any]] = {}


class EdgeCreate(EdgeBase):
    canvas_id: UUID


class EdgeUpdate(BaseModel):
    edge_type: Optional[EdgeType] = None
    label: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class EdgeInDB(EdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    canvas_id: UUID
    created_at: datetime
    updated_at: datetime
