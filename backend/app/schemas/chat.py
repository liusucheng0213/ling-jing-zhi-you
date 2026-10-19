"""
聊天模块Pydantic模型定义
包含请求和响应的数据校验模型
"""

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ResponseMode = Literal["auto", "brief", "normal", "detail"]


class TextChatRequest(BaseModel):
    """文本对话请求"""
    session_id: Optional[UUID] = Field(None, description="会话ID，首次对话可不传")
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息内容")
    spot_id: Optional[str] = Field(None, description="当前景点ID")
    avatar: Optional[str] = Field(None, description="指定数字人角色")
    route_id: Optional[UUID] = Field(None, description="当前讲解路线ID")
    response_mode: ResponseMode = Field(
        "auto",
        description="回答长度：auto自动判断、brief简答、normal常规、detail展开",
    )


class MultimodalEvidenceResponse(BaseModel):
    """图片或语音输入的可解释识别证据。"""

    model_config = ConfigDict(extra="allow")

    type: Optional[str] = Field(None, description="证据类型: voice/image")
    recognized_text: Optional[str] = Field(None, description="ASR识别文本")
    asr_provider: Optional[str] = Field(None, description="ASR服务提供方")
    asr_confidence: Optional[float] = Field(
        None,
        ge=0,
        le=1,
        description="ASR句级置信度；服务未提供时为null",
    )
    voice_emotion: Optional[str] = Field(None, description="原始声学情感")
    fused_emotion: Optional[str] = Field(None, description="文本与声学融合后的情感")
    acoustic_features: Optional[dict[str, Any]] = Field(None, description="声学特征及判定依据")
    emotion_fusion: Optional[dict[str, Any]] = Field(None, description="情感融合与冲突仲裁证据")
    candidates: List[dict[str, Any]] = Field(default_factory=list, description="图片识别候选")
    scene_description: Optional[str] = Field(None, description="图片中可直接观察到的场景描述")
    visual_facts: List[str] = Field(default_factory=list, description="图片中可直接观察到的事实")
    recognized_spots: List[str] = Field(default_factory=list, description="与景区知识库精确匹配的景点")
    composition_suggestions: List[str] = Field(default_factory=list, description="针对原图的构图与拍摄建议")
    publish_tip: Optional[str] = Field(None, description="基于原图的游记发布建议")


class ChatMessageResponse(BaseModel):
    """单条消息响应"""
    id: UUID
    role: str = Field(..., description="消息角色: user/assistant/system")
    content: str = Field(..., description="消息内容")
    content_type: str = Field(default="text", description="内容类型: text/audio/video/image")
    audio_url: Optional[str] = Field(None, description="音频URL")
    video_url: Optional[str] = Field(None, description="视频URL")
    emotion: Optional[str] = Field(None, description="情感标签")
    intent: Optional[str] = Field(None, description="意图识别结果")
    spot_id: Optional[str] = Field(None, description="关联景点ID")
    retrieved_docs: List[dict[str, Any]] = Field(default_factory=list, description="RAG来源片段")
    latency_ms: Optional[int] = Field(None, description="响应延迟毫秒")
    created_at: datetime


class DigitalHumanResponse(BaseModel):
    """数字人多模态输出"""
    avatar_code: str = Field(..., description="前端数字人编码")
    avatar_name: str = Field(..., description="数字人名称")
    avatar_title: Optional[str] = Field(None, description="数字人称号")
    emotion: str = Field(..., description="情感标签")
    expression: str = Field(..., description="表情/动作标签")
    audio_url: Optional[str] = Field(None, description="语音播放URL")
    video_url: Optional[str] = Field(None, description="数字人视频URL")
    stream_url: Optional[str] = Field(None, description="实时数字人流URL")
    render_mode: str = Field(..., description="渲染模式: xunfei_sdk/video")
    lip_sync_mode: str = Field(..., description="口型同步模式")
    provider: str = Field(..., description="数字人提供方")
    viseme_sequence: List[dict[str, Any]] = Field(default_factory=list, description="轻量口型关键帧")
    action_sequence: List[dict[str, Any]] = Field(default_factory=list, description="讯飞数字人动作序列")
    sdk_config: Optional[dict[str, Any]] = Field(None, description="讯飞WebSDK驱动配置")


class ChatResponse(BaseModel):
    """对话响应"""
    session_id: UUID = Field(..., description="会话ID")
    message: ChatMessageResponse = Field(..., description="助手回复消息")
    avatar: str = Field(..., description="当前数字人角色")
    suggested_questions: List[str] = Field(default_factory=list, description="推荐追问")
    digital_human: Optional[DigitalHumanResponse] = Field(None, description="数字人多模态输出")
    recognized_text: Optional[str] = Field(None, description="语音输入识别文本")
    retrieved_docs: List[dict[str, Any]] = Field(default_factory=list, description="答案引用的知识片段")
    confidence: Optional[float] = Field(None, description="问答可信度 0-1")
    answer_type: Optional[str] = Field(None, description="回答类型: fact/spot_guide/route/story/service/general")
    trace_id: Optional[UUID] = Field(None, description="可在管理端追踪的助手消息ID")
    multimodal_evidence: Optional[MultimodalEvidenceResponse] = Field(
        None,
        description="图片/语音等多模态识别证据",
    )


class ChatHistoryResponse(BaseModel):
    """聊天历史响应"""
    session_id: UUID
    messages: List[ChatMessageResponse]
    total: int = Field(..., description="消息总数")


class SessionCreateRequest(BaseModel):
    """创建会话请求"""
    spot_id: Optional[str] = Field(None, description="起始景点ID")
    avatar: Optional[str] = Field("舒窈", description="默认数字人角色")
    user_agent: Optional[str] = Field(None, description="用户代理信息")


class SessionCreateResponse(BaseModel):
    """创建会话响应"""
    session_id: UUID
    avatar: str
    welcome_message: str
    created_at: datetime
    digital_human: Optional[DigitalHumanResponse] = Field(None, description="欢迎语数字人多模态输出")


class AvatarSwitchRequest(BaseModel):
    """在保留会话历史的前提下切换常驻导游。"""

    avatar: str = Field(..., min_length=1, max_length=50, description="目标数字人角色")


class AvatarSwitchResponse(BaseModel):
    """数字人切换后的无播报连接配置。"""

    session_id: UUID
    avatar: str
    digital_human: DigitalHumanResponse


class FeedbackRequest(BaseModel):
    """游客满意度评价请求"""
    session_id: UUID = Field(..., description="会话ID")
    rating: int = Field(..., ge=1, le=5, description="满意度评分 1-5")
    feedback_text: Optional[str] = Field(None, max_length=500, description="评价文字内容")
    tags: List[str] = Field(default_factory=list, description="评价标签")
    would_recommend: Optional[bool] = Field(None, description="是否愿意推荐")
    dimension_scores: dict[str, int] = Field(default_factory=dict, description="分维度评分")


class FeedbackResponse(BaseModel):
    """游客满意度评价响应"""
    success: bool
    message: str
    session_id: UUID
    rating: int
    created_at: datetime
