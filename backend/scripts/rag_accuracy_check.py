"""RAG事实证据准确性验收脚本。

用法:
    python -m scripts.rag_accuracy_check

每个用例要求前3条证据同时覆盖指定事实，并可限定景点或文档类型。
它只验收检索证据；最终答案另由 ``qa_acceptance_check`` 验收。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.rag_engine import RAGEngine
from app.database import AsyncSessionLocal


@dataclass(frozen=True)
class RagCase:
    question: str
    required_groups: tuple[tuple[str, ...], ...]
    expected_spot_id: str | None = None
    expected_doc_type: str | None = None


CASES: tuple[RagCase, ...] = (
    RagCase("灵山大佛有多高？", (("88",), ("灵山大佛",)), "LS-011"),
    RagCase("灵山胜境的地址在哪里？", (("灵山路1号",),), expected_doc_type="official_web"),
    RagCase("灵山胜境四大主体景观是什么？", (("灵山大佛",), ("九龙灌浴",), ("灵山梵宫",), ("五印坛城",)), expected_doc_type="official_web"),
    RagCase("佛足坛和玄奘法师有什么关系？", (("佛足坛",), ("玄奘",)), "LS-003"),
    RagCase("阿育王柱有什么建筑特色？", (("花岗岩",), ("狮",)), "LS-008"),
    RagCase("祥符禅寺始建于什么时候？", (("唐",), ("贞观",)), "LS-010"),
    RagCase("五印坛城主要展示什么文化？", (("藏传佛教", "藏式"),), "LS-014"),
    RagCase("灵山梵宫有什么特色？", (("木雕",), ("琉璃",)), "LS-013"),
    RagCase("无尽意斋纪念的是谁？", (("赵朴初",),), "LS-016"),
    RagCase("轮椅游客需要注意什么？", (("轮椅",), ("台阶", "观光车"))),
    RagCase("今天九龙灌浴几点演出？", (("2026年2月1日",), ("400-168-0303",)), expected_doc_type="official_web"),
    RagCase("景区门票今天多少钱？", (("2026年2月1日",), ("400-168-0303",)), expected_doc_type="official_web"),
)


async def run() -> int:
    async with AsyncSessionLocal() as db:
        engine = RAGEngine(db_session=db, vector_dimension=1024)
        passed = 0
        rows: list[str] = []
        for case in CASES:
            results = await engine.hybrid_search(case.question, top_k=5)
            evidence = results[:3]
            haystack = "\n".join(f"{item.doc_title}\n{item.content}" for item in evidence)
            facts_ok = all(any(keyword in haystack for keyword in group) for group in case.required_groups)
            scope_ok = True
            if case.expected_spot_id:
                scope_ok = any(item.spot_id == case.expected_spot_id for item in evidence)
            if case.expected_doc_type:
                scope_ok = scope_ok and any(item.doc_type == case.expected_doc_type for item in evidence)
            ok = bool(evidence) and facts_ok and scope_ok
            passed += int(ok)
            top_title = results[0].doc_title if results else "无命中"
            rows.append(f"{'PASS' if ok else 'FAIL'} | {case.question} | top={top_title} | mode={engine.last_trace.get('mode')}")

    total = len(CASES)
    rate = passed / total if total else 0
    print("\n".join(rows))
    print(f"\nRAG evidence accuracy: {passed}/{total} = {rate:.1%}")
    if rate < 0.90:
        print("未达到90%验收线，请补充权威证据、重新生成embedding或检查检索配置。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
