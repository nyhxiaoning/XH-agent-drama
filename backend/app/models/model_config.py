import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Boolean, DateTime

from app.core.database import Base, GUID


class ModelConfig(Base):
    """模型配置与上架管理：支持按模型设置积分单价、启用/禁用、显示名称等。"""
    __tablename__ = "model_configs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    model_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False, index=True)  # image / video / audio / llm
    description = Column(String(512), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    order = Column(Integer, default=0, nullable=False)
    credits = Column(Integer, default=0, nullable=False)  # 0=使用全局默认；图片=每张，视频=每秒（向后兼容）
    # 视频模型三档定价（5s/10s/15s），0=未设置则回退到 credits 按秒计费
    credits_5s = Column(Integer, default=0, nullable=False)
    credits_10s = Column(Integer, default=0, nullable=False)
    credits_15s = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
