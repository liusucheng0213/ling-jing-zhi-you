"""游客端数字人配置API。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.core.avatar_orchestrator import AVATAR_PROFILES, DEFAULT_AVATAR_NAME
from app.core.avatar_channel import (
    AvatarOwnerType,
    avatar_channel_coordinator,
)
from app.database import get_db
from app.models import Avatar, BehaviorLog

router = APIRouter(tags=["数字人"])


class PublicAvatarResponse(BaseModel):
    """游客端可见的数字人展示配置。"""

    code: str
    name: str
    title: str
    description: str
    enabled: bool
    image_url: str | None = None


class AvatarChannelAcquireRequest(BaseModel):
    """数字人通道申请参数。"""

    owner_id: str = Field(min_length=6, max_length=120)
    owner_type: AvatarOwnerType


class AvatarChannelTokenRequest(BaseModel):
    """数字人通道续租或释放参数。"""

    lease_token: str = Field(min_length=16, max_length=120)


class AvatarChannelResponse(BaseModel):
    """数字人唯一通道状态。"""

    status: Literal[
        "idle",
        "occupied",
        "cooldown",
        "revoking",
        "revoked",
        "acquired",
    ]
    owner_type: AvatarOwnerType | None = None
    lease_token: str | None = None
    retry_after_ms: int = Field(default=0, ge=0)
    message: str


class AvatarTelemetryRequest(BaseModel):
    """真实浏览器 WebSDK 自然度与语音时延事件。"""

    session_id: UUID | None = None
    trace_id: UUID | None = None
    event_type: Literal[
        "voice_stop",
        "connection",
        "first_frame",
        "first_subtitle",
        "speech_start",
        "action",
        "complete",
        "interrupted",
        "disconnected",
        "authentication_failed",
    ]
    relative_ms: int | None = Field(default=None, ge=0, le=300_000)
    event_epoch_ms: int = Field(ge=0)
    avatar_code: str | None = Field(default=None, max_length=50)
    request_id: str | None = Field(default=None, max_length=160)
    input_mode: Literal["text", "voice", "image", "manual_tts", "session"] = "session"
    evidence_kind: Literal["human_microphone", "browser_sdk", "media_playback"] = "browser_sdk"
    event_data: dict[str, Any] = Field(default_factory=dict)
    spot_id: str | None = Field(default=None, max_length=50)


@router.get("/avatars", response_model=list[PublicAvatarResponse], summary="获取启用数字人列表")
async def list_public_avatars(db: AsyncSession = Depends(get_db)):
    """返回管理端启用的全部数字人。"""

    result = await db.execute(
        select(Avatar)
        .where(Avatar.is_active == True)  # noqa: E712
        .order_by(Avatar.sort_order, Avatar.created_at)
    )
    rows = result.scalars().all()
    if rows:
        return [
            PublicAvatarResponse(
                code=row.code,
                name=row.name,
                title=row.role_description or "AI数字人导游",
                description=row.personality_prompt or row.role_description or "",
                enabled=True,
                image_url=row.image_url,
            )
            for row in rows
        ]

    profile = AVATAR_PROFILES[DEFAULT_AVATAR_NAME]
    return [PublicAvatarResponse(
        code=profile.code,
        name=profile.name,
        title=profile.title,
        description=f"{profile.name}，{profile.title}。",
        enabled=True,
        image_url=None,
    )]


@router.get(
    "/avatar/channel",
    response_model=AvatarChannelResponse,
    summary="查看数字人唯一通道状态",
)
async def get_avatar_channel() -> AvatarChannelResponse:
    """返回游客端和后台共用的数字人唯一通道状态。"""

    result = await avatar_channel_coordinator.status()
    return AvatarChannelResponse(**result.to_dict())


@router.post(
    "/avatar/channel/acquire",
    response_model=AvatarChannelResponse,
    summary="申请数字人唯一通道",
)
async def acquire_avatar_channel(
    request: AvatarChannelAcquireRequest,
) -> AvatarChannelResponse:
    """申请租约；游客申请会优先撤销后台预览或探针。"""

    result = await avatar_channel_coordinator.acquire(
        request.owner_id,
        request.owner_type,
    )
    return AvatarChannelResponse(**result.to_dict())


@router.post(
    "/avatar/channel/heartbeat",
    response_model=AvatarChannelResponse,
    summary="续租数字人唯一通道",
)
async def heartbeat_avatar_channel(
    request: AvatarChannelTokenRequest,
) -> AvatarChannelResponse:
    """按租约令牌续期；被游客撤销时返回 revoked。"""

    result = await avatar_channel_coordinator.heartbeat(request.lease_token)
    return AvatarChannelResponse(**result.to_dict())


@router.post(
    "/avatar/channel/release",
    response_model=AvatarChannelResponse,
    summary="释放数字人唯一通道",
)
async def release_avatar_channel(
    request: AvatarChannelTokenRequest,
) -> AvatarChannelResponse:
    """幂等释放当前租约，并进入统一的 WebSDK 冷却期。"""

    result = await avatar_channel_coordinator.release(request.lease_token)
    return AvatarChannelResponse(**result.to_dict())


@router.post("/avatar/telemetry", summary="记录数字人浏览器遥测")
async def record_avatar_telemetry(
    request: AvatarTelemetryRequest,
    db: AsyncSession = Depends(get_db),
):
    """写入现有行为日志，供 A5 首帧、首字幕和真人语音验收汇总。"""

    payload = request.model_dump(mode="json", exclude={"session_id", "spot_id"})
    db.add(
        BehaviorLog(
            session_id=request.session_id,
            event_type="avatar_telemetry",
            event_data=payload,
            spot_id=request.spot_id,
        )
    )
    await db.commit()
    return {"accepted": True, "event_type": request.event_type}
