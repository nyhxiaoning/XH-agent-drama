"""
把短剧会话转换成画布结构（节点 + 连线），并提供事务/布局支持。
"""
import logging
from typing import Dict, Any, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud import canvas as crud_canvas
from app.crud import node as crud_node
from app.crud import edge as crud_edge
from app.schemas.canvas import CanvasCreate
from app.schemas.node import NodeCreate
from app.schemas.edge import EdgeCreate
from app.models.node import NodeType
from app.models.edge import EdgeType

logger = logging.getLogger(__name__)


def _replace_char_codes(text: str, char_name_map: Dict[str, str]) -> str:
    """把提示词里的 char_id（C001/C002 等）替换为角色真实姓名。"""
    if not text:
        return text
    result = text
    for char_id, name in char_name_map.items():
        if not char_id or not name:
            continue
        # 兼容 C001: / C001、/ C001） 等上下文
        result = result.replace(f"{char_id}:", f"{name}:")
        result = result.replace(f"{char_id}：", f"{name}：")
        result = result.replace(f" {char_id} ", f" {name} ")
        result = result.replace(f"({char_id})", f"({name})")
        result = result.replace(f"（{char_id}）", f"（{name}）")
        result = result.replace(f"{char_id}'s", f"{name}'s")
        result = result.replace(f"{char_id}’s", f"{name}’s")
        # 兜底：单独出现的 char_id
        result = result.replace(char_id, name)
    return result


def compute_layout(
    characters: List[Dict[str, Any]],
    scenes: List[Dict[str, Any]],
    storyboards: List[Dict[str, Any]],
    base_x: int = 100,
    base_y: int = 150,
    col_gap: int = 420,
    row_gap: int = 240,
) -> Dict[str, Tuple[int, int]]:
    """
    简单分层布局：
      第 0 列：剧本
      第 1 列：角色（按出场顺序）
      第 2 列：场景
      第 3 列：分镜（按集/场分组）
      第 4 列：视频（与分镜一一对应）
    """
    positions: Dict[str, Tuple[int, int]] = {}
    positions["script"] = (base_x, base_y)

    # 角色：第 1 列
    for i, char in enumerate(characters):
        positions[f"char_{char.get('char_id')}"] = (base_x + col_gap, base_y + i * row_gap)

    # 场景：第 2 列
    for i, scene in enumerate(scenes):
        positions[f"scene_{scene.get('scene_id')}"] = (base_x + col_gap * 2, base_y + i * row_gap)

    # 分镜：按 episode/scene 分组，每组内竖排，组间留空
    episode_groups: Dict[str, List[Dict[str, Any]]] = {}
    for sb in storyboards:
        ep = str(sb.get("episode_num", sb.get("linked_scene_id", "default")))
        episode_groups.setdefault(ep, []).append(sb)

    sb_idx = 0
    for ep, group in sorted(episode_groups.items()):
        for j, sb in enumerate(group):
            x = base_x + col_gap * 3
            y = base_y + sb_idx * row_gap
            positions[f"sb_{sb.get('storyboard_id')}"] = (x, y)
            positions[f"video_{sb.get('storyboard_id')}"] = (x + col_gap, y)
            sb_idx += 1

    return positions


def build_canvas_from_session(
    db: Session,
    session: Dict[str, Any],
    canvas_id: UUID = None,
    base_x: int = 100,
    base_y: int = 150,
    user_id: str = None,
) -> Dict[str, Any]:
    """
    创建画布结构（节点 + 连线）。
    调用方负责事务提交/回滚；本函数只 add 不 commit。
    """
    script = session.get("script") or {}
    character_data = session.get("character") or {}
    scene_data = session.get("scene") or {}
    assets = session.get("assets") or {"characters": [], "scenes": []}
    characters = character_data.get("characters") if character_data else assets.get("characters", [])
    scenes = scene_data.get("scenes") if scene_data else assets.get("scenes", [])
    storyboard = session.get("storyboard") or {"storyboards": []}
    if isinstance(storyboard, list):
        storyboard = {"storyboards": storyboard}
    storyboards = storyboard.get("storyboards", [])

    video_plan = session.get("video_plan") or {}
    video_plan_videos = video_plan.get("videos", []) if isinstance(video_plan, dict) else []
    video_prompt_map = {v.get("storyboard_id"): v.get("final_video_prompt") for v in video_plan_videos if v.get("storyboard_id")}
    # P0：透传 VideoComposerAgent 新增的 negative_prompt / lip_sync_target / generation_params
    video_meta_map = {
        v.get("storyboard_id"): v
        for v in video_plan_videos
        if v.get("storyboard_id")
    }

    locked_assets = session.get("locked_assets", [])
    asset_ids = session.get("asset_ids", [])

    # 角色 char_id -> 姓名映射，用于把 C001/C002 等代码替换为真实姓名
    char_name_map = {c.get("char_id"): (c.get("name") or c.get("char_id")) for c in characters if c.get("char_id")}

    # 画布名称：优先从编剧产出（full_script/screenwriter）中取实际项目标题，
    # 剧本上传模式下 script.project_title 只是占位符"用户上传剧本"
    full_script = session.get("full_script") or session.get("screenwriter") or {}
    screenplay = full_script.get("screenplay", {}) if isinstance(full_script, dict) else {}
    project_title = (
        screenplay.get("project_title")
        or full_script.get("project_title")
        or script.get("project_title")
        or "AI短剧"
    )

    # 画布
    if canvas_id:
        canvas = crud_canvas.get_canvas(db, canvas_id)
        if not canvas:
            raise ValueError("画布不存在")
    else:
        canvas_in = CanvasCreate(
            name=project_title + "的创作画布",
            description=(script.get("source_prompt", "") or "")[:200],
        )
        extra = {"user_id": str(user_id)} if user_id else None
        canvas = crud_canvas.create_canvas(db, canvas_in, commit=False, extra_data=extra)

    # 将锁定资产关联到画布
    for aid in asset_ids:
        try:
            crud_asset = __import__("app.crud.asset", fromlist=["update_asset_canvas_id"]).update_asset_canvas_id
            crud_asset(db, UUID(aid), canvas.id, commit=False)
        except Exception:
            logger.warning("[canvas_builder] 更新 asset canvas_id 失败: %s", aid, exc_info=True)

    # 布局
    positions = compute_layout(characters, scenes, storyboards, base_x=base_x, base_y=base_y)
    node_id_map: Dict[str, UUID] = {}
    created_nodes: List[Any] = []

    def _add_node(key: str, node_in: NodeCreate):
        x, y = positions.get(key, (base_x, base_y))
        # 通过 model_copy 修改坐标
        node_in_dict = node_in.model_dump(exclude_unset=True)
        node_in_dict["x"] = x
        node_in_dict["y"] = y
        node = crud_node.create_node(db, NodeCreate(**node_in_dict), commit=False)
        node_id_map[key] = node.id
        created_nodes.append(node)
        return node

    # 剧本节点
    _add_node("script", NodeCreate(
        canvas_id=canvas.id,
        node_type=NodeType.SCRIPT,
        title=script.get("project_title", "剧本"),
        prompt=script.get("source_prompt", ""),
        config={"script": script},
    ))

    # 角色节点
    for char in characters:
        locked = next((la for la in locked_assets if la.get("char_id") == char.get("char_id")), None)
        char_config = {
            "char_id": char.get("char_id"),
            "role": char.get("role"),
            "visual_anchor": char.get("visual_anchor", ""),
            "immutable_features": char.get("immutable_features", []),
        }
        if locked:
            char_config["asset_id"] = locked.get("asset_id")
        _add_node(f"char_{char.get('char_id')}", NodeCreate(
            canvas_id=canvas.id,
            node_type=NodeType.CHARACTER,
            title=char.get("name", "角色"),
            prompt=char.get("base_prompt", ""),
            style="",  # visual_anchor 可能很长，存到 config 中，避免 style 字段超 varchar(100)
            result_url=locked.get("asset_file_url") if locked else None,
            config=char_config,
        ))

    # 场景节点
    for scene in scenes:
        locked = next((la for la in locked_assets if la.get("scene_id") == scene.get("scene_id")), None)
        _add_node(f"scene_{scene.get('scene_id')}", NodeCreate(
            canvas_id=canvas.id,
            node_type=NodeType.SCENE,
            title=scene.get("name", "场景"),
            prompt=scene.get("base_prompt", ""),
            result_url=locked.get("asset_file_url") if locked else None,
            config={"scene_id": scene.get("scene_id"), "asset_id": locked.get("asset_id")} if locked else {"scene_id": scene.get("scene_id")},
        ))

    # 分镜节点
    for sb in storyboards:
        linked_chars = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
        linked_scene = sb.get("linked_scene_id")
        ref_asset_ids = []
        ref_images = []
        for cid in linked_chars:
            la = next((la for la in locked_assets if la.get("type") == "character" and la.get("char_id") == cid), None)
            if la and la.get("asset_id"):
                ref_asset_ids.append(la["asset_id"])
            if la and la.get("asset_file_url"):
                ref_images.append(la["asset_file_url"])
        scene_la = next((la for la in locked_assets if la.get("type") == "scene" and la.get("scene_id") == linked_scene), None)
        if scene_la and scene_la.get("asset_id"):
            ref_asset_ids.append(scene_la["asset_id"])
        if scene_la and scene_la.get("asset_file_url"):
            ref_images.append(scene_la["asset_file_url"])

        sb_id = sb.get("storyboard_id", "")
        sb_display_id = sb_id.replace("SB_", "")
        image_prompt = _replace_char_codes(sb.get("final_image_prompt") or "", char_name_map)
        video_prompt = _replace_char_codes(sb.get("final_video_prompt") or "", char_name_map)

        _add_node(f"sb_{sb_id}", NodeCreate(
            canvas_id=canvas.id,
            node_type=NodeType.STORYBOARD,
            title=f"分镜 {sb_display_id}",
            prompt=image_prompt or video_prompt,
            config={
                "storyboard_id": sb_id,
                "prev_storyboard_id": sb.get("prev_storyboard_id"),
                "shot_type": sb.get("shot_type"),
                "camera_movement": sb.get("camera_movement"),
                "composition": sb.get("composition"),
                "duration_seconds": sb.get("duration_seconds"),
                "final_image_prompt": image_prompt,
                "final_video_prompt": video_prompt,
                "visual_continuity": sb.get("visual_continuity"),
                "transition_from_prev": sb.get("transition_from_prev"),
                "reference_asset_ids": ref_asset_ids,
                "reference_images": ref_images,
                "linked_char_ids": linked_chars,
                "linked_scene_id": linked_scene,
            },
        ))

    # 视频节点
    for sb in storyboards:
        sb_id = sb.get("storyboard_id")
        sb_display_id = (sb_id or "").replace("SB_", "")
        # 视频提示词仅由 VideoComposerAgent 产出；分镜 Agent 不再输出 final_video_prompt
        rewritten_prompt = video_prompt_map.get(sb_id)
        prompt = _replace_char_codes(rewritten_prompt or "", char_name_map)
        # P0：透传负面提示词、口型锚点、生成参数（Seedance 枚举）
        video_meta = video_meta_map.get(sb_id) or {}
        negative_prompt = _replace_char_codes(video_meta.get("negative_prompt") or "", char_name_map)
        lip_sync_target = video_meta.get("lip_sync_target")
        generation_params = video_meta.get("generation_params") or {}
        _add_node(f"video_{sb_id}", NodeCreate(
            canvas_id=canvas.id,
            node_type=NodeType.VIDEO,
            title=f"视频 {sb_display_id}",
            prompt=prompt,
            config={
                "storyboard_id": sb_id,
                "check_status": "pending",
                "final_video_prompt": prompt,
                "negative_prompt": negative_prompt,
                "lip_sync_target": lip_sync_target,
                "generation_params": generation_params,
                "visual_continuity": sb.get("visual_continuity"),
                "transition_from_prev": sb.get("transition_from_prev"),
                "prev_storyboard_id": sb.get("prev_storyboard_id"),
                "linked_char_ids": sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else []),
                "linked_scene_id": sb.get("linked_scene_id"),
                "reference_asset_ids": [],
                "reference_images": [],
            },
        ))

    # 清理旧边
    crud_edge.delete_edges_by_canvas(db, canvas.id, exclude_default=True, commit=False)

    # 边
    seen: set = set()
    edges: List[EdgeCreate] = []

    def _add_edge(src_key: str, tgt_key: str, edge_type: EdgeType, label: str):
        if src_key not in node_id_map or tgt_key not in node_id_map:
            return
        src_id = node_id_map[src_key]
        tgt_id = node_id_map[tgt_key]
        key = (str(src_id), str(tgt_id), edge_type)
        if key in seen:
            return
        seen.add(key)
        edges.append(EdgeCreate(
            canvas_id=canvas.id,
            source_node_id=src_id,
            target_node_id=tgt_id,
            edge_type=edge_type,
            label=label,
        ))

    for char in characters:
        _add_edge("script", f"char_{char.get('char_id')}", EdgeType.REFERENCE, "角色")
    for scene in scenes:
        _add_edge("script", f"scene_{scene.get('scene_id')}", EdgeType.REFERENCE, "场景")
    for sb in storyboards:
        sb_key = f"sb_{sb.get('storyboard_id')}"
        linked_chars = sb.get("linked_char_ids") or ([sb.get("linked_char_id")] if sb.get("linked_char_id") else [])
        linked_scene = sb.get("linked_scene_id")
        for cid in linked_chars:
            _add_edge(f"char_{cid}", sb_key, EdgeType.SEQUENCE, "出镜")
        if linked_scene:
            _add_edge(f"scene_{linked_scene}", sb_key, EdgeType.SEQUENCE, "取景")

    # 相邻分镜顺序
    for sb in storyboards:
        prev_id = sb.get("prev_storyboard_id")
        cur_id = sb.get("storyboard_id")
        if prev_id and cur_id:
            _add_edge(f"sb_{prev_id}", f"sb_{cur_id}", EdgeType.SEQUENCE, "上一镜")

    # 分镜 → 视频
    for sb in storyboards:
        sb_id = sb.get("storyboard_id")
        _add_edge(f"sb_{sb_id}", f"video_{sb_id}", EdgeType.SEQUENCE, "生成")

    created_edges = crud_edge.bulk_create_edges(db, edges, commit=False)

    return {
        "canvas": canvas,
        "node_id_map": node_id_map,
        "created_nodes": created_nodes,
        "created_edges": created_edges,
        "edge_count": len(created_edges),
        "node_count": len(created_nodes),
        "character_nodes": [node_id_map.get(f"char_{c.get('char_id')}") for c in characters],
        "scene_nodes": [node_id_map.get(f"scene_{s.get('scene_id')}") for s in scenes],
        "storyboard_nodes": [node_id_map.get(f"sb_{sb.get('storyboard_id')}") for sb in storyboards],
        "video_nodes": [node_id_map.get(f"video_{sb.get('storyboard_id')}") for sb in storyboards],
    }
