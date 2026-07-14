"""
P11: IP 资产库复用 - 跨项目角色/场景资产检索。

模型定义：IPAsset 用于存储可跨项目复用的角色/场景资产。
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, JSON, Boolean, ForeignKey, Index
from app.core.database import Base, GUID


class IPAsset(Base):
    """IP 资产库：可跨项目复用的角色/场景资产。"""
    __tablename__ = "ip_assets"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=True, index=True)

    # 资产类型
    asset_type = Column(String(50), nullable=False)  # character | scene | prop
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # 视觉特征
    appearance_desc = Column(Text, nullable=True)  # 外貌描述
    outfit_desc = Column(Text, nullable=True)  # 服装描述
    immutable_features = Column(JSON, nullable=True, default=list)  # 不可变特征列表
    visual_anchors = Column(JSON, nullable=True, default=list)  # 视觉锚点

    # 图片资源
    image_url = Column(String(512), nullable=True)
    thumbnail_url = Column(String(512), nullable=True)
    reference_urls = Column(JSON, nullable=True, default=list)  # 多角度参考图

    # 风格标签
    style_tags = Column(JSON, nullable=True, default=list)  # ["realistic", "anime", "cyberpunk"]
    genre_tags = Column(JSON, nullable=True, default=list)  # ["都市", "古风", "科幻"]
    color_palette = Column(JSON, nullable=True, default=list)

    # 来源
    source_canvas_id = Column(GUID(), nullable=True)
    source_project_name = Column(String(255), nullable=True)

    # 复用统计
    reuse_count = Column(Integer, default=0)
    is_public = Column(Boolean, default=False)  # 是否公开到全局资产库
    is_featured = Column(Boolean, default=False)  # 是否精选

    # 元数据
    meta = Column(JSON, nullable=True, default=dict)
    tags = Column(JSON, nullable=True, default=list)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_ip_assets_user_type", "user_id", "asset_type"),
        Index("idx_ip_assets_public", "is_public"),
    )


class IPAssetRelation(Base):
    """IP 资产关联关系（如角色与场景的关联）。"""
    __tablename__ = "ip_asset_relations"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    ip_asset_id = Column(GUID(), ForeignKey("ip_assets.id"), nullable=False, index=True)
    related_asset_id = Column(GUID(), ForeignKey("ip_assets.id"), nullable=True)
    relation_type = Column(String(50), nullable=False)  # character_scene | character_prop | similar
    relation_meta = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
