import uuid
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Avatar(Base):
    """数字人形象表"""
    __tablename__ = "avatars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    role_description = Column(Text)
    image_url = Column(String(500))
    avatar_id = Column(String(100))  # 讯飞虚拟数字人形象ID
    voice_id = Column(String(100))   # 讯飞TTS音色ID
    voice_emotion = Column(String(50))  # 默认情感标签
    voice_params = Column(String(500))  # 音色参数JSON
    personality_prompt = Column(Text)
    default_greeting = Column(Text)
    trigger_spots = Column(String(500))  # JSON数组
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
