"""明信片复用既有视觉上下文的回归测试。"""

import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.api.v1.creative import generate_postcard
from app.core.creative_engine import CreativeEngine
from app.core.vision_router import VisionRouter
from app.schemas.creative import PostcardGenerateRequest


class PostcardPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_context_constrains_copy_without_second_vision_call(self) -> None:
        llm_call = AsyncMock(return_value="晨光落在水面，古朴屋檐映着浅金色云影，风从桥边吹来，正好把这一刻寄给远方。")
        vision_call = AsyncMock()

        with (
            patch("app.core.llm_router.llm_router.chat", new=llm_call),
            patch.object(VisionRouter, "analyze_image", new=vision_call),
        ):
            result = await CreativeEngine().generate_postcard(
                user_name="游客",
                spot="灵山胜境",
                quote="记住今天的晨光",
                template="classic",
                image_context="湖面有晨光倒影，右侧可见传统建筑屋檐，天空有浅金色云层",
            )

        self.assertIn("晨光", result["content"])
        llm_call.assert_awaited_once()
        vision_call.assert_not_awaited()
        messages = llm_call.await_args.kwargs["messages"]
        self.assertIn("只描写画面参考中明确出现", messages[0]["content"])
        self.assertIn("湖面有晨光倒影", messages[1]["content"])
        self.assertIn("不得出现“图片、照片、上传、识别、视觉模型、画面参考”", messages[0]["content"])
        self.assertEqual(llm_call.await_args.kwargs["max_tokens"], 1000)

    async def test_legacy_call_keeps_prompt_without_visual_constraints(self) -> None:
        llm_call = AsyncMock(return_value="风过灵山，钟声与晚霞一起落进旅途，愿这份安静陪你走向下一程。")

        with patch("app.core.llm_router.llm_router.chat", new=llm_call):
            await CreativeEngine().generate_postcard(
                user_name="游客",
                spot="灵山胜境",
                quote="旅途愉快",
            )

        messages = llm_call.await_args.kwargs["messages"]
        self.assertNotIn("已完成视觉理解", messages[0]["content"])
        self.assertNotIn("画面参考（仅作为文案内容约束）", messages[1]["content"])


class _FakePostcardEngine:
    def __init__(self) -> None:
        self.arguments: dict = {}

    async def generate_postcard(self, **kwargs) -> dict:
        self.arguments = kwargs
        return {
            "type": "postcard",
            "title": "来自灵山胜境的问候",
            "content": "湖面映着晨光，檐角收住一缕云，愿这份清亮也抵达你身边。",
            "spot": "灵山胜境",
            "template": kwargs["template"],
        }


class _FakeDb:
    def add(self, item) -> None:
        item.id = uuid.uuid4()

    async def commit(self) -> None:
        return None

    async def refresh(self, _item) -> None:
        return None


class PostcardApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_passes_and_records_optional_image_context(self) -> None:
        engine = _FakePostcardEngine()
        request = PostcardGenerateRequest(
            template="minimal",
            message="把晨光寄给朋友",
            image_context="  湖面有倒影，檐角位于画面右上方  ",
        )

        with patch("app.api.v1.creative._get_creative_engine", return_value=engine):
            response = await generate_postcard(request=request, db=_FakeDb(), current_user=None)

        self.assertEqual(engine.arguments["image_context"], request.image_context)
        self.assertEqual(response.metadata["image_context"], "湖面有倒影，檐角位于画面右上方")
        self.assertEqual(response.metadata["template"], "minimal")

    def test_image_context_is_optional_for_existing_clients(self) -> None:
        request = PostcardGenerateRequest(message="一路顺风")
        self.assertIsNone(request.image_context)
        self.assertEqual(request.template, "classic")


if __name__ == "__main__":
    unittest.main()
