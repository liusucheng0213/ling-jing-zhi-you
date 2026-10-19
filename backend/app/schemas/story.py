"""
RPG故事线模块Pydantic模型定义
"""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class StoryStartRequest(BaseModel):
    """开始故事线请求"""
    storyline_id: UUID = Field(..., description="故事线ID")
    user_id: Optional[UUID] = Field(None, description="用户ID")


class StoryProgressRequest(BaseModel):
    """推进故事请求"""
    storyline_id: UUID = Field(..., description="故事线ID")
    user_id: Optional[UUID] = Field(None, description="用户ID")
    choice: Optional[str] = Field(None, description="用户选择")
    action: Optional[str] = Field(None, description="用户动作")


class StoryLineItem(BaseModel):
    """故事线列表项"""
    id: UUID
    avatar_code: str = Field(..., description="关联数字人角色")
    title: str
    description: Optional[str] = None
    reward_badge: Optional[str] = Field(None, description="完成奖励徽章")
    reward_creative_type: Optional[str] = None
    is_active: bool
    sort_order: int


class StoryNodeInfo(BaseModel):
    """故事节点信息"""
    node_id: str
    title: str
    description: str
    choices: List[dict] = Field(default_factory=list)
    is_hidden: bool = False


class StoryProgressResponse(BaseModel):
    """故事进度响应"""
    storyline_id: UUID
    title: str
    avatar_code: Optional[str] = Field(None, description="关联数字人角色")
    reward_badge: Optional[str] = Field(None, description="完成奖励徽章")
    current_node: str
    current_node_title: Optional[str] = None
    current_node_description: Optional[str] = None
    current_node_spot_id: Optional[str] = Field(None, description="当前节点关联景点ID")
    completed_nodes: List[str] = Field(default_factory=list)
    is_completed: bool
    unlocked_hidden: bool
    choices: List[dict] = Field(default_factory=list)
    progress_percent: int = Field(..., ge=0, le=100, description="完成百分比")
    npc_line: Optional[str] = Field(None, description="NPC当前引导话术")
    task: Optional[str] = Field(None, description="当前任务")
    culture_note: Optional[str] = Field(None, description="当前节点文化解释")
    action_label: Optional[str] = Field(None, description="主要操作按钮文案")
    narrator_name: Optional[str] = Field(None, description="实际数字人讲述人名称")
    narration_text: Optional[str] = Field(None, description="本节点可直接朗读的讲述文本")
    choice_result: Optional[str] = Field(None, description="用户本次选择的剧情反馈")
    digital_human: Optional[dict[str, Any]] = Field(None, description="讯飞WebSDK数字人驱动配置")


class UserStoryProgressItem(BaseModel):
    """用户故事进度项"""
    storyline_id: UUID
    title: str
    avatar_code: str
    current_node: str
    is_completed: bool
    progress_percent: int
    unlocked_hidden: bool
    completed_at: Optional[datetime] = None
