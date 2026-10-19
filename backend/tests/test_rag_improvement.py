"""RAG知识改进闭环的针对性单元测试。"""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.v1 import chat
from app.api.v1.admin import knowledge, rag_trace
from app.core import rag_engine


class RagImprovementTests(unittest.TestCase):
    def test_trace_confidence_prefers_answer_confidence(self):
        sources = [{"score": 0.91}]
        self.assertEqual(rag_trace._trace_confidence({"confidence": 0.42}, sources), 0.42)
        self.assertEqual(rag_trace._trace_confidence({}, sources), 0.91)
        self.assertIsNone(rag_trace._trace_confidence({}, []))

    def test_image_observation_is_not_improvable(self):
        assistant = SimpleNamespace(intent="image_understanding")
        image_question = SimpleNamespace(content="这是什么？", content_type="image")
        self.assertFalse(rag_trace._is_improvable(assistant, image_question, {"confidence": 0.1}, []))

        assistant.intent = "ask_info"
        text_question = SimpleNamespace(content="这个景点几点开放？", content_type="text")
        self.assertTrue(rag_trace._is_improvable(assistant, text_question, {"confidence": 0.4}, [{"score": 0.4}]))
        self.assertFalse(rag_trace._is_improvable(assistant, text_question, {"confidence": 0.8}, [{"score": 0.8}]))

    def test_search_cache_can_be_invalidated_after_publish(self):
        rag_engine._search_cache["search:demo"] = (9999999999.0, ([], {}))
        self.assertEqual(rag_engine.invalidate_search_cache(), 1)
        self.assertEqual(rag_engine._search_cache, {})

    def test_trace_draft_requires_a_real_standard_answer(self):
        incomplete = SimpleNamespace(
            metadata_json={"source": "rag_trace"},
            content="问：灵山大佛多高？\n\n答：",
        )
        with self.assertRaises(HTTPException):
            knowledge._ensure_trace_knowledge_complete(incomplete)

        complete = SimpleNamespace(
            metadata_json={"source": "rag_trace"},
            content="问：灵山大佛多高？\n\n答：灵山大佛通高88米，其中佛体79米、莲花瓣9米。",
        )
        knowledge._ensure_trace_knowledge_complete(complete)

    def test_engine_result_snapshot_keeps_comparable_metrics(self):
        snapshot = rag_trace._snapshot_from_engine_result(
            {
                "content": "新的回答",
                "confidence": 0.88,
                "latency_ms": 920,
                "retrieved_docs": [{"document_id": "doc-1", "score": 0.9, "mode": "hybrid"}],
                "performance_trace": {
                    "rag_ms": 120,
                    "fast_reply": False,
                    "rag": {"mode": "hybrid", "total_ms": 118},
                },
            }
        )
        self.assertEqual(snapshot.answer, "新的回答")
        self.assertEqual(snapshot.source_count, 1)
        self.assertEqual(snapshot.confidence, 0.88)
        self.assertEqual(snapshot.rag_ms, 120)
        self.assertEqual(snapshot.total_ms, 920)


class ChatEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluation_uses_real_pipeline_mode_and_cleans_context(self):
        contexts = {}
        dialogue_engine = SimpleNamespace(contexts=contexts)

        async def fake_process_chat(**kwargs):
            contexts[str(kwargs["session_id"])] = {"temporary": True}
            return {"content": "复测回答", "retrieved_docs": []}

        with (
            patch.object(chat, "_process_chat", new=AsyncMock(side_effect=fake_process_chat)) as process_mock,
            patch.object(chat, "_get_dialogue_engine", return_value=dialogue_engine),
        ):
            result = await chat.run_chat_evaluation(
                message="复测问题",
                spot_id="LS-011",
                avatar="舒窈",
                db=SimpleNamespace(),
            )

        self.assertEqual(result["content"], "复测回答")
        self.assertTrue(process_mock.await_args.kwargs["evaluation_mode"])
        self.assertEqual(contexts, {})


if __name__ == "__main__":
    unittest.main()
