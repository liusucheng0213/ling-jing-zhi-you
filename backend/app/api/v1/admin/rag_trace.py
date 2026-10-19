"""管理后台-RAG可信溯源与知识改进闭环API。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ChatMessage, KnowledgeDocument, Session as ChatSession
from app.schemas.admin import (
    KnowledgeDetailResponse,
    KnowledgeDraftFromTraceRequest,
    RagAnswerSnapshot,
    RagImprovementResponse,
    RagImprovementSummary,
    RagQualityStatsResponse,
    RagRetestRequest,
    RagTraceItem,
    RagTraceListResponse,
)
from app.utils.jwt import get_current_admin

router = APIRouter(tags=["管理后台-RAG溯源"])

LOW_CONFIDENCE_THRESHOLD = 0.65


def _knowledge_response(doc: KnowledgeDocument) -> KnowledgeDetailResponse:
    return KnowledgeDetailResponse(
        id=doc.id,
        title=doc.title,
        doc_type=doc.doc_type,
        spot_id=doc.spot_id,
        content=doc.content,
        content_html=doc.content_html,
        status=doc.status,
        version=doc.version,
        metadata_json=doc.metadata_json or {},
        lang=doc.lang,
        created_by=doc.created_by,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        published_at=doc.published_at,
    )


def _extract_trace(raw: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """从ChatMessage.retrieved_docs中解析当前和旧版溯源结构。"""

    if not raw:
        return {}, []
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict) and "query_trace" in first:
            return first.get("query_trace") or {}, first.get("sources") or []
        if isinstance(first, dict):
            return {}, raw
    return {}, []


async def _find_previous_user_message(db: AsyncSession, message: ChatMessage) -> Optional[ChatMessage]:
    """查找同会话中当前助手回复前最近一条用户消息。"""

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == message.session_id)
        .where(ChatMessage.role == "user")
        .where(ChatMessage.created_at <= message.created_at)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _trace_confidence(trace: dict[str, Any], sources: list[dict[str, Any]]) -> Optional[float]:
    """统一使用游客回答置信度，旧数据缺失时才回退到最高来源分。"""

    value = trace.get("confidence")
    if value is not None:
        return round(float(value), 4)
    if not sources:
        return None
    return round(max((float(source.get("score") or 0) for source in sources), default=0.0), 4)


def _snapshot_from_trace(
    message: ChatMessage,
    trace: dict[str, Any],
    sources: list[dict[str, Any]],
) -> RagAnswerSnapshot:
    rag_trace = trace.get("rag") or {}
    rag_ms = trace.get("rag_ms") or rag_trace.get("total_ms") or (trace.get("timings") or {}).get("rag_ms")
    mode = rag_trace.get("mode") or (sources[0].get("mode") if sources else None)
    return RagAnswerSnapshot(
        answer=message.content,
        confidence=_trace_confidence(trace, sources),
        mode=mode,
        source_count=len(sources),
        rag_ms=int(rag_ms) if rag_ms is not None else None,
        total_ms=int(message.latency_ms) if message.latency_ms is not None else None,
        fast_reply=bool(trace.get("fast_reply")),
        sources=sources,
    )


def _snapshot_from_engine_result(engine_result: dict[str, Any]) -> RagAnswerSnapshot:
    sources = list(engine_result.get("retrieved_docs") or [])
    performance = engine_result.get("performance_trace") or {}
    rag_trace = performance.get("rag") or {}
    rag_ms = performance.get("rag_ms") or rag_trace.get("total_ms")
    mode = rag_trace.get("mode") or (sources[0].get("mode") if sources else None)
    return RagAnswerSnapshot(
        answer=str(engine_result.get("content") or ""),
        confidence=float(engine_result.get("confidence")) if engine_result.get("confidence") is not None else None,
        mode=mode,
        source_count=len(sources),
        rag_ms=int(rag_ms) if rag_ms is not None else None,
        total_ms=int(engine_result.get("latency_ms")) if engine_result.get("latency_ms") is not None else None,
        fast_reply=bool(performance.get("fast_reply")),
        sources=sources,
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _improvement_summary(doc: Optional[KnowledgeDocument]) -> Optional[RagImprovementSummary]:
    if doc is None:
        return None
    metadata = doc.metadata_json or {}
    improvement = metadata.get("improvement") or {}
    last_retest = improvement.get("last_retest") or {}
    if last_retest:
        result = last_retest.get("result") or "not_hit"
    elif doc.status == "published":
        result = "ready_to_retest"
    else:
        result = "draft"
    return RagImprovementSummary(
        document_id=doc.id,
        document_status=doc.status,
        retest_count=int(improvement.get("retest_count") or 0),
        last_retested_at=_parse_datetime(last_retest.get("retested_at")),
        result=result,
    )


def _is_improvable(
    message: ChatMessage,
    previous_user_message: Optional[ChatMessage],
    trace: dict[str, Any],
    sources: list[dict[str, Any]],
    threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> bool:
    """只有可由文本知识补全的低置信问答进入知识改进闭环。"""

    if previous_user_message is None or not (previous_user_message.content or "").strip():
        return False
    if previous_user_message.content_type == "image":
        return False
    if message.intent == "image_understanding" or trace.get("answer_type") == "image_observation":
        return False
    confidence = _trace_confidence(trace, sources)
    return not sources or confidence is None or confidence < threshold


async def _find_improvement_document(
    db: AsyncSession,
    message_id: UUID,
    document_id: Optional[UUID] = None,
) -> Optional[KnowledgeDocument]:
    query = select(KnowledgeDocument).where(
        KnowledgeDocument.metadata_json["source"].as_string() == "rag_trace",
        KnowledgeDocument.metadata_json["message_id"].as_string() == str(message_id),
    )
    if document_id is not None:
        query = query.where(KnowledgeDocument.id == document_id)
    else:
        query = query.where(KnowledgeDocument.status != "archived")
    result = await db.execute(query.order_by(desc(KnowledgeDocument.updated_at)).limit(1))
    return result.scalar_one_or_none()


async def _load_improvement_documents(
    db: AsyncSession,
    message_ids: list[UUID],
) -> dict[UUID, KnowledgeDocument]:
    if not message_ids:
        return {}
    result = await db.execute(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.status != "archived",
            KnowledgeDocument.metadata_json["source"].as_string() == "rag_trace",
            KnowledgeDocument.metadata_json["message_id"].as_string().in_([str(value) for value in message_ids]),
        )
        .order_by(desc(KnowledgeDocument.updated_at))
    )
    documents: dict[UUID, KnowledgeDocument] = {}
    for doc in result.scalars().all():
        raw_message_id = (doc.metadata_json or {}).get("message_id")
        try:
            source_message_id = UUID(str(raw_message_id))
        except (TypeError, ValueError):
            continue
        documents.setdefault(source_message_id, doc)
    return documents


async def _build_item(
    db: AsyncSession,
    message: ChatMessage,
    improvement_doc: Optional[KnowledgeDocument] = None,
) -> RagTraceItem:
    trace, sources = _extract_trace(message.retrieved_docs)
    previous_user_message = await _find_previous_user_message(db, message)
    rag_trace = trace.get("rag") or {}
    source_count = len(sources)
    confidence = _trace_confidence(trace, sources)
    rag_ms = trace.get("rag_ms") or rag_trace.get("total_ms") or (trace.get("timings") or {}).get("rag_ms")
    mode = rag_trace.get("mode") or (sources[0].get("mode") if sources else None)
    no_hit = source_count == 0
    low_confidence = no_hit or confidence is None or confidence < LOW_CONFIDENCE_THRESHOLD
    return RagTraceItem(
        id=message.id,
        message_id=message.id,
        session_id=message.session_id,
        question=previous_user_message.content if previous_user_message else None,
        answer=message.content[:500],
        created_at=message.created_at,
        latency_ms=message.latency_ms,
        rag_ms=int(rag_ms) if rag_ms is not None else None,
        mode=mode,
        confidence=confidence,
        low_confidence=low_confidence,
        no_hit=no_hit,
        fast_reply=bool(trace.get("fast_reply")),
        source_count=source_count,
        intent=message.intent,
        rag_success=bool(trace.get("rag_success") or source_count),
        retrieved_docs_count=int(trace.get("retrieved_docs_count") or source_count),
        trace=trace,
        sources=sources,
        improvable=_is_improvable(message, previous_user_message, trace, sources),
        improvement=_improvement_summary(improvement_doc),
    )


async def _build_items(db: AsyncSession, messages: list[ChatMessage]) -> list[RagTraceItem]:
    documents = await _load_improvement_documents(db, [message.id for message in messages])
    return [await _build_item(db, message, documents.get(message.id)) for message in messages]


def _build_improvement_response(
    message: ChatMessage,
    doc: KnowledgeDocument,
    question: str,
    trace: dict[str, Any],
    sources: list[dict[str, Any]],
) -> RagImprovementResponse:
    metadata = doc.metadata_json or {}
    improvement = metadata.get("improvement") or {}
    baseline_raw = improvement.get("baseline")
    before = RagAnswerSnapshot.model_validate(baseline_raw) if isinstance(baseline_raw, dict) else _snapshot_from_trace(message, trace, sources)
    last_retest = improvement.get("last_retest") or {}
    after_raw = last_retest.get("after")
    after = RagAnswerSnapshot.model_validate(after_raw) if isinstance(after_raw, dict) else None
    if last_retest:
        result = last_retest.get("result") or "not_hit"
    elif doc.status == "published":
        result = "ready_to_retest"
    else:
        result = "draft"
    return RagImprovementResponse(
        message_id=message.id,
        document_id=doc.id,
        document_status=doc.status,
        question=str(improvement.get("question") or question),
        retrieval_query=str(improvement.get("retrieval_query") or question),
        before=before,
        after=after,
        confidence_delta=last_retest.get("confidence_delta"),
        source_count_delta=int(last_retest.get("source_count_delta") or 0),
        new_document_hit=bool(last_retest.get("new_document_hit")),
        improved=bool(last_retest.get("improved")),
        result=result,
        retest_count=int(improvement.get("retest_count") or 0),
        last_retested_at=_parse_datetime(last_retest.get("retested_at")),
    )


async def _get_trace_message(db: AsyncSession, message_id: UUID) -> ChatMessage:
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    message = result.scalar_one_or_none()
    if not message or message.role != "assistant":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RAG记录不存在")
    return message


@router.get("/admin/rag-trace/recent", response_model=RagTraceListResponse, summary="最近RAG溯源")
async def get_recent_rag_traces(
    limit: int = Query(30, ge=1, le=100),
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """获取最近带有RAG溯源的助手回复。"""

    start_time = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant")
        .where(ChatMessage.created_at >= start_time)
        .where(ChatMessage.retrieved_docs.isnot(None))
        .order_by(desc(ChatMessage.created_at))
        .limit(limit * 2)
    )
    messages = [msg for msg in result.scalars().all() if msg.retrieved_docs][:limit]
    items = await _build_items(db, messages)
    return RagTraceListResponse(items=items, total=len(items))


@router.get("/admin/rag-trace/low-confidence", response_model=RagTraceListResponse, summary="低置信/无命中问题")
async def get_low_confidence_rag_traces(
    limit: int = Query(30, ge=1, le=100),
    days: int = Query(7, ge=1, le=90),
    min_score: float = Query(LOW_CONFIDENCE_THRESHOLD, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """获取无命中或回答置信度低于阈值的问题。"""

    start_time = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant")
        .where(ChatMessage.created_at >= start_time)
        .where(ChatMessage.retrieved_docs.isnot(None))
        .order_by(desc(ChatMessage.created_at))
        .limit(300)
    )

    messages: list[ChatMessage] = []
    for msg in result.scalars().all():
        trace, sources = _extract_trace(msg.retrieved_docs)
        if not trace and not sources:
            continue
        confidence = _trace_confidence(trace, sources)
        if not trace.get("rag_success") or not sources or confidence is None or confidence < min_score:
            messages.append(msg)
        if len(messages) >= limit:
            break
    items = await _build_items(db, messages)
    return RagTraceListResponse(items=items, total=len(items))


@router.get("/admin/rag-trace/slow", response_model=RagTraceListResponse, summary="RAG慢查询")
async def get_slow_rag_traces(
    limit: int = Query(30, ge=1, le=100),
    days: int = Query(7, ge=1, le=90),
    min_latency_ms: int = Query(3000, ge=100),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """获取响应延迟较高的RAG记录。"""

    start_time = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant")
        .where(ChatMessage.created_at >= start_time)
        .where(ChatMessage.latency_ms >= min_latency_ms)
        .where(ChatMessage.retrieved_docs.isnot(None))
        .order_by(desc(ChatMessage.latency_ms))
        .limit(limit)
    )
    messages = [msg for msg in result.scalars().all() if msg.retrieved_docs]
    items = await _build_items(db, messages)
    return RagTraceListResponse(items=items, total=len(items))


@router.get("/admin/rag-trace/stats", response_model=RagQualityStatsResponse, summary="RAG质量统计")
async def get_rag_trace_stats(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """统计RAG命中、低置信和耗时情况。"""

    start_time = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant")
        .where(ChatMessage.created_at >= start_time)
        .where(ChatMessage.retrieved_docs.isnot(None))
        .limit(1000)
    )
    messages = [msg for msg in result.scalars().all() if msg.retrieved_docs]
    total = len(messages)
    success = 0
    no_hit = 0
    low_conf = 0
    fast_reply = 0
    latency_values: list[int] = []
    rag_values: list[int] = []

    for msg in messages:
        trace, sources = _extract_trace(msg.retrieved_docs)
        if trace.get("rag_success"):
            success += 1
        if not sources:
            no_hit += 1
        confidence = _trace_confidence(trace, sources)
        if confidence is None or confidence < LOW_CONFIDENCE_THRESHOLD:
            low_conf += 1
        if trace.get("fast_reply"):
            fast_reply += 1
        if msg.latency_ms:
            latency_values.append(int(msg.latency_ms))
        rag_ms = trace.get("rag_ms") or (trace.get("rag") or {}).get("total_ms")
        if rag_ms:
            rag_values.append(int(rag_ms))

    avg_latency = int(sum(latency_values) / len(latency_values)) if latency_values else 0
    avg_rag = int(sum(rag_values) / len(rag_values)) if rag_values else 0
    return RagQualityStatsResponse(
        total=total,
        success_count=success,
        total_traced=total,
        rag_success_count=success,
        no_hit_count=no_hit,
        low_confidence_count=low_conf,
        avg_latency_ms=avg_latency,
        avg_rag_ms=avg_rag,
        fast_reply_count=fast_reply,
    )


@router.post("/admin/rag-trace/{message_id}/draft-knowledge", response_model=KnowledgeDetailResponse, summary="低置信问题转知识草稿")
async def create_knowledge_draft_from_trace(
    message_id: UUID,
    request: KnowledgeDraftFromTraceRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """把文本知识缺口沉淀为可编辑、可发布的唯一知识草稿。"""

    message = await _get_trace_message(db, message_id)
    existing = await _find_improvement_document(db, message_id)
    if existing is not None:
        return _knowledge_response(existing)

    previous_user_message = await _find_previous_user_message(db, message)
    trace, sources = _extract_trace(message.retrieved_docs)
    if not _is_improvable(message, previous_user_message, trace, sources):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该记录不是可通过文本知识补全的低置信问答",
        )

    question = (previous_user_message.content or "").strip()
    rag_trace = trace.get("rag") or {}
    retrieval_query = str(rag_trace.get("contextual_query") or question)
    baseline = _snapshot_from_trace(message, trace, sources)
    title = request.title or f"待补问答：{question[:40]}"
    doc = KnowledgeDocument(
        title=title,
        doc_type=request.doc_type,
        spot_id=request.spot_id or message.spot_id,
        content=f"问：{question}\n\n答：",
        status="draft",
        version=1,
        metadata_json={
            "source": "rag_trace",
            "message_id": str(message.id),
            "session_id": str(message.session_id) if message.session_id else None,
            "confidence": baseline.confidence,
            "rag_trace": trace,
            "improvement": {
                "schema_version": 1,
                "question": question,
                "retrieval_query": retrieval_query,
                "baseline": baseline.model_dump(mode="json"),
                "retest_count": 0,
                "last_retest": None,
                "created_at": datetime.now().isoformat(),
            },
        },
        lang="zh",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _knowledge_response(doc)


@router.get(
    "/admin/rag-trace/{message_id}/improvement",
    response_model=RagImprovementResponse,
    summary="查看知识改进前后对比",
)
async def get_rag_improvement(
    message_id: UUID,
    document_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """读取可刷新、可重复查看的知识改进案例。"""

    message = await _get_trace_message(db, message_id)
    doc = await _find_improvement_document(db, message_id, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识改进文档不存在")
    previous_user_message = await _find_previous_user_message(db, message)
    question = previous_user_message.content if previous_user_message else "未记录原始问题"
    trace, sources = _extract_trace(message.retrieved_docs)
    return _build_improvement_response(message, doc, question, trace, sources)


@router.post(
    "/admin/rag-trace/{message_id}/retest",
    response_model=RagImprovementResponse,
    summary="发布知识后复测原问题",
)
async def retest_rag_improvement(
    message_id: UUID,
    request: RagRetestRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """使用真实RAG与LLM主链路生成新回答并保存前后对比。"""

    message = await _get_trace_message(db, message_id)
    doc = await _find_improvement_document(db, message_id, request.document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识改进文档不存在")
    if doc.status != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先发布知识文档再复测")

    previous_user_message = await _find_previous_user_message(db, message)
    question = previous_user_message.content if previous_user_message else "未记录原始问题"
    trace, sources = _extract_trace(message.retrieved_docs)
    metadata = dict(doc.metadata_json or {})
    improvement = dict(metadata.get("improvement") or {})
    baseline_raw = improvement.get("baseline")
    before = RagAnswerSnapshot.model_validate(baseline_raw) if isinstance(baseline_raw, dict) else _snapshot_from_trace(message, trace, sources)
    retrieval_query = str(improvement.get("retrieval_query") or (trace.get("rag") or {}).get("contextual_query") or question)

    avatar = "舒窈"
    if message.session_id:
        session_result = await db.execute(select(ChatSession).where(ChatSession.id == message.session_id))
        source_session = session_result.scalar_one_or_none()
        if source_session and source_session.current_avatar:
            avatar = source_session.current_avatar

    from app.api.v1.chat import run_chat_evaluation
    from app.core.rag_engine import invalidate_search_cache

    invalidate_search_cache()
    engine_result = await run_chat_evaluation(
        message=retrieval_query,
        spot_id=doc.spot_id or message.spot_id,
        avatar=avatar,
        db=db,
    )
    after = _snapshot_from_engine_result(engine_result)
    new_document_hit = any(str(source.get("document_id") or "") == str(doc.id) for source in after.sources)
    confidence_delta = None
    if before.confidence is not None and after.confidence is not None:
        confidence_delta = round(after.confidence - before.confidence, 4)
    source_count_delta = after.source_count - before.source_count
    improved = new_document_hit and (
        before.source_count == 0
        or (confidence_delta is not None and confidence_delta > 0)
    )
    result = "improved" if improved else "hit_without_gain" if new_document_hit else "not_hit"
    retested_at = datetime.now()

    improvement.update(
        {
            "schema_version": 1,
            "question": question,
            "retrieval_query": retrieval_query,
            "baseline": before.model_dump(mode="json"),
            "retest_count": int(improvement.get("retest_count") or 0) + 1,
            "last_retest": {
                "after": after.model_dump(mode="json"),
                "confidence_delta": confidence_delta,
                "source_count_delta": source_count_delta,
                "new_document_hit": new_document_hit,
                "improved": improved,
                "result": result,
                "retested_at": retested_at.isoformat(),
            },
        }
    )
    metadata["improvement"] = improvement
    doc.metadata_json = metadata
    await db.commit()
    await db.refresh(doc)
    return _build_improvement_response(message, doc, question, trace, sources)
