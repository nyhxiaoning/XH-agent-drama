"""
P6: 会话版本管理 - 快照与回退。

在关键节点（script_ready, character_done, scene_done, storyboard_done, video_done）
自动创建会话快照，支持版本回退。
"""
import logging
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 最多保留的版本数
MAX_VERSIONS = 20

# 触发快照的阶段
SNAPSHOT_STAGES = [
    "script_ready",
    "character_done",
    "scene_done",
    "storyboard_done",
    "video_done",
    "review_pass",
]


def create_snapshot(
    session: Dict[str, Any],
    stage: str,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """创建会话快照。

    Args:
        session: 当前会话状态
        stage: 触发快照的阶段
        label: 可选标签

    Returns:
        快照字典
    """
    # 深拷贝关键数据，避免引用问题
    snapshot_data = {
        "script": copy.deepcopy(session.get("script")),
        "character_assets": copy.deepcopy(session.get("character_assets")),
        "scene_assets": copy.deepcopy(session.get("scene_assets")),
        "storyboard_data": copy.deepcopy(session.get("storyboard_data")),
        "video_plan": copy.deepcopy(session.get("video_plan")),
        "current_stage": session.get("current_stage", ""),
        "status": session.get("status", ""),
    }

    return {
        "version_id": f"v_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{stage}",
        "stage": stage,
        "label": label or stage,
        "timestamp": datetime.utcnow().isoformat(),
        "data": snapshot_data,
    }


def add_version_to_session(
    session: Dict[str, Any],
    stage: str,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """向会话的 version_history 添加快照。"""
    if "version_history" not in session:
        session["version_history"] = []

    snapshot = create_snapshot(session, stage, label)
    session["version_history"].append(snapshot)

    # 限制版本数
    if len(session["version_history"]) > MAX_VERSIONS:
        session["version_history"] = session["version_history"][-MAX_VERSIONS:]

    logger.info(
        "[VersionManager] 快照已创建: %s (stage=%s, total=%d)",
        snapshot["version_id"],
        stage,
        len(session["version_history"]),
    )
    return session


def should_snapshot(stage: str) -> bool:
    """判断当前阶段是否需要创建快照。"""
    return stage in SNAPSHOT_STAGES


def restore_version(
    session: Dict[str, Any],
    version_id: str,
) -> Optional[Dict[str, Any]]:
    """回退到指定版本。

    Args:
        session: 当前会话
        version_id: 要回退到的版本 ID

    Returns:
        更新后的 session，或 None 如果版本不存在
    """
    version_history = session.get("version_history", [])
    target = None
    for v in version_history:
        if v["version_id"] == version_id:
            target = v
            break

    if not target:
        logger.warning("[VersionManager] 版本不存在: %s", version_id)
        return None

    data = target["data"]

    # 回退前，先保存当前状态为一个新快照（以便撤销回退）
    add_version_to_session(session, "pre_restore", label=f"回退前快照({datetime.utcnow().strftime('%H:%M:%S')})")

    # 恢复数据
    session["script"] = copy.deepcopy(data.get("script"))
    session["character_assets"] = copy.deepcopy(data.get("character_assets"))
    session["scene_assets"] = copy.deepcopy(data.get("scene_assets"))
    session["storyboard_data"] = copy.deepcopy(data.get("storyboard_data"))
    session["video_plan"] = copy.deepcopy(data.get("video_plan"))
    session["current_stage"] = data.get("current_stage", "")
    session["status"] = data.get("status", "")

    logger.info("[VersionManager] 已回退到版本: %s", version_id)
    return session


def list_versions(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """列出会话的所有版本。"""
    version_history = session.get("version_history", [])
    return [
        {
            "version_id": v["version_id"],
            "stage": v["stage"],
            "label": v.get("label", v["stage"]),
            "timestamp": v["timestamp"],
        }
        for v in version_history
    ]


def diff_versions(
    session: Dict[str, Any],
    version_id_a: str,
    version_id_b: str,
) -> Dict[str, Any]:
    """对比两个版本的差异（简化版，只对比顶层 key）。"""
    version_history = session.get("version_history", [])
    va = next((v for v in version_history if v["version_id"] == version_id_a), None)
    vb = next((v for v in version_history if v["version_id"] == version_id_b), None)

    if not va or not vb:
        return {"error": "版本不存在"}

    da = va["data"]
    db = vb["data"]

    diff = {}
    for key in set(list(da.keys()) + list(db.keys())):
        val_a = da.get(key)
        val_b = db.get(key)
        if val_a != val_b:
            diff[key] = {
                "a": str(val_a)[:500] if val_a else None,
                "b": str(val_b)[:500] if val_b else None,
            }

    return diff
