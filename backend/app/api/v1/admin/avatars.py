"""管理后台-数字人形象配置API。"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.avatar_orchestrator import (
    AVATAR_PROFILES,
    DEFAULT_AVATAR_ACTION_PRESETS,
    DEFAULT_AVATAR_TRIGGER_SPOTS,
    get_avatar_orchestrator,
)
from app.database import get_db
from app.models import Avatar
from app.schemas.admin import AvatarConfigCreate, AvatarConfigResponse, AvatarConfigUpdate, AvatarHealthResponse
from app.utils.jwt import get_current_admin

router = APIRouter(prefix="/admin/avatars", tags=["管理后台-数字人"])
AVATAR_PREVIEW_DIR = Path(__file__).resolve().parents[3] / "static" / "avatar-previews"
AVATAR_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


class AvatarPreviewCaptureRequest(BaseModel):
    """浏览器从讯飞 WebSDK 当前画面截取的预览图。"""

    image_data: str = Field(..., min_length=32, max_length=4_000_000)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False) if isinstance(value, list) else json.dumps(value or {}, ensure_ascii=False)


def _appearance_bundle(profile) -> dict[str, str]:
    """把讯飞 Avatar 资源表达为不可拆分的形象与服装套装。"""

    costumes = {
        "lingxiaochan": "唐风襦裙，服饰随 Avatar ID 固定",
        "wuchanshi": "新中式雅士套装，服饰随 Avatar ID 固定",
        "xuanzang": "国风文士长衫，服饰随 Avatar ID 固定",
        "xiaowan": "国风轻礼服，服饰随 Avatar ID 固定",
        "zhaopuchu": "新中式文化讲解套装，服饰随 Avatar ID 固定",
    }
    return {
        "name": f"{profile.name}形象与服装套装",
        "gender": profile.gender,
        "costume_description": costumes.get(profile.code, "服饰随 Avatar ID 固定"),
    }


def _avatar_response(row: Avatar) -> AvatarConfigResponse:
    return AvatarConfigResponse(
        id=row.id,
        name=row.name,
        code=row.code,
        role_description=row.role_description,
        image_url=row.image_url,
        avatar_id=row.avatar_id,
        voice_id=row.voice_id,
        voice_emotion=row.voice_emotion,
        voice_params=_loads(row.voice_params, {}),
        personality_prompt=row.personality_prompt,
        default_greeting=row.default_greeting,
        trigger_spots=_loads(row.trigger_spots, []),
        is_active=bool(row.is_active),
        is_default=bool(row.is_default),
        sort_order=row.sort_order or 0,
        created_at=row.created_at,
    )


async def _seed_default_avatars(db: AsyncSession) -> None:
    """首次访问时写入环境变量中的默认数字人配置。"""

    for index, profile in enumerate(AVATAR_PROFILES.values(), start=1):
        exists = await db.execute(select(Avatar).where(Avatar.code == profile.code))
        if exists.scalar_one_or_none():
            continue
        db.add(
            Avatar(
                name=profile.name,
                code=profile.code,
                role_description=profile.title,
                avatar_id=profile.avatar_id,
                voice_id=profile.voice_id,
                voice_emotion="friendly" if profile.code == "lingxiaochan" else "neutral",
                voice_params=_dumps(
                    {
                        "provider": "xunfei",
                        "quality": 85,
                        "gender": profile.gender,
                        "appearance_bundle": _appearance_bundle(profile),
                        "action_presets": list(DEFAULT_AVATAR_ACTION_PRESETS.get(profile.code, ())),
                    }
                ),
                personality_prompt=f"{profile.name}，{profile.title}。",
                default_greeting=f"{profile.name}已准备好为游客讲解。",
                trigger_spots=_dumps(list(DEFAULT_AVATAR_TRIGGER_SPOTS.get(profile.code, ()))),
                is_active=True,
                is_default=profile.code == "lingxiaochan",
                sort_order=index,
            )
        )
    await db.commit()


async def _reset_default_avatars(db: AsyncSession) -> None:
    """用当前环境变量/代码默认值刷新内置数字人配置。"""

    for index, profile in enumerate(AVATAR_PROFILES.values(), start=1):
        result = await db.execute(select(Avatar).where(Avatar.code == profile.code))
        row = result.scalar_one_or_none()
        voice_params = {
            "provider": "xunfei",
            "quality": 90 if profile.gender == "male" else 94,
            "gender": profile.gender,
            "appearance_bundle": _appearance_bundle(profile),
            "action_presets": list(DEFAULT_AVATAR_ACTION_PRESETS.get(profile.code, ())),
        }
        if row:
            resources_unchanged = row.avatar_id == profile.avatar_id and row.voice_id == profile.voice_id
            if resources_unchanged:
                previous_params = _loads(row.voice_params, {})
                for key in ("preview_verified_at", "preview_avatar_id", "preview_voice_id"):
                    if previous_params.get(key):
                        voice_params[key] = previous_params[key]
            else:
                row.image_url = None
            row.name = profile.name
            row.role_description = profile.title
            row.avatar_id = profile.avatar_id
            row.voice_id = profile.voice_id
            row.voice_emotion = "friendly" if profile.code == "lingxiaochan" else "neutral"
            row.voice_params = _dumps(voice_params)
            row.personality_prompt = f"{profile.name}，{profile.title}。"
            row.default_greeting = f"{profile.name}已准备好为游客讲解。"
            row.trigger_spots = _dumps(list(DEFAULT_AVATAR_TRIGGER_SPOTS.get(profile.code, ())))
            row.is_active = True
            row.is_default = profile.code == "lingxiaochan"
            row.sort_order = index
        else:
            db.add(
                Avatar(
                    name=profile.name,
                    code=profile.code,
                    role_description=profile.title,
                    avatar_id=profile.avatar_id,
                    voice_id=profile.voice_id,
                    voice_emotion="friendly" if profile.code == "lingxiaochan" else "neutral",
                    voice_params=_dumps(voice_params),
                    personality_prompt=f"{profile.name}，{profile.title}。",
                    default_greeting=f"{profile.name}已准备好为游客讲解。",
                    trigger_spots=_dumps(list(DEFAULT_AVATAR_TRIGGER_SPOTS.get(profile.code, ()))),
                    is_active=True,
                    is_default=profile.code == "lingxiaochan",
                    sort_order=index,
                )
            )
    await db.commit()


@router.get("", response_model=list[AvatarConfigResponse], summary="数字人配置列表")
async def list_avatars(
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    query = select(Avatar).order_by(Avatar.sort_order, Avatar.created_at)
    if active_only:
        query = query.where(Avatar.is_active == True)  # noqa: E712
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        await _seed_default_avatars(db)
        result = await db.execute(query)
        rows = result.scalars().all()
    return [_avatar_response(row) for row in rows]


@router.post("", response_model=AvatarConfigResponse, summary="创建数字人配置")
async def create_avatar(
    payload: AvatarConfigCreate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    exists = await db.execute(select(Avatar).where(Avatar.code == payload.code))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="角色编码已存在")
    row = Avatar(
        name=payload.name,
        code=payload.code,
        role_description=payload.role_description,
        image_url=payload.image_url,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        voice_emotion=payload.voice_emotion,
        voice_params=_dumps(payload.voice_params),
        personality_prompt=payload.personality_prompt,
        default_greeting=payload.default_greeting,
        trigger_spots=_dumps(payload.trigger_spots),
        is_active=payload.is_active,
        is_default=payload.is_default,
        sort_order=payload.sort_order,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _avatar_response(row)


@router.post("/reset-defaults", response_model=list[AvatarConfigResponse], summary="重置为默认数字人配置")
async def reset_default_avatars(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """将内置五个数字人刷新为当前环境变量中的真实形象和VCN配置。"""

    del admin
    await _reset_default_avatars(db)
    result = await db.execute(select(Avatar).order_by(Avatar.sort_order, Avatar.created_at))
    return [_avatar_response(row) for row in result.scalars().all()]


@router.put("/{avatar_id}", response_model=AvatarConfigResponse, summary="更新数字人配置")
async def update_avatar(
    avatar_id: UUID,
    payload: AvatarConfigUpdate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    result = await db.execute(select(Avatar).where(Avatar.id == avatar_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数字人不存在")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        if key in {"voice_params", "trigger_spots"}:
            setattr(row, key, _dumps(value))
        else:
            setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return _avatar_response(row)


@router.put("/{avatar_id}/enabled", response_model=AvatarConfigResponse, summary="启停数字人")
async def set_avatar_enabled(
    avatar_id: UUID,
    enabled: bool = Query(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    result = await db.execute(select(Avatar).where(Avatar.id == avatar_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数字人不存在")
    row.is_active = enabled
    await db.commit()
    await db.refresh(row)
    return _avatar_response(row)


@router.get("/{avatar_id}/preview-config", summary="获取数字人实时预览配置")
async def get_avatar_preview_config(
    avatar_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """返回签名后的 WebSDK 配置，供管理后台逐个核验形象 ID。"""

    del admin
    result = await db.execute(select(Avatar).where(Avatar.id == avatar_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数字人不存在")
    if not row.avatar_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="该数字人未配置 Avatar ID")

    preview_text = f"您好，我是{row.name}。这是数字人形象预览。"
    try:
        payload = await get_avatar_orchestrator().render_reply(
            text=preview_text,
            avatar_name=row.code,
            emotion=row.voice_emotion or "neutral",
            session_id=f"admin-preview-{row.id}",
            audio_url=None,
            intent="greeting",
            prefer_video=True,
            db_session=db,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"预览配置生成失败：{exc}",
        ) from exc

    return {
        "avatar_id": row.avatar_id,
        "avatar_name": row.name,
        "image_url": row.image_url,
        "preview_text": preview_text,
        "sdk_config": payload.get("sdk_config"),
    }


@router.post("/{avatar_id}/preview-image", response_model=AvatarConfigResponse, summary="保存数字人预览截图")
async def save_avatar_preview_image(
    avatar_id: UUID,
    payload: AvatarPreviewCaptureRequest,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """保存 WebSDK 实际画面截图，并作为数字人列表头像。"""

    del admin
    result = await db.execute(select(Avatar).where(Avatar.id == avatar_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数字人不存在")

    try:
        header, encoded = payload.image_data.split(",", 1)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="预览图格式无效") from exc
    image_types = {
        "data:image/png;base64": ("png", b"\x89PNG\r\n\x1a\n"),
        "data:image/jpeg;base64": ("jpg", b"\xff\xd8\xff"),
        "data:image/webp;base64": ("webp", b"RIFF"),
    }
    image_type = image_types.get(header.lower())
    if not image_type:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="仅支持 PNG、JPEG 或 WebP 截图")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="预览图编码无效") from exc
    extension, signature = image_type
    if len(image_bytes) > 2_500_000 or not image_bytes.startswith(signature):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="预览图内容无效或超过 2.5MB")
    if extension == "webp" and image_bytes[8:12] != b"WEBP":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="WebP 预览图内容无效")

    AVATAR_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for old_file in AVATAR_PREVIEW_DIR.glob(f"{row.id}.*"):
        if old_file.is_file():
            old_file.unlink()
    output_path = AVATAR_PREVIEW_DIR / f"{row.id}.{extension}"
    output_path.write_bytes(image_bytes)
    row.image_url = f"/api/v1/avatar-previews/{output_path.name}?v={int(time.time())}"
    voice_params = _loads(row.voice_params, {})
    current_bundle = voice_params.get("appearance_bundle") or {}
    voice_params.update(
        {
            "preview_verified_at": datetime.now(timezone.utc).isoformat(),
            "preview_avatar_id": row.avatar_id,
            "preview_voice_id": row.voice_id,
            "appearance_bundle": {
                "name": current_bundle.get("name") or f"{row.name}形象与服装套装",
                "gender": current_bundle.get("gender") or voice_params.get("gender") or "unknown",
                "costume_description": current_bundle.get("costume_description") or "服饰随 Avatar ID 固定",
            },
        }
    )
    row.voice_params = _dumps(voice_params)
    await db.commit()
    await db.refresh(row)
    return _avatar_response(row)


@router.get("/{avatar_id}/health", response_model=AvatarHealthResponse, summary="数字人链路健康检查")
async def check_avatar_health(
    avatar_id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    result = await db.execute(select(Avatar).where(Avatar.id == avatar_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数字人不存在")

    checks = [
        {"name": "app_id", "ok": bool(settings.XFYUN_APP_ID), "detail": "XFYUN_APP_ID"},
        {"name": "api_key", "ok": bool(settings.XFYUN_API_KEY), "detail": "XFYUN_API_KEY"},
        {"name": "scene_id", "ok": bool(settings.XFYUN_AVATAR_SCENE_ID), "detail": "XFYUN_AVATAR_SCENE_ID"},
        {"name": "avatar_id", "ok": bool(row.avatar_id), "detail": row.avatar_id or "未配置"},
        {"name": "voice_id", "ok": bool(row.voice_id or settings.XFYUN_TTS_VCN), "detail": row.voice_id or settings.XFYUN_TTS_VCN or "未配置"},
    ]
    sdk_preview = None
    try:
        payload = await get_avatar_orchestrator().render_reply(
            text="数字人链路健康检查",
            avatar_name=row.name,
            emotion=row.voice_emotion or "neutral",
            session_id="health-check",
            audio_url="/api/v1/tts?text=health",
            intent="health_check",
            prefer_video=True,
            db_session=db,
        )
        sdk_preview = {
            "render_mode": payload.get("render_mode"),
            "provider": payload.get("provider"),
            "uses_signed_url": (payload.get("sdk_config") or {}).get("uses_signed_url"),
            "write_text_nlp": (payload.get("sdk_config") or {}).get("write_text_nlp"),
        }
        checks.append({"name": "sdk_payload", "ok": True, "detail": "payload生成成功"})
    except Exception as exc:
        checks.append({"name": "sdk_payload", "ok": False, "detail": str(exc)})
    return AvatarHealthResponse(
        avatar_code=row.code,
        avatar_name=row.name,
        ok=all(item["ok"] for item in checks),
        checks=checks,
        sdk_preview=sdk_preview,
    )
