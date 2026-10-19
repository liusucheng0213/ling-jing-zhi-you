"""回答长度模式与情境追问的定向测试。"""

import asyncio
import unittest

from pydantic import ValidationError

from app.api.v1.chat import (
    _resolve_response_mode,
    _response_max_tokens,
    _response_mode_instruction,
)
from app.core.dialogue_engine import DialogueContext, DialogueEngine, DialogueState, UserIntent
from app.core.llm_router import DeepSeekClient
from app.schemas.chat import TextChatRequest


class ResponseModeTests(unittest.TestCase):
    def test_auto_mode_only_expands_on_explicit_request(self) -> None:
        self.assertEqual(_resolve_response_mode("灵山大佛有什么看点", "auto"), "normal")
        self.assertEqual(_resolve_response_mode("请详细展开灵山大佛的历史", "auto"), "detail")
        self.assertEqual(_resolve_response_mode("请详细讲但只要简答", "brief"), "brief")

    def test_each_mode_uses_single_generation_budget(self) -> None:
        self.assertEqual(_response_max_tokens("快捷问题", "brief"), 120)
        self.assertEqual(_response_max_tokens("普通问题", "normal"), 220)
        self.assertEqual(_response_max_tokens("详细展开", "detail"), 480)
        self.assertIn("40-80", _response_mode_instruction("brief"))
        self.assertIn("180-300", _response_mode_instruction("detail"))

    def test_request_keeps_backward_compatible_auto_default(self) -> None:
        request = TextChatRequest(message="你好")
        self.assertEqual(request.response_mode, "auto")
        with self.assertRaises(ValidationError):
            TextChatRequest(message="你好", response_mode="tiny")

    def test_deepseek_payload_disables_thinking_without_changing_budget(self) -> None:
        client = DeepSeekClient("deepseek-v4-flash", "test-key", "https://example.invalid")
        payload = client._build_payload(
            [{"role": "user", "content": "简要介绍"}],
            temperature=0.8,
            stream=True,
            max_tokens=120,
            thinking={"type": "disabled"},
        )
        self.assertEqual(payload["max_tokens"], 120)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertTrue(payload["stream"])
        asyncio.run(client.client.aclose())


class ContextualSuggestionTests(unittest.TestCase):
    def test_suggestions_use_image_current_spot_and_next_stop(self) -> None:
        engine = DialogueEngine()
        context = DialogueContext(
            session_id="demo",
            current_state=DialogueState.EXPLAINING,
            turn_count=1,
        )

        suggestions = engine._generate_suggestions(
            context,
            UserIntent.ASK_INFO,
            current_spot_name="灵山大佛",
            next_spot_name="九龙灌浴",
            recognized_spots=["灵山梵宫"],
        )

        self.assertEqual(len(suggestions), 3)
        self.assertTrue(any("灵山梵宫" in item for item in suggestions))
        self.assertTrue(any("灵山大佛" in item for item in suggestions))
        self.assertTrue(any("九龙灌浴" in item for item in suggestions))

    def test_last_two_rounds_are_not_repeated(self) -> None:
        engine = DialogueEngine()
        context = DialogueContext(
            session_id="demo",
            current_state=DialogueState.EXPLAINING,
            turn_count=2,
        )

        first = engine._generate_suggestions(context, UserIntent.ASK_INFO)
        second = engine._generate_suggestions(context, UserIntent.ASK_INFO)
        third = engine._generate_suggestions(context, UserIntent.ASK_INFO)

        self.assertTrue(set(first).isdisjoint(second))
        self.assertTrue(set(first).isdisjoint(third))
        self.assertTrue(set(second).isdisjoint(third))


if __name__ == "__main__":
    unittest.main()
