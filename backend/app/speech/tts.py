"""Speech synthesis. Local: Piper (ONNX on the CPU), one sentence at a time. Hosted: any OpenAI-compatible
/audio/speech endpoint returning raw PCM. Returns 16-bit PCM and its sample rate."""

import asyncio
import time
from pathlib import Path

import httpx
import numpy as np

from app.config import get_settings


class LocalSynthesizer:
    def __init__(self, voice: str | None = None):
        from piper import PiperVoice

        s = get_settings()
        self.voice = PiperVoice.load(str(Path(s.models_dir) / "piper" / f"{voice or s.tts_voice}.onnx"))
        self.rate = self.voice.config.sample_rate

    def _run(self, text: str) -> bytes:
        chunks = list(self.voice.synthesize(text))
        return np.concatenate([c.audio_int16_array for c in chunks]).astype("<i2").tobytes() if chunks else b""

    async def synthesize(self, text: str) -> tuple[bytes, int, int]:
        started = time.perf_counter()
        pcm = await asyncio.to_thread(self._run, text)
        return pcm, self.rate, round((time.perf_counter() - started) * 1000)


class HostedSynthesizer:
    rate = 24_000  # OpenAI's raw PCM output

    def __init__(self):
        s = get_settings()
        self.url, self.key, self.model, self.voice = (
            s.tts_base_url.rstrip("/") + "/audio/speech",
            s.tts_api_key,
            s.tts_model or "tts-1",
            s.tts_voice,
        )

    async def synthesize(self, text: str) -> tuple[bytes, int, int]:
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(self.url, headers={"Authorization": f"Bearer {self.key}"},
                                  json={"model": self.model, "voice": self.voice, "input": text, "response_format": "pcm"})  # fmt: skip
            r.raise_for_status()
        return r.content, self.rate, round((time.perf_counter() - started) * 1000)


_synth = None


def synthesizer():
    global _synth
    if _synth is None:
        _synth = HostedSynthesizer() if get_settings().tts_provider == "openai_compat" else LocalSynthesizer()
    return _synth
