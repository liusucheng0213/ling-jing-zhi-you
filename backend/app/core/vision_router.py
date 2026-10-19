"""
图片理解能力路由。

本模块封装真实多模态图片理解入口。未配置视觉供应商、接口失败或模型未返回
结构化内容时，都返回明确状态，不根据文件名或上下文编造识别结果。
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from app.config import settings


@dataclass
class VisionAnalysisRequest:
    """图片理解请求。"""

    image_name: str
    task: str = "photo_review"
    spot_name: str | None = None
    context: str | None = None
    image_data_url: str | None = None


@dataclass
class VisionAnalysisResult:
    """图片理解结果。"""

    enabled: bool
    provider: str | None
    status: str
    message: str
    task: str
    image_name: str
    spot_name: str | None = None
    scene_description: str | None = None
    spot_candidates: list[str] = field(default_factory=list)
    answer: str | None = None
    visual_facts: list[str] = field(default_factory=list)
    confidence: float | None = None
    suggestions: list[str] = field(default_factory=list)
    safety_tips: list[str] = field(default_factory=list)
    publish_tip: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class VisionRouter:
    """多模态图片理解统一入口。"""

    BAILIAN_PROVIDERS = {"aliyun_bailian", "bailian", "dashscope"}
    KIMI_OPEN_PROVIDERS = {"kimi", "moonshot", "moonshot_ai"}
    KIMI_CODE_PROVIDERS = {"kimi_code", "kimi_membership", "kimi_for_coding"}
    KIMI_PROVIDERS = KIMI_OPEN_PROVIDERS | KIMI_CODE_PROVIDERS

    def __init__(self) -> None:
        self.provider = (settings.VISION_PROVIDER or "").strip().lower()
        self.model = (settings.VISION_MODEL or "").strip()
        self.base_url = (settings.VISION_BASE_URL or "").strip()
        self.api_key = (settings.VISION_API_KEY or "").strip()

    @property
    def enabled(self) -> bool:
        """是否已经配置可用视觉供应商。"""

        return bool(self.provider and self.model and self.api_key)

    async def analyze_image(self, request: VisionAnalysisRequest) -> VisionAnalysisResult:
        """分析图片；未启用或失败时返回真实状态，不生成假结果。"""

        if not self.enabled:
            return VisionAnalysisResult(
                enabled=False,
                provider=self.provider or None,
                status="disabled",
                message="图片理解能力尚未启用：请配置 VISION_PROVIDER、VISION_MODEL 和 VISION_API_KEY 后再接入真实识别。",
                task=request.task,
                image_name=request.image_name,
                spot_name=request.spot_name,
                suggestions=[
                    "当前可继续使用文字游记、拍照点图示和明信片下载。",
                    "照片点评上线前，不会根据图片文件名编造识别结果。",
                ],
                evidence={
                    "model_configured": bool(self.model),
                    "provider_configured": bool(self.provider),
                    "api_key_configured": bool(self.api_key),
                },
            )

        if not request.image_data_url:
            return VisionAnalysisResult(
                enabled=True,
                provider=self.provider,
                status="missing_image",
                message="请先选择一张照片，再进行真实照片点评。",
                task=request.task,
                image_name=request.image_name,
                spot_name=request.spot_name,
                evidence={"model": self.model},
            )

        if self.provider not in self.BAILIAN_PROVIDERS | self.KIMI_PROVIDERS:
            return VisionAnalysisResult(
                enabled=True,
                provider=self.provider,
                status="unsupported_provider",
                message=f"暂不支持视觉供应商 {self.provider}，当前支持阿里云百炼、Kimi 开放平台和 Kimi Code 会员通道。",
                task=request.task,
                image_name=request.image_name,
                spot_name=request.spot_name,
                evidence={"model": self.model},
            )

        return await self._analyze_with_openai_compatible(request)

    async def _analyze_with_openai_compatible(self, request: VisionAnalysisRequest) -> VisionAnalysisResult:
        """调用阿里百炼或 Kimi 的 OpenAI 兼容视觉接口。"""

        started_at = time.perf_counter()
        default_base_url = (
            "https://api.kimi.com/coding/v1"
            if self.provider in self.KIMI_CODE_PROVIDERS
            else "https://api.moonshot.cn/v1"
            if self.provider in self.KIMI_OPEN_PROVIDERS
            else "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        base_url = (self.base_url or default_base_url).rstrip("/")
        prompt = self._build_prompt(request)
        provider_label = (
            "Kimi Code"
            if self.provider in self.KIMI_CODE_PROVIDERS
            else "Kimi 开放平台"
            if self.provider in self.KIMI_OPEN_PROVIDERS
            else "阿里百炼"
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是灵山胜境景区的视觉导览助手。必须先观察图片像素再回答，"
                        "不得根据文件名猜测；不确定时明确说明不确定。内部思考保持简短，"
                        "只返回要求的JSON字段，不要输出Markdown或额外字段。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": request.image_data_url}},
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
            "temperature": 1 if self.provider in self.KIMI_CODE_PROVIDERS else 0.2,
            "max_tokens": 2400 if self.provider in self.KIMI_CODE_PROVIDERS else 800,
        }
        if self.provider in self.BAILIAN_PROVIDERS:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            timeout = httpx.Timeout(connect=4.0, read=35.0, write=10.0, pool=4.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
            content = result["choices"][0]["message"]["content"]
            parsed = self._parse_model_json(content)
            latency_ms = int((time.perf_counter() - started_at) * 1000)
        except httpx.HTTPStatusError as exc:
            logger.warning(f"{provider_label}视觉接口返回错误: {exc.response.status_code} {exc.response.text[:300]}")
            return self._error_result(
                request,
                "provider_error",
                self._describe_provider_error(provider_label, exc.response),
                {
                    "status_code": exc.response.status_code,
                    "model": self.model,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )
        except (httpx.HTTPError, KeyError, IndexError, TypeError, OSError) as exc:
            logger.warning(f"{provider_label}视觉接口调用异常: {exc}")
            return self._error_result(
                request,
                "provider_error",
                f"{provider_label}视觉接口调用异常，请稍后重试或检查网络与配置。",
                {
                    "error": exc.__class__.__name__,
                    "model": self.model,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )
        except ValueError as exc:
            logger.warning(f"{provider_label}视觉结果解析失败: {exc}")
            return self._error_result(
                request,
                "parse_error",
                "模型未返回可用的结构化图片理解结果，本次不展示识别结论。",
                {
                    "error": str(exc),
                    "model": self.model,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )

        return VisionAnalysisResult(
            enabled=True,
            provider=self.provider,
            status="success",
            message="照片点评完成。" if request.task == "photo_review" else "图片理解完成。",
            task=request.task,
            image_name=request.image_name,
            spot_name=request.spot_name,
            scene_description=self._clean_text(parsed.get("scene_description"), 240),
            spot_candidates=self._clean_list(parsed.get("spot_candidates"), 3, 40),
            answer=self._clean_text(parsed.get("answer"), 360),
            visual_facts=self._clean_list(parsed.get("visual_facts"), 5, 100),
            confidence=self._clean_confidence(parsed.get("confidence")),
            suggestions=self._clean_list(parsed.get("composition_suggestions"), 4, 80),
            safety_tips=self._clean_list(parsed.get("safety_tips"), 2, 80),
            publish_tip=self._clean_text(parsed.get("publish_tip"), 160),
            evidence={
                "provider": self.provider,
                "model": self.model,
                "base_url": base_url,
                "image_source": "data_url",
                "latency_ms": latency_ms,
                "request_id": result.get("request_id") or result.get("id"),
            },
        )

    def _build_prompt(self, request: VisionAnalysisRequest) -> str:
        """按任务构造严格的视觉分析提示词。"""

        if request.task == "creative_journey":
            return (
                "请一次完成景区照片识别与文创建议，返回严格JSON："
                "{"
                '"scene_description":"客观描述画面，无法确认时说明不确定",'
                '"spot_candidates":["可能的景点或场景，最多3个"],'
                '"visual_facts":["从图片中直接看见的事实，最多5条"],'
                '"answer":"结合可见元素作一段克制的文化导览，120字以内，不补写无法从图片确认的史实",'
                '"confidence":0.0,'
                '"composition_suggestions":["构图、光线、站位建议，3-4条"],'
                '"safety_tips":["仅在确有游览或拍摄风险时给出，最多2条"],'
                '"publish_tip":"匹配当前画面的游记发布建议"'
                "}。"
                f"游客补充说明：{request.context or '希望识别画面并用于游记和明信片'}。"
                f"游客已选择的关联景点：{request.spot_name or '未指定'}。"
                "confidence取0到1。画面事实、可能景点和文化解释必须明确区分，"
                "不得根据文件名或游客所选景点反推图片内容。"
            )

        if request.task in {"tour_qa", "image_chat"}:
            return (
                "请直接观察图片，并回答游客针对图片提出的问题。返回严格JSON："
                "{"
                '"scene_description":"客观描述画面，无法确认时说明不确定",'
                '"spot_candidates":["可能的景点或场景，最多3个"],'
                '"visual_facts":["从图片中直接看见的事实，最多5条"],'
                '"answer":"只基于图片直接回答游客问题，120字以内，不补写知识库事实",'
                '"confidence":0.0,'
                '"safety_tips":["仅当画面涉及游览或拍摄风险时给出，最多2条"]'
                "}。"
                f"游客问题：{request.context or '请判断图片内容，并介绍画面中的景点或看点。'}。"
                f"当前页面关联景点：{request.spot_name or '未指定'}。"
                "confidence取0到1。必须区分看得见的画面事实与无法从图片确认的信息。"
            )

        return (
            "请分析这张游客在灵山胜境相关场景拍摄的照片，返回严格JSON："
            "{"
            '"scene_description":"一句话描述画面，若无法识别请说明不确定",'
            '"spot_candidates":["可能的景点或场景，最多3个"],'
            '"visual_facts":["从图片中直接看见的事实，最多5条"],'
            '"confidence":0.0,'
            '"composition_suggestions":["构图、光线、站位、取景建议，3-4条"],'
            '"safety_tips":["游览或拍摄安全提醒，0-2条"],'
            '"publish_tip":"适合发到社区游记的一句话建议"'
            "}。"
            f"用户选择的关联景点：{request.spot_name or '未选择'}。"
            f"补充说明：{request.context or '无'}。"
            "confidence取0到1。不要声称已上传或已保存照片。"
        )

    @staticmethod
    def _describe_provider_error(provider_label: str, response: httpx.Response) -> str:
        """把供应商错误转换为游客和演示人员可操作的提示。"""

        error_code = ""
        try:
            payload = response.json()
            error_code = str((payload.get("error") or {}).get("code") or "")
        except (TypeError, ValueError):
            pass
        if error_code == "AllocationQuota.FreeTierOnly":
            return "阿里百炼视觉免费额度已用完，且已开启“免费额度用完即停”；关闭该开关并确保账户可用后即可恢复。"
        if response.status_code == 401 and provider_label == "Kimi 开放平台":
            return "当前密钥未被 Kimi 开放平台接受；请确认它来自开放平台，而不是 Kimi Code 会员控制台。"
        if response.status_code in {402, 403} and provider_label == "Kimi Code":
            return "Kimi Code 会员权益或模型权限当前不可用，请检查会员状态和对应模型档位。"
        if response.status_code == 403 and provider_label == "Kimi 开放平台":
            return "Kimi 开放平台余额或模型权限不足；Kimi 会员额度不能替代开放平台 API 余额。"
        return f"{provider_label}视觉接口调用失败：HTTP {response.status_code}。请检查模型名称、API Key 和账号权限。"

    @staticmethod
    def _parse_model_json(content: Any) -> dict[str, Any]:
        """解析模型返回的 JSON 对象。"""

        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty model content")
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("model content is not object")
        return parsed

    @staticmethod
    def _clean_text(value: Any, max_length: int) -> str | None:
        """清理模型文本字段。"""

        if value is None:
            return None
        text = str(value).strip()
        return text[:max_length] if text else None

    @classmethod
    def _clean_list(cls, value: Any, max_items: int, max_length: int) -> list[str]:
        """清理模型列表字段。"""

        if isinstance(value, str):
            source = [value]
        elif isinstance(value, list):
            source = value
        else:
            source = []
        items: list[str] = []
        for item in source:
            text = cls._clean_text(item, max_length)
            if text:
                items.append(text)
            if len(items) >= max_items:
                break
        return items

    @staticmethod
    def _clean_confidence(value: Any) -> float | None:
        """把模型置信度约束到0到1。"""

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        return round(min(1.0, max(0.0, confidence)), 3)

    def _error_result(
        self,
        request: VisionAnalysisRequest,
        status: str,
        message: str,
        evidence: dict[str, Any],
    ) -> VisionAnalysisResult:
        """构造失败响应。"""

        return VisionAnalysisResult(
            enabled=True,
            provider=self.provider,
            status=status,
            message=message,
            task=request.task,
            image_name=request.image_name,
            spot_name=request.spot_name,
            evidence={**evidence, "provider": self.provider},
        )
