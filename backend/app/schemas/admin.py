"""
管理后台模块Pydantic模型定义
"""

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ==================== 知识库模型 ====================

class KnowledgeListItem(BaseModel):
    """知识文档列表项"""
    id: UUID
    title: str
    doc_type: str
    spot_id: Optional[str] = None
    status: str = Field(..., description="状态: draft/published/archived")
    version: int
    lang: str
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    chunk_count: int = 0
    source_file: Optional[str] = None
    metadata_json: dict = Field(default_factory=dict)


class KnowledgeCreateRequest(BaseModel):
    """创建知识文档请求"""
    title: str = Field(..., min_length=1, max_length=500)
    doc_type: str = Field(..., description="文档类型")
    spot_id: Optional[str] = None
    content: str = Field(..., min_length=1)
    content_html: Optional[str] = None
    metadata_json: Optional[dict] = Field(default_factory=dict)
    lang: str = Field(default="zh")


class KnowledgeUpdateRequest(BaseModel):
    """更新知识文档请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    doc_type: Optional[str] = Field(None, min_length=1, max_length=50)
    content: Optional[str] = Field(None, min_length=1)
    content_html: Optional[str] = None
    spot_id: Optional[str] = None
    metadata_json: Optional[dict] = None
    lang: Optional[str] = None
    status: Optional[Literal["draft", "published", "archived"]] = None


class KnowledgeDetailResponse(BaseModel):
    """知识文档详情响应"""
    id: UUID
    title: str
    doc_type: str
    spot_id: Optional[str] = None
    content: str
    content_html: Optional[str] = None
    status: str
    version: int
    metadata_json: dict
    lang: str
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    chunks: List[dict[str, Any]] = Field(default_factory=list)


class KnowledgeRecallTestRequest(BaseModel):
    """知识库召回测试请求"""

    query: str = Field(..., min_length=1, max_length=500)
    spot_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=10)


class KnowledgeRecallHit(BaseModel):
    """知识库召回命中"""

    rank: int
    chunk_id: str
    document_id: str
    doc_title: str
    doc_type: Optional[str] = None
    spot_id: Optional[str] = None
    score: float
    vector_score: float = 0
    text_score: float = 0
    content: str
    reason: str


class KnowledgeRecallTestResponse(BaseModel):
    """知识库召回测试响应"""

    query: str
    mode: str
    confidence: float
    total_ms: Optional[int] = None
    hits: List[KnowledgeRecallHit] = Field(default_factory=list)


class KnowledgeDraftFromTraceRequest(BaseModel):
    """低置信问题转知识库草稿请求"""

    title: Optional[str] = Field(None, max_length=500)
    doc_type: str = Field(default="待补充问答")
    spot_id: Optional[str] = None


# ==================== 数据大屏模型 ====================

class DashboardOverviewResponse(BaseModel):
    """概览数据响应"""
    total_users: int = Field(..., description="总用户数")
    total_sessions: int = Field(..., description="总会话数")
    total_qa: int = Field(..., description="总问答数")
    today_active: int = Field(..., description="今日活跃")
    today_service: int = Field(0, description="今日服务会话数")
    week_service: int = Field(0, description="本周服务会话数（周一至今）")
    avg_satisfaction: float = Field(..., description="平均满意度")
    avg_latency_ms: int = Field(..., description="平均响应延迟")
    registered_users: int = Field(0, description="注册用户数")
    anonymous_visitors: int = Field(0, description="匿名独立访客数（浏览器标识口径）")
    satisfaction_count: int = Field(0, description="已提交满意度的会话数")


class DashboardRealtimeResponse(BaseModel):
    """实时运营总览"""

    online_sessions: int
    active_sessions_today: int
    hot_spots: List[dict[str, Any]] = Field(default_factory=list)
    low_confidence_questions: List[dict[str, Any]] = Field(default_factory=list)
    negative_emotion_alerts: List[dict[str, Any]] = Field(default_factory=list)
    asr_success_rate: float
    tts_success_rate: float
    avatar_success_rate: float
    avg_rag_ms: int
    avg_total_latency_ms: int
    is_sample: bool = False


class OptimizationMetricsResponse(BaseModel):
    """优化期指标"""

    photo_review_total: int = 0
    photo_review_success: int = 0
    photo_review_failed: int = 0
    community_posts: int = 0
    community_comments: int = 0
    community_favorites: int = 0
    community_reports: int = 0
    hidden_posts: int = 0
    is_sample: bool = False


class CommunityModerationPost(BaseModel):
    """社区管理帖子项"""

    id: UUID
    title: str
    content: str
    nickname: str
    visibility: str = "public"
    is_hidden: bool = False
    like_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0
    report_count: int = 0
    reports: List[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class CommunityModerationListResponse(BaseModel):
    """社区管理列表响应"""

    items: List[CommunityModerationPost]
    total: int


class CommunityModerationUpdateRequest(BaseModel):
    """社区管理状态更新请求"""

    is_hidden: bool
    reason: Optional[str] = Field(None, max_length=120)


class DailyStatsItem(BaseModel):
    """日统计项"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    service_count: int
    unique_users: int
    qa_count: int
    avg_latency_ms: Optional[int] = None
    satisfaction_avg: Optional[float] = None


class DailyStatsResponse(BaseModel):
    """日统计响应"""
    items: List[DailyStatsItem]
    total_days: int


class HotQuestionItem(BaseModel):
    """热门问答项"""
    question: str
    count: int
    category: Optional[str] = None


class HotQuestionsResponse(BaseModel):
    """热门问答响应"""
    items: List[HotQuestionItem]
    period: str = Field(..., description="统计周期")


class EmotionTrendItem(BaseModel):
    """情感趋势项"""
    date: str
    happy: float = Field(..., description="开心占比")
    neutral: float = Field(..., description="中性占比")
    sad: float = Field(..., description="悲伤占比")
    angry: float = Field(..., description="愤怒占比")
    surprised: float = Field(..., description="惊讶占比")


class EmotionTrendResponse(BaseModel):
    """情感趋势响应"""
    items: List[EmotionTrendItem]
    period: str


# ==================== RAG溯源模型 ====================

class RagAnswerSnapshot(BaseModel):
    """一次RAG回答的可比较快照。"""

    answer: str
    confidence: Optional[float] = None
    mode: Optional[str] = None
    source_count: int = 0
    rag_ms: Optional[int] = None
    total_ms: Optional[int] = None
    fast_reply: bool = False
    sources: List[dict[str, Any]] = Field(default_factory=list)


class RagImprovementSummary(BaseModel):
    """溯源列表中的知识改进进度摘要。"""

    document_id: UUID
    document_status: Literal["draft", "published", "archived"]
    retest_count: int = 0
    last_retested_at: Optional[datetime] = None
    result: Literal["draft", "ready_to_retest", "improved", "hit_without_gain", "not_hit"]


class RagRetestRequest(BaseModel):
    """发布知识后的原问题复测请求。"""

    document_id: UUID


class RagImprovementResponse(BaseModel):
    """知识补全前后的真实回答对比。"""

    message_id: UUID
    document_id: UUID
    document_status: Literal["draft", "published", "archived"]
    question: str
    retrieval_query: str
    before: RagAnswerSnapshot
    after: Optional[RagAnswerSnapshot] = None
    confidence_delta: Optional[float] = None
    source_count_delta: int = 0
    new_document_hit: bool = False
    improved: bool = False
    result: Literal["draft", "ready_to_retest", "improved", "hit_without_gain", "not_hit"]
    retest_count: int = 0
    last_retested_at: Optional[datetime] = None


class RagTraceItem(BaseModel):
    """RAG溯源记录"""

    id: UUID
    message_id: UUID
    session_id: Optional[UUID] = None
    question: Optional[str] = None
    answer: str
    created_at: datetime
    latency_ms: Optional[int] = None
    rag_ms: Optional[int] = None
    mode: Optional[str] = None
    confidence: Optional[float] = None
    low_confidence: bool = False
    no_hit: bool = False
    fast_reply: bool = False
    source_count: int = 0
    intent: Optional[str] = None
    rag_success: bool = False
    retrieved_docs_count: int = 0
    trace: dict[str, Any] = Field(default_factory=dict)
    sources: List[dict[str, Any]] = Field(default_factory=list)
    improvable: bool = False
    improvement: Optional[RagImprovementSummary] = None


class RagTraceListResponse(BaseModel):
    """RAG溯源列表响应"""

    items: List[RagTraceItem]
    total: int


class RagQualityStatsResponse(BaseModel):
    """RAG质量统计响应"""

    total: int
    success_count: int
    total_traced: int
    rag_success_count: int
    no_hit_count: int
    low_confidence_count: int
    avg_latency_ms: int
    avg_rag_ms: int
    fast_reply_count: int


# ==================== 数字人形象模型 ====================

class AvatarConfigBase(BaseModel):
    """数字人配置基础字段"""

    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=50)
    role_description: Optional[str] = None
    image_url: Optional[str] = None
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None
    voice_emotion: Optional[str] = None
    voice_params: dict[str, Any] = Field(default_factory=dict)
    personality_prompt: Optional[str] = None
    default_greeting: Optional[str] = None
    trigger_spots: List[str] = Field(default_factory=list)
    is_active: bool = True
    is_default: bool = False
    sort_order: int = 0


class AvatarConfigCreate(AvatarConfigBase):
    """创建数字人配置"""


class AvatarConfigUpdate(BaseModel):
    """更新数字人配置"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    role_description: Optional[str] = None
    image_url: Optional[str] = None
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None
    voice_emotion: Optional[str] = None
    voice_params: Optional[dict[str, Any]] = None
    personality_prompt: Optional[str] = None
    default_greeting: Optional[str] = None
    trigger_spots: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None


class AvatarConfigResponse(AvatarConfigBase):
    """数字人配置响应"""

    id: UUID
    created_at: datetime


class AvatarHealthResponse(BaseModel):
    """数字人链路健康检查响应"""

    avatar_code: str
    avatar_name: str
    ok: bool
    checks: List[dict[str, Any]] = Field(default_factory=list)
    sdk_preview: Optional[dict[str, Any]] = None
