"""后端事实问答并发稳定性与P95延迟门槛脚本。

用法:
    python -m scripts.api_stress_smoke --url http://localhost:8000 --concurrency 8 --requests 40
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass
class Result:
    ok: bool
    status_code: int
    latency_ms: int
    error: str = ""


QUESTIONS = (
    "灵山大佛有多高？",
    "灵山胜境四大主体景观是什么？",
    "五印坛城主要展示什么文化？",
    "轮椅游客需要注意什么？",
    "今天九龙灌浴几点演出？",
)


async def call_once(client: httpx.AsyncClient, index: int) -> Result:
    started_at = time.perf_counter()
    try:
        response = await client.post(
            "/api/v1/text",
            json={"message": QUESTIONS[index % len(QUESTIONS)], "avatar": "舒窈"},
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        payload = response.json() if response.status_code == 200 else {}
        content = str((payload.get("message") or {}).get("content") or "")
        return Result(
            ok=response.status_code == 200 and bool(content.strip()),
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return Result(False, 0, latency_ms, str(exc))


async def run(url: str, concurrency: int, requests: int, timeout: float, p95_limit_ms: int) -> int:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=url, timeout=timeout, limits=limits) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def guarded(index: int) -> Result:
            async with semaphore:
                return await call_once(client, index)

        results = await asyncio.gather(*(guarded(index) for index in range(requests)))

    ok_count = sum(1 for item in results if item.ok)
    latencies = [item.latency_ms for item in results]
    p95 = int(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else max(latencies, default=0)
    avg = int(sum(latencies) / len(latencies)) if latencies else 0
    failures = [item for item in results if not item.ok]
    print(f"requests={requests} concurrency={concurrency} ok={ok_count} fail={len(failures)} avg_ms={avg} p95_ms={p95}")
    for item in failures[:5]:
        print(f"FAIL status={item.status_code} latency_ms={item.latency_ms} error={item.error}")
    if p95 > p95_limit_ms:
        print(f"FAIL p95_ms={p95} exceeds limit_ms={p95_limit_ms}")
    return 0 if ok_count == requests and p95 <= p95_limit_ms else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--p95-limit-ms", type=int, default=5000)
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.concurrency, args.requests, args.timeout, args.p95_limit_ms))


if __name__ == "__main__":
    raise SystemExit(main())
