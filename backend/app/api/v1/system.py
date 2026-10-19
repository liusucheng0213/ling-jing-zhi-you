"""系统严格健康检查与真实链路探测。"""

from __future__ import annotations

import time
import asyncio
import uuid
from typing import Any

import aiohttp
import httpx
from fastapi import APIRouter, Query
from redis.asyncio import from_url as redis_from_url
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from app.core.avatar_channel import avatar_channel_coordinator
from app.core.avatar_orchestrator import AVATAR_PROFILES
from app.core.xunfei_avatar import XunfeiAvatarClient
from app.core.xunfei_tts import XunfeiTTSClient

router = APIRouter(tags=["系统"])


def _exception_payload(exc: BaseException) -> dict[str, str]:
    """返回可用于排障的异常信息，避免空字符串吞掉真实类型。"""

    return {
        "error": str(exc) or repr(exc),
        "error_type": exc.__class__.__name__,
    }


async def _timed_check(name: str, func) -> dict[str, Any]:
    """执行单项检查并记录耗时。"""

    started_at = time.perf_counter()
    try:
        payload = await func()
        return {
            "name": name,
            "ok": bool(payload.get("ok", True)),
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            **payload,
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            **_exception_payload(exc),
        }


async def _check_database() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT 1"))
        docs = await db.execute(text("SELECT count(*) FROM knowledge_documents WHERE status = 'published'"))
        chunks = await db.execute(text("SELECT count(*) FROM knowledge_chunks"))
        embedded = await db.execute(text("SELECT count(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"))
        return {
            "ok": True,
            "published_documents": int(docs.scalar() or 0),
            "knowledge_chunks": int(chunks.scalar() or 0),
            "embedded_chunks": int(embedded.scalar() or 0),
        }


async def _check_redis() -> dict[str, Any]:
    client = redis_from_url(settings.REDIS_URL, socket_connect_timeout=1.5, socket_timeout=1.5)
    try:
        pong = await client.ping()
        return {"ok": bool(pong)}
    finally:
        await client.aclose()


async def _check_embedding_service() -> dict[str, Any]:
    if not settings.EMBEDDING_SERVICE_URL:
        return {"ok": False, "error": "EMBEDDING_SERVICE_URL 未配置"}
    timeout = httpx.Timeout(connect=1.0, read=3.0, write=1.0, pool=1.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{settings.EMBEDDING_SERVICE_URL.rstrip('/')}/health")
        response.raise_for_status()
        data = response.json()
    runtime = data.get("runtime") or {}
    return {
        "ok": data.get("status") == "healthy",
        "service": data,
        "cuda_available": runtime.get("cuda_available", data.get("cuda_available")),
        "loaded_device": runtime.get("loaded_device", data.get("loaded_device")),
        "torch_version": runtime.get("torch_version"),
    }


async def _check_llm_probe() -> dict[str, Any]:
    from app.core.llm_router import llm_router

    text = await llm_router.chat(
        messages=[
            {"role": "system", "content": "你是接口健康检查器，请简短回答。"},
            {"role": "user", "content": "请用一句中文回答：系统正常。"},
        ],
        temperature=0.1,
        max_tokens=32,
        thinking={"type": "disabled"},
    )
    return {"ok": bool(text.strip()), "sample": text[:80], "model": settings.DEEPSEEK_MODEL}


async def _check_tts_probe() -> dict[str, Any]:
    client = XunfeiTTSClient()
    audio = await client.synthesize(
        text="灵境智游语音链路测试。",
        voice_id=settings.XFYUN_TTS_VCN,
        emotion="neutral",
        speed=1.0,
    )
    return {"ok": len(audio) > 1000, "bytes": len(audio), "vcn": settings.XFYUN_TTS_VCN}


async def _check_avatar_config() -> dict[str, Any]:
    configured_profiles = [
        profile.name for profile in AVATAR_PROFILES.values() if profile.avatar_id
    ]
    background_value = settings.XFYUN_AVATAR_BACKGROUND_RES_KEY.strip()
    background_type = settings.XFYUN_AVATAR_BACKGROUND_TYPE or "background_data"
    background_type_normalized = background_type.lower()
    background_start_keys: list[str] = []
    background_global_fields = ["data", "type"] if background_value else []
    if background_value and background_type_normalized in {"res_id", "resid", "resource_id"}:
        background_start_keys = ["res_id"]
        background_global_fields.extend(["res_id", "resId"])
    elif background_value and background_type_normalized in {"res_key", "reskey", "resource", "resource_key"}:
        background_start_keys = ["res_key"]
        background_global_fields.extend(["res_key", "resKey"])
    ok = bool(
        settings.XFYUN_APP_ID
        and settings.XFYUN_API_KEY
        and settings.XFYUN_API_SECRET
        and settings.XFYUN_AVATAR_SCENE_ID
        and configured_profiles
    )
    return {
        "ok": ok,
        "app_id_configured": bool(settings.XFYUN_APP_ID),
        "api_key_configured": bool(settings.XFYUN_API_KEY),
        "api_secret_configured": bool(settings.XFYUN_API_SECRET),
        "scene_id_configured": bool(settings.XFYUN_AVATAR_SCENE_ID),
        "configured_profiles": configured_profiles,
        "avatar_vcn": settings.XFYUN_AVATAR_VCN,
        "stream_protocol": settings.XFYUN_AVATAR_STREAM_PROTOCOL,
        "resolution": {
            "width": settings.XFYUN_AVATAR_WIDTH,
            "height": settings.XFYUN_AVATAR_HEIGHT,
            "fps": settings.XFYUN_AVATAR_FPS,
            "bitrate": settings.XFYUN_AVATAR_BITRATE,
        },
        "background_configured": bool(background_value),
        "background_type": background_type,
        "background_value_length": len(background_value),
        "background_global_fields": background_global_fields,
        "background_start_keys": background_start_keys,
        "background_note": "背景需要讯飞控制台素材可用、资源类型匹配，并在 WebSDK start 时带入；诊断不展示真实资源值。",
        "background_acceptance_hint": "如果配置值是原始图片 base64，类型通常应为 background_data；如果是控制台上传资源，需按讯飞返回字段使用 res_id 或 res_key。",
        "release_required": True,
        "release_note": "页面切换、刷新和卸载时必须释放 WebSDK 实例，避免占用多路讯飞连接。",
        "manual_acceptance_required": True,
        "acceptance_checklist": [
            "浏览器 Console 无 SDK 初始化、鉴权或播放错误",
            "Network/WebSocket 中数字人连接建立后可正常释放",
            "后端 sdk_config.global_params.background 与 start_options 已包含背景字段",
            "人物后方能看到配置的背景资源且无遮挡",
            "播报文本和动作指令能进入讯飞 WebSDK 主链路",
        ],
        "strict_note": "严格模式只验收讯飞虚拟数字人 WebSDK 主链路",
    }


async def _check_avatar_ws_probe() -> dict[str, Any]:
    """
    真实探测讯飞数字人 WebSocket 鉴权握手。

    这里只验证鉴权 URL 能否建立连接，不发送 start payload，避免健康检查生成视频流。
    """

    client = XunfeiAvatarClient()
    signed_url = client.build_signed_url(settings.XFYUN_AVATAR_SERVER_URL)
    if not signed_url:
        return {"ok": False, "error": "讯飞数字人鉴权配置不完整"}

    timeout = aiohttp.ClientTimeout(total=8, sock_connect=4, sock_read=4)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(signed_url, heartbeat=4) as ws:
                try:
                    message = await ws.receive(timeout=3)
                except asyncio.TimeoutError:
                    return {
                        "ok": True,
                        "handshake": "connected",
                        "first_message_type": "none",
                        "note": "WebSocket 已完成鉴权连接；未发送 start payload 时服务端可能不会主动下发首包。",
                    }
                if message.type == aiohttp.WSMsgType.TEXT:
                    return {
                        "ok": True,
                        "handshake": "connected",
                        "first_message_type": "text",
                        "first_message_preview": message.data[:160],
                    }
                if message.type == aiohttp.WSMsgType.CLOSED:
                    return {
                        "ok": False,
                        "handshake": "closed",
                        "close_code": ws.close_code,
                    }
                if message.type == aiohttp.WSMsgType.ERROR:
                    error = ws.exception()
                    return {
                        "ok": False,
                        "handshake": "error",
                        **(_exception_payload(error) if error else {"error": "unknown websocket error"}),
                    }
                return {
                    "ok": True,
                    "handshake": "connected",
                    "first_message_type": str(message.type),
                }
    except aiohttp.WSServerHandshakeError as exc:
        return {
            "ok": False,
            "handshake": "rejected",
            "status": exc.status,
            "reason": exc.message,
        }
    except Exception as exc:
        return {
            "ok": False,
            "handshake": "failed",
            **_exception_payload(exc),
        }


async def _check_avatar_ws_probe_leased() -> dict[str, Any]:
    """经通道租约串行执行数字人 WebSocket 探测，避免健康检查与游客争抢单路资源。"""

    lease = await avatar_channel_coordinator.acquire(
        f"health-probe-{uuid.uuid4().hex}",
        "showcase_probe",
    )
    if lease.status != "acquired" or not lease.lease_token:
        return {
            "ok": True,
            "skipped": True,
            "channel_status": lease.status,
            "note": lease.message or "数字人通道被占用，WebSocket 探测已跳过",
        }
    try:
        return await _check_avatar_ws_probe()
    finally:
        await avatar_channel_coordinator.release(lease.lease_token)


@router.get("/system/strict-health", summary="严格真实链路健康检查")
async def strict_health(
    probe_external: bool = Query(False, description="是否真实调用外部LLM/TTS接口"),
    require_cuda: bool = Query(False, description="是否要求embedding-service必须可用CUDA"),
):
    """
    严格健康检查。

    该接口只验收真实链路：数据库、Redis、知识库、embedding-service、
    数字人SDK配置必须逐项可见；probe_external=true 时会真实调用 LLM 和 TTS。
    """

    checks = [
        await _timed_check("database", _check_database),
        await _timed_check("redis", _check_redis),
        await _timed_check("embedding_service", _check_embedding_service),
        await _timed_check("avatar_sdk_config", _check_avatar_config),
    ]
    if probe_external:
        checks.extend(
            [
                await _timed_check("llm_deepseek", _check_llm_probe),
                await _timed_check("xunfei_tts", _check_tts_probe),
                await _timed_check("xunfei_avatar_ws", _check_avatar_ws_probe_leased),
            ]
        )

    if require_cuda:
        for item in checks:
            if item["name"] == "embedding_service" and not item.get("cuda_available"):
                item["ok"] = False
                item["error"] = "要求CUDA，但embedding-service未检测到CUDA"

    required = checks
    overall_ok = all(item["ok"] for item in required)
    return {
        "status": "pass" if overall_ok else "fail",
        "strict": True,
        "probe_external": probe_external,
        "require_cuda": require_cuda,
        "checks": checks,
    }


@router.get("/system/avatar-diagnostics", summary="数字人非敏感诊断")
async def avatar_diagnostics():
    """返回游客端可展示的数字人诊断信息，不包含密钥或签名串。"""

    config = await _check_avatar_config()
    return {
        "ok": config["ok"],
        "background_configured": config["background_configured"],
        "background_type": config["background_type"],
        "background_value_length": config["background_value_length"],
        "background_global_fields": config["background_global_fields"],
        "background_start_keys": config["background_start_keys"],
        "background_note": config["background_note"],
        "background_acceptance_hint": config["background_acceptance_hint"],
        "scene_id_configured": config["scene_id_configured"],
        "configured_profiles": config["configured_profiles"],
        "avatar_vcn": config["avatar_vcn"],
        "stream_protocol": config["stream_protocol"],
        "resolution": config["resolution"],
        "release_required": config["release_required"],
        "release_note": config["release_note"],
        "manual_acceptance_required": config["manual_acceptance_required"],
        "acceptance_checklist": config["acceptance_checklist"],
        "safe_fields_only": True,
    }
