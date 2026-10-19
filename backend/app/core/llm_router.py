"""
LLM路由模块
支持DeepSeek-V4双模型故障转移策略（Flash优先，Pro接续）
"""

import asyncio
from enum import Enum
from typing import Any, AsyncGenerator, Optional, List, Dict
from abc import ABC, abstractmethod
import httpx
from loguru import logger

from app.config import settings


class LLMProvider(Enum):
    """LLM提供商枚举"""
    DEEPSEEK = "deepseek"           # DeepSeek-V4-Flash：默认高速版
    DEEPSEEK_PRO = "deepseek_pro"   # DeepSeek-V4-Pro：复杂推理或故障转移
    QWEN = "qwen"                   # 预留备选模型


class BaseLLMClient(ABC):
    """LLM客户端抽象基类"""

    @abstractmethod
    async def chat(self, messages: List[Dict], temperature: float = 1.0, **kwargs) -> str:
        """非流式对话"""
        pass

    @abstractmethod
    async def chat_stream(self, messages: List[Dict], temperature: float = 1.0, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话"""
        pass


class DeepSeekClient(BaseLLMClient):
    """DeepSeek API客户端"""

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=settings.LLM_TIMEOUT)

    def _build_payload(
        self,
        messages: List[Dict],
        temperature: float,
        stream: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构造官方 ChatCompletions 载荷，并显式传递思考模式。"""

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": settings.LLM_TOP_P,
            "max_tokens": kwargs.get("max_tokens", settings.LLM_MAX_TOKENS),
            "stream": stream,
        }
        thinking = kwargs.get("thinking")
        if thinking:
            payload["thinking"] = thinking
        return payload

    async def chat(self, messages: List[Dict], temperature: float = 1.0, **kwargs) -> str:
        """调用DeepSeek API进行对话"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, temperature, False, **kwargs)

        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            choice = result["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            if not content.strip():
                finish_reason = choice.get("finish_reason")
                raise RuntimeError(f"DeepSeek返回空内容: finish_reason={finish_reason or 'unknown'}")
            return content
        except Exception as e:
            logger.error(f"DeepSeek API调用失败: {e}")
            raise

    async def chat_stream(self, messages: List[Dict], temperature: float = 1.0, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, temperature, True, **kwargs)

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                has_content = False
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        import json
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"]
                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                has_content = True
                                yield content
                        except:
                            pass
                if not has_content:
                    raise RuntimeError("DeepSeek流式返回空内容")
        except Exception as e:
            logger.error(f"DeepSeek流式API调用失败: {e}")
            raise


class LLMRouter:
    """LLM路由管理器：支持多模型热切换与故障转移"""

    def __init__(self):
        self._clients: Dict[LLMProvider, BaseLLMClient] = {}
        self._default_provider = LLMProvider.DEEPSEEK
        self._failover_chain = [LLMProvider.DEEPSEEK, LLMProvider.DEEPSEEK_PRO]
        self._init_clients()

    def _init_clients(self):
        """初始化所有LLM客户端"""
        if settings.DEEPSEEK_API_KEY:
            self._clients[LLMProvider.DEEPSEEK] = DeepSeekClient(
                model=settings.DEEPSEEK_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
            )
            self._clients[LLMProvider.DEEPSEEK_PRO] = DeepSeekClient(
                model=settings.DEEPSEEK_MODEL_PRO,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
            )

    async def chat(self, messages: List[Dict],
                   preferred: Optional[LLMProvider] = None,
                   temperature: float = 1.0,
                   **kwargs) -> str:
        """
        智能路由：优先使用指定模型，故障时切换到下一模型
        """
        providers = [preferred] if preferred else self._failover_chain
        last_error = None

        for provider in providers:
            try:
                client = self._clients.get(provider)
                if client:
                    return await client.chat(messages, temperature, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"{provider.value} 不可用，尝试下一个: {e}")
                if self._is_auth_error(e):
                    break
                continue

        raise last_error or RuntimeError("所有LLM provider均不可用")

    async def chat_stream(self, messages: List[Dict],
                          preferred: Optional[LLMProvider] = None,
                          temperature: float = 1.0,
                          **kwargs) -> AsyncGenerator[str, None]:
        """流式对话路由"""
        providers = [preferred] if preferred else self._failover_chain
        last_error = None

        for provider in providers:
            try:
                client = self._clients.get(provider)
                if client:
                    async for chunk in client.chat_stream(messages, temperature, **kwargs):
                        yield chunk
                    return
            except Exception as e:
                last_error = e
                logger.warning(f"{provider.value} 流式调用失败: {e}")
                if self._is_auth_error(e):
                    break
                continue

        raise last_error or RuntimeError("所有LLM provider均不可用")

    @staticmethod
    def _is_auth_error(error: Exception) -> bool:
        """鉴权错误无需继续切换模型，避免无意义串行等待。"""

        return isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {401, 403}


# 全局单例
llm_router = LLMRouter()
