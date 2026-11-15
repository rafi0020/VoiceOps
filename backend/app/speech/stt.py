"""Speech recognition. Local: faster-whisper (CTranslate2) on the CPU or the GPU. Hosted: any OpenAI-compatible
/audio/transcriptions endpoint (OpenAI, Groq, a gateway). One model per process; recognitions run one at a time
on it (CTranslate2 uses all its threads for one request), and the waiting time is part of what is measured."""

import asyncio
import io
import time
import wave
from pathlib import Path

import httpx
import numpy as np

from app.config import get_settings
from app.speech.audio import RATE

PROMPT = "Account number, postcode, date of birth, broadband, router, engineer, bill, credit."


class LocalTranscriber:
    def __init__(self):
        from faster_whisper import WhisperModel

        s = get_settings()
        local = Path(s.models_dir) / "whisper" / s.stt_model
        self.model = WhisperModel(
            str(local) if local.exists() else s.stt_model,
            device=s.stt_device,
            compute_type=s.stt_compute_type,
            cpu_threads=4,
        )
        self.lock = asyncio.Lock()

    def _run(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(audio, beam_size=1, language="en", vad_filter=False, condition_on_previous_text=False,
                                            initial_prompt=PROMPT, without_timestamps=True)  # fmt: skip
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def transcribe(self, audio: np.ndarray) -> tuple[str, dict]:
        queued = time.perf_counter()
        async with self.lock:
            started = time.perf_counter()
            said = await asyncio.to_thread(self._run, audio)
        done = time.perf_counter()
        return said, {"stt_wait_ms": round((started - queued) * 1000), "stt_ms": round((done - started) * 1000)}


class HostedTranscriber:
    def __init__(self):
        s = get_settings()
        self.url, self.key, self.model = (
            s.stt_base_url.rstrip("/") + "/audio/transcriptions",
            s.stt_api_key,
            s.stt_model,
        )

    async def transcribe(self, audio: np.ndarray) -> tuple[str, dict]:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(self.url, headers={"Authorization": f"Bearer {self.key}"}, data={"model": self.model, "language": "en"},
                                  files={"file": ("turn.wav", buffer.getvalue(), "audio/wav")})  # fmt: skip
            r.raise_for_status()
        return r.json().get("text", "").strip(), {
            "stt_wait_ms": 0,
            "stt_ms": round((time.perf_counter() - started) * 1000),
        }


_transcriber = None


def transcriber():
    global _transcriber
    if _transcriber is None:
        _transcriber = HostedTranscriber() if get_settings().stt_provider == "openai_compat" else LocalTranscriber()
    return _transcriber
