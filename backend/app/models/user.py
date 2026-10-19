import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone = Column(String(20), unique=True, nullable=True)
    nickname = Column(String(100))
    avatar_url = Column(String(500))
    interests = Column(Text)  # 兴趣标签JSON
    age_group = Column(String(20))
    visit_count = Column(Integer, default=0)
    last_visit_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
