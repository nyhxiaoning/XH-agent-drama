from typing import List
from app.schemas.canvas import CanvasCreate, CanvasUpdate, CanvasInDB
from app.schemas.node import NodeCreate, NodeUpdate, NodeInDB, NodeAction
from app.schemas.edge import EdgeCreate, EdgeUpdate, EdgeInDB
from app.schemas.task import TaskInDB, TaskList
from app.schemas.asset import (
    AssetCreate, AssetUpdate, AssetInDB, AssetType,
    AgentRequest, AgentStepEvent, NodeContext
)


class CanvasDetail(CanvasInDB):
    nodes: List[NodeInDB] = []
    edges: List[EdgeInDB] = []
