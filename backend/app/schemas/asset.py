from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.models.asset import AssetType


class AssetBase(BaseModel):
    name: str = "未命名资产"
    asset_type: AssetType = AssetType.IMAGE
    tags: List[str] = []
    description: Optional[str] = None
    meta: Dict[str, Any] = {}
    canvas_id: Optional[UUID] = None


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_type: Optional[AssetType] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    canvas_id: Optional[UUID] = None


class AssetInDB(AssetBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[str] = None
    file_path: str
    file_url: str
    thumbnail_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class AgentRequest(BaseModel):
    pipeline: str = "text_to_image"
    prompt: str
    style: str = "realistic"
    canvas_id: Optional[str] = None
    node_id: Optional[str] = None
    extra: Dict[str, Any] = {}


class AgentStepEvent(BaseModel):
    agent_name: str
    step_name: str
    content: str
    meta: Dict[str, Any] = {}


class NodeContext(BaseModel):
    node_id: str
    node: Optional[Dict[str, Any]] = None
    chat_history: List[Dict[str, Any]] = []
    connected_nodes: List[Dict[str, Any]] = []
    related_assets: List[Dict[str, Any]] = []
