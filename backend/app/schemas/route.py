"""
路线模块Pydantic模型定义
"""

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RouteNodeInfo(BaseModel):
    """路线节点信息"""
    id: UUID
    spot_id: str
    spot_name: Optional[str] = None
    order: int
    stay_time: int = Field(..., description="建议停留分钟数")
    description: Optional[str] = None


class RouteBranchNode(BaseModel):
    """路线可选支线节点"""
    title: str
    type: Literal["photo", "rest", "culture", "shortcut"] = Field(..., description="支线类型")
    description: str
    near_spot: Optional[str] = Field(None, description="临近景点")
    extra_time: Optional[int] = Field(None, description="预计额外耗时分钟")


class DynamicRoutePlanNode(BaseModel):
    """动态路线计划中的已核验景点节点"""
    id: UUID = Field(..., description="原始路线节点ID")
    spot_id: str
    spot_name: str
    original_order: int = Field(..., description="节点在预设路线中的原始顺序")
    planned_order: int = Field(..., description="节点在本次动态计划中的顺序")
    stay_time: int = Field(..., ge=1, description="本次建议停留分钟数")
    description: Optional[str] = None
    is_current: bool = Field(False, description="是否为游客当前所在景点")


class DynamicRoutePlan(BaseModel):
    """根据当前点、已游节点、时长和体力约束生成的动态计划"""
    nodes: List[DynamicRoutePlanNode] = Field(default_factory=list)
    estimated_duration: int = Field(0, ge=0, description="预计总时长分钟，含节点间步行缓冲")
    requested_duration: Optional[int] = Field(None, description="游客填写的可用时长分钟")
    is_trimmed: bool = Field(False, description="是否相对原始已核验路线发生裁剪")
    reasons: List[str] = Field(default_factory=list, description="动态编排与裁剪理由")


class RouteListItem(BaseModel):
    """路线列表项"""
    id: UUID
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    total_time: Optional[int] = Field(None, description="预计总时长分钟")
    total_distance: Optional[int] = Field(None, description="总距离米")
    difficulty: str = Field(default="easy", description="难度: easy/medium/hard")
    node_count: int = Field(default=0, description="节点数量")
    match_score: Optional[int] = Field(None, description="个性化匹配分")
    matched_interests: List[str] = Field(default_factory=list, description="命中的兴趣标签")
    recommend_reason: Optional[str] = Field(None, description="推荐理由")
    explanation_focus: List[str] = Field(default_factory=list, description="个性化讲解重点")
    recommend_mode: Optional[str] = Field(None, description="推荐模式: personalized/default_hot/location")
    match_reasons: List[str] = Field(default_factory=list, description="推荐命中原因")
    avoid_reasons: List[str] = Field(default_factory=list, description="不推荐或需注意原因")
    next_best_spots: List[str] = Field(default_factory=list, description="下一批优先游览景点")
    profile_snapshot: dict = Field(default_factory=dict, description="本次推荐使用的画像快照")
    dynamic_plan: Optional[DynamicRoutePlan] = Field(None, description="本次请求生成的动态节点计划")


class RouteDetailResponse(BaseModel):
    """路线详情响应"""
    id: UUID
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    total_time: Optional[int] = None
    total_distance: Optional[int] = None
    difficulty: str
    nodes: List[RouteNodeInfo] = Field(default_factory=list)
    branch_nodes: List[RouteBranchNode] = Field(default_factory=list, description="可选支线")
    rest_tips: List[str] = Field(default_factory=list, description="休息与补给提醒")
    route_notes: List[str] = Field(default_factory=list, description="游览注意事项")
    created_at: datetime


class RouteRecommendRequest(BaseModel):
    """路线推荐请求"""
    interests: List[str] = Field(default_factory=list, description="兴趣标签")
    duration: Optional[int] = Field(None, description="可用时长分钟")
    difficulty: Optional[str] = Field(None, description="偏好难度")
    spot_id: Optional[str] = Field(None, description="当前所在景点")
    session_id: Optional[UUID] = Field(None, description="会话ID，用于合并对话识别兴趣")
    companion_type: Optional[str] = Field(None, description="同行人群: solo/family/elderly/group")
    mobility: Optional[str] = Field(None, description="体力水平: low/normal/high")
    accessibility_required: bool = Field(False, description="是否需要无障碍优先")
    preferred_style: Optional[str] = Field(None, description="偏好讲解风格")
    visited_spots: List[str] = Field(default_factory=list, description="已游览景点ID")
    skipped_spots: List[str] = Field(default_factory=list, description="游客明确跳过的景点ID")


class RoutePlanRequest(BaseModel):
    """针对指定路线生成或更新本次实时游览计划。"""

    spot_id: Optional[str] = Field(None, description="当前所在景点")
    visited_spots: List[str] = Field(default_factory=list, description="已游览景点ID")
    skipped_spots: List[str] = Field(default_factory=list, description="已跳过景点ID")
    duration: Optional[int] = Field(None, ge=15, le=720, description="从现在起可用时长分钟")
    mobility: Optional[Literal["low", "normal", "high"]] = Field(None, description="当前体力")
    accessibility_required: bool = Field(False, description="是否需要无障碍优先")


class RouteJourneyEventRequest(BaseModel):
    """游客端实时行程状态事件。"""

    route_id: UUID
    journey_id: str = Field(..., min_length=1, max_length=100)
    session_id: Optional[UUID] = None
    event_type: Literal[
        "started",
        "arrived",
        "spot_completed",
        "spot_skipped",
        "replanned",
        "completed",
        "ended",
    ]
    spot_id: Optional[str] = Field(None, max_length=50)
    progress_percent: int = Field(0, ge=0, le=100)
    visited_spots: List[str] = Field(default_factory=list)
    skipped_spots: List[str] = Field(default_factory=list)
    estimated_remaining_minutes: Optional[int] = Field(None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class RouteJourneyEventResponse(BaseModel):
    """行程事件记录结果。"""

    recorded: bool = True
    event_id: UUID
    created_at: datetime


class RouteInterestProfileRequest(BaseModel):
    """游客兴趣画像保存请求"""
    session_id: Optional[UUID] = Field(None, description="会话ID")
    interests: List[str] = Field(default_factory=list, description="兴趣标签")
    source: str = Field(default="profile", description="来源: profile/chat/onboarding")
    companion_type: Optional[str] = None
    duration: Optional[int] = None
    mobility: Optional[str] = None
    accessibility_required: bool = False
    preferred_style: Optional[str] = None
    visited_spots: List[str] = Field(default_factory=list)


class RouteInterestProfileResponse(BaseModel):
    """游客兴趣画像响应"""
    session_id: Optional[UUID] = None
    interests: List[str] = Field(default_factory=list)
    source: str = "profile"
    updated: bool = True
