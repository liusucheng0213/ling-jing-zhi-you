import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from .base import Base

class Session(Base):
    """会话表"""
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="active")  # active/closed/expired
    current_spot_id = Column(String(50))
    current_avatar = Column(String(50), default="灵小禅")
    dialogue_state = Column(String(50), default="welcome")
    turn_count = Column(Integer, default=0)
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime)
    satisfaction_score = Column(Integer)
    ip_address = Column(String(50))
    user_agent = Column(Text)

class ChatMessage(Base):
    """聊天记录表"""
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"))
    role = Column(String(20), nullable=False)  # user/assistant/system
    content = Column(Text, nullable=False)
    content_type = Column(String(20), default="text")  # text/audio/video/image
    audio_url = Column(String(500))
    video_url = Column(String(500))
    emotion = Column(String(50))
    intent = Column(String(50))
    spot_id = Column(String(50))
    retrieved_docs = Column(JSON, default=list)
    latency_ms = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
