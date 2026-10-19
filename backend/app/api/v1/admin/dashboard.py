"""
管理后台-数据大屏API模块
提供概览数据、日统计、热门问答和情感趋势等数据接口
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AnalyticsDaily,
    BehaviorLog,
    ChatMessage,
    CreativeContent,
    EmotionHistory,
    Session as ChatSession,
    User,
)
from app.schemas.admin import (
    DailyStatsItem,
    DailyStatsResponse,
    DashboardRealtimeResponse,
    DashboardOverviewResponse,
    EmotionTrendItem,
    EmotionTrendResponse,
    HotQuestionItem,
    HotQuestionsResponse,
    OptimizationMetricsResponse,
)
from app.utils.jwt import get_current_admin

router = APIRouter(tags=["管理后台-数据大屏"])


def _infer_emotion_from_text(content: str) -> str:
    """在没有情感历史记录时，从真实游客文本推导基础情感分布。"""

    text = (content or "").lower()
    if any(word in text for word in ("生气", "投诉", "太差", "骗人", "糟糕")):
        return "angry"
    if any(word in text for word in ("难过", "失望", "遗憾", "伤心")):
        return "sad"
    if any(word in text for word in ("惊讶", "震撼", "没想到", "壮观")):
        return "surprised"
    if any(word in text for word in ("很好", "真棒", "喜欢", "谢谢", "开心", "漂亮", "满意", "值得推荐")):
        return "happy"
    return "neutral"


@router.get("/admin/dashboard/overview", response_model=DashboardOverviewResponse, summary="概览数据")
async def get_overview(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    获取数据大屏概览数据

    包含总用户数、总会话数、总问答数、今日活跃等核心指标。
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())
    anonymous_identity = func.coalesce(func.nullif(ChatSession.user_agent, ""), "anonymous")
    visitor_identity = case(
        (ChatSession.user_id.isnot(None), cast(ChatSession.user_id, String)),
        else_=anonymous_identity,
    )

    # 使用一个数据库往返取得概览。未登录游客按浏览器标识统计，缺失标识统一归入“匿名”，
    # 避免真实匿名会话因为 user_id 为空而全部显示为 0。
    overview_result = await db.execute(
        select(
            select(func.count(User.id)).scalar_subquery().label("registered_users"),
            select(func.count(func.distinct(anonymous_identity)))
            .where(ChatSession.user_id.is_(None))
            .scalar_subquery()
            .label("anonymous_visitors"),
            select(func.count(ChatSession.id)).scalar_subquery().label("total_sessions"),
            select(func.count(ChatSession.id))
            .where(ChatSession.started_at >= today)
            .scalar_subquery()
            .label("today_service"),
            select(func.count(ChatSession.id))
            .where(ChatSession.started_at >= week_start)
            .scalar_subquery()
            .label("week_service"),
            select(func.count(ChatMessage.id))
            .where(ChatMessage.role == "assistant")
            .scalar_subquery()
            .label("total_qa"),
            select(func.count(func.distinct(visitor_identity)))
            .where(ChatSession.started_at >= today)
            .scalar_subquery()
            .label("today_active"),
            select(func.avg(ChatSession.satisfaction_score))
            .where(ChatSession.satisfaction_score.isnot(None))
            .scalar_subquery()
            .label("avg_satisfaction"),
            select(func.count(ChatSession.satisfaction_score))
            .where(ChatSession.satisfaction_score.isnot(None))
            .scalar_subquery()
            .label("satisfaction_count"),
            select(func.avg(ChatMessage.latency_ms))
            .where(ChatMessage.latency_ms.isnot(None))
            .scalar_subquery()
            .label("avg_latency"),
        )
    )
    row = overview_result.one()
    registered_users = int(row.registered_users or 0)
    anonymous_visitors = int(row.anonymous_visitors or 0)
    total_users = registered_users + anonymous_visitors

    return DashboardOverviewResponse(
        total_users=total_users,
        total_sessions=int(row.total_sessions or 0),
        total_qa=int(row.total_qa or 0),
        today_active=int(row.today_active or 0),
        today_service=int(row.today_service or 0),
        week_service=int(row.week_service or 0),
        avg_satisfaction=round(float(row.avg_satisfaction or 0), 2),
        avg_latency_ms=int(row.avg_latency or 0),
        registered_users=registered_users,
        anonymous_visitors=anonymous_visitors,
        satisfaction_count=int(row.satisfaction_count or 0),
    )


@router.get("/admin/dashboard/daily", response_model=DailyStatsResponse, summary="日统计")
async def get_daily_stats(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    days: int = Query(30, ge=1, le=365, description="最近N天"),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    获取日统计数据

    返回指定时间范围内的每日服务统计。
    """
    # 计算日期范围
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d")
    else:
        end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start = end - timedelta(days=days - 1)

    end_exclusive = end + timedelta(days=1)

    # 查询日统计表
    result = await db.execute(
        select(AnalyticsDaily)
        .where(AnalyticsDaily.date >= start)
        .where(AnalyticsDaily.date < end_exclusive)
        .order_by(AnalyticsDaily.date)
    )
    records = result.scalars().all()

    anonymous_identity = func.coalesce(func.nullif(ChatSession.user_agent, ""), "anonymous")
    visitor_identity = case(
        (ChatSession.user_id.isnot(None), cast(ChatSession.user_id, String)),
        else_=anonymous_identity,
    )
    session_result = await db.execute(
        select(
            func.date(ChatSession.started_at).label("date"),
            func.count(ChatSession.id).label("service_count"),
            func.count(func.distinct(visitor_identity)).label("unique_users"),
            func.avg(ChatSession.satisfaction_score).label("satisfaction_avg"),
        )
        .where(ChatSession.started_at >= start, ChatSession.started_at < end_exclusive)
        .group_by("date")
    )
    message_result = await db.execute(
        select(
            func.date(ChatMessage.created_at).label("date"),
            func.count(ChatMessage.id).label("qa_count"),
            func.avg(ChatMessage.latency_ms).label("avg_latency_ms"),
        )
        .where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= start,
            ChatMessage.created_at < end_exclusive,
        )
        .group_by("date")
    )

    daily_data: dict[str, dict] = {}
    current = start
    while current <= end:
        daily_data[current.strftime("%Y-%m-%d")] = {
            "service_count": 0,
            "unique_users": 0,
            "qa_count": 0,
            "avg_latency_ms": None,
            "satisfaction_avg": None,
        }
        current += timedelta(days=1)

    for date, service_count, unique_users, satisfaction_avg in session_result.all():
        key = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        daily_data.setdefault(key, {}).update(
            service_count=int(service_count or 0),
            unique_users=int(unique_users or 0),
            satisfaction_avg=round(float(satisfaction_avg), 2) if satisfaction_avg is not None else None,
        )
    for date, qa_count, avg_latency_ms in message_result.all():
        key = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        daily_data.setdefault(key, {}).update(
            qa_count=int(qa_count or 0),
            avg_latency_ms=int(avg_latency_ms) if avg_latency_ms is not None else None,
        )

    # 已生成的日统计表是权威聚合结果；存在时覆盖相同日期的实时回算值。
    for record in records:
        key = record.date.strftime("%Y-%m-%d")
        daily_data.setdefault(key, {}).update(
            service_count=int(record.service_count or 0),
            unique_users=int(record.unique_users or 0),
            qa_count=int(record.qa_count or 0),
            avg_latency_ms=record.avg_latency_ms,
            satisfaction_avg=(
                round(float(record.satisfaction_avg), 2)
                if record.satisfaction_avg is not None
                else None
            ),
        )

    items = [DailyStatsItem(date=date, **values) for date, values in sorted(daily_data.items())]

    return DailyStatsResponse(
        items=items,
        total_days=len(items),
    )


@router.get("/admin/dashboard/hot-questions", response_model=HotQuestionsResponse, summary="热门问答")
async def get_hot_questions(
    period: str = Query("7d", description="统计周期: 1d/7d/30d"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    获取热门问答统计

    返回指定周期内被问得最多的问题。
    """
    # 计算时间范围
    now = datetime.now()
    period_map = {
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    delta = period_map.get(period, timedelta(days=7))
    start_time = now - delta

    # 查询用户消息，按内容分组统计
    result = await db.execute(
        select(ChatMessage.content, func.count(ChatMessage.id).label("count"))
        .where(ChatMessage.role == "user")
        .where(ChatMessage.created_at >= start_time)
        .group_by(ChatMessage.content)
        .order_by(desc("count"))
        .limit(limit)
    )
    rows = result.all()

    items = []
    for content, count in rows:
        # 简单分类
        category = _classify_question(content)
        items.append(
            HotQuestionItem(
                question=content[:100] + "..." if len(content) > 100 else content,
                count=count,
                category=category,
            )
        )

    return HotQuestionsResponse(
        items=items,
        period=period,
    )


@router.get("/admin/dashboard/emotion-trend", response_model=EmotionTrendResponse, summary="情感趋势")
async def get_emotion_trend(
    days: int = Query(30, ge=7, le=90, description="统计天数"),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    获取情感趋势数据

    返回指定天数内每日的情感分布趋势。
    """
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)

    # 按天和情感类型分组统计
    result = await db.execute(
        select(
            func.date(EmotionHistory.created_at).label("date"),
            EmotionHistory.emotion_type,
            func.count(EmotionHistory.id).label("count"),
        )
        .where(EmotionHistory.created_at >= start)
        .group_by("date", EmotionHistory.emotion_type)
        .order_by("date")
    )
    rows = result.all()

    # 整理数据
    date_emotions = {}
    for date, emotion_type, count in rows:
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        if date_str not in date_emotions:
            date_emotions[date_str] = {}
        date_emotions[date_str][emotion_type] = count

    if not rows:
        # 情感引擎历史表为空时仍使用真实提问文本，而不是生成随机比例。
        message_result = await db.execute(
            select(ChatMessage.created_at, ChatMessage.content)
            .where(ChatMessage.role == "user", ChatMessage.created_at >= start)
            .order_by(ChatMessage.created_at)
            .limit(2000)
        )
        for created_at, content in message_result.all():
            date_str = created_at.strftime("%Y-%m-%d") if created_at else end.strftime("%Y-%m-%d")
            emotion_type = _infer_emotion_from_text(content)
            bucket = date_emotions.setdefault(date_str, {})
            bucket[emotion_type] = bucket.get(emotion_type, 0) + 1

    items = []
    for date_str in sorted(date_emotions.keys()):
        emotions = date_emotions[date_str]
        total = sum(emotions.values())

        if total > 0:
            items.append(
                EmotionTrendItem(
                    date=date_str,
                    happy=round(emotions.get("happy", 0) / total, 2),
                    neutral=round(emotions.get("neutral", 0) / total, 2),
                    sad=round(emotions.get("sad", 0) / total, 2),
                    angry=round(emotions.get("angry", 0) / total, 2),
                    surprised=round(emotions.get("surprised", 0) / total, 2),
                )
            )

    # 如果数据不足，从AnalyticsDaily补充
    if len(items) < days:
        result = await db.execute(
            select(AnalyticsDaily)
            .where(AnalyticsDaily.date >= start)
            .where(AnalyticsDaily.date <= end + timedelta(days=1))
            .order_by(AnalyticsDaily.date)
        )
        records = result.scalars().all()

        existing_dates = {item.date for item in items}
        for record in records:
            date_str = record.date.strftime("%Y-%m-%d")
            if date_str not in existing_dates and record.emotion_distribution:
                dist = record.emotion_distribution
                total = sum(dist.values()) if dist else 0
                if total > 0:
                    items.append(
                        EmotionTrendItem(
                            date=date_str,
                            happy=round(dist.get("happy", 0) / total, 2),
                            neutral=round(dist.get("neutral", 0) / total, 2),
                            sad=round(dist.get("sad", 0) / total, 2),
                            angry=round(dist.get("angry", 0) / total, 2),
                            surprised=round(dist.get("surprised", 0) / total, 2),
                        )
                    )

    items.sort(key=lambda x: x.date)

    return EmotionTrendResponse(
        items=items,
        period=f"{days}天",
    )


def _classify_question(content: str) -> str:
    """
    简单的问题分类

    基于关键词对问题进行分类。
    """
    content = content.lower()

    keywords = {
        "历史": ["历史", "多久", "年", "建立", "创建", "起源"],
        "景点": ["景点", "哪里", "什么地方", "推荐", "去哪", "玩什么"],
        "门票": ["门票", "票价", "多少钱", "收费", "免费"],
        "交通": ["怎么去", "交通", "路线", "地铁", "公交", "停车"],
        "餐饮": ["吃", "饭", "餐厅", "素斋", "食堂", "美食"],
        "宗教": ["佛", "菩萨", "拜", "祈福", "许愿", " religious"],
        "文化": ["文化", "传说", "故事", "典故", "诗词", "书法"],
    }

    for category, words in keywords.items():
        for word in words:
            if word in content:
                return category

    return "其他"


@router.get("/admin/dashboard/realtime", response_model=DashboardRealtimeResponse, summary="实时运营总览")
async def get_realtime_dashboard(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """实时运营概览：会话、热门景点、低置信问题和链路质量。"""

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    recent = now - timedelta(minutes=30)

    online_result = await db.execute(
        select(func.count(ChatSession.id)).where(
            ChatSession.status == "active",
            ChatSession.started_at >= recent,
        )
    )
    active_today_result = await db.execute(
        select(func.count(ChatSession.id)).where(ChatSession.started_at >= today)
    )
    hot_spot_result = await db.execute(
        select(ChatMessage.spot_id, func.count(ChatMessage.id).label("count"))
        .where(ChatMessage.created_at >= today)
        .where(ChatMessage.spot_id.isnot(None))
        .group_by(ChatMessage.spot_id)
        .order_by(desc("count"))
        .limit(8)
    )
    low_conf_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant")
        .where(ChatMessage.created_at >= today)
        .where(ChatMessage.retrieved_docs.isnot(None))
        .order_by(desc(ChatMessage.created_at))
        .limit(100)
    )
    emotion_result = await db.execute(
        select(EmotionHistory.emotion_type, func.count(EmotionHistory.id).label("count"))
        .where(EmotionHistory.created_at >= today)
        .group_by(EmotionHistory.emotion_type)
    )
    behavior_result = await db.execute(
        select(BehaviorLog.event_type, BehaviorLog.event_data)
        .where(BehaviorLog.created_at >= today)
        .where(BehaviorLog.event_type.in_(["voice_quality", "tts_quality", "avatar_quality"]))
        .limit(500)
    )

    low_confidence_questions = []
    rag_values: list[int] = []
    latency_values: list[int] = []
    for msg in low_conf_result.scalars().all():
        raw = msg.retrieved_docs or []
        first = raw[0] if isinstance(raw, list) and raw else {}
        trace = first.get("query_trace") if isinstance(first, dict) else {}
        sources = first.get("sources") if isinstance(first, dict) else []
        top_score = max((float(item.get("score") or 0) for item in sources or []), default=0)
        calibrated_confidence = (trace or {}).get("confidence")
        answer_confidence = (
            float(calibrated_confidence)
            if calibrated_confidence is not None
            else top_score
        )
        if msg.latency_ms:
            latency_values.append(int(msg.latency_ms))
        rag_ms = (trace or {}).get("rag_ms") or ((trace or {}).get("rag") or {}).get("total_ms")
        if rag_ms:
            rag_values.append(int(rag_ms))
        # 欢迎语等非检索消息的 sources 为空，不能按 0 分误报为低置信回答。
        if sources and answer_confidence < 0.65 and len(low_confidence_questions) < 8:
            low_confidence_questions.append({
                "message_id": str(msg.id),
                "answer": msg.content[:120],
                "confidence": round(answer_confidence, 3),
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })

    emotion_counts = {row[0]: row[1] for row in emotion_result.all()}
    negative_emotion_alerts = [
        {"emotion": key, "count": value}
        for key, value in emotion_counts.items()
        if key in {"frustrated", "anxious", "angry", "sad", "tired"} and value >= 1
    ]

    quality = {
        "voice_quality": {"total": 0, "ok": 0},
        "tts_quality": {"total": 0, "ok": 0},
        "avatar_quality": {"total": 0, "ok": 0},
    }
    behavior_rows = behavior_result.all()
    for event_type, event_data in behavior_rows:
        if event_type not in quality:
            continue
        quality[event_type]["total"] += 1
        if not (event_data or {}).get("failed"):
            quality[event_type]["ok"] += 1

    def rate(key: str) -> float:
        total = quality[key]["total"]
        if not total:
            return 1.0
        return round(quality[key]["ok"] / total, 3)

    hot_spots = [{"spot_id": row[0], "count": row[1]} for row in hot_spot_result.all()]
    return DashboardRealtimeResponse(
        online_sessions=int(online_result.scalar() or 0),
        active_sessions_today=int(active_today_result.scalar() or 0),
        hot_spots=hot_spots,
        low_confidence_questions=low_confidence_questions,
        negative_emotion_alerts=negative_emotion_alerts,
        asr_success_rate=rate("voice_quality"),
        tts_success_rate=rate("tts_quality"),
        avatar_success_rate=rate("avatar_quality"),
        avg_rag_ms=int(sum(rag_values) / len(rag_values)) if rag_values else 0,
        avg_total_latency_ms=int(sum(latency_values) / len(latency_values)) if latency_values else 0,
        is_sample=any(bool((event_data or {}).get("demo_seed")) for _, event_data in behavior_rows),
    )


@router.get("/admin/dashboard/optimization-metrics", response_model=OptimizationMetricsResponse, summary="优化期指标")
async def get_optimization_metrics(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """照片点评与社区运营指标，全部来自真实行为日志和文创内容。"""

    del admin
    vision_result = await db.execute(
        select(BehaviorLog.event_data).where(BehaviorLog.event_type == "vision_photo_review")
    )
    vision_rows = [row[0] or {} for row in vision_result.all()]
    post_result = await db.execute(
        select(CreativeContent).where(CreativeContent.content_type == "community_post")
    )
    posts = post_result.scalars().all()

    community_comments = 0
    community_favorites = 0
    community_reports = 0
    hidden_posts = 0
    for post in posts:
        metadata = post.meta_info or {}
        community_comments += int(metadata.get("comment_count") or 0)
        community_favorites += int(metadata.get("favorite_count") or 0)
        community_reports += int(metadata.get("report_count") or 0)
        if metadata.get("is_hidden"):
            hidden_posts += 1

    return OptimizationMetricsResponse(
        photo_review_total=len(vision_rows),
        photo_review_success=sum(1 for item in vision_rows if item.get("status") == "success"),
        photo_review_failed=sum(1 for item in vision_rows if item.get("status") != "success"),
        community_posts=len(posts),
        community_comments=community_comments,
        community_favorites=community_favorites,
        community_reports=community_reports,
        hidden_posts=hidden_posts,
        is_sample=(
            any(bool(item.get("demo_seed")) for item in vision_rows)
            or any(bool((post.meta_info or {}).get("demo_seed")) for post in posts)
        ),
    )
