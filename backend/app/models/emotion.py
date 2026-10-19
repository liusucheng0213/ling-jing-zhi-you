import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class EmotionHistory(Base):
    """情感历史表"""
    __tablename__ = "emotion_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    emotion_type = Column(String(50), nullable=False)
    intensity = Column(Integer)
    trigger_text = Column(Text)
    spot_id = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
