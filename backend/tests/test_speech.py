"""Speech: the recogniser hears what the synthesiser says, turns are found in a stream of audio (and silence, a
click or a monologue are handled), and citations are not read aloud."""

import os
from pathlib import Path

import numpy as np
import pytest

from app.speech.audio import RATE, float_to_pcm16, pcm16_to_float, resample
from app.speech.text import sentences, speakable
from app.speech.vad import TurnDetector

MODELS = Path(os.environ["MODELS_DIR"])
needs_models = pytest.mark.skipif(
    not (MODELS / "piper" / "en_US-ryan-medium.onnx").exists(), reason="speech models not downloaded here"
)


def wer(reference: str, hypothesis: str) -> float:
    import re

    r, h = re.findall(r"[a-z0-9']+", reference.lower()), re.findall(r"[a-z0-9']+", hypothesis.lower())
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(1, len(r))


async def customer_says(text: str) -> np.ndarray:
    """A customer's voice (a different voice from the agent's), at 16 kHz."""
    from app.speech.tts import LocalSynthesizer

    pcm, rate, _ = await LocalSynthesizer("en_US-ryan-medium").synthesize(text)
    return resample(pcm16_to_float(pcm), rate, RATE)


def test_citations_are_kept_in_text_but_not_spoken_and_replies_split_into_sentences():
    said = "You get 9.33 a day after two working days [outages-and-compensation §2]. Ok. Shall I open a ticket?"
    assert speakable(said) == "You get 9.33 a day after two working days. Ok. Shall I open a ticket?"
    assert sentences(said) == ["You get 9.33 a day after two working days.", "Ok. Shall I open a ticket?"]


@pytest.mark.speech
@needs_models
async def test_the_recogniser_hears_what_was_said():
    from app.speech.stt import LocalTranscriber

    text = "Hello, my broadband has been down since this morning and the router lights are red."
    heard, timings = await LocalTranscriber().transcribe(await customer_says(text))
    assert wer(text, heard) < 0.2, heard
    assert timings["stt_ms"] > 0


@pytest.mark.speech
@needs_models
async def test_a_turn_is_found_between_silences_and_noise_is_not_a_turn():
    speech = await customer_says("I would like to check my last bill please.")
    silence = np.zeros(RATE, np.float32)
    click = (np.random.default_rng(1).standard_normal(int(0.08 * RATE)) * 0.3).astype(np.float32)
    detector = TurnDetector(silence_ms=600, min_speech_ms=250, max_turn_s=30)
    events = []
    for chunk in np.array_split(
        np.concatenate([silence, click, silence, speech, silence]), 200
    ):  # arrives in small frames
        events += detector.feed(float_to_pcm16(chunk))
    turns = [e for e in events if e.kind == "turn"]
    assert len(turns) == 1 and not turns[0].cut
    assert abs(len(turns[0].audio) - len(speech)) < 0.9 * RATE  # the speech, a little pre-roll and the closing silence
    assert detector.feed(float_to_pcm16(np.zeros(2 * RATE, np.float32))) == []


@pytest.mark.speech
@needs_models
async def test_a_monologue_is_cut_at_the_maximum_turn_length():
    speech = await customer_says(
        "And another thing about the bill, and another thing, and another thing about my router and my phone and the engineer"
    )
    detector = TurnDetector(silence_ms=600, min_speech_ms=250, max_turn_s=3)
    events = detector.feed_float(np.tile(speech, 3))
    cut = [e for e in events if e.kind == "turn" and e.cut]
    assert cut and all(len(e.audio) <= 3 * RATE + 512 for e in cut)
