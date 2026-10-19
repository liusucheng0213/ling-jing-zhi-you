"""
讯飞语音识别(ASR)客户端
支持语音转文字，使用讯飞开放平台WebAPI
"""

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Optional

try:
    import aiohttp
except ImportError:
    raise ImportError("请先安装 aiohttp: pip install aiohttp")

from loguru import logger

from app.config import settings


class XunfeiASRClient:
    """
    讯飞语音识别客户端

    使用讯飞开放平台语音识别API，支持PCM/WAV音频格式
    参考文档: https://www.xfyun.cn/doc/asr/voicedictation/API.html
    """

    # 讯飞API配置
    HOST = "iat-api.xfyun.cn"
    PATH = "/v2/iat"
    PROTOCOL = "wss"

    def __init__(
        self,
        app_id: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        engine_type: str = "sms16k",  # 引擎类型: sms16k(16k采样率)
        timeout: float = 30.0,
    ):
        self.app_id = app_id or settings.XFYUN_APP_ID
        self.api_key = api_key or settings.XFYUN_API_KEY
        self.api_secret = api_secret or settings.XFYUN_API_SECRET
        self.engine_type = engine_type
        self.timeout = timeout

        if not all([self.app_id, self.api_key, self.api_secret]):
            logger.warning("讯飞ASR配置不完整，语音识别功能将不可用")

    def _build_auth_url(self) -> str:
        """
        构建带鉴权参数的WebSocket URL

        使用HMAC-SHA256签名算法生成鉴权参数
        """
        date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

        # 构建签名原文
        signature_origin = f"host: {self.HOST}\n"
        signature_origin += f"date: {date}\n"
        signature_origin += f"GET {self.PATH} HTTP/1.1"

        # HMAC-SHA256签名
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")

        # 构建authorization
        authorization_origin = (
            f'api_key="{self.api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature}"'
        )
        authorization = base64.b64encode(
            authorization_origin.encode("utf-8")
        ).decode("utf-8")

        # 构建完整URL
        params = {
            "authorization": authorization,
            "date": date,
            "host": self.HOST,
        }
        query_string = urllib.parse.urlencode(params)
        return f"{self.PROTOCOL}://{self.HOST}{self.PATH}?{query_string}"

    def _build_request_body(
        self,
        audio_base64: str,
        status: int = 0,
    ) -> dict:
        """
        构建请求体

        Args:
            audio_base64: base64编码的音频数据
            status: 0=第一帧, 1=中间帧, 2=最后一帧
        """
        return {
            "common": {"app_id": self.app_id},
            "business": {
                "language": "zh_cn",  # 中文
                "domain": "iat",  # 语音识别
                "accent": "mandarin",  # 普通话
                "engine_type": self.engine_type,
                "vad_eos": 3000,  # 静音检测结束时间(ms)
            },
            "data": {
                "status": status,
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
                "audio": audio_base64,
            },
        }

    async def transcribe(
        self,
        audio_data: bytes,
        audio_format: str = "pcm",
    ) -> str:
        """
        语音识别：将音频数据转换为文字

        Args:
            audio_data: 音频二进制数据（PCM或WAV格式）
            audio_format: 音频格式，'pcm' 或 'wav'

        Returns:
            识别出的文字内容

        Raises:
            RuntimeError: 识别失败
            ValueError: 配置错误或音频格式不支持
        """
        if not all([self.app_id, self.api_key, self.api_secret]):
            raise ValueError("讯飞ASR配置不完整，无法执行语音识别")

        # 如果是WAV格式，跳过头部44字节
        if audio_format.lower() == "wav":
            audio_data = self._strip_wav_header(audio_data)

        # base64编码
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        # 分段发送（每段约1280ms音频，约20480字节@16kHz/16bit/mono）
        chunk_size = 20480
        chunks = [
            audio_base64[i : i + chunk_size]
            for i in range(0, len(audio_base64), chunk_size)
        ]

        if not chunks:
            logger.warning("音频数据为空")
            return ""

        ws_url = self._build_auth_url()
        recognized_texts: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    ws_url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as ws:
                    # 发送音频帧
                    for idx, chunk in enumerate(chunks):
                        if idx == 0:
                            status = 0  # 第一帧
                        elif idx == len(chunks) - 1:
                            status = 2  # 最后一帧
                        else:
                            status = 1  # 中间帧

                        body = self._build_request_body(chunk, status)
                        await ws.send_str(json.dumps(body))

                        # 接收响应
                        if status == 2:
                            # 最后一帧，接收所有结果
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    result = self._parse_response(msg.data)
                                    if result:
                                        recognized_texts.append(result)
                                    # 检查是否结束
                                    try:
                                        data = json.loads(msg.data)
                                        if data.get("data", {}).get("status") == 2:
                                            break
                                    except (json.JSONDecodeError, KeyError):
                                        pass
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    logger.error(f"WebSocket错误: {ws.exception()}")
                                    break

                    await ws.close()

        except aiohttp.ClientError as e:
            logger.error(f"讯飞ASR连接失败: {e}")
            raise RuntimeError(f"语音识别连接失败: {e}") from e
        except Exception as e:
            logger.error(f"讯飞ASR处理异常: {e}")
            raise RuntimeError(f"语音识别处理异常: {e}") from e

        final_text = "".join(recognized_texts)
        logger.info(f"语音识别完成: 识别到 {len(final_text)} 个字符")
        return final_text

    def _parse_response(self, message: str) -> str:
        """
        解析讯飞ASR响应，提取识别文本

        Args:
            message: WebSocket返回的JSON字符串

        Returns:
            提取的文本，解析失败返回空字符串
        """
        try:
            data = json.loads(message)

            # 检查错误码
            code = data.get("code")
            if code != 0:
                logger.error(f"讯飞ASR返回错误: code={code}, message={data.get('message')}")
                return ""

            # 提取识别结果
            result_data = data.get("data", {})
            result = result_data.get("result", {})
            ws_array = result.get("ws", [])

            text_parts: list[str] = []
            for ws_item in ws_array:
                cw_array = ws_item.get("cw", [])
                for cw in cw_array:
                    text_parts.append(cw.get("w", ""))

            return "".join(text_parts)

        except json.JSONDecodeError:
            logger.warning(f"无法解析ASR响应: {message[:200]}")
            return ""
        except Exception as e:
            logger.warning(f"解析ASR响应异常: {e}")
            return ""

    @staticmethod
    def _strip_wav_header(wav_data: bytes) -> bytes:
        """
        去除WAV文件头部，返回纯PCM数据

        Args:
            wav_data: WAV格式音频数据

        Returns:
            PCM音频数据
        """
        if len(wav_data) < 44:
            return wav_data
        # WAV头部固定44字节
        return wav_data[44:]

    async def transcribe_file(self, file_path: str) -> str:
        """
        从文件路径读取音频并识别

        Args:
            file_path: 音频文件路径

        Returns:
            识别出的文字内容
        """
        try:
            with open(file_path, "rb") as f:
                audio_data = f.read()

            # 根据扩展名判断格式
            fmt = "wav" if file_path.lower().endswith(".wav") else "pcm"
            return await self.transcribe(audio_data, audio_format=fmt)

        except FileNotFoundError:
            logger.error(f"音频文件不存在: {file_path}")
            raise
        except Exception as e:
            logger.error(f"读取音频文件失败: {e}")
            raise RuntimeError(f"读取音频文件失败: {e}") from e

    async def health_check(self) -> bool:
        """
        健康检查：验证配置是否正确

        Returns:
            配置是否完整
        """
        is_ok = all([self.app_id, self.api_key, self.api_secret])
        if not is_ok:
            logger.warning("讯飞ASR健康检查失败: 配置不完整")
        return is_ok


# ============================================================================
# 全局单例
# ============================================================================

_asr_client: Optional[XunfeiASRClient] = None


def get_asr_client() -> XunfeiASRClient:
    """获取ASR客户端单例"""
    global _asr_client
    if _asr_client is None:
        _asr_client = XunfeiASRClient()
    return _asr_client
