import uuid
from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Route(Base):
    """路线表"""
    __tablename__ = "routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    tags = Column(JSON, default=list)
    total_time = Column(Integer)
    total_distance = Column(Integer)
    difficulty = Column(String(20), default="easy")  # easy/medium/hard
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())


class RouteNode(Base):
    """路线节点表"""
    __tablename__ = "route_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id = Column(UUID(as_uuid=True), ForeignKey("routes.id"), nullable=False)
    spot_id = Column(String(50), ForeignKey("spots.id"), nullable=False)
    order = Column(Integer, nullable=False)
    stay_time = Column(Integer, default=30)  # 建议停留分钟数
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
