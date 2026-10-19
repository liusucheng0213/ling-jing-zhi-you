"""管理后台用户列表与行为摘要接口。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ChatMessage, Session, User, UserStoryProgress
from app.utils.jwt import get_current_admin


router = APIRouter(prefix="/admin/users", tags=["管理后台-用户管理"])


class AdminUserItem(BaseModel):
    """用户列表项。"""

    id: str
    nickname: str
    phone: str | None = None
    status: Literal["active", "inactive"]
    created_at: datetime | None = None
    last_active: datetime | None = None
    total_sessions: int = 0
    total_qa: int = 0
    visit_count: int = 0
    age_group: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_sample: bool = False


class AdminUserListResponse(BaseModel):
    """分页用户列表。"""

    items: list[AdminUserItem]
    total: int
    page: int
    page_size: int


def _mask_phone(phone: str | None) -> str | None:
    """对手机号做最小化展示。"""

    if not phone:
        return None
    if len(phone) >= 7:
        return f"{phone[:3]}****{phone[-4:]}"
    return "****"


def _parse_interests(raw: str | None) -> list[str]:
    """兼容JSON数组与逗号分隔的历史兴趣字段。"""

    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]


@router.get("", response_model=AdminUserListResponse, summary="分页获取真实用户统计")
async def list_admin_users(
    q: str | None = Query(default=None, max_length=100),
    status: Literal["all", "active", "inactive"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """从用户、会话、消息和故事进度表聚合后台用户数据。"""

    session_stats = (
        select(
            Session.user_id.label("user_id"),
            func.count(Session.id).label("total_sessions"),
            func.max(Session.started_at).label("session_last_active"),
        )
        .where(Session.user_id.isnot(None))
        .group_by(Session.user_id)
        .subquery()
    )
    message_stats = (
        select(
            Session.user_id.label("user_id"),
            func.count(ChatMessage.id).filter(ChatMessage.role == "user").label("total_qa"),
        )
        .join(ChatMessage, ChatMessage.session_id == Session.id)
        .where(Session.user_id.isnot(None))
        .group_by(Session.user_id)
        .subquery()
    )
    story_stats = (
        select(
            UserStoryProgress.user_id.label("user_id"),
            func.count(UserStoryProgress.id).label("story_count"),
        )
        .group_by(UserStoryProgress.user_id)
        .subquery()
    )

    last_active_expr = func.coalesce(
        func.greatest(User.last_visit_at, session_stats.c.session_last_active),
        User.last_visit_at,
        session_stats.c.session_last_active,
        User.created_at,
    )
    active_cutoff = datetime.now() - timedelta(days=7)
    stmt = (
        select(
            User,
            func.coalesce(session_stats.c.total_sessions, 0).label("total_sessions"),
            func.coalesce(message_stats.c.total_qa, 0).label("total_qa"),
            func.coalesce(story_stats.c.story_count, 0).label("story_count"),
            last_active_expr.label("last_active"),
        )
        .outerjoin(session_stats, session_stats.c.user_id == User.id)
        .outerjoin(message_stats, message_stats.c.user_id == User.id)
        .outerjoin(story_stats, story_stats.c.user_id == User.id)
    )

    keyword = (q or "").strip()
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                User.nickname.ilike(pattern),
                User.phone.ilike(pattern),
                cast(User.id, String).ilike(pattern),
            )
        )
    if status == "active":
        stmt = stmt.where(last_active_expr >= active_cutoff)
    elif status == "inactive":
        stmt = stmt.where(last_active_expr < active_cutoff)

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(last_active_expr.desc().nullslast(), User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items: list[AdminUserItem] = []
    for user, total_sessions, total_qa, story_count, last_active in rows:
        is_sample = bool((user.nickname or "").startswith("演示游客"))
        display_name = (
            f"游客_{str(user.id).split('-')[0]}"
            if is_sample
            else (user.nickname or f"游客_{str(user.id).split('-')[0]}")
        )
        tags = _parse_interests(user.interests)[:3]
        if int(total_sessions or 0) >= 3:
            tags.append("多次使用")
        if int(story_count or 0) > 0:
            tags.append("故事参与者")
        if user.age_group == "60+":
            tags.append("长者用户")
        items.append(
            AdminUserItem(
                id=str(user.id),
                nickname=display_name,
                phone=_mask_phone(user.phone),
                status="active" if last_active and last_active >= active_cutoff else "inactive",
                created_at=user.created_at,
                last_active=last_active,
                total_sessions=int(total_sessions or 0),
                total_qa=int(total_qa or 0),
                visit_count=int(user.visit_count or 0),
                age_group=user.age_group,
                tags=list(dict.fromkeys(tags)),
                is_sample=is_sample,
            )
        )

    return AdminUserListResponse(items=items, total=total, page=page, page_size=page_size)
