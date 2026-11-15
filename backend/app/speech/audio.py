"""Audio formats on the wire and between models: 16-bit little-endian PCM, mono."""

import numpy as np

RATE = 16_000  # what the browser sends and Whisper wants


def pcm16_to_float(data: bytes) -> np.ndarray:
    """Whole samples only: a stray trailing byte cannot be a sample, so it is left out rather than raising."""
    whole = data[: len(data) - len(data) % 2]
    return np.frombuffer(whole, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Linear resampling: enough for speech recognition and for playback of synthesised speech."""
    if src == dst or len(audio) == 0:
        return audio.astype(np.float32)
    positions = np.arange(0, len(audio) * dst / src) * src / dst
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)
