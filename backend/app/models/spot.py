from sqlalchemy import Column, String, Text, Integer, Float, Boolean, DateTime, JSON, func
from .base import Base

class Spot(Base):
    """景点信息表"""
    __tablename__ = "spots"

    id = Column(String(50), primary_key=True, comment="景点ID，如 LS-001")
    name = Column(String(200), nullable=False)
    scenic_area = Column(String(100), nullable=False)
    location = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    coordinate_system = Column(String(20), default="WGS84")
    coordinate_status = Column(String(20), default="estimated")
    coordinate_source = Column(Text)
    coordinate_source_id = Column(String(100))
    coordinate_accuracy_meters = Column(Float)
    coordinate_verified_at = Column(DateTime(timezone=True))
    source_latitude = Column(Float)
    source_longitude = Column(Float)
    source_coordinate_system = Column(String(20))
    building_params = Column(Text)
    core_function = Column(Text)
    cultural_connotation = Column(Text)
    detailed_intro = Column(Text)
    highlights = Column(Text)
    performance_info = Column(Text)
    photos = Column(JSON, default=list)
    tags = Column(JSON, default=list)
    route_order = Column(Integer, default=0)
    best_visit_time = Column(String(200))
    qr_code = Column(String(100))
    lang = Column(String(10), default="zh")  # 多语种预留
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
