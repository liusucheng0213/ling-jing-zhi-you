"""多模态视觉路由与文创短文本约束回归测试。"""

import json
import unittest
from unittest.mock import patch

from app.core.creative_engine import CreativeEngine
from app.core.vision_router import VisionAnalysisRequest, VisionRouter


class _FakeResponse:
    status_code = 200
    headers = {"x-request-id": "vision-test-request"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "scene_description": "画面中有湖面和传统建筑",
                        "spot_candidates": ["灵山胜境"],
                        "visual_facts": ["可见水面", "可见建筑屋檐"],
                        "answer": "这是一处中式园林景观。",
                        "confidence": 0.82,
                        "composition_suggestions": ["稍微降低机位，让屋檐与水面形成前后层次"],
                        "publish_tip": "适合配一段关于水面倒影的短游记。",
                        "safety_tips": [],
                    }, ensure_ascii=False),
                },
            }],
        }


class _FakeAsyncClient:
    captured: dict = {}

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        self.__class__.captured = {"url": url, "payload": json, "has_auth": bool(headers.get("Authorization"))}
        return _FakeResponse()


class VisionRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_kimi_code_uses_membership_endpoint_and_fixed_temperature(self) -> None:
        router = VisionRouter()
        router.provider = "kimi_code"
        router.api_key = "test-key"
        router.base_url = ""
        router.model = "kimi-for-coding-highspeed"
        request = VisionAnalysisRequest(
            image_name="scene.jpg",
            image_data_url="data:image/jpeg;base64,AA==",
            task="tour_qa",
            context="图里有什么？",
        )

        with patch("app.core.vision_router.httpx.AsyncClient", _FakeAsyncClient):
            result = await router.analyze_image(request)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.visual_facts, ["可见水面", "可见建筑屋檐"])
        self.assertEqual(result.confidence, 0.82)
        self.assertEqual(_FakeAsyncClient.captured["url"], "https://api.kimi.com/coding/v1/chat/completions")
        self.assertEqual(_FakeAsyncClient.captured["payload"]["temperature"], 1)
        self.assertEqual(_FakeAsyncClient.captured["payload"]["max_tokens"], 2400)
        self.assertNotIn("response_format", _FakeAsyncClient.captured["payload"])

    def test_json_parser_accepts_markdown_fence(self) -> None:
        parsed = VisionRouter._parse_model_json('```json\n{"confidence": 0.7}\n```')
        self.assertEqual(parsed["confidence"], 0.7)

    def test_creative_journey_prompt_requests_all_fields_in_one_vision_call(self) -> None:
        prompt = VisionRouter()._build_prompt(
            VisionAnalysisRequest(
                image_name="scene.jpg",
                task="creative_journey",
                context="想做成一张明信片",
            )
        )
        self.assertIn('"scene_description"', prompt)
        self.assertIn('"visual_facts"', prompt)
        self.assertIn('"composition_suggestions"', prompt)
        self.assertIn('"publish_tip"', prompt)
        self.assertIn('"answer"', prompt)


class CreativeEngineTests(unittest.TestCase):
    def test_poem_line_limits_fit_mobile_cards(self) -> None:
        source = "一\n二\n三\n四\n五\n六\n七\n八\n九"
        self.assertEqual(len(CreativeEngine._normalize_poem(source, "现代").splitlines()), 8)
        self.assertEqual(len(CreativeEngine._normalize_poem(source, "古典").splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
