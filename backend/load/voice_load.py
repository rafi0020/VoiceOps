"""Latency of real calls through the running stack: recorded customer speech streamed in real time over the voice
socket (through nginx), as a browser would, with several calls at once.

    uv run python -m load.voice_load --calls 1 --turns 3 --tag cpu-stub

What is measured, per customer turn:
  perceived   from the last sample of the customer's speech leaving the client to the first byte of the answer's
              audio arriving: what a caller hears as the pause. It includes the 600 ms of silence that ends a turn.
  server      the server's own end of speech (when the turn was detected) to the first audio byte it sent, split
              into recognition (and time queued for it), the agent, and synthesis of the first sentence.
The customer's voice is Piper en_US-ryan-medium; the agent's is en_US-lessac-medium.
"""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import websockets

from app.speech.audio import RATE, float_to_pcm16, pcm16_to_float, resample
from app.speech.tts import LocalSynthesizer

HERE = Path(__file__).parent
LINES = [
    "Hi, my broadband has been down since this morning.",
    "My account number is L T one zero zero zero zero one, postcode N G four two A B, born the fourteenth of March 1985.",
    "Okay, when will it be fixed?",
    "Will I get any compensation for this?",
    "No, that's everything, thank you.",
]
FRAME = RATE * 20 // 1000


async def speech() -> list[bytes]:
    voice = LocalSynthesizer("en_US-ryan-medium")
    out = []
    for line in LINES:
        pcm, rate, _ = await voice.synthesize(line)
        out.append(float_to_pcm16(resample(pcm16_to_float(pcm), rate, RATE)))
    return out


async def one_call(base: str, cookie: str, turns: list[bytes], results: list[dict]) -> None:
    async with httpx.AsyncClient(base_url=base, cookies={"voiceops_session": cookie}) as http:
        me = (await http.get("/api/auth/me")).json()
        call = (
            await http.post("/api/calls", json={"channel": "voice"}, headers={"X-CSRF-Token": me["csrf_token"]})
        ).json()
    ws_url = base.replace("http", "ws") + f"/api/voice/{call['id']}"
    async with websockets.connect(
        ws_url, additional_headers={"Cookie": f"voiceops_session={cookie}", "Origin": base}, max_size=None
    ) as ws:
        state = {"first_audio": None, "latency": None, "speaking": False}

        async def reader():
            async for message in ws:
                if isinstance(message, bytes):
                    if state["first_audio"] is None and state.get("sent_at"):
                        state["first_audio"] = time.perf_counter()
                    continue
                m = json.loads(message)
                if m["type"] == "latency":
                    state["latency"] = m
                elif m["type"] == "state":
                    state["speaking"] = m["state"] == "speaking"

        task = asyncio.create_task(reader())
        await asyncio.sleep(4)  # the greeting plays first
        silence = float_to_pcm16(np.zeros(FRAME, np.float32))
        for audio in turns:
            state.update(first_audio=None, latency=None, sent_at=None)
            for i in range(0, len(audio), FRAME * 2):
                await ws.send(audio[i : i + FRAME * 2])
                await asyncio.sleep(0.02)  # real time
            state["sent_at"] = time.perf_counter()
            deadline = time.perf_counter() + 60
            while (state["latency"] is None or state["first_audio"] is None) and time.perf_counter() < deadline:
                await ws.send(silence)  # the line stays open; silence ends the turn
                await asyncio.sleep(0.02)
            if state["first_audio"]:
                lat = state["latency"] or {}
                results.append({"perceived_ms": round((state["first_audio"] - state["sent_at"]) * 1000), "server_ms": lat.get("first_audio_ms"),
                                "stt_ms": lat.get("stt_ms"), "stt_wait_ms": lat.get("stt_wait_ms"), "agent_ms": lat.get("agent_ms"), "tts_first_ms": lat.get("tts_first_ms")})  # fmt: skip
            while state["speaking"]:  # let the answer finish before the next turn
                await ws.send(silence)
                await asyncio.sleep(0.02)
            for _ in range(25):
                await ws.send(silence)
                await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "end"}))
        task.cancel()


def pct(values: list[float], p: float) -> float | None:
    values = sorted(v for v in values if v is not None)
    return values[min(len(values) - 1, int(len(values) * p))] if values else None


async def main(args) -> None:
    turns = (await speech())[: args.turns]
    async with httpx.AsyncClient(base_url=args.host) as http:
        r = await http.post("/api/auth/login", json={"email": "agent@larkspur.demo", "password": "Agent#Demo2026"})
        r.raise_for_status()
        cookie = r.cookies["voiceops_session"]
    results: list[dict] = []
    started = time.perf_counter()
    await asyncio.gather(*[one_call(args.host, cookie, turns, results) for _ in range(args.calls)])
    summary = {"tag": args.tag, "calls": args.calls, "turns_measured": len(results), "seconds": round(time.perf_counter() - started, 1),
               **{f"{k}_p50": pct([r[k] for r in results], 0.5) for k in ("perceived_ms", "server_ms", "stt_ms", "stt_wait_ms", "agent_ms", "tts_first_ms")},
               **{f"{k}_p95": pct([r[k] for r in results], 0.95) for k in ("perceived_ms", "server_ms", "stt_ms")}}  # fmt: skip
    print(json.dumps(summary))
    out = HERE / "results" / "voice_latency.jsonl"
    with out.open("a") as f:
        f.write(json.dumps(summary | {"at": datetime.now(UTC).isoformat(timespec="seconds"), "turns": results}) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="http://localhost:3400")
    parser.add_argument("--calls", type=int, default=1)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--tag", default="")
    asyncio.run(main(parser.parse_args()))
