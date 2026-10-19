"""
管理后台-知识库API模块
提供知识文档的CRUD管理和发布功能
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select, desc, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models import KnowledgeDocument, KnowledgeChunk, User
from app.schemas.admin import (
    KnowledgeCreateRequest,
    KnowledgeDetailResponse,
    KnowledgeListItem,
    KnowledgeRecallHit,
    KnowledgeRecallTestRequest,
    KnowledgeRecallTestResponse,
    KnowledgeUpdateRequest,
)
from app.utils.jwt import get_current_admin

router = APIRouter(tags=["管理后台-知识库"])


def _knowledge_response(doc: KnowledgeDocument, chunks: Optional[List[KnowledgeChunk]] = None) -> KnowledgeDetailResponse:
    """统一组装知识文档详情响应。"""

    chunk_items = [
        {
            "id": str(chunk.id),
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "char_count": chunk.char_count or len(chunk.content or ""),
            "token_count": chunk.token_count,
            "parent_title": (doc.metadata_json or {}).get("parent_chunks", {}).get(str(chunk.chunk_index), {}).get("title"),
        }
        for chunk in (chunks or [])
    ]
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
        chunks=chunk_items,
    )


def _ensure_trace_knowledge_complete(doc: KnowledgeDocument) -> None:
    """RAG补全草稿发布前必须填写实际标准答案。"""

    metadata = doc.metadata_json or {}
    if metadata.get("source") != "rag_trace":
        return
    content = (doc.content or "").strip()
    if "答：" in content:
        answer = content.split("答：", 1)[1].strip()
    elif "## 标准答案" in content:
        answer = content.split("## 标准答案", 1)[1].strip()
    else:
        answer = content
    placeholders = ("请填写", "请补充", "待补充标准答案")
    if len(answer) < 5 or any(marker in answer for marker in placeholders):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="发布前请填写完整的标准答案",
        )


def _invalidate_rag_search_cache() -> None:
    """知识索引发生变化后清理进程内检索结果缓存。"""

    from app.core.rag_engine import invalidate_search_cache

    invalidate_search_cache()


async def _rebuild_chunks(db: AsyncSession, doc: KnowledgeDocument) -> None:
    """重建文档分块，确保RAG检索索引与当前正文一致。"""

    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    chunks = _split_content(doc.content, chunk_size=420)
    parent_chunks = _build_parent_chunk_metadata(doc.content)
    metadata = dict(doc.metadata_json or {})
    metadata["rag_strategy"] = "parent_child"
    metadata["parent_chunk_count"] = len(parent_chunks)
    metadata["parent_chunks"] = {}
    for i, chunk_text in enumerate(chunks):
        parent = _find_parent_for_child(parent_chunks, chunk_text)
        if parent:
            metadata["parent_chunks"][str(i)] = {
                "index": parent["index"],
                "title": parent["title"],
                "summary": parent["summary"],
            }
        db.add(
            KnowledgeChunk(
                document_id=doc.id,
                chunk_index=i,
                content=f"{parent['title']}\n{parent['summary']}\n\n{chunk_text}".strip() if parent else chunk_text,
                char_count=len(chunk_text),
                token_count=max(1, len(chunk_text) // 2),
            )
        )
    doc.metadata_json = metadata


async def _rebuild_chunks_with_embeddings(db: AsyncSession, doc: KnowledgeDocument) -> None:
    """重建分块并同步生成向量，发布后立即可被RAG检索。"""

    await _rebuild_chunks(db, doc)
    await db.flush()
    from app.core.rag_engine import RAGEngine

    rag_engine = RAGEngine(db_session=db, vector_dimension=1024)
    result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    )
    chunks = result.scalars().all()
    for chunk in chunks:
        embedding = await rag_engine._get_embedding(chunk.content)
        await rag_engine._insert_embedding(chunk.id, embedding)


async def _resolve_admin_user_id(db: AsyncSession, admin: dict) -> Optional[UUID]:
    """配置型管理员未必在用户表存在，存在时才写入created_by外键。"""

    user_id = admin.get("user_id")
    if not user_id:
        return None
    admin_uuid = UUID(user_id)
    result = await db.execute(select(User.id).where(User.id == admin_uuid))
    return result.scalar_one_or_none()


def _decode_upload_content(raw: bytes, filename: str) -> str:
    """解析上传的文本类知识文档。"""

    allowed_suffix = {".txt", ".md", ".markdown", ".csv", ".json", ".pdf", ".docx", ".xlsx"}
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"
    if f".{suffix}" not in allowed_suffix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支持 txt、md、csv、json、pdf、docx、xlsx 知识文档上传",
        )

    if suffix == "pdf":
        try:
            from pypdf import PdfReader
            import io

            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if text:
                return text
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PDF解析失败: {exc}") from exc
    if suffix == "docx":
        try:
            import docx
            import io

            document = docx.Document(io.BytesIO(raw))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
            if text:
                return text
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"DOCX解析失败: {exc}") from exc
    if suffix == "xlsx":
        try:
            import openpyxl
            import io

            workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            rows = []
            for sheet in workbook.worksheets:
                rows.append(f"# {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value) for value in row if value is not None]
                    if values:
                        rows.append(" | ".join(values))
            text = "\n".join(rows).strip()
            if text:
                return text
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"XLSX解析失败: {exc}") from exc

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding).strip()
            if text:
                return text
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="文件内容无法解析，请上传 UTF-8 或 GB18030 编码文本",
    )


@router.get("/admin/knowledge", response_model=List[KnowledgeListItem], summary="获取知识文档列表")
async def get_knowledge_list(
    status: Optional[str] = Query(None, description="状态筛选: draft/published/archived"),
    doc_type: Optional[str] = Query(None, description="文档类型筛选"),
    spot_id: Optional[str] = Query(None, description="景点ID筛选"),
    search: Optional[str] = Query(None, description="标题关键词搜索"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    获取知识文档列表（管理员）

    支持多条件筛选和分页查询。
    """
    query = (
        select(KnowledgeDocument, func.count(KnowledgeChunk.id).label("chunk_count"))
        .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .group_by(KnowledgeDocument.id)
    )

    if status:
        query = query.where(KnowledgeDocument.status == status)
    if doc_type:
        query = query.where(KnowledgeDocument.doc_type == doc_type)
    if spot_id:
        query = query.where(KnowledgeDocument.spot_id == spot_id)
    if search:
        query = query.where(KnowledgeDocument.title.ilike(f"%{search}%"))

    query = query.order_by(desc(KnowledgeDocument.updated_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.all()

    return [
        KnowledgeListItem(
            id=doc.id,
            title=doc.title,
            doc_type=doc.doc_type,
            spot_id=doc.spot_id,
            status=doc.status,
            version=doc.version,
            lang=doc.lang,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            published_at=doc.published_at,
            chunk_count=chunk_count or 0,
            source_file=(doc.metadata_json or {}).get("source_file") or doc.source_file,
            metadata_json=doc.metadata_json or {},
        )
        for doc, chunk_count in rows
    ]


@router.get("/admin/knowledge/{doc_id}", response_model=KnowledgeDetailResponse, summary="获取知识文档详情")
async def get_knowledge_detail(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """查看知识文档正文、元数据和父子分块结果。"""

    result = await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识文档不存在")

    chunk_result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    )
    chunks = list(chunk_result.scalars().all())
    return _knowledge_response(doc, chunks)


@router.post("/admin/knowledge", response_model=KnowledgeDetailResponse, summary="创建知识文档")
async def create_knowledge(
    request: KnowledgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    创建新的知识文档

    创建后状态为draft，需要调用发布接口才能生效。
    """
    doc = KnowledgeDocument(
        title=request.title,
        doc_type=request.doc_type,
        spot_id=request.spot_id,
        content=request.content,
        content_html=request.content_html,
        metadata_json=request.metadata_json or {},
        lang=request.lang,
        status="draft",
        version=1,
        created_by=await _resolve_admin_user_id(db, admin),
    )
    db.add(doc)
    await db.flush()
    await _rebuild_chunks(db, doc)
    await db.commit()
    await db.refresh(doc)

    chunk_result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    )
    return _knowledge_response(doc, list(chunk_result.scalars().all()))


@router.post("/admin/knowledge/upload", response_model=KnowledgeDetailResponse, summary="上传知识文档")
async def upload_knowledge_file(
    file: UploadFile = File(..., description="知识文档文件，支持txt/md/csv/json"),
    doc_type: str = Form("景点介绍"),
    spot_id: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    publish: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """上传并入库知识文档，自动完成RAG文本分块。"""

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    content = _decode_upload_content(raw, file.filename or "knowledge.txt")
    doc = KnowledgeDocument(
        title=title or (file.filename or "未命名知识文档").rsplit(".", 1)[0],
        doc_type=doc_type,
        spot_id=spot_id,
        content=content,
        content_html=None,
        metadata_json={
            "source_file": file.filename,
            "upload_content_type": file.content_type,
            "ingestion_method": "admin_upload",
            "rag_strategy": "parent_child",
        },
        lang="zh",
        status="published" if publish else "draft",
        version=1,
        created_by=await _resolve_admin_user_id(db, admin),
        published_at=datetime.now() if publish else None,
    )
    db.add(doc)
    await db.flush()
    if publish:
        await _rebuild_chunks_with_embeddings(db, doc)
    else:
        await _rebuild_chunks(db, doc)
    await db.commit()
    await db.refresh(doc)
    if publish:
        _invalidate_rag_search_cache()

    chunk_result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    )
    return _knowledge_response(doc, list(chunk_result.scalars().all()))


@router.put("/admin/knowledge/{doc_id}", response_model=KnowledgeDetailResponse, summary="更新知识文档")
async def update_knowledge(
    doc_id: UUID,
    request: KnowledgeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    更新知识文档

    更新内容时自动增加版本号；未明确传入状态时，编辑后的文档回到草稿。
    """
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识文档不存在",
        )

    previous_status = doc.status
    fields_set = request.model_fields_set
    content_changed = request.content is not None and request.content != doc.content
    document_changed = bool(
        fields_set.intersection(
            {"title", "doc_type", "content", "content_html", "spot_id", "metadata_json", "lang"}
        )
    )

    # 更新字段
    if request.title is not None:
        doc.title = request.title
    if request.doc_type is not None:
        doc.doc_type = request.doc_type
    if request.content is not None:
        doc.content = request.content
    if "content_html" in fields_set:
        doc.content_html = request.content_html
    if "spot_id" in fields_set:
        doc.spot_id = request.spot_id
    if "metadata_json" in fields_set:
        doc.metadata_json = request.metadata_json
    if request.lang is not None:
        doc.lang = request.lang

    # 未明确指定状态时，编辑后的知识先回到草稿；管理员可显式保存并发布或归档。
    if request.status is not None:
        doc.status = request.status
    elif document_changed:
        doc.status = "draft"
    if document_changed:
        doc.version += 1
    if doc.status == "published" and previous_status != "published":
        doc.published_at = datetime.now()
    if doc.status == "published":
        _ensure_trace_knowledge_complete(doc)

    search_index_changed = (
        document_changed and (previous_status == "published" or doc.status == "published")
    ) or (
        previous_status != doc.status
        and (previous_status == "published" or doc.status == "published")
    )

    await db.flush()
    if doc.status == "published" and (content_changed or previous_status != "published"):
        await _rebuild_chunks_with_embeddings(db, doc)
    elif content_changed:
        await _rebuild_chunks(db, doc)
    await db.commit()
    await db.refresh(doc)
    if search_index_changed:
        _invalidate_rag_search_cache()

    chunk_result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    )
    return _knowledge_response(doc, list(chunk_result.scalars().all()))


@router.delete("/admin/knowledge/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除知识文档")
async def delete_knowledge(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    删除知识文档

    删除文档会级联删除所有关联的分片数据。
    """
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识文档不存在",
        )

    was_published = doc.status == "published"
    await db.delete(doc)
    await db.commit()
    if was_published:
        _invalidate_rag_search_cache()

    return None


@router.post("/admin/knowledge/{doc_id}/publish", response_model=KnowledgeDetailResponse, summary="发布知识文档")
async def publish_knowledge(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """
    发布知识文档

    发布后将文档状态设为published，并记录发布时间。
    只有published状态的文档才能被RAG检索使用。
    """
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识文档不存在",
        )

    if doc.status == "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文档已发布",
        )

    _ensure_trace_knowledge_complete(doc)
    doc.status = "published"
    doc.published_at = datetime.now()
    await _rebuild_chunks_with_embeddings(db, doc)
    await db.commit()
    await db.refresh(doc)
    _invalidate_rag_search_cache()

    chunk_result = await db.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    )
    return _knowledge_response(doc, list(chunk_result.scalars().all()))


@router.post("/admin/knowledge/recall-test", response_model=KnowledgeRecallTestResponse, summary="知识库召回测试")
async def test_knowledge_recall(
    request: KnowledgeRecallTestRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """输入问题后查看RAG命中、分数和排序原因。"""

    from app.core.rag_engine import RAGEngine

    engine = RAGEngine(db_session=db, vector_dimension=1024)
    results = await engine.hybrid_search(request.query, top_k=request.top_k, spot_id=request.spot_id)
    trace = dict(getattr(engine, "last_trace", {}) or {})
    hits = []
    for index, item in enumerate(results):
        vector_score = round(float(item.vector_score or 0), 4)
        text_score = round(float(item.text_score or 0), 4)
        reason_parts = []
        if text_score:
            reason_parts.append("词面命中")
        if vector_score:
            reason_parts.append("语义向量命中")
        if item.spot_id == request.spot_id and request.spot_id:
            reason_parts.append("景点过滤匹配")
        hits.append(
            KnowledgeRecallHit(
                rank=index + 1,
                chunk_id=str(item.chunk_id),
                document_id=str(item.document_id),
                doc_title=item.doc_title,
                doc_type=item.doc_type,
                spot_id=item.spot_id,
                score=round(float(item.score or 0), 4),
                vector_score=vector_score,
                text_score=text_score,
                content=str(item.content or "")[:500],
                reason="、".join(reason_parts) or "综合排序命中",
            )
        )
    confidence = min(1.0, max((hit.score for hit in hits), default=0))
    return KnowledgeRecallTestResponse(
        query=request.query,
        mode=trace.get("mode", "unknown"),
        confidence=confidence,
        total_ms=trace.get("total_ms"),
        hits=hits,
    )


@router.get("/admin/knowledge-embedding-health", summary="本地Embedding健康检查")
async def get_embedding_health(
    probe: bool = Query(False, description="是否执行一次真实向量生成探测"),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """检查真实 embedding 链路是否可用。

    线上对话的取向量顺序与 RAGEngine._get_embedding 完全一致：
    1. 配置了 EMBEDDING_SERVICE_URL 时，向量由独立嵌入服务生成（推荐部署方式）；
    2. 否则回退到 API 进程内的本地 BGE-M3（USE_LOCAL_EMBEDDING=true）。

    因此健康检查必须探测"实际生效的那条链路"，而不是在 API 容器里
    盲目加载本地模型——API 镜像按设计不安装 sentence-transformers。
    """

    del db, admin
    import httpx

    from app.core.embedding_provider import LocalEmbeddingProvider, get_local_embedding_provider

    provider = get_local_embedding_provider()
    runtime = provider.runtime_info()
    model_path = Path(runtime["model_path"])
    service_url = settings.EMBEDDING_SERVICE_URL.rstrip("/")
    use_service = bool(service_url)
    local_backend = (settings.EMBEDDING_LOCAL_BACKEND or "auto").lower()

    def check(name: str, ok: bool, value, status_hint: str | None = None) -> dict:
        return {
            "name": name,
            "ok": ok,
            "value": value,
            # pass=通过 fail=失败 skip=当前链路不需要该项
            "status": status_hint or ("pass" if ok else "fail"),
        }

    checks: list[dict] = [
        check("EMBEDDING_SERVICE_URL", use_service, service_url or "未配置"),
        check("USE_LOCAL_EMBEDDING", bool(settings.USE_LOCAL_EMBEDDING), settings.USE_LOCAL_EMBEDDING),
        check("模型目录", model_path.exists(), str(model_path)),
    ]

    # ---------- 链路一：独立嵌入服务（线上主链路） ----------
    service_health: dict | None = None
    if use_service:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0)) as client:
                resp = await client.get(f"{service_url}/health")
                resp.raise_for_status()
                service_health = resp.json()
            svc_runtime = service_health.get("runtime") or {}
            svc_desc = (
                f"backend={svc_runtime.get('loaded_backend') or svc_runtime.get('configured_backend')}, "
                f"device={svc_runtime.get('loaded_device') or svc_runtime.get('configured_device')}"
            )
            checks.append(check("嵌入服务 /health", service_health.get("status") == "healthy", svc_desc))
        except Exception as exc:
            checks.append(check("嵌入服务 /health", False, f"{service_url} 不可达: {exc}"))
    else:
        checks.append(check("嵌入服务 /health", True, "未配置 EMBEDDING_SERVICE_URL，跳过", "skip"))

    # ---------- 链路二：API 进程内本地模型（兜底链路） ----------
    onnx_model = model_path / "onnx" / "model.onnx"
    pytorch_weights = model_path / "pytorch_model.bin"
    tokenizer = model_path / "tokenizer.json"

    pytorch_ok = pytorch_weights.exists() and not LocalEmbeddingProvider._is_lfs_pointer(pytorch_weights)
    onnx_ok = onnx_model.exists() and not LocalEmbeddingProvider._is_lfs_pointer(onnx_model)
    tokenizer_ok = tokenizer.exists() and not LocalEmbeddingProvider._is_lfs_pointer(tokenizer)

    if local_backend in ("onnx", "onnxruntime"):
        # 明确使用 ONNX 后端时，ONNX 权重才是硬性要求；其余情况不展示该行，
        # 避免非当前后端的可选文件在面板上显示为"失败"造成误读。
        checks.append(check("ONNX权重", onnx_ok, str(onnx_model)))
        checks.append(check("PyTorch权重", pytorch_ok, f"{pytorch_weights}（非当前后端，可选）", "skip" if not pytorch_ok else "pass"))
    else:
        checks.append(check("PyTorch权重", pytorch_ok, str(pytorch_weights)))
    checks.append(check("tokenizer.json", tokenizer_ok, str(tokenizer)))

    # ---------- 真实探测：严格走线上同款链路 ----------
    probe_result = None
    if probe:
        if use_service:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=2.0, read=12.0, write=2.0, pool=2.0)) as client:
                    resp = await client.post(f"{service_url}/embed", json={"text": "灵山大佛与梵宫导览知识库健康检查"})
                    resp.raise_for_status()
                    data = resp.json()
                vector = data.get("embedding") or []
                probe_result = {
                    "ok": True,
                    "via": "embedding-service",
                    "dimension": len(vector),
                    "non_zero": any(abs(value) > 1e-12 for value in vector),
                    "loaded_backend": data.get("backend"),
                    "loaded_device": data.get("device"),
                }
            except Exception as exc:
                probe_result = {"ok": False, "via": "embedding-service", "error": str(exc)}
        else:
            try:
                vector = await asyncio.wait_for(provider.embed("灵山大佛与梵宫导览知识库健康检查"), timeout=12)
                probe_result = {
                    "ok": True,
                    "via": "local-provider",
                    "dimension": len(vector),
                    "non_zero": any(abs(value) > 1e-12 for value in vector),
                    "loaded_backend": provider.backend_info.name if provider.backend_info else None,
                    "loaded_device": provider.backend_info.device if provider.backend_info else None,
                }
            except Exception as exc:
                probe_result = {"ok": False, "via": "local-provider", "error": str(exc)}

    service_ok = use_service and any(
        item["name"] == "嵌入服务 /health" and item["ok"] for item in checks
    )
    local_ok = bool(settings.USE_LOCAL_EMBEDDING) and model_path.exists() and (pytorch_ok or onnx_ok) and tokenizer_ok

    return {
        "ok": service_ok or local_ok,
        "active_chain": "embedding-service" if use_service else "local-provider",
        "runtime": runtime,
        "service": service_health,
        "checks": checks,
        "probe": probe_result,
    }


def _split_content(content: str, chunk_size: int = 500) -> List[str]:
    """
    子块分块：按段落和句末符号尽量保留语义，供向量/词面检索精确召回。
    """
    paragraphs = content.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [content]


def _build_parent_chunk_metadata(content: str, parent_size: int = 1400) -> List[dict]:
    """构建父块元数据，生成时用于给子块补足上下文。"""

    paragraphs = [para.strip() for para in content.split("\n\n") if para.strip()]
    parents: List[dict] = []
    current: List[str] = []
    current_len = 0
    for para in paragraphs or [content]:
        if current and current_len + len(para) > parent_size:
            parent_text = "\n\n".join(current)
            parents.append(_summarize_parent(parent_text, len(parents)))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)
    if current:
        parents.append(_summarize_parent("\n\n".join(current), len(parents)))
    return parents


def _summarize_parent(text: str, index: int) -> dict:
    """生成轻量父块标题和摘要，不依赖外部模型，保证上传链路稳定。"""

    first_line = next((line.strip("# ").strip() for line in text.splitlines() if line.strip()), "")
    title = first_line[:48] or f"父块 {index + 1}"
    summary = text.replace("\n", " ")[:180]
    return {"index": index, "title": f"父块{index + 1}: {title}", "summary": summary, "content": text}


def _find_parent_for_child(parents: List[dict], child_text: str) -> Optional[dict]:
    """根据子块文本在父块中的位置选择父块上下文。"""

    for parent in parents:
        if child_text[:80] in parent["content"] or child_text in parent["content"]:
            return parent
    return parents[0] if parents else None
