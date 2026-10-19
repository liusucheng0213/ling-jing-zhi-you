"""管理后台-社区内容管理。"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CreativeContent
from app.schemas.admin import (
    CommunityModerationListResponse,
    CommunityModerationPost,
    CommunityModerationUpdateRequest,
)
from app.utils.jwt import get_current_admin

router = APIRouter(prefix="/admin/community", tags=["管理后台-社区管理"])


def _moderation_post(row: CreativeContent) -> CommunityModerationPost:
    """转换社区管理帖子响应。"""

    metadata = row.meta_info or {}
    return CommunityModerationPost(
        id=row.id,
        title=row.title or "灵山游记",
        content=row.content,
        nickname=metadata.get("nickname") or "游客",
        visibility=metadata.get("visibility") or "public",
        is_hidden=bool(metadata.get("is_hidden") or False),
        like_count=int(metadata.get("like_count") or 0),
        comment_count=int(metadata.get("comment_count") or 0),
        favorite_count=int(metadata.get("favorite_count") or 0),
        report_count=int(metadata.get("report_count") or 0),
        reports=list(metadata.get("reports") or [])[-10:],
        created_at=row.created_at,
    )


@router.get("/posts", response_model=CommunityModerationListResponse, summary="社区帖子管理列表")
async def list_community_posts(
    keyword: str | None = Query(None, max_length=80),
    only_reported: bool = Query(False),
    include_hidden: bool = Query(True),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """按时间倒序返回社区帖子，支持搜索和举报筛选。"""

    del admin
    query = (
        select(CreativeContent)
        .where(CreativeContent.content_type == "community_post")
        .order_by(desc(CreativeContent.created_at))
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    items: list[CreativeContent] = []
    keyword_text = (keyword or "").strip().lower()
    for row in rows:
        metadata = row.meta_info or {}
        if not include_hidden and metadata.get("is_hidden"):
            continue
        if only_reported and int(metadata.get("report_count") or 0) <= 0:
            continue
        if keyword_text and keyword_text not in f"{row.title or ''} {row.content} {metadata.get('nickname') or ''}".lower():
            continue
        items.append(row)

    paged = items[offset : offset + limit]
    return CommunityModerationListResponse(
        items=[_moderation_post(row) for row in paged],
        total=len(items),
    )


@router.put("/posts/{post_id}/visibility", response_model=CommunityModerationPost, summary="隐藏或恢复社区帖子")
async def update_community_post_visibility(
    post_id: UUID,
    payload: CommunityModerationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """隐藏或恢复帖子，不做物理删除。"""

    result = await db.execute(
        select(CreativeContent).where(
            CreativeContent.id == post_id,
            CreativeContent.content_type == "community_post",
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="社区帖子不存在")

    metadata = dict(row.meta_info or {})
    metadata["is_hidden"] = bool(payload.is_hidden)
    metadata["moderation_reason"] = payload.reason
    metadata["moderated_at"] = datetime.utcnow().isoformat()
    metadata["moderated_by"] = admin.get("username") or admin.get("sub") or "admin"
    row.meta_info = metadata
    await db.commit()
    await db.refresh(row)
    return _moderation_post(row)
