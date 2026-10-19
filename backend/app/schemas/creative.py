"""
文创生成模块Pydantic模型定义
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PoemGenerateRequest(BaseModel):
    """生成纪念诗词请求"""
    spot_id: Optional[str] = Field(None, description="关联景点ID")
    theme: Optional[str] = Field(None, description="主题关键词")
    style: Optional[str] = Field("古典", description="诗词风格")
    user_input: Optional[str] = Field(None, max_length=500, description="用户输入的感悟")


class PostcardGenerateRequest(BaseModel):
    """生成明信片请求"""
    spot_id: Optional[str] = Field(None, description="关联景点ID")
    template: Optional[str] = Field("classic", description="模板风格")
    message: Optional[str] = Field(None, max_length=200, description="用户留言")
    include_photo: bool = Field(True, description="是否包含景点照片")
    image_context: Optional[str] = Field(
        None,
        max_length=800,
        description="已经由视觉模型提取的画面文字上下文；明信片接口不会再次读取或上传图片",
    )


class JournalGenerateRequest(BaseModel):
    """生成游记请求"""
    spots: list[str] = Field(default_factory=list, description="游览景点列表")
    emotions: list[str] = Field(default_factory=list, description="情感记录列表")
    user_input: Optional[str] = Field(None, max_length=500, description="用户补充描述")


class JournalPolishRequest(BaseModel):
    """AI润色游记请求"""
    title: Optional[str] = Field(None, max_length=80, description="游记标题")
    content: str = Field(..., min_length=1, max_length=1200, description="游记正文")
    spots: list[str] = Field(default_factory=list, description="关联景点")


class JournalPolishResponse(BaseModel):
    """AI润色游记响应"""
    title: str
    content: str


class CommunityPostCreateRequest(BaseModel):
    """社区游记发布请求"""
    title: str = Field(..., min_length=1, max_length=80, description="标题")
    content: str = Field(..., min_length=1, max_length=1200, description="正文")
    spots: list[str] = Field(default_factory=list, description="关联景点")
    image_names: list[str] = Field(default_factory=list, max_length=3, description="图片原始文件名")
    image_data_urls: list[str] = Field(default_factory=list, max_length=3, description="压缩后的图片 Data URL")
    nickname: Optional[str] = Field(None, max_length=40, description="昵称快照")
    avatar_url: Optional[str] = Field(None, max_length=500, description="头像快照")
    bio: Optional[str] = Field(None, max_length=80, description="自我介绍快照")
    visibility: str = Field("public", pattern="^(public|followers|private)$", description="可见范围")


class CommunityComment(BaseModel):
    """社区评论项"""
    id: str
    nickname: str
    avatar_url: str
    content: str
    created_at: datetime


class CommunityPostResponse(BaseModel):
    """社区游记响应"""
    id: UUID
    title: str
    content: str
    nickname: str
    avatar_url: str
    bio: str = ""
    image_names: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    like_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0
    is_liked: bool = False
    is_favorited: bool = False
    is_followed: bool = False
    is_hidden: bool = False
    visibility: str = "public"
    report_count: int = 0
    follower_count: int = 0
    comments: list[CommunityComment] = Field(default_factory=list)
    created_at: datetime


class CommunityFeedResponse(BaseModel):
    """社区信息流响应"""
    items: list[CommunityPostResponse]
    total: int


class CommunityAuthorProfileResponse(BaseModel):
    """社区作者资料快照响应"""
    nickname: str
    avatar_url: str
    bio: str = ""
    visibility: str = "public"
    is_followed: bool = False
    follower_count: int = 0
    post_count: int = 0
    posts: list[CommunityPostResponse] = Field(default_factory=list)


class CommunityCommentCreateRequest(BaseModel):
    """发表评论请求"""
    content: str = Field(..., min_length=1, max_length=160, description="评论内容")
    nickname: Optional[str] = Field(None, max_length=40, description="昵称快照")
    avatar_url: Optional[str] = Field(None, max_length=500, description="头像快照")


class CommunityReportRequest(BaseModel):
    """举报社区帖子请求"""
    reason: str = Field(..., min_length=1, max_length=120, description="举报原因")
    nickname: Optional[str] = Field(None, max_length=40, description="昵称快照")


class PhotoTip(BaseModel):
    """拍照建议项"""
    location: str = Field(..., description="拍照地点")
    angle: str = Field(..., description="推荐角度")
    time: str = Field(..., description="推荐时间")
    tip: str = Field(..., description="拍摄技巧")
    description: str = Field(..., description="推荐理由")
    safety: Optional[str] = Field(None, description="现场安全与秩序提示")
    image_key: Optional[str] = Field(None, description="前端静态图key")
    marker_x: Optional[float] = Field(None, ge=0, le=100, description="推荐机位横向百分比")
    marker_y: Optional[float] = Field(None, ge=0, le=100, description="推荐机位纵向百分比")
    frame_x: Optional[float] = Field(None, ge=0, le=100, description="取景框横向百分比")
    frame_y: Optional[float] = Field(None, ge=0, le=100, description="取景框纵向百分比")
    frame_width: Optional[float] = Field(None, ge=0, le=100, description="取景框宽度百分比")
    frame_height: Optional[float] = Field(None, ge=0, le=100, description="取景框高度百分比")


class PhotoTipsResponse(BaseModel):
    """拍照推荐响应"""
    spot_id: Optional[str] = None
    spot_name: str
    tips: list[PhotoTip]


class CreativeItem(BaseModel):
    """文创内容项"""
    id: UUID
    content_type: str = Field(..., description="类型: poem/postcard/badge/journal/painting")
    title: Optional[str] = None
    content: str
    metadata: dict = Field(default_factory=dict)
    is_shared: bool
    shared_at: Optional[datetime] = None
    created_at: datetime


class CreativeGenerateResponse(BaseModel):
    """文创生成响应"""
    id: UUID
    content_type: str
    title: Optional[str] = None
    content: str
    image_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class CreativeListResponse(BaseModel):
    """文创列表响应"""
    items: list[CreativeItem]
    total: int


class VisionAnalyzeRequest(BaseModel):
    """图片理解请求"""
    image_name: str = Field(..., min_length=1, max_length=200, description="待分析图片文件名")
    task: str = Field("photo_review", max_length=40, description="分析任务")
    spot_name: Optional[str] = Field(None, max_length=80, description="关联景点")
    context: Optional[str] = Field(None, max_length=300, description="补充上下文")
    image_data_url: Optional[str] = Field(None, max_length=8_000_000, description="本地照片data URL，仅用于本次分析")


class VisionAnalyzeResponse(BaseModel):
    """图片理解能力响应"""
    enabled: bool
    provider: Optional[str] = None
    status: str
    message: str
    task: str
    image_name: str
    spot_name: Optional[str] = None
    scene_description: Optional[str] = None
    spot_candidates: list[str] = Field(default_factory=list)
    visual_facts: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    suggestions: list[str] = Field(default_factory=list)
    safety_tips: list[str] = Field(default_factory=list)
    publish_tip: Optional[str] = None
    evidence: dict = Field(default_factory=dict)
