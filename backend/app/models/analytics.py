import uuid
from sqlalchemy import Column, String, DateTime, Integer, Float, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class BehaviorLog(Base):
    """行为日志表"""
    __tablename__ = "behavior_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String(50), nullable=False)
    event_data = Column(JSON, default=dict)
    spot_id = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())


class AnalyticsDaily(Base):
    """日统计表"""
    __tablename__ = "analytics_daily"

    date = Column(DateTime, primary_key=True)
    service_count = Column(Integer, default=0)
    unique_users = Column(Integer, default=0)
    qa_count = Column(Integer, default=0)
    avg_latency_ms = Column(Integer)
    satisfaction_avg = Column(Float)
    top_questions = Column(JSON, default=list)
    emotion_distribution = Column(JSON)
    top_routes = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())
