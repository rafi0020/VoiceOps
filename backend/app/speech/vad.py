"""Finding the customer's turns in a stream of audio: Silero VAD (the ONNX model shipped with faster-whisper) run
window by window with its state carried over, so each 32 ms of audio is judged once.

A turn starts when speech is detected and ends after `silence_ms` without it. Sounds shorter than
`min_speech_ms` (a cough, a click) are not turns. A monologue longer than `max_turn_s` is cut there and handed on,
so recognition never waits on an unbounded buffer. A short pre-roll is kept so the first syllable is not lost.
"""

from dataclasses import dataclass, field

import numpy as np
from faster_whisper.vad import get_vad_model

from app.speech.audio import RATE, pcm16_to_float

WINDOW = 512  # 32 ms at 16 kHz, what the model was trained on
CONTEXT = 64
START, END = 0.5, 0.35  # hysteresis: harder to start a turn than to keep one going
PRE_ROLL = 10  # windows (320 ms) kept before speech starts

_model = None


def model():
    global _model
    if _model is None:
        _model = get_vad_model()
    return _model


@dataclass
class Event:
    kind: str  # "speech_start" | "turn"
    audio: np.ndarray | None = None
    cut: bool = False  # the turn was cut at the maximum length


@dataclass
class TurnDetector:
    silence_ms: int = 600
    min_speech_ms: int = 250
    max_turn_s: int = 30
    _pending: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    _context: np.ndarray = field(default_factory=lambda: np.zeros(CONTEXT, np.float32))
    _h: np.ndarray = field(default_factory=lambda: np.zeros((1, 1, 128), np.float32))
    _c: np.ndarray = field(default_factory=lambda: np.zeros((1, 1, 128), np.float32))
    _history: list = field(default_factory=list)
    _turn: list = field(default_factory=list)
    _speaking: bool = False
    _speech_windows: int = 0
    _silent_windows: int = 0

    def probability(self, window: np.ndarray) -> float:
        batch = np.concatenate([self._context, window])[None, :]
        out, self._h, self._c = model().session.run(None, {"input": batch, "h": self._h, "c": self._c})
        self._context = window[-CONTEXT:]
        return float(np.asarray(out).reshape(-1)[0])

    @property
    def in_speech(self) -> bool:
        """The customer is speaking now (a turn has started and not yet ended)."""
        return bool(self._speaking)

    def feed(self, pcm16: bytes) -> list[Event]:
        return self.feed_float(pcm16_to_float(pcm16))

    def feed_float(self, audio: np.ndarray) -> list[Event]:
        events: list[Event] = []
        self._pending = np.concatenate([self._pending, audio.astype(np.float32)])
        while len(self._pending) >= WINDOW:
            window, self._pending = self._pending[:WINDOW], self._pending[WINDOW:]
            p = self.probability(window)
            if not self._speaking:
                self._history = [*self._history[-(PRE_ROLL - 1) :], window]
                if p >= START:
                    self._speaking, self._turn, self._speech_windows, self._silent_windows = (
                        True,
                        list(self._history),
                        1,
                        0,
                    )
                    events.append(Event("speech_start"))
                continue
            self._turn.append(window)
            if p >= END:
                self._speech_windows += 1
                self._silent_windows = 0
            else:
                self._silent_windows += 1
            if self._silent_windows * WINDOW * 1000 / RATE >= self.silence_ms:
                self._finish(events, cut=False)
            elif len(self._turn) * WINDOW / RATE >= self.max_turn_s:
                self._finish(events, cut=True)
        return events

    def end_turn(self) -> list[Event]:
        """The caller let go of the talk button: a turn in progress ends now, without waiting for the silence."""
        events: list[Event] = []
        if self._speaking:
            self._finish(events, cut=False)
        return events

    def _finish(self, events: list[Event], *, cut: bool) -> None:
        if self._speech_windows * WINDOW * 1000 / RATE >= self.min_speech_ms:
            kept = (
                self._turn if cut else self._turn[: len(self._turn) - self._silent_windows]
            )  # the closing silence only slows recognition
            events.append(Event("turn", np.concatenate(kept), cut))
        self._speaking, self._turn, self._history, self._speech_windows, self._silent_windows = False, [], [], 0, 0
