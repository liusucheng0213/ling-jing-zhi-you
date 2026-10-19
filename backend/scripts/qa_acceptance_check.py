"""端到端事实问答验收：最终回答、来源、置信度与延迟同时达标。"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import math
import time

import httpx


@dataclass(frozen=True)
class QaCase:
    question: str
    required_groups: tuple[tuple[str, ...], ...]
    forbidden: tuple[str, ...] = ()


CASES = (
    QaCase("灵山大佛有多高？", (("88",),)),
    QaCase("灵山胜境的地址在哪里？", (("灵山路1号",),)),
    QaCase("灵山胜境四大主体景观是什么？", (("灵山大佛",), ("九龙灌浴",), ("灵山梵宫",), ("五印坛城",))),
    QaCase("佛足坛和玄奘法师有什么关系？", (("佛足坛",), ("玄奘",))),
    QaCase("阿育王柱有什么建筑特色？", (("花岗岩",), ("狮",))),
    QaCase("祥符禅寺始建于什么时候？", (("唐",), ("贞观",))),
    QaCase("五印坛城主要展示什么文化？", (("藏传佛教", "藏式"),)),
    QaCase("灵山梵宫有什么特色？", (("木雕",), ("琉璃",))),
    QaCase("无尽意斋纪念的是谁？", (("赵朴初",),)),
    QaCase("轮椅游客在景区需要注意什么？", (("轮椅",), ("台阶", "观光车"))),
    QaCase("今天九龙灌浴几点演出？", (("无法",), ("400-168-0303",)), ("10:35", "11:30")),
    QaCase("景区门票今天多少钱？", (("无法",), ("400-168-0303",)), ("210元", "105元")),
)


async def run(base_url: str, timeout: float, max_latency_ms: int) -> int:
    rows: list[tuple[bool, int, str]] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        for case in CASES:
            started = time.perf_counter()
            response = await client.post("/api/v1/text", json={"message": case.question, "avatar": "舒窈"})
            latency_ms = int((time.perf_counter() - started) * 1000)
            data = response.json() if response.status_code == 200 else {}
            content = str((data.get("message") or {}).get("content") or "")
            facts_ok = all(any(term in content for term in group) for group in case.required_groups)
            forbidden_ok = not any(term in content for term in case.forbidden)
            evidence_ok = len(data.get("retrieved_docs") or []) > 0 and float(data.get("confidence") or 0) >= 0.75
            latency_ok = latency_ms <= max_latency_ms
            ok = response.status_code == 200 and facts_ok and forbidden_ok and evidence_ok and latency_ok
            rows.append((ok, latency_ms, case.question))
            print(
                f"{'PASS' if ok else 'FAIL'} | {latency_ms}ms | confidence={data.get('confidence')} "
                f"| sources={len(data.get('retrieved_docs') or [])} | {case.question}"
            )

    passed = sum(1 for ok, _, _ in rows if ok)
    latencies = [latency for _, latency, _ in rows]
    ordered = sorted(latencies)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else 0
    rate = passed / len(rows)
    print(f"\nEnd-to-end fact QA: {passed}/{len(rows)} = {rate:.1%}, p95={p95}ms")
    return 0 if rate >= 0.90 and p95 <= max_latency_ms else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-latency-ms", type=int, default=5000)
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.timeout, args.max_latency_ms))


if __name__ == "__main__":
    raise SystemExit(main())
