"""The voice session driven with recorded audio, as the browser drives it: a spoken turn is recognised, answered and
spoken back with its latency recorded; speaking over the agent stops it and the transcript keeps what was said;
noise is not a turn; a typed turn works the same way."""

import asyncio
import os
from pathlib import Path

import numpy as np
import pytest

from app.llm.stub import reply
from app.speech.audio import RATE, float_to_pcm16
from tests.conftest import rows
from tests.test_calls_api import ME, call, customer, start
from tests.test_speech import customer_says

MODELS = Path(os.environ["MODELS_DIR"])
pytestmark = [
    pytest.mark.speech,
    pytest.mark.skipif(
        not (MODELS / "piper" / "en_US-lessac-medium.onnx").exists(), reason="speech models not downloaded here"
    ),
]


class Client:
    def __init__(self):
        self.messages, self.audio = [], bytearray()

    async def send_json(self, m):
        self.messages.append(m)

    async def send_bytes(self, b):
        self.audio += b

    def kinds(self):
        return [m["type"] for m in self.messages]

    async def until(self, check, seconds=60):
        for _ in range(int(seconds / 0.05)):
            if check():
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"not reached; messages: {self.messages[-8:]}")


async def feed(session, audio: np.ndarray, frame_ms: int = 20):
    """The browser sends audio as the microphone captures it: at the speed it plays. Faster than that is dropped by
    the session's audio budget, so the frames are paced here."""
    step = RATE * frame_ms // 1000
    for i in range(0, len(audio), step):
        await session.on_audio(float_to_pcm16(audio[i : i + step]))
        await asyncio.sleep(frame_ms / 1000)


SILENCE = np.zeros(RATE, np.float32)


async def session_for(team):
    from app.voice.session import VoiceSession

    c = await start(team.agent)
    client = Client()
    session = VoiceSession(team.org_id, c["id"], client.send_json, client.send_bytes)
    await session.start()
    return c, client, session


async def test_a_spoken_turn_is_recognised_answered_spoken_and_timed(team, stub_llm):
    await customer(team)
    c, client, session = await session_for(team)
    stub_llm.script = [reply("", [call("verify_identity", **ME)]), reply("Thanks Jo, you're verified. How can I help?")]
    await feed(
        session,
        np.concatenate([SILENCE, await customer_says("My account is A B one two three four five six."), SILENCE]),
    )
    await client.until(lambda: "latency" in client.kinds())
    transcript = next(m for m in client.messages if m["type"] == "transcript")
    assert "123456" in transcript["text"].replace(" ", "")
    assert (
        next(m for m in client.messages if m["type"] == "agent_text")["text"]
        == "Thanks Jo, you're verified. How can I help?"
    )
    assert len(client.audio) > 22050  # more than half a second of speech came back
    latency = next(m for m in client.messages if m["type"] == "latency")
    assert latency["first_audio_ms"] > 0 and latency["stt_ms"] > 0 and "agent_ms" in latency
    stored = await rows(team.org_id, "SELECT timings FROM turns WHERE call_id = :c AND speaker = 'customer'", c=c["id"])
    assert stored[0][0]["first_audio_ms"] == latency["first_audio_ms"]
    await session.close()


async def test_speaking_over_the_agent_stops_it_and_the_transcript_keeps_what_was_said(team, stub_llm, monkeypatch):
    from app.speech import tts

    real = tts.synthesizer()

    class Slow:
        async def synthesize(self, text):
            await asyncio.sleep(0.6)  # long enough to speak over
            return await real.synthesize(text)

    monkeypatch.setattr("app.voice.session.synthesizer", lambda: Slow())
    c, client, session = await session_for(team)
    stub_llm.script = [
        reply(
            "First, our opening hours are nine to five every weekday. Second, we close on bank holidays. Third, you can also write to us."
        )
    ]
    await session.on_text("When are you open?")
    await client.until(lambda: sum(1 for m in client.messages if m["type"] == "audio") >= 1)
    await feed(session, await customer_says("Sorry, stop, I have another question."))
    await client.until(lambda: "clear" in client.kinds())
    agent = await rows(
        team.org_id,
        "SELECT text, interrupted FROM turns WHERE call_id = :c AND speaker = 'agent' ORDER BY idx DESC LIMIT 1",
        c=c["id"],
    )
    assert agent[0].interrupted is True and "Third" not in agent[0].text
    await session.close()


async def test_noise_and_silence_are_not_turns(team, stub_llm):
    c, client, session = await session_for(team)
    click = (np.random.default_rng(2).standard_normal(int(0.08 * RATE)) * 0.3).astype(np.float32)
    await feed(session, np.concatenate([SILENCE, click, SILENCE, SILENCE]))
    await asyncio.sleep(0.5)
    assert "transcript" not in client.kinds() and stub_llm.calls == []
    await session.close()
