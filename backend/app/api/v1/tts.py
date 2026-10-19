"""TTS语音合成API模块。"""

import os
import tempfile
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse
from loguru import logger

from app.config import settings
from app.core.xunfei_tts import XunfeiTTSClient
from app.core.avatar_orchestrator import resolve_avatar_profile

router = APIRouter(tags=["语音合成"])

XFYUN_EMOTION_MAP = {
    "neutral": "neutral",
    "happy": "cheerful",
    "excited": "cheerful",
    "curious": "cheerful",
    "calm": "calm",
    "tired": "gentle",
    "frustrated": "gentle",
    "anxious": "calm",
}

# 数字人 WebSDK 的 x4 发音人与独立在线 TTS 属于不同授权能力。
# 这里仅为明确调用 /tts 的纯音频入口选用当前账号已验证可用的 TTS 音色；
# 数字人主链路仍使用 AvatarProfile.voice_id，不受此映射影响。
TTS_VOICE_MAP = {
    "lingxiaochan": "xiaoyan",
    "wuchanshi": "aisjiuxu",
    "xuanzang": "aisjiuxu",
    "zhaopuchu": "aisjiuxu",
    "xiaowan": "x4_lingxiaoyue_oral_emo",
}


def _resolve_xfyun_voice(avatar: str) -> str:
    """按数字人形象解析对应讯飞发音人。"""

    profile = resolve_avatar_profile(avatar)
    return TTS_VOICE_MAP.get(profile.code) or settings.XFYUN_TTS_VCN or "xiaoyan"


async def _run_xfyun_tts(text: str, avatar: str, emotion: str, speed: float, output_file: str) -> bool:
    """调用讯飞 TTS 并写入本地临时文件。"""

    client = XunfeiTTSClient()
    if not client.is_configured:
        return False

    voice_id = _resolve_xfyun_voice(avatar)
    try:
        audio = await client.synthesize(
            text=text,
            voice_id=voice_id,
            emotion=XFYUN_EMOTION_MAP.get(emotion, "neutral"),
            speed=speed,
            pitch=1.0,
            volume=70,
        )
        with open(output_file, "wb") as f:
            f.write(audio)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
            logger.info(f"[TTS] 讯飞TTS成功: voice_id={voice_id}")
            return True
    except Exception as exc:
        logger.warning(f"[TTS] 讯飞TTS失败: voice_id={voice_id}, error={exc}")
        return False

    logger.warning("[TTS] 讯飞TTS返回音频无效")
    return False


@router.get("/tts", summary="文本转语音")
async def text_to_speech(
    text: str,
    background_tasks: BackgroundTasks,
    avatar: str = "舒窈",
    emotion: str = "neutral",
    speed: float = 1.0,
):
    """文本转语音接口"""
    if not text or not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本不能为空")

    if len(text) > 2000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本长度不能超过2000字符")

    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, f"tts_{uuid.uuid4().hex}.mp3")

    logger.info(f"[TTS] 开始: avatar={avatar}, vcn={_resolve_xfyun_voice(avatar)}, len={len(text)}")

    tts_source = "xunfei-tts"
    success = await _run_xfyun_tts(text, avatar, emotion, speed, output_file)

    if not success or not os.path.exists(output_file) or os.path.getsize(output_file) < 1000:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="语音合成失败")

    file_size = os.path.getsize(output_file)
    logger.info(f"TTS成功: source={tts_source}, size={file_size}B")

    background_tasks.add_task(os.remove, output_file)
    return FileResponse(
        output_file,
        media_type="audio/mpeg",
        filename=f"tts_{avatar}.mp3",
    )
