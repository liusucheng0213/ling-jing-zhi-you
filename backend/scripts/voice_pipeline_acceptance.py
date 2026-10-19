"""真实语音链路验收：TTS测试音频 -> 讯飞ASR -> 声学情感 -> RAG -> 数字人配置。"""

from __future__ import annotations

import argparse
import asyncio
from array import array
from dataclasses import dataclass
import math
import time

import httpx

from app.api.v1.chat import _analyze_voice_acoustics
from app.core.avatar_orchestrator import AvatarOrchestrator, EXPRESSION_MAP
from app.core.emotion_engine import EmotionEngine
from app.schemas.chat import MultimodalEvidenceResponse


@dataclass(frozen=True)
class VoiceCase:
    spoken_text: str
    recognized_terms: tuple[str, ...]
    answer_terms: tuple[str, ...]
    avatar: str


CASES = (
    VoiceCase("灵山大佛有多高", ("灵山大佛", "多高"), ("88",), "舒窈"),
    VoiceCase("阿育王柱有什么特色", ("阿育王柱", "特色"), ("花岗岩", "狮"), "明朗"),
    VoiceCase("今天九龙灌浴几点演出", ("九龙灌浴", "演出"), ("无法", "400-168-0303"), "雨桐"),
)


def _synthetic_pcm(amplitude: int, duration_sec: float = 2.0) -> bytes:
    """生成带自然停顿的16kHz PCM，供声学阈值验收。"""

    sample_rate = 16000
    samples = array("h")
    total = int(sample_rate * duration_sec)
    for index in range(total):
        frame_index = index // 320
        if frame_index % 5 == 0:
            samples.append(0)
            continue
        value = int(amplitude * math.sin(2 * math.pi * 220 * index / sample_rate))
        samples.append(max(-32768, min(32767, value)))
    return samples.tobytes()


async def run_fusion_acceptance() -> bool:
    """验收声学分类、冲突仲裁及数字人下游表达。"""

    engine = EmotionEngine()
    cases = (
        {
            "name": "high-energy-over-tired-text",
            "pcm": _synthetic_pcm(12000),
            "text": "我有点累，想休息一下",
            "emotion": "excited",
            "expression": "delighted",
            "action": "鼓掌",
            "tts": "cheerful",
        },
        {
            "name": "low-energy-over-happy-text",
            "pcm": _synthetic_pcm(700),
            "text": "太棒了，我今天特别开心",
            "emotion": "tired",
            "expression": "gentle",
            "action": "右手加油",
            "tts": "gentle",
        },
    )
    passed = True
    for case in cases:
        acoustic = _analyze_voice_acoustics(case["pcm"])
        fused = await engine.analyze_multimodal(
            case["text"],
            voice_emotion_hint=acoustic["emotion"],
            voice_emotion_confidence=acoustic["confidence"],
            voice_emotion_reason=acoustic["reason"],
        )
        arbitration = (fused.get("details") or {}).get("arbitration") or {}
        strategy = engine.get_response_strategy(fused["type"])
        action_sequence = AvatarOrchestrator._select_action_sequence("测试回复", fused["type"], "")
        ok = all(
            (
                acoustic["emotion"] == case["emotion"],
                acoustic["confidence"] >= 0.60,
                fused["type"] == case["emotion"],
                arbitration.get("conflict") is True,
                arbitration.get("decision") == "high_confidence_voice_over_text",
                arbitration.get("selected_source") == "voice_acoustic",
                EXPRESSION_MAP[fused["type"]] == case["expression"],
                strategy["tts_emotion"] == case["tts"],
                action_sequence[0]["name"] == case["action"],
            )
        )
        passed = passed and ok
        print(
            f"{'PASS' if ok else 'FAIL'} | {case['name']} "
            f"| acoustic={acoustic['emotion']}:{acoustic['confidence']} "
            f"| text={fused['details']['text']['type']} "
            f"| fused={fused['type']} | decision={arbitration.get('decision')}"
        )

    unknown_asr = MultimodalEvidenceResponse(
        type="voice",
        asr_provider="xunfei-asr",
        asr_confidence=None,
    )
    schema_ok = unknown_asr.model_dump()["asr_confidence"] is None
    passed = passed and schema_ok
    print(f"{'PASS' if schema_ok else 'FAIL'} | unknown-asr-confidence-is-null")
    return passed


async def run(base_url: str, timeout: float, max_latency_ms: int) -> int:
    fusion_passed = await run_fusion_acceptance()
    rows: list[tuple[bool, int]] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        for index, case in enumerate(CASES):
            tts = await client.get(
                "/api/v1/tts",
                params={"text": case.spoken_text, "avatar": case.avatar},
            )
            started = time.perf_counter()
            response = await client.post(
                "/api/v1/voice",
                files={"audio": (f"voice-{index}.mp3", tts.content, "audio/mpeg")},
                data={"avatar": case.avatar},
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            data = response.json() if response.status_code == 200 else {}
            recognized = str(data.get("recognized_text") or "")
            content = str((data.get("message") or {}).get("content") or "")
            evidence = data.get("multimodal_evidence") or {}
            acoustic = evidence.get("acoustic_features") or {}
            ok = all(
                (
                    tts.status_code == 200,
                    len(tts.content) > 1000,
                    response.status_code == 200,
                    all(term in recognized for term in case.recognized_terms),
                    all(term in content for term in case.answer_terms),
                    evidence.get("asr_provider") == "xunfei-asr",
                    evidence.get("asr_confidence") is None,
                    acoustic.get("algorithm") == "pcm-energy-v1",
                    bool(evidence.get("emotion_fusion")),
                    bool((data.get("digital_human") or {}).get("sdk_config")),
                    latency_ms <= max_latency_ms,
                )
            )
            rows.append((ok, latency_ms))
            print(
                f"{'PASS' if ok else 'FAIL'} | {latency_ms}ms | avatar={case.avatar} "
                f"| recognized={recognized} | emotion={evidence.get('voice_emotion')}"
            )

    latencies = [latency for _, latency in rows]
    ordered = sorted(latencies)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else 0
    passed = sum(1 for ok, _ in rows if ok)
    print(f"\nVoice pipeline: {passed}/{len(rows)}, p95={p95}ms")
    return 0 if fusion_passed and passed == len(rows) and p95 <= max_latency_ms else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-latency-ms", type=int, default=5000)
    parser.add_argument("--fusion-only", action="store_true")
    args = parser.parse_args()
    if args.fusion_only:
        return 0 if asyncio.run(run_fusion_acceptance()) else 1
    return asyncio.run(run(args.url, args.timeout, args.max_latency_ms))


if __name__ == "__main__":
    raise SystemExit(main())
