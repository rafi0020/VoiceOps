"""How well the recogniser hears customers: word error rate on 24 customer sentences spoken by a synthetic voice
that is not the agent's (Piper en_US-ryan-medium), clean and with white noise at 15 dB and 5 dB signal-to-noise.

    python -m eval.run_wer            # the recogniser in STT_* settings (CPU base.en by default)

Synthetic speech is cleaner than people on phones; these figures are a floor on error, not a promise. Numbers are
compared as digits ("four five one two" and "4512" are the same words here), since that is how account numbers
are used.
"""

import asyncio
import json
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.speech.audio import RATE, pcm16_to_float, resample
from app.speech.stt import LocalTranscriber
from app.speech.tts import LocalSynthesizer

HERE = Path(__file__).parent
SENTENCES = [
    "Hi, my broadband has been down since this morning.", "My account number is L T one zero zero zero zero one.",
    "The postcode is N G four two A B.", "My date of birth is the fourteenth of March nineteen eighty five.",
    "I think I've been charged twice for the sports add on.", "Can I speak to a real person please?",
    "The engineer didn't turn up yesterday afternoon.", "How much does it cost to use my phone in France?",
    "I'd like to cancel my contract at the end of the month.", "My router has a red light and nothing is working.",
    "Can I pay my overdue bill in instalments?", "I'm moving house next week, what do I need to do?",
    "The phone number on the account is oh seven seven double oh nine double oh oh three.", "My internet keeps dropping out every few minutes.",
    "Why is my bill higher than last month?", "I'd like a goodwill credit for the slow speeds.",
    "No, that's everything, thank you very much.", "Sorry, could you say that again?",
    "My mother is in hospital and she uses a medical alarm on this line.", "What time will the engineer arrive tomorrow?",
    "I want to make a complaint about the service.", "Is there an outage in my area right now?",
    "Yes, please go ahead and open a ticket.", "How long will it take to fix?",
]  # fmt: skip
UNITS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


def normalise(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower().replace("-", " "))
    out: list[str] = []
    for w in words:
        if w in ("double", "triple"):
            out.append(w)
            continue
        w = UNITS.get(w, w)
        if out and out[-1] in ("double", "triple"):
            out[-1] = w * (2 if out[-1] == "double" else 3)
        elif out and w.isdigit() and out[-1].isdigit() and len(w) <= 4:
            out[-1] += w  # spoken digits run together, as an account number is written
        else:
            out.append(w)
    return out


def wer(reference: str, hypothesis: str) -> float:
    r, h = normalise(reference), normalise(hypothesis)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(1, len(r))


def noisy(audio: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    power = float(np.mean(audio**2)) or 1e-9
    noise = np.random.default_rng(seed).standard_normal(len(audio)).astype(np.float32) * np.sqrt(
        power / 10 ** (snr_db / 10)
    )
    return np.clip(audio + noise, -1, 1).astype(np.float32)


async def main() -> None:
    s = get_settings()
    voice, stt = LocalSynthesizer("en_US-ryan-medium"), LocalTranscriber()
    await stt.transcribe(np.zeros(RATE, np.float32))  # load the model before timing anything
    rows = []
    for n, sentence in enumerate(SENTENCES):
        pcm, rate, _ = await voice.synthesize(sentence)
        clean = resample(pcm16_to_float(pcm), rate, RATE)
        for condition, audio in (
            ("clean", clean),
            ("noise 15 dB", noisy(clean, 15, n)),
            ("noise 5 dB", noisy(clean, 5, n)),
        ):
            heard, timings = await stt.transcribe(audio)
            rows.append({"sentence": sentence, "condition": condition, "heard": heard, "wer": round(wer(sentence, heard), 4),
                         "stt_ms": timings["stt_ms"], "audio_ms": round(len(audio) / 16)})  # fmt: skip
            print(f"  {condition:<12} {rows[-1]['wer']:.2f}  {heard[:70]}")
    by = {c: {"wer": round(statistics.mean(r["wer"] for r in rows if r["condition"] == c), 4),
              "real_time_factor": round(sum(r["stt_ms"] for r in rows if r["condition"] == c) / sum(r["audio_ms"] for r in rows if r["condition"] == c), 3),
              "p50_stt_ms": statistics.median(r["stt_ms"] for r in rows if r["condition"] == c)} for c in ("clean", "noise 15 dB", "noise 5 dB")}  # fmt: skip
    name = f"wer-{s.stt_model}-{s.stt_device}"
    print(json.dumps(by, indent=1))
    (HERE / "results" / f"{name}.json").write_text(json.dumps({"name": name, "model": s.stt_model, "device": s.stt_device, "compute_type": s.stt_compute_type,
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "n": len(SENTENCES), "by_condition": by, "rows": rows}, indent=1))  # fmt: skip


if __name__ == "__main__":
    asyncio.run(main())
