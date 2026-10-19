import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class CreativeContent(Base):
    """AI文创内容表"""
    __tablename__ = "creative_contents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    content_type = Column(String(50), nullable=False)  # poem/postcard/badge/journal/painting
    title = Column(String(200))
    content = Column(Text, nullable=False)
    meta_info = Column("metadata", JSON, default=dict)
    is_shared = Column(Boolean, default=False)
    shared_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
