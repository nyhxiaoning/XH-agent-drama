import os
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from typing import List

# ── 文件日志配置 ──────────────────────────────────────────
_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_log_dir, exist_ok=True)
_file_handler = RotatingFileHandler(
    os.path.join(_log_dir, "app.log"),
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.root.addHandler(_file_handler)
logging.root.setLevel(logging.INFO)
# uvicorn / httpx 也输出到文件
for _name in ("uvicorn", "uvicorn.access", "httpx", "app"):
    _lg = logging.getLogger(_name)
    _lg.addHandler(_file_handler)

logger = logging.getLogger(__name__)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from sqlalchemy.orm import Session
from app.core.database import engine, Base, SessionLocal
from app.core.tasks import task_manager, Task, TaskStatus
from app.core.ws import ws_manager
from app.workers.ai_worker import ai_worker
from app.api.v1 import api_router
from app import models
from app.models.node import NodeStatus, NodeType
from app.models.edge import EdgeType
from app.models.asset import Asset, AssetType
from app.models.failed_refund import FailedRefund
from app.crud import node as crud_node
from app.schemas.asset import AssetCreate
from app.services.session_store import set_store, SQLitePersistentSessionStore, DEFAULT_TTL_SECONDS, CLEANUP_EVERY_SECONDS
from app.services import credit_service
import uuid as _uuid


def _is_sqlite() -> bool:
    return "sqlite" in str(engine.url).lower()


def _column_exists(conn, table: str, column: str) -> bool:
    """判断指定表中是否存在某列，兼容 SQLite 与 PostgreSQL。"""
    from sqlalchemy import text
    if _is_sqlite():
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    else:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": column}).fetchall()
        return bool(rows)


def _persist_failed_refund(task, exc: Exception) -> None:
    """退款失败时把记录持久化到 failed_refunds 表，等后台定时重试。"""
    try:
        refund_db = SessionLocal()
        try:
            refund_db.add(FailedRefund(
                user_id=_uuid.UUID(task.user_id),
                amount=task.cost,
                reason=f"{task.task_type}_refund",
                ref_id=task.node_id,
                description=f"任务失败退还：{task.error or '未知错误'}",
                last_error=str(exc),
            ))
            refund_db.commit()
        finally:
            refund_db.close()
    except Exception:
        logger.exception("[credit] 持久化失败退款记录失败 task=%s", task.id)


def _migrate_assets_canvas_id():
    """兼容旧数据库：为 assets 表添加缺失列（若不存在）。"""
    from sqlalchemy import text
    # 需要检查的列及其 DDL
    asset_columns = [
        ("canvas_id", "ALTER TABLE assets ADD COLUMN canvas_id CHAR(36)"),
        ("meta", "ALTER TABLE assets ADD COLUMN meta JSON"),
        ("tags", "ALTER TABLE assets ADD COLUMN tags JSON"),
        ("thumbnail_url", "ALTER TABLE assets ADD COLUMN thumbnail_url VARCHAR(512)"),
        ("mime_type", "ALTER TABLE assets ADD COLUMN mime_type VARCHAR(100)"),
        ("file_size", "ALTER TABLE assets ADD COLUMN file_size INTEGER"),
        ("width", "ALTER TABLE assets ADD COLUMN width INTEGER"),
        ("height", "ALTER TABLE assets ADD COLUMN height INTEGER"),
        ("duration", "ALTER TABLE assets ADD COLUMN duration INTEGER"),
        ("user_id", "ALTER TABLE assets ADD COLUMN user_id VARCHAR(255)"),
    ]
    for col, ddl in asset_columns:
        try:
            with engine.connect() as conn:
                if not _column_exists(conn, "assets", col):
                    conn.execute(text(ddl))
                    if col == "canvas_id":
                        conn.execute(text("CREATE INDEX ix_assets_canvas_id ON assets (canvas_id)"))
                    elif col == "user_id":
                        conn.execute(text("CREATE INDEX ix_assets_user_id ON assets (user_id)"))
                    conn.commit()
                    logger.info("[migrate] assets.%s 列添加成功", col)
        except Exception:
            logger.exception("[migrate] assets.%s 迁移失败", col)


def _migrate_new_tables():
    """兼容旧数据库：新增用户中心/积分/管理员相关表与字段。

    移除每条 try/except，让异常向上传播触发启动失败（`engine.begin()` 会自动回滚事务）。
    `_column_exists` 检查保留做幂等性，避免重复 ALTER 报错。
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        # 新表由 Base.metadata.create_all 自动创建，这里只处理旧表 ALTER
        if not _column_exists(conn, "users", "avatar_url"):
            conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512)"))
        if not _column_exists(conn, "users", "is_active"):
            conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT true"))
        if not _column_exists(conn, "users", "invited_by"):
            conn.execute(text("ALTER TABLE users ADD COLUMN invited_by CHAR(36)"))
        if not _column_exists(conn, "users", "last_login_at"):
            conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP"))


def _migrate_model_config_tiers():
    """兼容旧数据库：为 model_configs 表添加三档定价列（credits_5s/10s/15s）。

    独立于 _migrate_new_tables 执行，避免因新列迁移失败导致整个启动崩溃。
    """
    from sqlalchemy import text
    for col in ("credits_5s", "credits_10s", "credits_15s"):
        try:
            with engine.connect() as conn:
                if not _column_exists(conn, "model_configs", col):
                    conn.execute(text(f"ALTER TABLE model_configs ADD COLUMN {col} INTEGER DEFAULT 0 NOT NULL"))
                    conn.commit()
                    logger.info("[migrate] model_configs.%s 列添加成功", col)
        except Exception:
            logger.exception("[migrate] model_configs.%s 迁移失败", col)


def _seed_model_configs(db: Session):
    """初始化模型配置种子数据。

    所有模型类型（image/video/llm）均采用白名单管理，
    未在种子列表中的模型启动时自动清理。
    同时强制删除 config.py 中 DEPRECATED_MODELS 列出的废弃模型。
    """
    from app.models.model_config import ModelConfig
    from sqlalchemy import text

    # 系统内置模型白名单（image/video/llm 统一管理）
    seeds = [
        ("gpt-image-2", "gpt-image-2", "image", "OpenAI GPT-Image-2", 10),
        ("gemini-3.1-flash-lite-image", "Gemini 3.1 Flash Lite", "image", "Google Gemini 图片模型 (Nano Banana Lite)", 10),
        ("dall-e-3", "DALL·E 3", "image", "OpenAI DALL·E 3", 10),
        ("doubao-seedream-5-0-pro-260628", "豆包 Seedream 5.0 Pro", "image", "火山引擎豆包 Seedream 5.0 Pro 文生图/图生图模型", 10),
        ("doubao-seedance-2-0-260128", "Seedance 2.0", "video", "火山引擎 Seedance 2.0 标准版", 100),
        ("doubao-seedance-2-0-fast-260128", "Seedance 2.0 Fast", "video", "火山引擎 Seedance 2.0 快速版", 80),
        ("wan2.7-video", "万相视频", "video", "阿里云万相视频模型", 100),
        ("wan2.7-t2v", "万相 T2V", "video", "阿里云万相文生视频模型", 100),
        ("wan2.7-i2v", "万相 I2V", "video", "阿里云万相图生视频模型", 100),
        ("wan2.7-r2v", "万相 R2V", "video", "阿里云万相参考视频模型", 100),
        ("viduq3-turbo", "Vidu Q3 Turbo", "video", "Modelink Vidu Q3 Turbo 视频生成模型（支持文生/图生/参考生/首尾帧）", 100),
        ("gpt-5.6-terra", "GPT-5.6 Terra", "llm", "OpenAI GPT-5.6 Terra 旗舰大模型", 0),
        ("gpt-5.6-luna", "GPT-5.6 Luna", "llm", "OpenAI GPT-5.6 Luna 旗舰大模型", 0),
    ]
    allowed_ids = {model_id for model_id, *_ in seeds}

    # 1. 用原生 SQL 强制删除废弃模型（不依赖 ORM 的 notin_ 逻辑，防止兼容性问题）
    from app.core.config import settings as _settings
    for dep_id in _settings.DEPRECATED_MODELS:
        result = db.execute(text("DELETE FROM model_configs WHERE model_id = :mid"), {"mid": dep_id})
        if result.rowcount > 0:
            logger.info("[seed] 强制删除废弃模型: %s (影响 %d 行)", dep_id, result.rowcount)

    # 2. 只清理废弃模型（DEPRECATED_MODELS），不清理用户在后台手动添加的模型
    #    用户添加的任何模型都保留，重启不会被删
    #    （上面的原生 SQL DELETE 已经做了这一步，这里不再额外清理）

    # 3. 添加缺失的内置模型配置；已存在的保持原样，避免覆盖用户自定义名称/积分
    for model_id, name, mtype, description, credits in seeds:
        existing = db.query(ModelConfig).filter(ModelConfig.model_id == model_id).first()
        if not existing:
            db.add(ModelConfig(
                id=_uuid.uuid4(),
                model_id=model_id,
                name=name,
                type=mtype,
                description=description,
                credits=credits,
            ))
    db.commit()


# 节点类型 → 资产类型映射
_NODE_TYPE_TO_ASSET_TYPE = {
    NodeType.IMAGE: AssetType.IMAGE,
    NodeType.VIDEO: AssetType.VIDEO,
    NodeType.CHARACTER: AssetType.CHARACTER,
    NodeType.SCENE: AssetType.SCENE,
    NodeType.STORYBOARD: AssetType.IMAGE,
    NodeType.SCRIPT: AssetType.IMAGE,
}


def _try_save_asset(db, node, result_url: str, thumbnail_url: str | None, result_type: str, user_id: str | None = None):
    """节点生成成功后自动保存到资产库，关联到节点的画布和用户。"""
    try:
        # 避免重复保存：同一节点同一 url 不重复创建
        existing = db.query(Asset).filter(
            Asset.file_url == result_url,
            Asset.canvas_id == node.canvas_id,
        ).first()
        if existing:
            return

        # 从画布获取 user_id 和 team_id（确保团队画布的资产继承 team_id）
        from app.models.canvas import Canvas
        canvas = db.query(Canvas).filter(Canvas.id == node.canvas_id).first()
        if not user_id and canvas and canvas.user_id:
            user_id = canvas.user_id
        team_id = canvas.team_id if canvas else None

        asset_type = _NODE_TYPE_TO_ASSET_TYPE.get(node.node_type, AssetType.IMAGE)
        cfg = node.config or {}
        meta: dict = {"node_id": str(node.id), "source": "canvas_generate"}
        if node.node_type == NodeType.CHARACTER:
            meta["char_id"] = cfg.get("char_id")
            meta["immutable_features"] = cfg.get("immutable_features", [])
            meta["base_prompt"] = cfg.get("base_prompt")
            meta["visual_anchor"] = cfg.get("visual_anchor")
        elif node.node_type == NodeType.SCENE:
            meta["scene_id"] = cfg.get("scene_id")
            meta["base_prompt"] = cfg.get("base_prompt")
        asset = Asset(
            name=node.title or "生成结果",
            asset_type=asset_type,
            file_url=result_url,
            file_path=result_url,
            thumbnail_url=thumbnail_url or result_url,
            canvas_id=node.canvas_id,
            user_id=user_id,
            team_id=team_id,
            tags=[node.node_type.value, "ai-generated"],
            description=node.prompt or "",
            meta=meta,
        )
        db.add(asset)
        db.commit()
    except Exception:
        logger.exception("[asset] 自动保存资产失败 node=%s url=%s", node.id, result_url)


def _auto_create_storyboard_25_nodes(db, source_node, panels: list):
    """25宫格分镜任务完成后，自动在画布上创建 25 个分镜节点。

    按 5x5 网格布局排列，并创建 REFERENCE 边和 SEQUENCE 边。
    """
    from app.schemas.node import NodeCreate
    from app.schemas.edge import EdgeCreate
    from app.crud import node as crud_node
    from app.crud import edge as crud_edge

    base_x = (source_node.x or 0) + (source_node.width or 240) + 60
    base_y = source_node.y or 0
    col_gap = 280
    row_gap = 220

    created_ids = []
    for panel in panels:
        idx = panel.get("index", 0)
        grid_row = panel.get("grid_row", (idx - 1) // 5)
        grid_col = panel.get("grid_col", (idx - 1) % 5)

        sb_node = crud_node.create_node(db, NodeCreate(
            canvas_id=source_node.canvas_id,
            node_type=NodeType.STORYBOARD,
            title=f"分镜 {idx}",
            prompt=panel.get("prompt") or panel.get("description", ""),
            x=base_x + grid_col * col_gap,
            y=base_y + grid_row * row_gap,
            config={
                "storyboard_id": f"SB_25_{idx:03d}",
                "panel_index": idx,
                "grid_row": grid_row,
                "grid_col": grid_col,
                "description": panel.get("description", ""),
                "shot_type": panel.get("shot_type", ""),
                "duration_seconds": panel.get("duration_seconds", 3),
                "source_node_id": str(source_node.id),
                "preset_source": "storyboard_25",
            },
        ), commit=False)
        created_ids.append(sb_node.id)

    db.commit()

    # 创建 REFERENCE 边：源节点 → 每个分镜
    for nid in created_ids:
        crud_edge.create_edge(db, EdgeCreate(
            canvas_id=source_node.canvas_id,
            source_node_id=source_node.id,
            target_node_id=nid,
            edge_type=EdgeType.REFERENCE,
            label="分镜",
        ), commit=False)
    db.commit()

    # 创建相邻分镜的 SEQUENCE 边
    for i in range(1, len(created_ids)):
        crud_edge.create_edge(db, EdgeCreate(
            canvas_id=source_node.canvas_id,
            source_node_id=created_ids[i - 1],
            target_node_id=created_ids[i],
            edge_type=EdgeType.SEQUENCE,
            label="下一镜",
        ), commit=False)
    db.commit()

    logger.info("[main] storyboard_25 自动创建 %d 个分镜节点", len(created_ids))


def _run_alembic_migrations():
    """通过 Alembic 执行数据库迁移（替代 Base.metadata.create_all）。

    策略：
    1. 检测数据库中是否已有业务表但缺少 alembic_version 表
       → 说明是通过 create_all 创建的旧库，先 stamp head 标记为当前版本
    2. 正常执行 alembic upgrade head
       → 新库会执行全部迁移脚本创建表
       → 已 stamp 的旧库会跳过已应用的迁移
    """
    from sqlalchemy import inspect as sa_inspect
    from alembic.config import Config as AlembicConfig
    from alembic import command
    import os as _os

    alembic_ini_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "alembic.ini"
    )
    alembic_dir = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "alembic"
    )

    alembic_cfg = AlembicConfig(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", alembic_dir)
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # 检测旧库：有业务表但没有 alembic_version 表
    has_business_tables = bool(existing_tables & {"users", "canvases", "nodes"})
    has_alembic_version = "alembic_version" in existing_tables

    if has_business_tables and not has_alembic_version:
        logger.info("[startup] 检测到已有数据库（通过 create_all 创建），执行 alembic stamp head")
        try:
            command.stamp(alembic_cfg, "head")
            logger.info("[startup] alembic stamp head 完成，已有数据库已标记为最新迁移版本")
        except Exception as exc:
            logger.warning("[startup] alembic stamp head 失败（将回退到 create_all）: %s", exc)
            # 回退：用 create_all 确保表存在
            Base.metadata.create_all(bind=engine)
    elif not has_business_tables and not has_alembic_version:
        # 全新数据库：执行迁移脚本创建所有表
        logger.info("[startup] 全新数据库，执行 alembic upgrade head 创建表结构")
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("[startup] alembic upgrade head 完成")
        except Exception as exc:
            logger.exception("[startup] alembic upgrade head 失败: %s", exc)
            raise
    else:
        # 已有 alembic_version：正常执行增量迁移
        logger.info("[startup] 执行 alembic upgrade head（增量迁移）")
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("[startup] alembic upgrade head 完成")
        except Exception as exc:
            logger.exception("[startup] alembic upgrade head 失败: %s", exc)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库迁移：通过 Alembic 管理表结构（替代 Base.metadata.create_all）
    try:
        _run_alembic_migrations()
        logger.info("[startup] 数据库迁移完成")
    except Exception:
        logger.exception("[startup] 数据库迁移失败！请检查 DATABASE_URL 和 PostgreSQL 权限")
        raise

    # 兼容性迁移：为旧数据库补齐通过 ALTER TABLE 添加的列
    # （新库通过 Alembic 初始迁移已包含这些列，以下函数内部有 _column_exists 幂等检查）
    try:
        _migrate_assets_canvas_id()
        _migrate_new_tables()
        _migrate_model_config_tiers()
    except Exception:
        logger.exception("[startup] 兼容性列迁移失败")
        raise

    seed_db = SessionLocal()
    try:
        _seed_model_configs(seed_db)
    except Exception:
        logger.exception("[seed] model_configs 初始化失败")
    finally:
        seed_db.close()

    # ── 自动创建管理员账户（首次启动） ──────────────────
    # 环境变量 ADMIN_EMAIL / ADMIN_PASSWORD 配置，不存在则跳过
    _admin_email = os.getenv("ADMIN_EMAIL", "admin@xinghe.com")
    _admin_password = os.getenv("ADMIN_PASSWORD", "admin123456")
    try:
        admin_db = SessionLocal()
        from app.models.user import User
        existing = admin_db.query(User).filter(User.is_admin == True).first()
        if existing:
            logger.info("[startup] admin account exists: %s, skip", existing.email or existing.phone)
        else:
            from app.services.auth_service import get_password_hash
            admin_user = User(
                name="Admin",
                email=_admin_email,
                password_hash=get_password_hash(_admin_password),
                is_admin=True,
                is_active=True,
                credits=999999,
            )
            admin_db.add(admin_user)
            admin_db.commit()
            logger.info("[startup] admin account created: %s", _admin_email)
    except Exception:
        logger.exception("[startup] admin account creation failed")
    finally:
        admin_db.close()

    # 初始化会话存储（SQLite 持久化）
    set_store(SQLitePersistentSessionStore(SessionLocal))

    # ── LLM 配置诊断日志 ──────────────────────────────────────
    # 启动时打印 LLM 配置摘要，帮助快速定位"卡住无请求记录"类问题
    _llm_provider = settings.LLM_PROVIDER or "ark"
    _llm_model = settings.LLM_MODEL_NAME or "(未配置)"
    _ark_key_ok = bool(settings.VOLCENGINE_ARK_API_KEY) and "YOUR_" not in settings.VOLCENGINE_ARK_API_KEY
    _api91_key_ok = bool(settings.API91_API_KEY) and "YOUR_" not in settings.API91_API_KEY
    _dashscope_key_ok = bool(settings.DASHSCOPE_API_KEY) and "YOUR_" not in settings.DASHSCOPE_API_KEY
    _modelink_key_ok = bool(settings.MODELINK_API_KEY) and "YOUR_" not in settings.MODELINK_API_KEY
    logger.info(
        "[startup] LLM 配置: provider=%s model=%s | Ark key=%s (base=%s) | 91API key=%s (base=%s) | DashScope key=%s | Modelink key=%s (base=%s)",
        _llm_provider, _llm_model,
        "✓" if _ark_key_ok else "✗", settings.VOLCENGINE_ARK_API_BASE_URL,
        "✓" if _api91_key_ok else "✗", settings.API91_BASE_URL,
        "✓" if _dashscope_key_ok else "✗",
        "✓" if _modelink_key_ok else "✗", settings.MODELINK_API_BASE_URL,
    )
    if _llm_provider == "api91" and not _api91_key_ok:
        logger.warning("[startup] ⚠ LLM_PROVIDER=api91 但 API91_API_KEY 未配置！LLM 调用将失败。")
    elif _llm_provider == "ark" and not _ark_key_ok:
        logger.warning("[startup] ⚠ LLM_PROVIDER=ark 但 VOLCENGINE_ARK_API_KEY 未配置！LLM 调用将失败。")
    # 清理启动前可能残留的会话锁（服务重启场景）
    try:
        _cleanup_db = SessionLocal()
        try:
            from app.models.session import AgentSession as _AS
            from datetime import datetime as _dt
            _cleanup_db.query(_AS).filter(_AS.lock_version.isnot(None)).update(
                {"lock_version": None, "updated_at": _dt.utcnow()}, synchronize_session=False
            )
            _cleanup_db.commit()
            logger.info("[startup] 已清理所有残留会话锁")
        finally:
            _cleanup_db.close()
    except Exception:
        logger.debug("[startup] 清理会话锁跳过（可能表不存在）")

    # 会话过期清理循环（每小时检查一次，清理超过 TTL 的会话）
    async def _session_cleanup_loop():
        while True:
            try:
                await asyncio.sleep(CLEANUP_EVERY_SECONDS)
                store = SQLitePersistentSessionStore(SessionLocal)
                try:
                    removed = store.cleanup_expired(DEFAULT_TTL_SECONDS)
                    if removed:
                        logger.info("[SessionStore] 清理过期会话 %d 条", removed)
                except Exception:
                    logger.warning("[SessionStore] 清理过期会话失败", exc_info=True)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("[SessionStore] 清理循环异常", exc_info=True)

    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    for sub in ["images", "videos", "audio", "thumbnails"]:
        os.makedirs(os.path.join(uploads_dir, sub), exist_ok=True)

    async def on_task_progress(task_id: str, progress: int):
        task = task_manager.get_task(task_id)
        if not task:
            return
        db = SessionLocal()
        try:
            crud_node.update_node_status(
                db,
                task.node_id,
                NodeStatus.PROCESSING,
                progress=progress,
            )
        except Exception as db_exc:
            logger.error("[on_task_progress] 数据库操作失败 task=%s err=%s", task_id, db_exc)
        finally:
            db.close()
        # 确保 WebSocket 消息总是发送，即使数据库操作失败
        try:
            await ws_manager.send_task_update(task)
        except Exception as ws_exc:
            logger.warning("[on_task_progress] WS 消息发送失败 task=%s err=%s", task_id, ws_exc)

    ai_worker.set_progress_callback(on_task_progress)

    async def on_task_status_change(task: Task):
        db = SessionLocal()
        try:
            if task.status == TaskStatus.RUNNING:
                crud_node.update_node_status(db, task.node_id, NodeStatus.PROCESSING, progress=task.progress)
            elif task.status == TaskStatus.QUEUED:
                crud_node.update_node_status(db, task.node_id, NodeStatus.PENDING, progress=0)
            elif task.status == TaskStatus.SUCCESS:
                result_url = None
                thumbnail_url = None
                variant_urls: List[str] = []
                if task.result:
                    result_url = task.result.get("url")
                    thumbnail_url = task.result.get("thumbnail_url")
                    # 多图回写：把所有变体存到 node.config["variants"]
                    images = task.result.get("images") or []
                    if isinstance(images, list) and len(images) > 1:
                        variant_urls = [img.get("url") for img in images if isinstance(img, dict) and img.get("url")]
                crud_node.update_node_status(
                    db, task.node_id, NodeStatus.SUCCESS,
                    progress=100, result_url=result_url, error_msg=None
                )
                if thumbnail_url:
                    node = crud_node.get_node(db, task.node_id)
                    if node:
                        node.thumbnail_url = thumbnail_url
                        if variant_urls:
                            node_config = node.config or {}
                            node_config["variants"] = variant_urls
                            node.config = node_config
                        db.add(node)
                        db.commit()
                # ── 预设 LLM 功能结果回写 ──
                # storyboard_25: 把 panels 存入 node.config 供前端调用 create_nodes 端点
                # script_parse / film_analysis: 把 LLM 返回内容存入 node.config
                preset_feature = task.params.get("preset_feature") if task.params else None
                if preset_feature and task.result:
                    node = crud_node.get_node(db, task.node_id)
                    if node:
                        node_config = dict(node.config or {})
                        node_config["preset_result"] = task.result.get("content", "")
                        if preset_feature == "storyboard_25":
                            panels = task.result.get("panels") or []
                            node_config["storyboard_25_panels"] = panels
                            # 自动创建 25 个分镜节点到画布
                            if panels:
                                try:
                                    _auto_create_storyboard_25_nodes(db, node, panels)
                                except Exception as sb_exc:
                                    logger.warning("[main] storyboard_25 自动创建节点失败: %s", sb_exc)
                        elif preset_feature == "script_parse":
                            node_config["script_parse_data"] = task.result.get("parsed_data")
                        elif preset_feature == "film_analysis":
                            node_config["film_analysis_data"] = task.result.get("analysis")
                        elif preset_feature == "script_optimize":
                            # 脚本优化：用优化后内容替换 prompt
                            optimized = task.result.get("content", "")
                            if optimized:
                                node.prompt = optimized
                        node.config = node_config
                        db.add(node)
                        db.commit()
                # 图片/视频生成成功后自动保存到资产库，关联到当前画布
                # 多图：把所有变体都存到资产库；单图：仅存主图
                if result_url and task.result:
                    result_type = task.result.get("type", "")
                    node = crud_node.get_node(db, task.node_id)
                    if node and node.canvas_id:
                        if variant_urls:
                            # 多图批量保存
                            for v_url in variant_urls:
                                _try_save_asset(db, node, v_url, v_url, result_type, user_id=task.user_id)
                        else:
                            _try_save_asset(db, node, result_url, thumbnail_url, result_type, user_id=task.user_id)
            elif task.status == TaskStatus.FAILED:
                crud_node.update_node_status(
                    db, task.node_id, NodeStatus.FAILED,
                    error_msg=task.error
                )
                # 任务最终失败时退还已扣积分（幂等保障：仅退一次）
                if task.cost and task.user_id:
                    refund_reason = f"{task.task_type}_refund"
                    try:
                        if credit_service.has_refund_record(db, _uuid.UUID(task.user_id), task.node_id, refund_reason):
                            logger.info("[credit] 退款已存在，跳过 task=%s node=%s", task.id, task.node_id)
                        else:
                            credit_service.refund_credits(
                                db=db,
                                user_id=_uuid.UUID(task.user_id),
                                amount=task.cost,
                                reason=refund_reason,
                                ref_id=task.node_id,
                                description=f"任务失败退还：{task.error or '未知错误'}",
                            )
                            db.commit()
                    except Exception as exc:
                        db.rollback()
                        logger.exception("[credit] 退款失败 task=%s node=%s", task.id, task.node_id)
                        _persist_failed_refund(task, exc)
            elif task.status == TaskStatus.RETRYING:
                crud_node.update_node_status(
                    db, task.node_id, NodeStatus.PROCESSING,
                    error_msg=f"重试中({task.retry_count}/{task.max_retries}): {task.error}"
                )
            elif task.status == TaskStatus.CANCELLED:
                crud_node.update_node_status(db, task.node_id, NodeStatus.CANCELLED, error_msg="已取消")
                # 用户取消时退还已扣积分（幂等保障：避免重复退款）
                if task.cost and task.user_id:
                    refund_reason = f"{task.task_type}_refund"
                    try:
                        if credit_service.has_refund_record(db, _uuid.UUID(task.user_id), task.node_id, refund_reason):
                            logger.info("[credit] 取消退款已存在，跳过 task=%s node=%s", task.id, task.node_id)
                        else:
                            credit_service.refund_credits(
                                db=db,
                                user_id=_uuid.UUID(task.user_id),
                                amount=task.cost,
                                reason=refund_reason,
                                ref_id=task.node_id,
                                description="用户取消任务退还积分",
                            )
                            db.commit()
                    except Exception as exc:
                        db.rollback()
                        logger.exception("[credit] 取消退款失败 task=%s node=%s", task.id, task.node_id)
                        _persist_failed_refund(task, exc)
        except Exception as db_exc:
            # 数据库操作失败不应阻断 WebSocket 消息推送
            logger.error("[on_task_status_change] 数据库操作失败 task=%s status=%s err=%s", task.id, task.status, db_exc)
        finally:
            db.close()
        # 确保 WebSocket 消息总是发送，即使数据库操作失败
        # 否则前端节点会永远卡在 processing 状态，点生图"没反应"
        try:
            await ws_manager.send_task_update(task)
        except Exception as ws_exc:
            logger.warning("[on_task_status_change] WS 消息发送失败 task=%s err=%s", task.id, ws_exc)

    task_manager.on_status_change(on_task_status_change)
    task_manager.set_worker(ai_worker.process)

    # 从数据库恢复历史任务记录（供前端查询）
    restore_fn = getattr(task_manager, "restore_from_db", None)
    if callable(restore_fn):
        restore_fn()
    else:
        logger.warning("[startup] TaskManager.restore_from_db 方法不存在，跳过任务恢复")

    await task_manager.start()

    async def _heartbeat_loop():
        while True:
            try:
                await asyncio.sleep(30)
                await ws_manager.broadcast_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("[ws] 心跳广播异常", exc_info=True)

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    # 后台定时重试失败退款（每 5 分钟一次）
    async def _refund_retry_loop():
        while True:
            try:
                await asyncio.sleep(300)
                retry_db = SessionLocal()
                try:
                    pending = retry_db.query(FailedRefund).filter(FailedRefund.resolved == False).limit(50).all()
                    for r in pending:
                        try:
                            credit_service.refund_credits(
                                db=retry_db,
                                user_id=r.user_id,
                                amount=r.amount,
                                reason=r.reason,
                                ref_id=r.ref_id,
                                description=r.description or "积分退还",
                            )
                            retry_db.commit()
                            r.resolved = True
                            retry_db.commit()
                        except Exception as exc:
                            retry_db.rollback()
                            r.retry_count += 1
                            r.last_error = str(exc)
                            retry_db.commit()
                finally:
                    retry_db.close()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("[refund] 退款重试循环异常", exc_info=True)

    refund_task = asyncio.create_task(_refund_retry_loop())

    db = SessionLocal()
    try:
        processing_nodes = db.query(models.Node).filter(
            models.Node.status.in_([NodeStatus.PENDING, NodeStatus.PROCESSING])
        ).all()
        for n in processing_nodes:
            crud_node.update_node_status(db, n.id, NodeStatus.FAILED, error_msg="服务重启，请重新生成")
    finally:
        db.close()

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    refund_task.cancel()
    try:
        await refund_task
    except asyncio.CancelledError:
        pass
    await task_manager.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="小云雀AI创作平台后端 - 完整骨架版（含Agent编排/资产管理/版本快照）",
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS 配置：未配置 CORS_ORIGINS 时回退到开发常用源，生产环境必须显式配置域名列表
    from app.core.config import _DEV_CORS_ORIGINS
    _raw_cors = settings.CORS_ORIGINS.strip()
    if not _raw_cors:
        _cors_origins = _DEV_CORS_ORIGINS
        _cors_credentials = True
    else:
        _cors_origins = [o.strip() for o in _raw_cors.split(",") if o.strip()]
        _cors_credentials = True

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("[unhandled] %s %s -> %s: %s", request.method, request.url.path, type(exc).__name__, exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": str(exc) if settings.DEBUG else "服务器内部错误",
                "path": str(request.url.path),
            },
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={"code": 404, "message": "资源不存在", "path": str(request.url.path)},
        )

    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    app.mount("/static", StaticFiles(directory=uploads_dir), name="static")

    @app.get("/health", tags=["health"])
    def health_check():
        # 检测数据库连通性
        db_ok = True
        db_error = ""
        try:
            from sqlalchemy import text
            db = SessionLocal()
            try:
                db.execute(text("SELECT 1"))
            finally:
                db.close()
        except Exception as exc:
            db_ok = False
            db_error = str(exc)

        return {
            "status": "ok" if db_ok else "degraded",
            "project": settings.PROJECT_NAME,
            "version": "1.0.0",
            "db": "ok" if db_ok else f"error: {db_error}",
            "ws_connections": ws_manager.get_connection_count(),
            "active_tasks": len([t for t in task_manager.get_all_tasks() if t.status in (TaskStatus.RUNNING, TaskStatus.QUEUED)]),
        }

    @app.get("/debug/llm-model", tags=["debug"])
    def debug_llm_model():
        """诊断接口：查看系统实际使用的 LLM 模型配置。"""
        from app.services.ai_service import _sanitize_llm_model
        from app.core.model_tiers import resolve_model, resolve_model_for_agent, TaskTier
        return {
            "LLM_MODEL_NAME (默认模型)": settings.LLM_MODEL_NAME,
            "LLM_PROVIDER (服务商)": settings.LLM_PROVIDER,
            "LLM_MODEL_LITE (轻量)": settings.LLM_MODEL_LITE,
            "LLM_MODEL_STANDARD (标准)": settings.LLM_MODEL_STANDARD,
            "LLM_MODEL_CREATIVE (旗舰)": settings.LLM_MODEL_CREATIVE,
            "DEPRECATED_MODELS (废弃列表)": list(settings.DEPRECATED_MODELS),
            "resolve_model(LITE)": resolve_model(TaskTier.LITE),
            "resolve_model(STANDARD)": resolve_model(TaskTier.STANDARD),
            "resolve_model(CREATIVE)": resolve_model(TaskTier.CREATIVE),
            "resolve_model_for_agent(platform_brain)": resolve_model_for_agent("platform_brain"),
            "resolve_model_for_agent(param_extractor)": resolve_model_for_agent("param_extractor"),
            "_sanitize_llm_model(None)": _sanitize_llm_model(None),
            "_sanitize_llm_model('gpt-5.6-terra')": _sanitize_llm_model("gpt-5.6-terra"),
            "_sanitize_llm_model('deepseek-v4-flash')": _sanitize_llm_model("deepseek-v4-flash"),
        }

    @app.get("/debug/video-config", tags=["debug"])
    def debug_video_config():
        """诊断接口：查看视频生成模型配置和 API Key 状态。"""
        from app.services.ai_service import _is_placeholder_key
        return {
            "MODELINK_API_BASE_URL": settings.MODELINK_API_BASE_URL,
            "MODELINK_API_KEY (已配置)": bool(settings.MODELINK_API_KEY and "YOUR_" not in settings.MODELINK_API_KEY),
            "MODELINK_API_KEY (前6位)": settings.MODELINK_API_KEY[:6] + "..." if settings.MODELINK_API_KEY else "(空)",
            "MODELINK_VIDEO_MODEL_ID": settings.MODELINK_VIDEO_MODEL_ID,
            "VOLCENGINE_ARK_API_KEY (已配置)": bool(settings.VOLCENGINE_ARK_API_KEY and "YOUR_" not in settings.VOLCENGINE_ARK_API_KEY),
            "VOLCENGINE_ARK_MODEL_ID_STANDARD": settings.VOLCENGINE_ARK_MODEL_ID_STANDARD,
            "VOLCENGINE_ARK_MODEL_ID_FAST": settings.VOLCENGINE_ARK_MODEL_ID_FAST,
            "DASHSCOPE_API_KEY (已配置)": bool(settings.DASHSCOPE_API_KEY and "YOUR_" not in settings.DASHSCOPE_API_KEY),
            "uploads/videos 目录存在": os.path.isdir(os.path.join(uploads_dir, "videos")),
            "uploads/videos 文件数": len(os.listdir(os.path.join(uploads_dir, "videos"))) if os.path.isdir(os.path.join(uploads_dir, "videos")) else 0,
        }

    @app.post("/debug/modelink-test", tags=["debug"])
    async def debug_modelink_test(prompt: str = "一只猫在草地上奔跑"):
        """诊断接口：直接调用 Modelink API 测试视频生成流程。"""
        import httpx
        import json as _json

        if not settings.MODELINK_API_KEY:
            return {"error": "MODELINK_API_KEY 未配置"}

        base_url = settings.MODELINK_API_BASE_URL.rstrip("/")
        endpoint = "/queue/fal-ai/vidu/q3/text-to-video/turbo"
        url = f"{base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {settings.MODELINK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"prompt": prompt, "duration": 4, "aspect_ratio": "16:9"}

        result = {"step1_create": {}, "step2_poll": {}, "step3_video_url": ""}

        # Step 1: 创建任务
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=headers)
                result["step1_create"]["status_code"] = resp.status_code
                result["step1_create"]["response"] = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:500]
        except Exception as exc:
            result["step1_create"]["error"] = str(exc)
            return result

        # Step 2: 轮询状态
        create_data = result["step1_create"].get("response", {})
        if not isinstance(create_data, dict):
            return result

        request_id = create_data.get("request_id")
        response_url = create_data.get("response_url", "")
        result["step2_poll"]["request_id"] = request_id
        result["step2_poll"]["response_url"] = response_url

        if not response_url and request_id:
            response_url = f"{base_url}/queue/fal-ai/vidu/q3/text-to-video/turbo/requests/{request_id}"

        if response_url:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(response_url, headers=headers)
                    result["step2_poll"]["status_code"] = resp.status_code
                    poll_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    result["step2_poll"]["response"] = _json.dumps(poll_data, ensure_ascii=False)[:1000] if poll_data else resp.text[:500]
            except Exception as exc:
                result["step2_poll"]["error"] = str(exc)

        return result

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()

# ── 启动时打印 LLM 模型配置 ──────────────────────────────
logger.warning("=" * 60)
logger.warning("LLM 模型配置 (启动时打印)")
logger.warning("=" * 60)
logger.warning("  LLM_MODEL_NAME (默认): %s", settings.LLM_MODEL_NAME)
logger.warning("  LLM_PROVIDER (服务商): %s", settings.LLM_PROVIDER)
logger.warning("  LLM_MODEL_LITE (轻量): %s", settings.LLM_MODEL_LITE)
logger.warning("  LLM_MODEL_STANDARD (标准): %s", settings.LLM_MODEL_STANDARD)
logger.warning("  LLM_MODEL_CREATIVE (旗舰): %s", settings.LLM_MODEL_CREATIVE)
logger.warning("  DEPRECATED_MODELS (废弃): %s", settings.DEPRECATED_MODELS)
logger.warning("  API91_BASE_URL: %s", settings.API91_BASE_URL)
logger.warning("  ARK_BASE_URL: %s", settings.VOLCENGINE_ARK_API_BASE_URL)
logger.warning("=" * 60)

# ── API 速率限制 ──────────────────────────────────────────
# 全局限流器：按客户端 IP 限流，默认每分钟 120 次请求
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
