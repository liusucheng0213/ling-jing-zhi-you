import base64
import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse

from app.config import settings


class XunfeiAvatarClient:
    """讯飞虚拟数字人 WebSDK 鉴权客户端"""

    def __init__(self):
        self.app_id = settings.XFYUN_APP_ID
        self.api_key = settings.XFYUN_API_KEY
        self.api_secret = settings.XFYUN_API_SECRET
        self.server_url = settings.XFYUN_AVATAR_SERVER_URL or "wss://avatar.cn-huadong-1.xf-yun.com/v1/interact"

    @property
    def is_configured(self) -> bool:
        return bool(self.app_id and self.api_key and self.api_secret)

    def build_signed_url(self, server_url: str | None = None) -> str:
        if not self.is_configured:
            return ""

        target = server_url or self.server_url
        parsed = urlparse(target)
        host = parsed.netloc
        path = parsed.path or "/v1/interact"
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
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
        return f"{target}?{urlencode({'authorization': authorization, 'date': date, 'host': host}, quote_via=quote)}"
