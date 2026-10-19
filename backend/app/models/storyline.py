import uuid
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class StoryLine(Base):
    """故事线定义表"""
    __tablename__ = "storylines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_code = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    plot_points = Column(JSON, default=list)
    hidden_triggers = Column(JSON, default=list)
    reward_badge = Column(String(100))
    reward_creative_type = Column(String(50))
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class UserStoryProgress(Base):
    """用户故事进度表"""
    __tablename__ = "user_story_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    storyline_id = Column(UUID(as_uuid=True), nullable=False)
    current_node = Column(String(50), default="start")
    completed_nodes = Column(JSON, default=list)
    is_completed = Column(Boolean, default=False)
    unlocked_hidden = Column(Boolean, default=False)
    unlocked_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
