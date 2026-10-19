"""
讯飞语音合成API客户端。

使用讯飞 WebSocket TTS，输出 mp3/lame 音频字节。数字人 SDK
本身会在 writeText 时完成播报，这里只服务明确调用 `/api/v1/tts` 的音频播放入口。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse

import aiohttp
from loguru import logger

from app.config import settings


class XunfeiTTSClient:
    """讯飞TTS客户端"""

    def __init__(self):
        self.app_id = settings.XFYUN_APP_ID
        self.api_key = settings.XFYUN_API_KEY
        self.api_secret = settings.XFYUN_API_SECRET
        self.base_url = settings.XFYUN_TTS_URL or "wss://tts-api.xfyun.cn/v2/tts"

    @property
    def is_configured(self) -> bool:
        """TTS 调用所需配置是否完整。"""

        return bool(self.app_id and self.api_key and self.api_secret)

    def _build_auth_url(self) -> str:
        """构建讯飞 WebSocket 鉴权 URL。"""

        parsed = urllib.parse.urlparse(self.base_url)
        host = parsed.netloc
        path = parsed.path or "/v2/tts"
        date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
        return f"{self.base_url}?{urllib.parse.urlencode({'authorization': authorization, 'date': date, 'host': host})}"

    async def synthesize(
        self,
        text: str,
        voice_id: str = "xiaoyan",
        emotion: str | int = "neutral",
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: int = 50,
    ) -> bytes:
        """
        语音合成

        参数:
            text: 要合成的文本
            voice_id: 音色ID（xiaoyan/xiaoqiang/xiaomei等）
            emotion: 情感标签（neutral/cheerful/gentle/calm等）
            speed: 语速倍率（0.5-2.0）
            pitch: 音调倍率
            volume: 音量（0-100）

        返回: mp3/lame 音频字节
        """
        if not self.is_configured:
            raise ValueError("讯飞TTS API密钥未配置")

        speed_value = max(0, min(100, int(speed * 50)))
        pitch_value = max(0, min(100, int(pitch * 50)))
        volume_value = max(0, min(100, int(volume)))
        sample_rate = 24000 if settings.XFYUN_TTS_SAMPLE_RATE == 24000 else 16000
        vcn = voice_id or settings.XFYUN_TTS_VCN

        payload = {
            "common": {"app_id": self.app_id},
            "business": {
                "aue": settings.XFYUN_TTS_AUE or "lame",
                "auf": f"audio/L16;rate={sample_rate}",
                "vcn": vcn,
                "speed": speed_value,
                "volume": volume_value,
                "pitch": pitch_value,
                "tte": "UTF8",
                "ent": "intp65",
                "sfl": 1,
            },
            "data": {
                "status": 2,
                "text": self._encode_text(text),
            },
        }
        emotion_value = self._normalize_emotion(emotion)
        if emotion_value is not None:
            payload["business"]["emotion"] = emotion_value

        try:
            audio_parts: list[bytes] = []
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    self._build_auth_url(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as ws:
                    await ws.send_str(json.dumps(payload, ensure_ascii=False))
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type == aiohttp.WSMsgType.ERROR:
                                raise RuntimeError(f"讯飞TTS WebSocket错误: {ws.exception()}")
                            continue
                        result = json.loads(msg.data)
                        if result.get("code", 0) != 0:
                            raise RuntimeError(f"讯飞TTS返回错误: {result}")
                        data = result.get("data") or {}
                        if data.get("audio"):
                            audio_parts.append(base64.b64decode(data["audio"]))
                        if data.get("status") == 2:
                            break

            audio = b"".join(audio_parts)
            if len(audio) < 1000:
                raise RuntimeError("讯飞TTS返回音频为空或过小")
            logger.info(f"讯飞TTS成功: vcn={vcn}, bytes={len(audio)}")
            return audio

        except Exception as e:
            logger.error(f"讯飞TTS调用失败: {e}")
            raise

    def _encode_text(self, text: str) -> str:
        """Base64编码文本"""
        import base64
        return base64.b64encode(text.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _normalize_emotion(emotion: str | int | None) -> int | None:
        """
        规范化讯飞TTS情感参数。

        讯飞部分TTS能力的 business.emotion 要求为整数；普通 happy/curious
        等业务标签不能直接透传，否则会触发参数校验错误。未配置数字情感时
        交给发音人默认风格，保证合成链路优先可用。
        """

        if emotion is None:
            return None
        if isinstance(emotion, int):
            return emotion
        value = str(emotion).strip()
        if value.isdigit():
            return int(value)
        return None
