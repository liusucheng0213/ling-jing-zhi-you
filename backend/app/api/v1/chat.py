"""
游客端对话API模块
提供文本对话、语音对话、历史消息查询和会话管理功能
"""

import time
import uuid
import asyncio
import base64
from array import array
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Avatar, BehaviorLog, EmotionHistory, KnowledgeDocument, Route, RouteNode, Session as ChatSession, ChatMessage, Spot
from app.core.avatar_orchestrator import DEFAULT_AVATAR_TRIGGER_SPOTS, resolve_avatar_profile
from app.schemas.chat import (
    AvatarSwitchRequest,
    AvatarSwitchResponse,
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatResponse,
    FeedbackRequest,
    FeedbackResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    ResponseMode,
    TextChatRequest,
)
from app.utils.jwt import get_current_user

router = APIRouter(tags=["对话"])
ANONYMOUS_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _resolve_spot_avatar(
    db: AsyncSession,
    spot_id: str | None,
    fallback_avatar: str | None,
) -> str:
    """优先按后台触发景点配置选择数字人，无位置时保留用户选择。"""

    fallback_name = resolve_avatar_profile(fallback_avatar).name
    if not spot_id:
        return fallback_name
    spot_name = await db.scalar(select(Spot.name).where(Spot.id == spot_id).limit(1))
    if not spot_name:
        return fallback_name

    rows = (
        await db.execute(
            select(Avatar)
            .where(Avatar.is_active == True)  # noqa: E712
            .order_by(Avatar.sort_order, Avatar.created_at)
        )
    ).scalars().all()
    for row in rows:
        try:
            trigger_spots = json.loads(row.trigger_spots or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            trigger_spots = []
        if spot_id in trigger_spots or spot_name in trigger_spots:
            return row.name

    for code, trigger_spots in DEFAULT_AVATAR_TRIGGER_SPOTS.items():
        if spot_name in trigger_spots:
            return resolve_avatar_profile(code).name
    return fallback_name


async def _select_chat_avatar(
    db: AsyncSession,
    spot_id: str | None,
    explicit_avatar: str | None,
    session_avatar: str | None,
) -> str:
    """游客明确选角优先；仅旧客户端未传角色时使用景点触发规则。"""

    if explicit_avatar:
        return resolve_avatar_profile(explicit_avatar).name
    return await _resolve_spot_avatar(db, spot_id, session_avatar or "舒窈")


# ==================== 角色人设映射 ====================

AVATAR_PERSONALITIES = {
    "舒窈": "你是数字人导游舒窈，使用聆小璇音色。表达亲切清楚，擅长首次游览、亲子问答和轻松路线推荐。",
    "明朗": "你是数字人导游明朗，使用明哥音色。表达沉稳简练，擅长文化背景、参观礼仪与慢行路线讲解。",
    "风屿": "你是数字人导游风屿，使用聆飞哲音色。擅长区分历史事实与文化传说，并以研学方式讲述西行文化。",
    "明泽": "你是数字人导游明泽，使用明哥音色。表达儒雅严谨，擅长建筑、传统工艺和佛教艺术脉络。",
    "雨桐": "你是数字人导游雨桐，使用聆小玥音色。表达温和自然，擅长江南美学、拍摄点位和文创灵感。",
}


async def _resolve_avatar_personality(db: AsyncSession, avatar_name: str) -> str:
    """优先使用后台保存的人设；未配置时使用代码内置的安全人设。"""

    try:
        profile = resolve_avatar_profile(avatar_name)
        result = await db.execute(
            select(Avatar)
            .where(Avatar.is_active == True)  # noqa: E712
            .where((Avatar.name == profile.name) | (Avatar.code == profile.code))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row and row.personality_prompt and row.personality_prompt.strip():
            return row.personality_prompt.strip()
    except Exception as exc:
        logger.warning(f"读取后台数字人人设失败，使用内置人设: {exc}")
    return AVATAR_PERSONALITIES.get(resolve_avatar_profile(avatar_name).name, "")

# ==================== 全局引擎实例（延迟初始化） ====================

_dialogue_engine = None
_emotion_engine = None
_avatar_orchestrator = None
StreamCallback = Callable[[dict[str, Any]], Awaitable[None]]


INTEREST_KEYWORDS = {
    "历史": ["历史", "典故", "文化", "古迹", "由来"],
    "文化": ["文化", "佛教", "佛法", "禅", "玄奘", "艺术"],
    "自然": ["自然", "风光", "风景", "山水", "湖", "树"],
    "摄影": ["拍照", "摄影", "打卡", "出片", "照片"],
    "亲子": ["孩子", "小朋友", "亲子", "家庭"],
    "美食": ["美食", "吃", "餐饮", "素斋", "饭"],
    "禅修": ["禅修", "静心", "冥想", "安静"],
    "轻松": ["轻松", "少走", "不累", "休息", "慢一点"],
}

CONTEXTUAL_ENTITIES = (
    "灵山大照壁",
    "五明桥",
    "灵山大佛",
    "九龙灌浴",
    "灵山梵宫",
    "五印坛城",
    "祥符禅寺",
    "佛足坛",
    "阿育王柱",
    "五智门",
    "菩提大道",
    "降魔浮雕",
    "百子戏弥勒",
    "佛教文化博览馆",
    "曼飞龙塔",
    "无尽意斋",
    "拈花湾",
    "拈花广场",
    "梵天花海",
    "香月花街",
    "妙音台",
    "拈花堂",
    "五灯湖",
    "鹿鸣谷",
    "拈花塔",
)
CONTEXTUAL_REFERENCES = ("它", "他", "她", "那里", "那儿", "这个", "那个", "该景点", "这座", "那座")
NIANHUA_TERMS = (
    "拈花湾",
    "拈花广场",
    "梵天花海",
    "香月花街",
    "妙音台",
    "拈花堂",
    "五灯湖",
    "鹿鸣谷",
    "拈花塔",
)


def _extract_interests(text: str) -> list[str]:
    """从自然语言中抽取游客兴趣标签。"""

    matched: list[str] = []
    lowered = text.lower()
    for interest, keywords in INTEREST_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            matched.append(interest)
    return matched


async def _restore_dialogue_history(
    db: AsyncSession,
    session_id: uuid.UUID,
    context: Any,
) -> None:
    """服务重启后从数据库恢复最近三轮，确保会话ID对应的上下文仍然连续。"""

    if context.history:
        return
    # 当前请求的用户消息已加入AsyncSession但尚未提交；关闭自动flush，只读取历史已提交消息。
    with db.no_autoflush:
        rows = (
            await db.execute(
                select(ChatMessage.role, ChatMessage.content, ChatMessage.emotion, ChatMessage.intent)
                .where(ChatMessage.session_id == session_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(6)
            )
        ).all()
    for role, content, emotion, intent in reversed(rows):
        context.add_message(role, content, emotion=emotion, intent=intent)
    context.turn_count = sum(1 for role, *_ in rows if role == "user")


def _resolve_contextual_query(message: str, context: Any) -> str:
    """将“它/那里”等追问绑定到最近明确景点，仅用于检索，不改写游客原话。"""

    if any(entity in message for entity in CONTEXTUAL_ENTITIES):
        return message
    if not any(reference in message for reference in CONTEXTUAL_REFERENCES):
        return message

    # 用户明确提过的实体优先于助手回复，避免被一段包含多个景点的推荐文本带偏。
    for preferred_role in ("user", "assistant"):
        for item in reversed(context.history):
            if item.get("role") != preferred_role:
                continue
            content = str(item.get("content") or "")
            candidates = [entity for entity in CONTEXTUAL_ENTITIES if entity in content]
            if candidates:
                entity = max(candidates, key=content.rfind)
                return f"{entity}，{message}"
    return message


async def _save_interest_profile(
    db: AsyncSession,
    session_id: uuid.UUID,
    message: str,
    interests: list[str],
    user_id: Optional[uuid.UUID] = None,
    spot_id: Optional[str] = None,
) -> None:
    """写入会话兴趣画像行为日志。"""

    if not interests:
        return
    db.add(
        BehaviorLog(
            user_id=user_id,
            session_id=session_id,
            event_type="interest_profile",
            event_data={
                "interests": interests,
                "evidence_text": message[:300],
                "source": "chat",
            },
            spot_id=spot_id,
        )
    )


async def _load_saved_interests(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> list[str]:
    """恢复会话最近一次已确认兴趣，不要求客户端重复传参。"""

    result = await db.execute(
        select(BehaviorLog.event_data)
        .where(
            BehaviorLog.session_id == session_id,
            BehaviorLog.event_type == "interest_profile",
        )
        .order_by(desc(BehaviorLog.created_at))
        .limit(1)
    )
    payload = result.scalar_one_or_none() or {}
    interests = payload.get("interests") if isinstance(payload, dict) else []
    return [str(item) for item in interests or [] if str(item) in INTEREST_KEYWORDS]


async def _load_route_interests(
    db: AsyncSession,
    route_id: Optional[uuid.UUID],
) -> list[str]:
    """把路线标签映射为最低优先级的讲解偏好。"""

    if not route_id:
        return []
    result = await db.execute(select(Route.tags).where(Route.id == route_id))
    tags = result.scalar_one_or_none() or []
    joined = " ".join(str(item) for item in tags)
    return _extract_interests(joined)


async def _resolve_effective_interests(
    db: AsyncSession,
    session_id: uuid.UUID,
    message: str,
    route_id: Optional[uuid.UUID],
) -> tuple[list[str], str]:
    """固定执行“本轮明确表达 > 已保存兴趣 > 当前路线标签”。"""

    explicit = _extract_interests(message)
    if explicit:
        return explicit, "current_turn"
    saved = await _load_saved_interests(db, session_id)
    if saved:
        return saved, "saved_profile"
    route_interests = await _load_route_interests(db, route_id)
    return route_interests, "route_tags" if route_interests else "none"


def _resolve_scenic_area(query: str) -> str:
    """显式提及拈花湾时才跨景区检索，普通灵山问答保持隔离。"""

    return "拈花湾禅意小镇" if any(term in query for term in NIANHUA_TERMS) else "灵山胜境"


async def _save_emotion_history(
    db: AsyncSession,
    session_id: uuid.UUID,
    message: str,
    emotion_result: dict[str, Any],
    user_id: Optional[uuid.UUID] = None,
    spot_id: Optional[str] = None,
) -> None:
    """写入每轮情感分析结果，供管理端趋势统计。"""

    db.add(
        EmotionHistory(
            user_id=user_id or ANONYMOUS_USER_ID,
            session_id=session_id,
            emotion_type=emotion_result.get("type", "neutral"),
            intensity=int(emotion_result.get("intensity") or 1),
            trigger_text=message[:500],
            spot_id=spot_id,
        )
    )


async def _build_route_context(
    db: AsyncSession,
    route_id: Optional[uuid.UUID],
    interests: list[str],
    spot_id: Optional[str] = None,
) -> str:
    """生成当前路线的个性化讲解上下文。"""

    if not route_id:
        return ""
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        return ""

    result = await db.execute(
        select(RouteNode, Spot)
        .outerjoin(Spot, RouteNode.spot_id == Spot.id)
        .where(RouteNode.route_id == route_id)
        .order_by(RouteNode.order)
    )
    nodes = result.all()
    node_text = "；".join(
        f"{node.order}.{spot.name if spot else node.spot_id}({node.stay_time}分钟，{node.description or '按现场动线游览'})"
        for node, spot in nodes
    )
    focus = "、".join(interests) if interests else "核心景点、游览动线"
    selected_spot = next((spot for node, spot in nodes if spot and node.spot_id == spot_id), None)
    selected_facts = ""
    if selected_spot:
        fact_parts = [
            selected_spot.core_function,
            selected_spot.cultural_connotation,
            selected_spot.detailed_intro,
            selected_spot.highlights,
            selected_spot.best_visit_time,
        ]
        selected_facts = "\n当前节点可靠资料：" + "；".join(
            str(part).strip() for part in fact_parts if part
        )[:1200]
    return (
        f"\n当前游客正在路线「{route.name}」中，路线标签：{'、'.join(route.tags or [])}。"
        f"游客兴趣：{focus}。请结合兴趣做个性化路线讲解，重点提醒下一站、停留时间和讲解重点。"
        f"\n路线节点：{node_text}{selected_facts}\n"
        "以上内容来自路线与景点数据库。不得补写其中没有出现的年代、人物、典故、距离或设施；资料不足时请直接说明。\n"
    )


async def _resolve_suggestion_places(
    db: AsyncSession,
    spot_id: Optional[str],
    route_id: Optional[uuid.UUID],
) -> tuple[Optional[str], Optional[str]]:
    """解析当前景点与活动路线下一站，供追问按钮使用。"""

    current_spot_name = None
    if spot_id:
        current_spot_name = await db.scalar(select(Spot.name).where(Spot.id == spot_id).limit(1))

    next_spot_name = None
    if route_id:
        rows = (
            await db.execute(
                select(RouteNode.spot_id, Spot.name)
                .outerjoin(Spot, RouteNode.spot_id == Spot.id)
                .where(RouteNode.route_id == route_id)
                .order_by(RouteNode.order)
            )
        ).all()
        if rows:
            current_index = next(
                (index for index, row in enumerate(rows) if row.spot_id == spot_id),
                -1,
            )
            next_index = current_index + 1
            if 0 <= next_index < len(rows):
                row = rows[next_index]
                next_spot_name = row.name or row.spot_id

    return current_spot_name, next_spot_name


def _get_dialogue_engine():
    """获取对话引擎单例（延迟导入避免循环依赖）"""
    global _dialogue_engine
    if _dialogue_engine is None:
        from app.core.dialogue_engine import DialogueEngine
        _dialogue_engine = DialogueEngine()
    return _dialogue_engine


def _get_emotion_engine():
    """获取情感引擎单例（延迟导入）"""
    global _emotion_engine
    if _emotion_engine is None:
        from app.core.emotion_engine import EmotionEngine
        _emotion_engine = EmotionEngine()
    return _emotion_engine


def _get_avatar_orchestrator():
    """获取数字人编排器单例（延迟导入）"""
    global _avatar_orchestrator
    if _avatar_orchestrator is None:
        from app.core.avatar_orchestrator import get_avatar_orchestrator
        _avatar_orchestrator = get_avatar_orchestrator()
    return _avatar_orchestrator


# ==================== 核心对话处理函数 ====================

async def _process_chat(
    message: str,
    session_id: uuid.UUID,
    spot_id: Optional[str],
    avatar: str,
    db: AsyncSession,
    route_id: Optional[uuid.UUID] = None,
    voice_emotion_hint: Optional[str] = None,
    voice_emotion_confidence: Optional[float] = None,
    voice_emotion_reason: Optional[str] = None,
    stream_callback: Optional[StreamCallback] = None,
    evaluation_mode: bool = False,
    response_mode: ResponseMode = "auto",
    recognized_spots: Optional[list[str]] = None,
) -> dict:
    """
    真实对话引擎处理流程

    串联 DialogueEngine -> EmotionEngine -> RAGEngine -> LLMRouter，
    完成意图识别、情感分析、知识检索、LLM生成回复的完整链路。
    """
    start_time = time.time()
    stage_timings: dict[str, int] = {}

    async def emit(event: dict[str, Any]) -> None:
        if stream_callback:
            await stream_callback(event)

    def mark_stage(name: str, stage_start: float) -> None:
        stage_timings[name] = int((time.time() - stage_start) * 1000)

    # 获取各引擎实例
    dialogue_engine = _get_dialogue_engine()
    emotion_engine = _get_emotion_engine()

    # 获取或创建对话上下文
    context = dialogue_engine.get_or_create_context(
        session_id=str(session_id),
        user_id=None,
    )
    context.current_avatar = avatar
    context.current_spot_id = spot_id
    if not evaluation_mode:
        await _restore_dialogue_history(db, session_id, context)
    retrieval_query = _resolve_contextual_query(message, context)
    scenic_area = _resolve_scenic_area(retrieval_query)
    resolved_response_mode = _resolve_response_mode(message, response_mode)
    current_spot_name, next_spot_name = await _resolve_suggestion_places(db, spot_id, route_id)

    # 1. 情感分析（文本 + 语音情感融合）
    emotion_result = {"type": "neutral", "confidence": 0.5, "intensity": 1}
    stage_start = time.time()
    await emit({"type": "stage", "stage": "emotion", "message": "情感分析"})
    try:
        if voice_emotion_hint is not None:
            # 语音对话场景：多模态情感融合
            emotion_result = await emotion_engine.analyze_multimodal(
                text=message,
                voice_emotion_hint=voice_emotion_hint,
                voice_emotion_confidence=voice_emotion_confidence,
                voice_emotion_reason=voice_emotion_reason,
            )
        else:
            # 文本对话场景：纯文本情感分析
            emotion_result = await emotion_engine.analyze_text(message)
        context.user_emotion = emotion_result.get("type", "neutral")
        arbitration = (emotion_result.get("details") or {}).get("arbitration") or {}
        logger.info(
            f"情感分析结果: type={context.user_emotion}, confidence={emotion_result.get('confidence')}, "
            f"decision={arbitration.get('decision', 'text_only')}"
        )
    except Exception as e:
        logger.warning(f"情感分析失败，使用默认值neutral: {e}")
        context.user_emotion = "neutral"
    mark_stage("emotion_ms", stage_start)

    # 融合情感必须在检索快答和LLM回答之前确定，保证数字人表达、回复策略和温度一致。
    stage_start = time.time()
    response_strategy = emotion_engine.get_response_strategy(context.user_emotion)
    emotion_temperature_map = {
        "excited": 1.2,
        "happy": 1.0,
        "curious": 1.1,
        "neutral": 0.8,
        "tired": 0.6,
        "frustrated": 0.7,
        "anxious": 0.6,
    }
    temperature = emotion_temperature_map.get(context.user_emotion, 0.8)
    logger.info(
        f"情感策略: style={response_strategy.get('dialogue_style')}, temperature={temperature}"
    )
    mark_stage("strategy_ms", stage_start)

    explicit_interests = _extract_interests(message)
    interests, interest_source = await _resolve_effective_interests(
        db,
        session_id,
        message,
        route_id,
    )
    if not evaluation_mode:
        await _save_emotion_history(
            db=db,
            session_id=session_id,
            message=message,
            emotion_result=emotion_result,
            spot_id=spot_id,
        )
        await _save_interest_profile(
            db=db,
            session_id=session_id,
            message=message,
            interests=explicit_interests,
            spot_id=spot_id,
        )

    # 2. 意图识别
    stage_start = time.time()
    await emit({"type": "stage", "stage": "intent", "message": "意图识别"})
    intent = dialogue_engine.recognize_intent(message)
    context.user_intent = intent
    context.add_message(
        "user",
        message,
        emotion=context.user_emotion,
        intent=intent.value,
    )
    context.turn_count += 1
    logger.info(f"意图识别结果: {intent.value}")
    mark_stage("intent_ms", stage_start)

    # 3. 状态转移
    stage_start = time.time()
    new_state = dialogue_engine.transition_state(context, intent)
    logger.info(f"状态转移: -> {new_state.value}")
    mark_stage("state_ms", stage_start)

    # 4. RAG知识检索（ASK_INFO / ASK_STORY 意图时触发）
    from app.core.dialogue_engine import UserIntent

    retrieved_context = ""
    rag_success = False
    rag_trace: dict[str, Any] = {}
    if intent in (
        UserIntent.ASK_INFO,
        UserIntent.ASK_STORY,
        UserIntent.ASK_ROUTE,
        UserIntent.ASK_RECOMMEND,
    ):
        stage_start = time.time()
        await emit({"type": "stage", "stage": "rag", "message": "检索知识库"})
        try:
            from app.core.rag_engine import RAGEngine

            rag_engine = RAGEngine(db_session=db, vector_dimension=1024)
            results = await rag_engine.hybrid_search(
                query=retrieval_query,
                top_k=5,
                spot_id=spot_id,
                scenic_area=scenic_area,
            )
            rag_trace = dict(getattr(rag_engine, "last_trace", {}) or {})
            rag_trace["scenic_area"] = scenic_area
            if retrieval_query != message:
                rag_trace["contextual_query"] = retrieval_query
            if results:
                await _hydrate_matching_spot_reference(db, retrieval_query, results)
                # 生成时只使用最相关的前三条证据，避免长上下文压过用户本轮问题；
                # 完整命中列表仍保留在 retrieved_docs 中用于溯源。
                retrieved_context = rag_engine.format_context(results[:3])
                context.retrieved_docs = _build_retrieved_docs(results, rag_trace)
                rag_success = True
                logger.info(f"RAG检索成功: 获取到 {len(results)} 条知识片段")
                # 简答与详答交给同一次 LLM 按长度提示生成；知识库快答只服务常规模式，
                # 避免快捷按钮过长或显式“展开”仍返回短模板。
                fast_reply = (
                    _try_build_fast_rag_reply(retrieval_query, results, context)
                    if resolved_response_mode == "normal"
                    else None
                )
                if fast_reply:
                    await emit({"type": "delta", "delta": fast_reply})
                    context.add_message(
                        "assistant",
                        fast_reply,
                        emotion=context.user_emotion,
                        intent=intent.value,
                    )
                    suggested_questions = dialogue_engine._generate_suggestions(
                        context,
                        intent,
                        current_spot_name=current_spot_name,
                        next_spot_name=next_spot_name,
                        recognized_spots=recognized_spots,
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    mark_stage("rag_ms", stage_start)
                    logger.info(f"高置信知识库快答完成: latency={latency_ms}ms")
                    return {
                        "content": fast_reply,
                        "emotion": context.user_emotion,
                        "intent": intent.value,
                        "state": new_state.value,
                        "suggested_questions": suggested_questions,
                        "latency_ms": latency_ms,
                        "rag_success": True,
                        "retrieved_docs_count": len(context.retrieved_docs),
                        "retrieved_docs": context.retrieved_docs,
                        "confidence": 0.92,
                        "answer_type": _infer_answer_type(message, intent.value, spot_id),
                        "emotion_analysis": emotion_result,
                        "response_strategy": response_strategy,
                        "performance_trace": {
                            **stage_timings,
                            "total_ms": latency_ms,
                            "rag": rag_trace,
                            "fast_reply": True,
                            "response_mode": resolved_response_mode,
                            "interest_profile": {
                                "interests": interests,
                                "source": interest_source,
                            },
                            "emotion_fusion": (emotion_result.get("details") or {}).get("arbitration"),
                        },
                    }
            else:
                logger.info("RAG检索无结果")
        except Exception as e:
            logger.error(f"RAG检索失败，严格模式不降级: {e}")
            raise RuntimeError(f"RAG检索失败: {e}") from e
        finally:
            mark_stage("rag_ms", stage_start)

    # 5. 构建 system_prompt（融入角色人设和融合后的情感策略）
    avatar_personality = await _resolve_avatar_personality(db, avatar)
    system_prompt = dialogue_engine.build_system_prompt(
        context=context,
        avatar_personality=avatar_personality,
    )
    system_prompt += (
        "\n本轮情感响应策略："
        f"表达风格为{response_strategy.get('dialogue_style')}；"
        f"内容深度为{response_strategy.get('content_depth')}；"
        f"服务建议为{response_strategy.get('recommendation')}。\n"
    )
    system_prompt += f"\n本轮长度要求：{_response_mode_instruction(resolved_response_mode)}\n"
    if interests:
        system_prompt += (
            f"\n游客当前兴趣画像：{'、'.join(interests)}（来源：{interest_source}）。"
            "核心事实必须保持不变，但讲解重点、语气和现场建议应明显贴合这些兴趣。\n"
        )

    # 7. 构建 user_prompt（融入RAG检索结果）
    route_context = await _build_route_context(db, route_id, interests, spot_id)
    user_prompt = dialogue_engine.build_user_prompt(
        user_input=message,
        context=context,
        retrieved_context=f"{route_context}{retrieved_context}",
    )

    # 8. 调用 LLM 生成回复
    from app.core.llm_router import llm_router

    try:
        await emit({"type": "stage", "stage": "llm", "message": "生成回复"})
        stage_start = time.time()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # 如果有历史对话，加入上下文（最近3轮）
        recent_history = context.get_recent_history(3)
        if recent_history and len(recent_history) > 1:
            # 将历史对话插入到 system 和 user 之间
            history_messages = []
            for msg in recent_history[:-1]:  # 排除当前这条（已经作为user_prompt）
                if msg["role"] in ("user", "assistant"):
                    history_messages.append({
                        "role": msg["role"],
                        "content": msg["content"][:500],  # 限制长度
                    })
            if history_messages:
                messages = [
                    {"role": "system", "content": system_prompt},
                    *history_messages,
                    {"role": "user", "content": user_prompt},
                ]

        max_tokens = _response_max_tokens(message, resolved_response_mode)
        if stream_callback:
            chunks: list[str] = []
            try:
                async for chunk in llm_router.chat_stream(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    thinking={"type": "disabled"},
                ):
                    if not isinstance(chunk, str) or not chunk:
                        continue
                    if "llm_first_token_ms" not in stage_timings:
                        stage_timings["llm_first_token_ms"] = int(
                            (time.time() - stage_start) * 1000
                        )
                    chunks.append(chunk)
                    await emit({"type": "delta", "delta": chunk})
                reply_text = "".join(chunks)
            except Exception:
                if chunks:
                    raise
                # 部分兼容网关会接受 chat/completions 却不返回增量字段。
                # 未向客户端发出任何分片时可安全切换为单次生成，避免整轮失败。
                logger.warning("LLM流式通道无增量，当前轮回退为非流式生成")
                reply_text = await llm_router.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    thinking={"type": "disabled"},
                )
                stage_timings["llm_first_token_ms"] = int(
                    (time.time() - stage_start) * 1000
                )
                await emit({"type": "delta", "delta": reply_text})
        else:
            reply_text = await llm_router.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking={"type": "disabled"},
            )
        logger.info(f"LLM生成完成: 回复长度={len(reply_text)}")
    except Exception as e:
        logger.error(f"LLM生成失败，严格模式不生成降级回复: {e}")
        raise RuntimeError(f"LLM生成失败: {e}") from e
    mark_stage("llm_ms", stage_start)

    # 9. 更新对话上下文
    context.add_message(
        "assistant",
        reply_text,
        emotion=context.user_emotion,
        intent=intent.value,
    )

    # 10. 生成建议追问
    suggested_questions = dialogue_engine._generate_suggestions(
        context,
        intent,
        current_spot_name=current_spot_name,
        next_spot_name=next_spot_name,
        recognized_spots=recognized_spots,
    )

    # 11. 计算延迟
    latency_ms = int((time.time() - start_time) * 1000)

    # 组装结果
    result = {
        "content": reply_text,
        "emotion": context.user_emotion,
        "intent": intent.value,
        "state": new_state.value,
        "suggested_questions": suggested_questions,
        "latency_ms": latency_ms,
        "rag_success": rag_success or bool(route_context),
        "retrieved_docs_count": len(context.retrieved_docs),
        "retrieved_docs": context.retrieved_docs,
        "confidence": 0.9 if route_context else _compute_confidence({"retrieved_docs": context.retrieved_docs, "rag_success": rag_success}),
        "answer_type": _infer_answer_type(message, intent.value, spot_id),
        "emotion_analysis": emotion_result,
        "response_strategy": response_strategy,
        "performance_trace": {
            **stage_timings,
            "total_ms": latency_ms,
            "rag": rag_trace,
            "route_db_context": bool(route_context),
            "fast_reply": False,
            "response_mode": resolved_response_mode,
            "interest_profile": {
                "interests": interests,
                "source": interest_source,
            },
            "scenic_area": scenic_area,
            "emotion_fusion": (emotion_result.get("details") or {}).get("arbitration"),
        },
    }

    logger.info(
        f"对话处理完成: session={session_id}, "
        f"intent={intent.value}, emotion={context.user_emotion}, "
        f"state={new_state.value}, latency={latency_ms}ms"
    )

    return result


async def run_chat_evaluation(
    message: str,
    spot_id: Optional[str],
    avatar: str,
    db: AsyncSession,
) -> dict:
    """以真实问答主链路执行一次不落游客数据、不生成数字人的管理端复测。"""

    evaluation_session_id = uuid.uuid4()
    try:
        return await _process_chat(
            message=message,
            session_id=evaluation_session_id,
            spot_id=spot_id,
            avatar=avatar,
            db=db,
            evaluation_mode=True,
        )
    finally:
        dialogue_engine = _get_dialogue_engine()
        dialogue_engine.contexts.pop(str(evaluation_session_id), None)


async def run_chat_evaluation_conversation(
    messages: list[str],
    spot_id: Optional[str],
    avatar: str,
    db: AsyncSession,
) -> dict:
    """在同一临时上下文中复测多轮追问，不落游客数据或数字人任务。"""

    if not messages:
        raise ValueError("多轮评测至少需要一条消息")
    evaluation_session_id = uuid.uuid4()
    try:
        result: dict[str, Any] = {}
        for message in messages:
            result = await _process_chat(
                message=message,
                session_id=evaluation_session_id,
                spot_id=spot_id,
                avatar=avatar,
                db=db,
                evaluation_mode=True,
                response_mode="normal",
            )
        return result
    finally:
        dialogue_engine = _get_dialogue_engine()
        dialogue_engine.contexts.pop(str(evaluation_session_id), None)


def _try_build_fast_rag_reply(message: str, results: list, context: Any = None) -> Optional[str]:
    """对高频事实问题走知识库快答，确保演示时核心问答稳定低延迟。"""

    if not results:
        return None
    # 行程开启/到站等伴游引导语需结合行程上下文由大模型组织，不走景点事实快答
    if message.startswith(("我已开始「", "我已到达路线节点「", "我已切换到路线节点「")):
        return None
    conflict_reply = _try_build_conflict_reply(message, results)
    if conflict_reply:
        return conflict_reply
    dynamic_reply = _try_build_dynamic_info_reply(message, results)
    if dynamic_reply:
        return dynamic_reply
    verified_reply = _try_build_verified_fact_reply(message, results)
    if verified_reply:
        return verified_reply
    route_spot_reply = _try_build_route_spot_reply(message, results)
    if route_spot_reply:
        return route_spot_reply
    # 同一景点的连续提问优先交给大模型结合上下文重新组织，避免结构化快答
    # 原样重复；数字、位置等精确事实仍保持稳定回答。
    if _recent_assistant_covered_spot(message, context) and not _is_precise_fact_question(message):
        return None
    spot_fact_reply = _try_build_spot_fact_reply(message, results)
    if spot_fact_reply:
        return spot_fact_reply
    direct_terms = (
        "门票",
        "票价",
        "开放时间",
        "营业时间",
        "表演时间",
        "多高",
        "高度",
        "交通",
        "怎么到达",
        "餐饮",
        "素斋",
        "停车",
        "停车场",
        "地址",
        "在哪里",
        "拍照",
        "打卡",
        "无障碍",
        "轮椅",
    )
    complex_terms = ("为什么", "详细", "深入", "比较", "写", "创作", "规划", "路线", "故事")
    if not any(term in message for term in direct_terms):
        return None
    if any(term in message for term in complex_terms):
        return None

    top = results[0]
    content = _clean_retrieved_content(str(top.content))
    if len(content) > 180:
        content = content[:180].rstrip("，。；、 ") + "。"
    title = top.doc_title or "景区资料"
    return f"根据《{title}》的资料，{content}"


def _try_build_conflict_reply(message: str, results: list) -> Optional[str]:
    """资料口径冲突时并列展示差异，不擅自选择答案。"""

    conflict_terms = ("哪个准确", "哪个对", "到底", "不一致", "确定", "确认", "为什么")
    if not any(term in message for term in conflict_terms):
        return None
    for result in results:
        metadata = getattr(result, "metadata_json", None) or {}
        conflicts = metadata.get("conflicts") or []
        if metadata.get("conflict_status") in {None, "none", "resolved"} or not conflicts:
            continue
        conflict = conflicts[0]
        structured = str(conflict.get("structured_value") or "结构化资料未标注")
        narrative = str(conflict.get("narrative_value") or "叙述资料未标注")
        return (
            f"不能直接确认其中一个口径。A5官方资料包存在未核实冲突：结构化数据写为“{structured}”，"
            f"而叙述性指南写为“{narrative}”。当前系统保留两种资料口径，不把任一数值擅自判定为最终事实。"
        )
    return None


def _resolve_response_mode(message: str, requested_mode: ResponseMode = "auto") -> ResponseMode:
    """把自动模式解析为本轮实际回答长度，不触发额外模型调用。"""

    if requested_mode != "auto":
        return requested_mode
    detail_terms = (
        "详细",
        "展开",
        "完整",
        "深入",
        "全面",
        "来龙去脉",
        "多介绍",
        "多讲讲",
        "系统讲",
    )
    return "detail" if any(term in message for term in detail_terms) else "normal"


def _response_mode_instruction(mode: ResponseMode) -> str:
    """返回不会与流式输出冲突的长度提示。"""

    instructions = {
        "brief": "只写1-2句，总长度必须控制在40-80个中文字符；第一句直接回答核心结论，第二句可给一个自然追问，不列清单、不复述问题。",
        "normal": "先给结论再补充必要背景，控制在80-140个中文字符、2-4句，避免重复上一轮表达。",
        "detail": "分层展开关键背景与现场看点，控制在180-300个中文字符，信息完整但不堆砌资料。",
        "auto": "控制在80-140个中文字符、2-4句。",
    }
    return instructions[mode]


def _response_max_tokens(message: str, response_mode: ResponseMode = "auto") -> int:
    """按本轮模式设置单次生成预算；流式结束后不再裁剪正文。"""

    resolved = _resolve_response_mode(message, response_mode)
    return {"brief": 120, "normal": 220, "detail": 480, "auto": 220}[resolved]


def _recent_assistant_covered_spot(message: str, context: Any) -> bool:
    """判断最近回复是否已经介绍过本轮景点。"""

    if context is None:
        return False
    spot_aliases = (
        ("灵山大佛", "大佛"),
        ("九龙灌浴",),
        ("灵山梵宫", "梵宫"),
        ("五印坛城", "坛城"),
        ("佛足坛",),
        ("祥符禅寺", "禅寺"),
        ("阿育王柱", "王柱"),
        ("无尽意斋", "意斋"),
    )
    targets = [
        aliases
        for aliases in spot_aliases
        if any(alias in message for alias in aliases)
    ]
    if not targets:
        return False
    recent = getattr(context, "history", [])[-12:]
    assistant_texts = [
        str(item.get("content") or "")
        for item in recent
        if item.get("role") == "assistant"
    ]
    return any(
        any(alias in content for alias in aliases)
        for aliases in targets
        for content in assistant_texts
    )


def _is_precise_fact_question(message: str) -> bool:
    """精确事实重复询问仍应稳定返回，不为了变化而改写数字。"""

    precise_terms = (
        "多高",
        "高度",
        "参数",
        "材质",
        "用铜",
        "耗铜",
        "铸铜",
        "地址",
        "在哪",
        "哪里",
        "位于",
        "位置",
        "怎么到",
        "门票",
        "票价",
        "开放时间",
        "营业时间",
        "几点",
    )
    return any(term in message for term in precise_terms)


def _try_build_dynamic_info_reply(message: str, results: list) -> Optional[str]:
    """实时问题拒绝冒充；普通查询可展示带日期声明的历史演示基线。"""

    realtime_terms = (
        "今天",
        "今日",
        "现在",
        "实时",
        "几点",
        "场次",
        "当天",
        "当前",
    )
    baseline_terms = (
        "门票",
        "票价",
        "多少钱",
        "开放时间",
        "营业时间",
        "演出时间",
        "表演时间",
        "吉祥颂",
    )
    if any(term in message for term in realtime_terms):
        return (
            "灵山胜境原官网已公告自2026年2月1日起停止服务，我目前无法通过该网站核验当天的票务、"
            "开放区域或演出场次。资料库中的历史时间和价格可能已经变化，请致电景区咨询电话"
            "400-168-0303，或以到访当天的景区现场公告为准。"
        )
    if not any(term in message for term in baseline_terms):
        return None
    if not results:
        return None
    topic_terms = (
        ("门票", "票价", "多少钱", "收费", "购票", "预约")
        if any(term in message for term in ("门票", "票价", "多少钱", "收费", "购票", "预约"))
        else ("开放时间", "营业时间", "开园", "闭园")
        if any(term in message for term in ("开放时间", "营业时间", "开园", "闭园"))
        else ("演出时间", "表演时间", "吉祥颂", "九龙灌浴", "场次")
    )

    def relevance(result) -> int:
        title = str(result.doc_title or "")
        content = str(result.content or "")
        score = sum(5 for term in topic_terms if term in title)
        score += sum(1 for term in topic_terms if term in content)
        if "停服" in title or "不用于证明当前票价" in content:
            score -= 12
        return score

    top = max(results, key=relevance)
    content = _clean_retrieved_content(str(top.content))[:260].rstrip("，。；、 ") + "。"
    return (
        f"以下是资料库中的历史演示基线（有效日期按2025年公开资料记录，非当日实时信息）：{content} "
        "出发前请以景区现场公告、官方小程序或400-168-0303咨询结果为准。"
    )


def _clean_retrieved_content(content: str) -> str:
    """移除父块摘要包装，保留实际子块并压平空白。"""

    child = content.split("\n\n", 1)[-1] if "\n\n" in content else content
    return " ".join(child.split())


async def _hydrate_matching_spot_reference(
    db: AsyncSession,
    message: str,
    results: list,
) -> None:
    """将命中景点的首条子块替换为完整 Word 结构化记录。"""

    hydrated_documents: set[str] = set()
    for result in results:
        if result.doc_type != "spot_reference" or not result.document_id:
            continue
        name = str(result.doc_title or "").rsplit("-", 1)[-1]
        short_name = name.removeprefix("灵山")
        if not name or (name not in message and (not short_name or short_name not in message)):
            continue
        document_key = str(result.document_id)
        if document_key in hydrated_documents:
            continue
        try:
            document_id = uuid.UUID(document_key)
        except ValueError:
            continue
        document = await db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).limit(1)
        )
        if document and document.content:
            result.content = document.content
            hydrated_documents.add(document_key)


def _try_build_verified_fact_reply(message: str, results: list) -> Optional[str]:
    """优先抽取能同时覆盖问题实体的权威事实片段。"""

    named_terms = (
        "灵山大佛",
        "九龙灌浴",
        "灵山梵宫",
        "五印坛城",
        "佛足坛",
        "祥符禅寺",
        "阿育王柱",
        "无尽意斋",
        "赵朴初",
        "玄奘",
    )
    required = [term for term in named_terms if term in message]
    content_terms: list[str] = []
    if any(term in message for term in ("地址", "在哪里", "怎么到")):
        content_terms.append("灵山路1号")
    if "四大主体景观" in message:
        content_terms.append("四大主体景观")
    if len(required) < 2 and not content_terms:
        return None

    candidates = []
    for result in results:
        content = _clean_retrieved_content(str(result.content or ""))
        if required and not all(term in content for term in required):
            continue
        if content_terms and not all(term in content for term in content_terms):
            continue
        metadata = getattr(result, "metadata_json", None) or {}
        source_rank = 3 if metadata.get("source_package") else 2 if result.doc_type == "official_web" else 1
        candidates.append((source_rank, float(result.score or 0), result, content))
    if not candidates:
        return None
    _, _, result, content = max(candidates, key=lambda item: (item[0], item[1]))
    content = _truncate_fact(content, 320)
    return f"根据《{result.doc_title}》的核验资料，{content}"


def _truncate_fact(value: str, limit: int = 240) -> str:
    """在句子边界压缩结构化事实字段，避免快答过长。"""

    value = " ".join(value.split()).strip("，。；; ")
    if len(value) <= limit:
        return value
    clipped = value[:limit]
    boundary = max(clipped.rfind("。"), clipped.rfind("；"), clipped.rfind("，"))
    if boundary >= limit // 2:
        clipped = clipped[:boundary]
    return clipped.rstrip("，。；; ") + "…"


def _try_build_spot_fact_reply(message: str, results: list) -> Optional[str]:
    """从 Word 景点结构化字段直接回答，避免大模型补写未提供的事实。"""

    matched = None
    for result in results:
        metadata = getattr(result, "metadata_json", None) or {}
        source_spot_id = result.spot_id or metadata.get("source_spot_id")
        if result.doc_type != "spot_reference" or not source_spot_id:
            continue
        content = str(result.content or "")
        name = _extract_spot_field(content, "景点名称")
        short_name = name.removeprefix("灵山") if name else ""
        if name and (name in message or (short_name and short_name in message)):
            matched = (source_spot_id, name, result.doc_title)
            break
    if not matched:
        return None

    spot_id, name, _title = matched
    related = [
        str(result.content or "")
        for result in results
        if result.doc_type == "spot_reference"
        and (
            result.spot_id
            or (getattr(result, "metadata_json", None) or {}).get("source_spot_id")
        ) == spot_id
    ]
    focused_terms = (
        "多高",
        "高度",
        "多少",
        "参数",
        "材质",
        "用铜",
        "耗铜",
        "铸铜",
        "建筑特色",
        "建筑",
        "特色",
        "亮点",
        "看点",
        "在哪",
        "位置",
        "地址",
        "怎么到",
        "什么时候",
        "始建",
        "历史",
        "沿革",
        "由来",
        "文化",
        "寓意",
        "象征",
        "关系",
        "纪念",
        "是谁",
        "注意",
        "建议",
        "适合",
        "轮椅",
        "老人",
        "怎么玩",
    )
    # “介绍一下某景点”属于开放式讲解，由 LLM 基于证据自然改写；
    # 只有字段明确的问题才走确定性快答。
    if not any(term in message for term in focused_terms):
        return None

    def field(label: str) -> str:
        candidates = [_extract_spot_field(content, label) for content in related]
        candidates = [value for value in candidates if value]
        return _truncate_fact(max(candidates, key=len)) if candidates else ""

    height_question = any(term in message for term in ("多高", "高度"))
    material_question = any(term in message for term in ("材质", "用铜", "耗铜", "铸铜"))
    feature_question = any(term in message for term in ("特色", "亮点", "看点"))
    position_question = any(term in message for term in ("在哪", "哪里", "位于", "位置", "地址", "怎么到"))

    labels: list[str]
    if any(
        term in message
        for term in ("多高", "高度", "多少", "参数", "材质", "用铜", "耗铜", "铸铜", "建筑特色", "建筑")
    ):
        labels = ["建筑/景观参数", "游玩亮点", "特色亮点"]
    elif position_question:
        labels = ["具体位置", "游览建议"]
    elif feature_question:
        labels = ["游玩亮点", "建筑/景观参数", "特色亮点", "详细介绍"]
    elif any(term in message for term in ("什么时候", "始建", "历史", "沿革", "由来")):
        labels = ["历史沿革", "文化内涵"]
    elif any(term in message for term in ("文化", "寓意", "象征", "关系", "纪念", "是谁")):
        labels = ["文化内涵", "历史沿革", "核心功能"]
    elif any(term in message for term in ("注意", "建议", "适合", "轮椅", "老人", "怎么玩")):
        labels = ["游览建议", "适合人群", "备注"]
    else:
        labels = ["游玩亮点", "建筑/景观参数", "特色亮点", "核心功能", "文化内涵"]

    facts = [field(label) for label in labels]
    facts = [fact for index, fact in enumerate(facts) if fact and fact not in facts[:index]][:2]
    if height_question and facts:
        concise_height = _select_fact_clauses(facts[0], ("高", "米", "m"), limit=2)
        facts = [concise_height or facts[0]]
    elif material_question and facts:
        concise_material = _select_fact_clauses(facts[0], ("铜", "材质", "面板"), limit=2)
        facts = [concise_material or facts[0]]
    elif feature_question and facts:
        # “特色”至少保留一个游览亮点和一个结构/材质事实；分别限长，
        # 避免只剩体验话术而漏掉花岗岩、铜材、尺度等可核验信息。
        facts = [_truncate_fact(fact, 72) for fact in facts[:2]]
    elif position_question:
        facts = facts[:1]
    if not facts:
        return None
    body = "；".join(facts).rstrip("。；") + "。"
    return f"{name}：{body}"


def _select_fact_clauses(value: str, keywords: tuple[str, ...], limit: int = 2) -> str:
    """从结构化长字段中只保留与本轮问题直接相关的短分句。"""

    clauses = [item.strip() for item in re.split(r"[，,；;。]", value) if item.strip()]
    matched = [
        clause
        for clause in clauses
        if any(keyword in clause for keyword in keywords)
    ]
    return "，".join(matched[:limit])


def _extract_spot_field(content: str, label: str) -> str:
    """从公开资料包的结构化景点文本中提取单个字段。"""

    labels = (
        "景区名称|景点ID|景点名称|具体位置|建筑/景观参数|核心功能|"
        "文化内涵|历史沿革|详细介绍|特色亮点|游玩亮点|游览建议|"
        "适合人群|演艺/开放信息|备注"
    )
    matched = re.search(
        rf"{re.escape(label)}[：:]\s*(.*?)(?=\s+(?:{labels})[：:]|\n\n|$)",
        content,
        flags=re.DOTALL,
    )
    if not matched:
        return ""
    value = " ".join(matched.group(1).split()).strip("，。；; ")
    # 资料整合时可能追加非结构化补充标签；不要把标签本身回显给游客。
    for marker in ("导览资料补充", "资料包叙述补充"):
        if marker in value:
            value = value.split(marker, 1)[0].rstrip("，。；; ")
    return value


def _try_build_route_spot_reply(message: str, results: list) -> Optional[str]:
    """对已指定景点的路线讲解直接抽取结构化证据，避免重复调用LLM。"""

    if "路线节点" not in message or not any(term in message for term in ("介绍", "看点", "游览提醒")):
        return None
    top = results[0]
    if float(top.score or 0) < 0.72 or not top.spot_id:
        return None

    content = str(top.content or "")
    name = _extract_spot_field(content, "景点名称") or str(top.doc_title or "当前景点").split("-")[-1]
    position = _extract_spot_field(content, "具体位置")
    parameters = _extract_spot_field(content, "建筑/景观参数")
    function = _extract_spot_field(content, "核心功能")
    if not any((position, parameters, function)):
        return None

    sentences: list[str] = []
    if position:
        sentences.append(f"{name}位于{position}。")
    else:
        sentences.append(f"{name}是本路线的重要节点。")
    if function:
        sentences.append(f"它主要承担{function}。")
    if parameters:
        sentences.append(f"公开资料记载：{parameters}。")
    sentences.append("参观时可重点观察建筑尺度、材质细节及其与周边景观的关系。")
    sentences.append("开放区域、人流管控和摄影规则可能临时调整，请以景区当天公告与现场导视为准。")
    return "".join(sentences)


def _build_retrieved_docs(results: list, rag_trace: dict[str, Any]) -> list[dict[str, Any]]:
    """构建可写入聊天记录的RAG溯源信息。"""

    return [
        {
            "rank": index + 1,
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "doc_title": r.doc_title,
            "doc_type": r.doc_type,
            "spot_id": r.spot_id,
            "metadata": getattr(r, "metadata_json", None) or {},
            "score": round(float(r.score or 0), 4),
            "vector_score": round(float(r.vector_score or 0), 4),
            "text_score": round(float(r.text_score or 0), 4),
            "content": str(r.content or "")[:260],
            "mode": rag_trace.get("mode", "unknown"),
            "cache_hit": bool(rag_trace.get("cache_hit")),
            "embedding_cache_hit": bool(rag_trace.get("embedding_cache_hit")),
            "rag_ms": rag_trace.get("total_ms"),
            "lexical_ms": rag_trace.get("lexical_ms"),
            "vector_ms": rag_trace.get("vector_ms"),
        }
        for index, r in enumerate(results)
    ]


def _build_trace_payload(engine_result: dict, digital_human_ms: Optional[int] = None) -> list[dict[str, Any]]:
    """合并检索命中和性能数据，写入ChatMessage.retrieved_docs。"""

    trace = dict(engine_result.get("performance_trace") or {})
    if digital_human_ms is not None:
        trace["digital_human_ms"] = digital_human_ms
    return [
        {
            "query_trace": {
                "rag_success": engine_result.get("rag_success", False),
                "retrieved_docs_count": engine_result.get("retrieved_docs_count", 0),
                "confidence": engine_result.get("confidence"),
                "answer_type": engine_result.get("answer_type"),
                "intent": engine_result.get("intent"),
                "emotion": engine_result.get("emotion"),
                **trace,
            },
            "sources": engine_result.get("retrieved_docs") or [],
            **({"multimodal_evidence": engine_result.get("multimodal_evidence")} if engine_result.get("multimodal_evidence") else {}),
        }
    ]


def _extract_response_metadata(retrieved_docs: Any) -> tuple[list[dict[str, Any]], Optional[float], Optional[str], Optional[dict[str, Any]]]:
    """从ChatMessage.retrieved_docs解析面向游客端的证据字段。"""

    if not isinstance(retrieved_docs, list) or not retrieved_docs:
        return [], None, None, None
    first = retrieved_docs[0]
    if not isinstance(first, dict):
        return [], None, None, None
    trace = first.get("query_trace") or {}
    sources = first.get("sources") or []
    confidence = trace.get("confidence")
    if confidence is None and sources:
        confidence = max((float(source.get("score") or 0) for source in sources), default=0)
    return sources, confidence, trace.get("answer_type"), first.get("multimodal_evidence")


def _infer_answer_type(message: str, intent: str | None, spot_id: str | None = None) -> str:
    """按场景给回答分类，供游客端和大屏统计。"""

    text = message or ""
    if intent == "ask_route" or any(term in text for term in ("路线", "怎么走", "行程", "游览")):
        return "route"
    if intent == "ask_story" or any(term in text for term in ("故事", "传说", "典故", "历史")):
        return "story"
    if spot_id or any(term in text for term in ("景点", "大佛", "梵宫", "禅寺", "坛城")):
        return "spot_guide"
    if any(term in text for term in ("门票", "开放时间", "停车", "餐饮", "卫生间", "无障碍")):
        return "service"
    if any(term in text for term in ("多高", "多少", "几点", "在哪", "是什么")):
        return "fact"
    return "general"


def _compute_confidence(engine_result: dict) -> float:
    """按检索通道与来源等级校准可信度，避免直接展示不可解释的RRF小分值。"""

    docs = engine_result.get("retrieved_docs") or []
    if docs:
        best = 0.0
        for doc in docs:
            vector_score = float(doc.get("vector_score") or 0)
            text_score = float(doc.get("text_score") or 0)
            evidence_score = max(vector_score, text_score)
            if vector_score > 0 and text_score > 0:
                evidence_score += 0.08
            metadata = doc.get("metadata") or {}
            if metadata.get("source_package"):
                evidence_score = max(evidence_score, 0.92)
            elif doc.get("doc_type") == "official_web":
                evidence_score = max(evidence_score, 0.88)
            elif doc.get("doc_type") == "spot_reference" and doc.get("spot_id"):
                evidence_score = max(evidence_score, 0.84)
            best = max(best, evidence_score)
        return round(min(0.96, max(0.35, best)), 3)
    return 0.62 if engine_result.get("rag_success") else 0.35


def _chat_message_response(message: ChatMessage) -> ChatMessageResponse:
    """将ORM聊天消息转换为响应模型。"""

    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        content_type=message.content_type,
        audio_url=message.audio_url,
        video_url=message.video_url,
        emotion=message.emotion,
        intent=message.intent,
        spot_id=message.spot_id,
        retrieved_docs=_extract_response_metadata(message.retrieved_docs)[0],
        latency_ms=message.latency_ms,
        created_at=message.created_at,
    )


def _chat_response(
    *,
    session_id: uuid.UUID,
    assistant_message: ChatMessage,
    avatar: str,
    suggested_questions: list[str],
    digital_human: Optional[dict[str, Any]],
    recognized_text: Optional[str] = None,
) -> ChatResponse:
    """统一组装扩展后的对话响应。"""

    docs, confidence, answer_type, multimodal_evidence = _extract_response_metadata(assistant_message.retrieved_docs)
    return ChatResponse(
        session_id=session_id,
        message=_chat_message_response(assistant_message),
        avatar=avatar,
        suggested_questions=suggested_questions,
        digital_human=digital_human,
        recognized_text=recognized_text,
        retrieved_docs=docs,
        confidence=confidence,
        answer_type=answer_type,
        trace_id=assistant_message.id,
        multimodal_evidence=multimodal_evidence,
    )


# ==================== 多模态辅助函数 ====================

def _detect_audio_format(audio: UploadFile) -> str:
    """根据文件名和content-type识别音频格式。"""
    filename = (audio.filename or "").lower()
    content_type = (audio.content_type or "").lower()
    if filename.endswith(".wav") or "wav" in content_type:
        return "wav"
    if filename.endswith(".webm") or "webm" in content_type or "opus" in content_type:
        return "webm"
    if filename.endswith(".mp3") or "mpeg" in content_type:
        return "mp3"
    if filename.endswith(".m4a") or "mp4" in content_type:
        return "m4a"
    return "pcm"


async def _convert_audio_to_pcm16k(audio_data: bytes, source_format: str) -> bytes:
    """
    将浏览器录音转成讯飞IAT可识别的16kHz/16bit/mono PCM。

    MediaRecorder在Chrome/Edge里通常产出webm/opus；讯飞ASR WebSocket示例
    使用 raw PCM，因此这里统一用ffmpeg转换。
    """
    if source_format == "pcm":
        return audio_data

    def _run_ffmpeg() -> bytes:
        input_suffix = f".{source_format}"
        input_path = ""
        output_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=input_suffix) as src:
                src.write(audio_data)
                input_path = src.name
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pcm") as dst:
                output_path = dst.name

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "ffmpeg转换失败")[:500])
            with open(output_path, "rb") as f:
                return f.read()
        finally:
            for path in (input_path, output_path):
                if path and os.path.exists(path):
                    os.remove(path)

    return await asyncio.to_thread(_run_ffmpeg)


def _analyze_voice_acoustics(pcm_data: bytes, sample_rate: int = 16000) -> dict[str, Any]:
    """从16bit单声道PCM提取可解释的基础声学情感线索。"""

    usable = pcm_data[: len(pcm_data) - (len(pcm_data) % 2)]
    if len(usable) < sample_rate // 5 * 2:
        return {
            "emotion": "neutral",
            "confidence": 0.3,
            "reason": "audio_too_short",
            "duration_sec": round(len(usable) / sample_rate / 2, 3),
            "algorithm": "pcm-energy-v1",
        }

    samples = array("h")
    samples.frombytes(usable)
    if sys.byteorder != "little":
        samples.byteswap()

    frame_size = 320  # 20ms @ 16kHz
    frame_rms: list[float] = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if len(frame) < frame_size // 2:
            continue
        frame_rms.append(math.sqrt(sum(value * value for value in frame) / len(frame)))

    if not frame_rms:
        return {
            "emotion": "neutral",
            "confidence": 0.3,
            "reason": "no_complete_audio_frame",
            "duration_sec": round(len(samples) / sample_rate, 3),
            "algorithm": "pcm-energy-v1",
        }

    ordered_rms = sorted(frame_rms)
    noise_floor = ordered_rms[max(0, int(len(ordered_rms) * 0.15) - 1)]
    voiced_threshold = max(350.0, noise_floor * 2.2)
    voiced_flags = [value >= voiced_threshold for value in frame_rms]
    voiced_values = [value for value, voiced in zip(frame_rms, voiced_flags) if voiced]
    voiced_ratio = sum(voiced_flags) / len(voiced_flags)
    segment_switches = sum(
        1 for index in range(1, len(voiced_flags)) if voiced_flags[index] != voiced_flags[index - 1]
    )
    duration_sec = len(samples) / sample_rate
    segment_switch_rate = segment_switches / max(duration_sec, 0.1)
    mean_voiced_rms = sum(voiced_values) / len(voiced_values) if voiced_values else 0.0
    p90_rms = ordered_rms[min(len(ordered_rms) - 1, int(len(ordered_rms) * 0.9))]
    peak = max(abs(value) for value in samples)
    zero_crossings = sum(
        1
        for index in range(1, len(samples))
        if (samples[index - 1] < 0 <= samples[index]) or (samples[index - 1] >= 0 > samples[index])
    )
    zero_crossing_rate = zero_crossings / max(len(samples), 1)

    emotion = "neutral"
    confidence = 0.55
    reason = "moderate_energy_and_pacing"
    if voiced_ratio < 0.08:
        confidence = 0.38
        reason = "insufficient_voiced_audio"
    elif mean_voiced_rms >= 4200 and (p90_rms >= 7000 or segment_switch_rate >= 3.5):
        emotion = "excited"
        energy_support = min(0.10, max(0.0, (mean_voiced_rms - 4200) / 30000))
        peak_support = min(0.05, max(0.0, (p90_rms - 7000) / 50000))
        pacing_support = min(0.03, max(0.0, (segment_switch_rate - 3.5) / 50))
        confidence = min(0.80, 0.62 + energy_support + peak_support + pacing_support)
        reason = "high_energy_or_fast_segment_changes"
    elif mean_voiced_rms <= 900 and voiced_ratio >= 0.15:
        emotion = "tired"
        low_energy_support = min(0.12, max(0.0, (900 - mean_voiced_rms) / 4500))
        duration_support = min(0.04, max(0.0, (duration_sec - 0.5) / 25))
        confidence = min(0.78, 0.60 + low_energy_support + duration_support)
        reason = "sustained_low_voice_energy"

    return {
        "emotion": emotion,
        "confidence": round(confidence, 3),
        "reason": reason,
        "duration_sec": round(duration_sec, 3),
        "mean_voiced_rms": round(mean_voiced_rms, 1),
        "p90_rms": round(p90_rms, 1),
        "peak": int(peak),
        "voiced_ratio": round(voiced_ratio, 3),
        "segment_switches_per_sec": round(segment_switch_rate, 3),
        "zero_crossing_rate": round(zero_crossing_rate, 4),
        "algorithm": "pcm-energy-v1",
    }


async def _transcribe_voice(
    audio: UploadFile,
    audio_data: bytes,
    transcript_hint: Optional[str] = None,
) -> tuple[str, str, Optional[float], bytes]:
    """
    真实语音识别。

    严格调用后端讯飞ASR，不使用浏览器识别文本兜底。
    """
    from app.core.xunfei_asr import get_asr_client

    audio_format = _detect_audio_format(audio)
    try:
        asr_audio_data = await _convert_audio_to_pcm16k(audio_data, audio_format)
        asr_client = get_asr_client()
        text = await asr_client.transcribe(asr_audio_data, audio_format="pcm")
        if text.strip():
            # 当前讯飞实时听写客户端仅返回识别文本，没有提供句级置信度。
            return text.strip(), "xunfei-asr", None, asr_audio_data
    except Exception as exc:
        logger.warning(f"ASR识别失败: {exc}")

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="讯飞ASR语音识别不可用",
    )


async def _build_digital_human_payload(
    *,
    text: str,
    avatar: str,
    emotion: str,
    session_id: uuid.UUID,
    intent: str = "",
    prefer_video: bool,
    db: Optional[AsyncSession] = None,
) -> dict:
    """生成数字人多模态输出。"""
    orchestrator = _get_avatar_orchestrator()
    audio_url = orchestrator.build_tts_url(text, avatar, emotion)
    return await orchestrator.render_reply(
        text=text,
        avatar_name=avatar,
        emotion=emotion,
        session_id=str(session_id),
        audio_url=audio_url,
        intent=intent,
        prefer_video=prefer_video,
        db_session=db,
    )


def _fit_db_url(value: Optional[str], limit: int = 500) -> Optional[str]:
    """数据库URL字段当前为varchar(500)，超长播放地址只放响应载荷，不入库。"""
    if not value:
        return None
    return value if len(value) <= limit else None


# ==================== API端点 ====================

@router.post("/text", response_model=ChatResponse, summary="文本对话")
async def text_chat(
    request: TextChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    文本对话接口

    接收用户文本消息，通过 DialogueEngine + EmotionEngine + RAGEngine + LLMRouter
    完成完整的对话处理链路，返回AI数字人回复。
    支持多轮对话，通过session_id保持上下文。
    """
    # 获取或创建会话
    session = None
    if request.session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == request.session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在",
            )
    avatar = await _select_chat_avatar(
        db,
        request.spot_id,
        request.avatar,
        session.current_avatar if session else None,
    )
    if session is None:
        session = ChatSession(
            user_id=current_user.get("user_id") if current_user else None,
            current_spot_id=request.spot_id,
            current_avatar=avatar,
        )
        db.add(session)
        await db.flush()
    else:
        session.current_avatar = avatar

    # 保存用户消息
    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        content=request.message,
        content_type="text",
        spot_id=request.spot_id,
    )
    db.add(user_message)

    # 调用真实对话引擎
    engine_result = await _process_chat(
        message=request.message,
        session_id=session.id,
        spot_id=request.spot_id,
        avatar=avatar,
        db=db,
        route_id=request.route_id,
        response_mode=request.response_mode,
    )
    digital_stage_start = time.time()
    digital_human = await _build_digital_human_payload(
        text=engine_result["content"],
        avatar=avatar,
        emotion=engine_result.get("emotion") or "neutral",
        session_id=session.id,
        intent=engine_result.get("intent") or "",
        prefer_video=True,
        db=db,
    )
    digital_human_ms = int((time.time() - digital_stage_start) * 1000)

    # 保存助手回复
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=engine_result["content"],
        content_type="text",
        audio_url=_fit_db_url(digital_human.get("audio_url")),
        video_url=_fit_db_url(digital_human.get("video_url")),
        emotion=engine_result.get("emotion"),
        intent=engine_result.get("intent"),
        spot_id=request.spot_id,
        retrieved_docs=_build_trace_payload(engine_result, digital_human_ms),
        latency_ms=engine_result.get("latency_ms", 1500),
    )
    db.add(assistant_message)

    # 更新会话状态
    session.turn_count += 1
    session.dialogue_state = engine_result.get("state", "chatting")
    if request.spot_id:
        session.current_spot_id = request.spot_id

    await db.commit()
    await db.refresh(assistant_message)

    return _chat_response(
        session_id=session.id,
        assistant_message=assistant_message,
        avatar=avatar,
        suggested_questions=engine_result.get("suggested_questions", []),
        digital_human=digital_human,
    )


def _sse_event(payload: dict[str, Any]) -> str:
    """序列化SSE事件。"""

    return "data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n"


@router.post("/text/stream", summary="文本对话流式输出")
async def text_chat_stream(
    request: TextChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """文本对话流式接口，保持 final 事件与 ChatResponse 兼容。"""

    async def event_generator():
        try:
            session = None
            if request.session_id:
                result = await db.execute(select(ChatSession).where(ChatSession.id == request.session_id))
                session = result.scalar_one_or_none()
                if not session:
                    yield _sse_event({"type": "error", "message": "会话不存在"})
                    return
            avatar = await _select_chat_avatar(
                db,
                request.spot_id,
                request.avatar,
                session.current_avatar if session else None,
            )
            if session is None:
                session = ChatSession(
                    user_id=current_user.get("user_id") if current_user else None,
                    current_spot_id=request.spot_id,
                    current_avatar=avatar,
                )
                db.add(session)
                await db.flush()
            else:
                session.current_avatar = avatar

            yield _sse_event({"type": "session", "session_id": str(session.id), "avatar": avatar})

            user_message = ChatMessage(
                session_id=session.id,
                role="user",
                content=request.message,
                content_type="text",
                spot_id=request.spot_id,
            )
            db.add(user_message)

            events: list[dict[str, Any]] = []

            async def stream_callback(event: dict[str, Any]) -> None:
                events.append(event)

            engine_task = asyncio.create_task(
                _process_chat(
                    message=request.message,
                    session_id=session.id,
                    spot_id=request.spot_id,
                    avatar=avatar,
                    db=db,
                    route_id=request.route_id,
                    stream_callback=stream_callback,
                    response_mode=request.response_mode,
                )
            )

            sent_index = 0
            while not engine_task.done():
                while sent_index < len(events):
                    yield _sse_event(events[sent_index])
                    sent_index += 1
                await asyncio.sleep(0.03)

            engine_result = await engine_task
            while sent_index < len(events):
                yield _sse_event(events[sent_index])
                sent_index += 1

            yield _sse_event({"type": "stage", "stage": "digital_human", "message": "生成数字人驱动"})
            digital_stage_start = time.time()
            digital_human = await _build_digital_human_payload(
                text=engine_result["content"],
                avatar=avatar,
                emotion=engine_result.get("emotion") or "neutral",
                session_id=session.id,
                intent=engine_result.get("intent") or "",
                prefer_video=True,
                db=db,
            )
            digital_human_ms = int((time.time() - digital_stage_start) * 1000)

            assistant_message = ChatMessage(
                session_id=session.id,
                role="assistant",
                content=engine_result["content"],
                content_type="text",
                audio_url=_fit_db_url(digital_human.get("audio_url")),
                video_url=_fit_db_url(digital_human.get("video_url")),
                emotion=engine_result.get("emotion"),
                intent=engine_result.get("intent"),
                spot_id=request.spot_id,
                retrieved_docs=_build_trace_payload(engine_result, digital_human_ms),
                latency_ms=engine_result.get("latency_ms", 1500),
            )
            db.add(assistant_message)

            session.turn_count += 1
            session.dialogue_state = engine_result.get("state", "chatting")
            if request.spot_id:
                session.current_spot_id = request.spot_id

            await db.commit()
            await db.refresh(assistant_message)

            response = _chat_response(
                session_id=session.id,
                assistant_message=assistant_message,
                avatar=avatar,
                suggested_questions=engine_result.get("suggested_questions", []),
                digital_human=digital_human,
            )
            yield _sse_event({"type": "final", "data": response.model_dump(mode="json")})
        except Exception as exc:
            logger.error(f"流式文本对话失败: {exc}", exc_info=True)
            yield _sse_event({"type": "error", "message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/voice", response_model=ChatResponse, summary="语音对话")
async def voice_chat(
    session_id: Optional[str] = Form(None, description="会话ID"),
    spot_id: Optional[str] = Form(None, description="当前景点ID"),
    route_id: Optional[str] = Form(None, description="当前路线ID"),
    avatar: Optional[str] = Form(None, description="指定数字人角色"),
    response_mode: ResponseMode = Form("brief", description="回答长度模式；语音默认简答"),
    voice_emotion: Optional[str] = Form(None, description="兼容旧客户端的语音情感提示"),
    transcript_hint: Optional[str] = Form(None, description="浏览器Web Speech识别文本"),
    audio: UploadFile = File(..., description="音频文件"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    语音对话接口

    上传音频文件，系统通过ASR识别语音内容，再通过完整的AI引擎链路
    （DialogueEngine + EmotionEngine + RAGEngine + LLMRouter）生成回复，
    最后通过TTS合成语音返回。
    """
    # 读取音频数据
    audio_data = await audio.read()
    if not audio_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="音频文件不能为空")

    # 语音转文字（ASR）
    asr_started_at = time.time()
    transcribed_text, asr_provider, asr_confidence, pcm_audio = await _transcribe_voice(
        audio=audio,
        audio_data=audio_data,
        transcript_hint=transcript_hint,
    )
    asr_ms = int((time.time() - asr_started_at) * 1000)
    acoustic_evidence = _analyze_voice_acoustics(pcm_audio)
    detected_voice_emotion = str(acoustic_evidence.get("emotion") or "neutral")
    audio_duration_estimate = acoustic_evidence.get("duration_sec", 0)
    logger.info(
        f"语音识别结果: provider={asr_provider}, emotion={detected_voice_emotion}, "
        f"confidence={acoustic_evidence.get('confidence')}, text={transcribed_text}"
    )

    try:
        request_session_id = uuid.UUID(session_id) if session_id else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_id格式错误") from exc
    try:
        request_route_id = uuid.UUID(route_id) if route_id else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="route_id格式错误") from exc

    # 复用文本对话逻辑
    text_request = TextChatRequest(
        session_id=request_session_id,
        message=transcribed_text,
        spot_id=spot_id,
        avatar=avatar,
        route_id=request_route_id,
        response_mode=response_mode,
    )

    # 获取或创建会话
    session = None
    if text_request.session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == text_request.session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在",
            )
    avatar = await _select_chat_avatar(
        db,
        text_request.spot_id,
        text_request.avatar,
        session.current_avatar if session else None,
    )
    if session is None:
        session = ChatSession(
            user_id=current_user.get("user_id") if current_user else None,
            current_spot_id=text_request.spot_id,
            current_avatar=avatar,
        )
        db.add(session)
        await db.flush()
    else:
        session.current_avatar = avatar

    # 保存用户语音消息
    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        content=transcribed_text,
        content_type="audio",
        spot_id=text_request.spot_id,
        retrieved_docs=[{
            "voice_evidence": {
                "asr_provider": asr_provider,
                "asr_confidence": asr_confidence,
                "voice_emotion": detected_voice_emotion,
                "client_emotion_hint": voice_emotion,
                "acoustic_features": acoustic_evidence,
                "audio_bytes": len(audio_data),
                "duration_estimate_sec": audio_duration_estimate,
            }
        }],
    )
    db.add(user_message)
    db.add(
        BehaviorLog(
            user_id=session.user_id,
            session_id=session.id,
            event_type="voice_quality",
            event_data={
                "asr_provider": asr_provider,
                "asr_confidence": asr_confidence,
                "voice_emotion": detected_voice_emotion,
                "client_emotion_hint": voice_emotion,
                "acoustic_features": acoustic_evidence,
                "audio_bytes": len(audio_data),
                "duration_estimate_sec": audio_duration_estimate,
                "failed": False,
            },
            spot_id=text_request.spot_id,
        )
    )

    # 调用真实对话引擎（传入语音情感提示）
    engine_result = await _process_chat(
        message=transcribed_text,
        session_id=session.id,
        spot_id=text_request.spot_id,
        avatar=avatar,
        db=db,
        route_id=text_request.route_id,
        voice_emotion_hint=detected_voice_emotion,
        voice_emotion_confidence=acoustic_evidence.get("confidence"),
        voice_emotion_reason=acoustic_evidence.get("reason"),
        response_mode=text_request.response_mode,
    )
    engine_result.setdefault("performance_trace", {})["asr_ms"] = asr_ms
    emotion_analysis = engine_result.get("emotion_analysis") or {}
    engine_result["multimodal_evidence"] = {
        "type": "voice",
        "recognized_text": transcribed_text,
        "asr_provider": asr_provider,
        "asr_confidence": asr_confidence,
        "voice_emotion": detected_voice_emotion,
        "fused_emotion": engine_result.get("emotion"),
        "client_emotion_hint": voice_emotion,
        "acoustic_features": acoustic_evidence,
        "emotion_fusion": emotion_analysis,
        "duration_estimate_sec": audio_duration_estimate,
    }

    digital_stage_start = time.time()
    digital_human = await _build_digital_human_payload(
        text=engine_result["content"],
        avatar=avatar,
        emotion=engine_result.get("emotion") or detected_voice_emotion,
        session_id=session.id,
        intent=engine_result.get("intent") or "",
        prefer_video=True,
        db=db,
    )
    digital_human_ms = int((time.time() - digital_stage_start) * 1000)
    audio_url = digital_human.get("audio_url")

    # 保存助手语音回复
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=engine_result["content"],
        content_type="audio",
        audio_url=_fit_db_url(audio_url),
        video_url=_fit_db_url(digital_human.get("video_url")),
        emotion=engine_result.get("emotion"),
        intent=engine_result.get("intent"),
        spot_id=text_request.spot_id,
        retrieved_docs=_build_trace_payload(engine_result, digital_human_ms),
        latency_ms=engine_result.get("latency_ms", 2500),
    )
    db.add(assistant_message)

    # 更新会话状态
    session.turn_count += 1
    session.dialogue_state = engine_result.get("state", "chatting")

    await db.commit()
    await db.refresh(assistant_message)

    return _chat_response(
        session_id=session.id,
        assistant_message=assistant_message,
        avatar=avatar,
        suggested_questions=engine_result.get("suggested_questions", []),
        digital_human=digital_human,
        recognized_text=transcribed_text,
    )


@router.post("/image", response_model=ChatResponse, summary="图片对话")
async def image_chat(
    image: UploadFile = File(..., description="景区图片"),
    message: Optional[str] = Form(None, description="图片相关问题"),
    creative_mode: bool = Form(False, description="同时返回构图、发布与文创所需信息"),
    session_id: Optional[str] = Form(None, description="会话ID"),
    spot_id: Optional[str] = Form(None, description="当前景点ID"),
    route_id: Optional[str] = Form(None, description="当前路线ID"),
    avatar: Optional[str] = Form(None, description="指定数字人角色"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """图片对话接口"""
    content_type = (image.content_type or "").lower()
    filename = (image.filename or "").lower()
    image_suffixes = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
    if not content_type.startswith("image/") and not filename.endswith(image_suffixes):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请上传图片文件")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片不能为空")
    if len(image_bytes) > 8 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="图片不能超过8MB")

    try:
        request_session_id = uuid.UUID(session_id) if session_id else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_id格式错误") from exc
    try:
        request_route_id = uuid.UUID(route_id) if route_id else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="route_id格式错误") from exc

    session = None
    if request_session_id:
        result = await db.execute(select(ChatSession).where(ChatSession.id == request_session_id))
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    selected_avatar = await _select_chat_avatar(
        db,
        spot_id,
        avatar,
        session.current_avatar if session else None,
    )
    if session is None:
        session = ChatSession(
            user_id=current_user.get("user_id") if current_user else None,
            current_spot_id=spot_id,
            current_avatar=selected_avatar,
        )
        db.add(session)
        await db.flush()
    else:
        session.current_avatar = selected_avatar

    mime_by_suffix = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    normalized_mime = content_type if content_type in set(mime_by_suffix.values()) else ""
    if not normalized_mime:
        normalized_mime = next((mime for suffix, mime in mime_by_suffix.items() if filename.endswith(suffix)), "")
    if not normalized_mime:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="图片理解支持 JPG、PNG 和 WebP 格式，请转换后重试。",
        )

    from app.core.vision_router import VisionAnalysisRequest, VisionRouter

    user_question = message.strip() if message and message.strip() else "请判断图片内容，并介绍画面中的景点或看点。"
    spot_name = await db.scalar(select(Spot.name).where(Spot.id == spot_id).limit(1)) if spot_id else None
    image_data_url = f"data:{normalized_mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    vision_result = await VisionRouter().analyze_image(
        VisionAnalysisRequest(
            image_name=image.filename or "景区图片",
            image_data_url=image_data_url,
            task="creative_journey" if creative_mode else "tour_qa",
            spot_name=spot_name,
            context=user_question,
        )
    )
    if vision_result.status != "success":
        logger.warning(
            "图片对话视觉识别失败: provider={} status={} message={}",
            vision_result.provider,
            vision_result.status,
            vision_result.message,
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=vision_result.message)

    visual_facts = vision_result.visual_facts or []
    matched_spots = vision_result.spot_candidates or []
    all_spot_names = list((await db.scalars(select(Spot.name))).all())
    visual_text = " ".join([vision_result.scene_description or "", *matched_spots, *visual_facts])
    recognized_spot_names = [name for name in all_spot_names if name and name in visual_text]
    if spot_name and spot_name not in recognized_spot_names:
        recognized_spot_names.insert(0, spot_name)
    background_terms = ("景点", "介绍", "历史", "文化", "故事", "典故", "路线", "看点", "建筑", "多高", "哪里")
    needs_rag = bool(recognized_spot_names) and (
        creative_mode or any(term in user_question for term in background_terms)
    )

    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        content=user_question,
        content_type="image",
        spot_id=spot_id,
    )
    db.add(user_message)

    if needs_rag:
        creative_context = (
            f"构图建议：{'；'.join(vision_result.suggestions) if vision_result.suggestions else '未提供'}。"
            f"发布建议：{vision_result.publish_tip or '未提供'}。"
            if creative_mode else ""
        )
        prompt = (
            "游客上传了一张图片，视觉模型已经读取真实图片像素。"
            f"画面描述：{vision_result.scene_description or '未能形成可靠描述'}。"
            f"直接可见事实：{'；'.join(visual_facts) if visual_facts else '无可靠事实'}。"
            f"视觉模型直接回答：{vision_result.answer or '未提供'}。"
            f"已由景区数据精确确认的景点：{', '.join(recognized_spot_names)}。"
            f"{creative_context}"
            f"游客问题：{user_question}。"
            "请先回答游客针对图片的问题，只能用知识库补充上述已确认景点的文化背景；"
            "不要把视觉候选当作已确认事实，无法确认时明确说明，控制在180字以内。"
        )
        engine_result = await _process_chat(
            message=prompt,
            session_id=session.id,
            spot_id=spot_id,
            avatar=selected_avatar,
            db=db,
            route_id=request_route_id,
            response_mode="normal",
            recognized_spots=recognized_spot_names,
        )
        generated_content = str(engine_result.get("content") or "")
        if vision_result.answer and not any(name in generated_content for name in recognized_spot_names):
            engine_result["content"] = vision_result.answer
            engine_result["rag_success"] = False
            engine_result["retrieved_docs"] = []
            engine_result["retrieved_docs_count"] = 0
            engine_result["confidence"] = vision_result.confidence
            engine_result["answer_type"] = "image_observation"
    else:
        direct_answer = vision_result.answer or vision_result.scene_description or "我已读取图片，但暂时无法形成可靠结论。"
        if creative_mode:
            image_suggestions = ["让数字人讲讲这张照片", "写成游记", "生成照片明信片"]
        else:
            from app.core.dialogue_engine import DialogueState, UserIntent

            image_context = _get_dialogue_engine().get_or_create_context(
                session_id=str(session.id),
                user_id=None,
            )
            image_context.current_state = DialogueState.EXPLAINING
            image_context.current_spot_id = spot_id
            current_spot_name, next_spot_name = await _resolve_suggestion_places(
                db,
                spot_id,
                request_route_id,
            )
            image_suggestions = _get_dialogue_engine()._generate_suggestions(
                image_context,
                UserIntent.ASK_INFO,
                current_spot_name=current_spot_name,
                next_spot_name=next_spot_name,
                recognized_spots=recognized_spot_names,
            )
        engine_result = {
            "content": direct_answer,
            "emotion": "curious",
            "intent": "image_understanding",
            "state": "chatting",
            "suggested_questions": image_suggestions,
            "retrieved_docs": [],
            "retrieved_docs_count": 0,
            "rag_success": False,
            "confidence": vision_result.confidence,
            "answer_type": "image_observation",
            "latency_ms": vision_result.evidence.get("latency_ms") or 0,
            "performance_trace": {"vision_ms": vision_result.evidence.get("latency_ms")},
        }
    engine_result["multimodal_evidence"] = {
        "type": "image",
        "filename": image.filename,
        "size_bytes": len(image_bytes),
        "provider": vision_result.provider,
        "model": vision_result.evidence.get("model"),
        "request_id": vision_result.evidence.get("request_id"),
        "latency_ms": vision_result.evidence.get("latency_ms"),
        "confidence": vision_result.confidence,
        "scene_description": vision_result.scene_description,
        "visual_facts": visual_facts,
        "spot_candidates": matched_spots,
        "recognized_spots": recognized_spot_names,
        "composition_suggestions": vision_result.suggestions,
        "safety_tips": vision_result.safety_tips,
        "publish_tip": vision_result.publish_tip,
        "creative_mode": creative_mode,
    }

    digital_stage_start = time.time()
    digital_human = await _build_digital_human_payload(
        text=engine_result["content"],
        avatar=selected_avatar,
        emotion=engine_result.get("emotion") or "neutral",
        session_id=session.id,
        intent=engine_result.get("intent") or "",
        prefer_video=True,
        db=db,
    )
    digital_human_ms = int((time.time() - digital_stage_start) * 1000)

    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=engine_result["content"],
        content_type="text",
        audio_url=_fit_db_url(digital_human.get("audio_url")),
        video_url=_fit_db_url(digital_human.get("video_url")),
        emotion=engine_result.get("emotion"),
        intent=engine_result.get("intent"),
        spot_id=spot_id,
        retrieved_docs=_build_trace_payload(engine_result, digital_human_ms),
        latency_ms=engine_result.get("latency_ms", 1500),
    )
    db.add(assistant_message)
    db.add(
        BehaviorLog(
            user_id=session.user_id,
            session_id=session.id,
            event_type="vision_image_chat",
            event_data={
                "status": vision_result.status,
                "provider": vision_result.provider,
                "model": vision_result.evidence.get("model"),
                "latency_ms": vision_result.evidence.get("latency_ms"),
                "confidence": vision_result.confidence,
                "image_name": image.filename,
                "creative_mode": creative_mode,
            },
            spot_id=spot_id,
        )
    )

    session.turn_count += 1
    session.dialogue_state = engine_result.get("state", "chatting")
    if spot_id:
        session.current_spot_id = spot_id

    await db.commit()
    await db.refresh(assistant_message)

    recognized_text = f"画面识别：{vision_result.scene_description or '已完成图片理解'}"
    return _chat_response(
        session_id=session.id,
        assistant_message=assistant_message,
        avatar=selected_avatar,
        suggested_questions=engine_result.get("suggested_questions", []),
        digital_human=digital_human,
        recognized_text=recognized_text,
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse, summary="获取历史消息")
async def get_chat_history(
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定会话的历史消息列表

    参数:
        session_id: 会话ID
        limit: 返回消息数量上限
        offset: 偏移量
    """
    # 验证会话存在
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    # 查询消息列表
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
        .offset(offset)
    )
    messages = result.scalars().all()

    # 查询总数
    count_result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    total = len(count_result.scalars().all())

    return ChatHistoryResponse(
        session_id=session_id,
        messages=[_chat_message_response(msg) for msg in reversed(messages)],
        total=total,
    )


@router.post("/session", response_model=SessionCreateResponse, summary="创建新会话")
async def create_session(
    request: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    创建新的对话会话

    每个游客首次对话时应先创建会话。
    """
    session = ChatSession(
        user_id=current_user.get("user_id") if current_user else None,
        current_spot_id=request.spot_id,
        current_avatar=request.avatar or "舒窈",
        user_agent=request.user_agent,
        status="active",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # 生成欢迎语（根据角色人设定制）
    avatar = request.avatar or "舒窈"
    welcome_messages = {
        "舒窈": "您好，我是舒窈。今天由我使用聆小璇音色为您讲解，可以问我景点、路线和亲子游览问题。",
        "明朗": "您好，我是明朗。今天由我使用明哥音色，为您提供稳重清晰的文化讲解和慢行建议。",
        "风屿": "您好，我是风屿。今天由我使用聆飞哲音色，陪您了解历史故事、文化传说和研学线索。",
        "明泽": "您好，我是明泽。今天由我使用明哥音色，为您介绍灵山的建筑、工艺与艺术脉络。",
        "雨桐": "您好，我是雨桐。今天由我使用聆小玥音色，陪您发现建筑光影、拍照点位和文创灵感。",
    }
    welcome = welcome_messages.get(avatar, f"您好！我是{avatar}，很高兴为您服务！")

    # 保存欢迎消息
    welcome_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=welcome,
        content_type="text",
        emotion="friendly",
    )
    db.add(welcome_msg)
    await db.commit()

    # 初始化对话引擎上下文
    dialogue_engine = _get_dialogue_engine()
    context = dialogue_engine.get_or_create_context(session_id=str(session.id))
    context.current_avatar = avatar
    context.current_spot_id = request.spot_id
    context.add_message("assistant", welcome, emotion="friendly")

    digital_human = await _build_digital_human_payload(
        text=welcome,
        avatar=avatar,
        emotion="friendly",
        session_id=session.id,
        intent="greeting",
        prefer_video=True,
        db=db,
    )

    return SessionCreateResponse(
        session_id=session.id,
        avatar=avatar,
        welcome_message=welcome,
        created_at=session.started_at or datetime.now(),
        digital_human=digital_human,
    )


@router.put(
    "/session/{session_id}/avatar",
    response_model=AvatarSwitchResponse,
    summary="切换当前会话的常驻数字人",
)
async def switch_session_avatar(
    session_id: uuid.UUID,
    request: AvatarSwitchRequest,
    db: AsyncSession = Depends(get_db),
):
    """保留会话历史，只返回新角色的静默 WebSDK 连接配置。"""

    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id).limit(1))
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    avatar = resolve_avatar_profile(request.avatar).name
    session.current_avatar = avatar
    await db.commit()

    context = _get_dialogue_engine().get_or_create_context(session_id=str(session.id))
    context.current_avatar = avatar
    digital_human = await _build_digital_human_payload(
        text="",
        avatar=avatar,
        emotion="neutral",
        session_id=session.id,
        intent="avatar_switch",
        prefer_video=True,
        db=db,
    )
    # 切换接口只建立连接，不触发普通 TTS 或数字人欢迎语。
    digital_human["audio_url"] = None

    return AvatarSwitchResponse(
        session_id=session.id,
        avatar=avatar,
        digital_human=digital_human,
    )


@router.post("/feedback", response_model=FeedbackResponse, summary="提交满意度评价")
async def submit_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    提交会话满意度评价

    游客在对话结束后对服务质量进行评分和文字评价。
    评价数据将用于管理后台的游客反馈分析和满意度统计。
    """
    # 验证会话存在
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == request.session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    # 更新会话满意度评分
    session.satisfaction_score = request.rating

    # 保存评价反馈消息
    feedback_message = ChatMessage(
        session_id=session.id,
        role="system",
        content=f"[游客评价] 评分: {request.rating}/5" + (
            f" | 反馈: {request.feedback_text}" if request.feedback_text else ""
        ),
        content_type="feedback",
        emotion="feedback",
        retrieved_docs=[{
            "feedback": {
                "rating": request.rating,
                "feedback_text": request.feedback_text,
                "tags": request.tags,
                "would_recommend": request.would_recommend,
                "dimension_scores": request.dimension_scores,
            }
        }],
    )
    db.add(feedback_message)
    db.add(
        BehaviorLog(
            user_id=session.user_id,
            session_id=session.id,
            event_type="feedback",
            event_data={
                "rating": request.rating,
                "feedback_text": request.feedback_text,
                "tags": request.tags,
                "would_recommend": request.would_recommend,
                "dimension_scores": request.dimension_scores,
            },
            spot_id=session.current_spot_id,
        )
    )
    await db.commit()

    logger.info(
        f"游客反馈提交: session={request.session_id}, "
        f"rating={request.rating}, tags={request.tags}"
    )

    return FeedbackResponse(
        success=True,
        message="感谢您的评价！",
        session_id=request.session_id,
        rating=request.rating,
        created_at=datetime.now(),
    )
