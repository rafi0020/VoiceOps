"""The voice session with the real call service and a scripted model, but fake speech: synthesis is instant (as the
real one nearly is, against the seconds a sentence takes to play) and turns are pushed in directly. Found by the final
review: the speech tests slowed synthesis down to make barge-in possible, so they could not see that barge-in only
worked while audio was still being sent."""

import asyncio

import numpy as np
import pytest

from app.llm.stub import reply
from app.speech.vad import Event
from tests.conftest import rows
from tests.test_calls_api import ME, call, customer, start

RATE = 22050  # the synthesiser's rate
MIC_RATE = 16_000  # what the browser sends
SECONDS_PER_SENTENCE = 2.0


class Client:
    def __init__(self):
        self.messages, self.audio = [], bytearray()

    async def send_json(self, m):
        self.messages.append(m)

    async def send_bytes(self, b):
        self.audio += b

    def kinds(self):
        return [m["type"] for m in self.messages]

    def said(self):
        return [m["text"] for m in self.messages if m["type"] == "agent_text"]

    async def until(self, check, seconds=10):
        for _ in range(int(seconds / 0.02)):
            if check():
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"not reached; messages: {self.messages[-8:]}")


class InstantSynth:
    async def synthesize(self, text):
        return b"\0\0" * int(RATE * SECONDS_PER_SENTENCE), RATE, 5


class Recogniser:
    """Returns the scripted transcripts in order, after a delay like a CPU recogniser's."""

    def __init__(self, said: list[str], delay: float = 0.3, error: Exception | None = None):
        self.said, self.delay, self.error = list(said), delay, error

    async def transcribe(self, audio):
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.said.pop(0), {"stt_ms": 1}


class Detector:
    """Stands in for the VAD: the test says when speech starts, stops without a turn, or ends as a turn."""

    def __init__(self):
        self.events, self.in_speech, self.released = [], False, []

    def feed(self, pcm):
        out, self.events = self.events, []
        return out

    def end_turn(self):
        out, self.released, self.in_speech = self.released, [], False  # as the real detector: nothing in progress
        return out


@pytest.fixture
def speech(monkeypatch):
    def use(recogniser: Recogniser | None = None):
        monkeypatch.setattr("app.voice.session.synthesizer", lambda: InstantSynth())
        monkeypatch.setattr("app.voice.session.transcriber", lambda: recogniser or Recogniser([]))

    return use


async def open_session(team):
    from app.voice.session import VoiceSession

    c = await start(team.agent)
    client = Client()
    session = VoiceSession(team.org_id, c["id"], client.send_json, client.send_bytes)
    session.detector = Detector()
    await session.start()
    return c, client, session


async def speech_starts(session):
    session.detector.in_speech = True
    session.detector.events = [Event("speech_start")]
    await session.on_audio(b"")


async def turn_ends(session):
    session.detector.in_speech = False
    session.detector.events = [Event("turn", audio=b"\0" * 3200)]
    await session.on_audio(b"")


async def sound_fades(session):
    """A cough or a click: speech started, then the detector dropped it as too short to be a turn."""
    session.detector.in_speech = False
    session.detector.events = []
    await session.on_audio(b"")


async def last_agent_turn(team, call_id):
    return (await rows(team.org_id, "SELECT text, interrupted FROM turns WHERE call_id = :c AND speaker = 'agent' ORDER BY idx DESC LIMIT 1", c=call_id))[0]  # fmt: skip


async def test_speaking_over_the_agent_after_all_its_audio_was_sent_still_stops_it(team, stub_llm, speech):
    speech()
    c, client, session = await open_session(team)
    stub_llm.script = [
        reply("Our shop opens at nine in the morning. It closes at five in the evening. It is shut on bank holidays.")
    ]
    await session.on_text("When are you open?")
    await client.until(lambda: "audio_end" in client.kinds())  # three sentences, six seconds, sent in an instant
    await asyncio.sleep(0.3)
    await speech_starts(session)  # the caller speaks during the first sentence
    assert "clear" in client.kinds()
    kept = await last_agent_turn(team, c["id"])
    assert kept.interrupted and kept.text == "Our shop opens at nine in the morning."
    await session.close()


async def test_a_reply_to_half_a_sentence_is_not_spoken_while_the_caller_carries_on(team, stub_llm, speech):
    speech(Recogniser(["My account number is", "A B one two three four five six"]))
    c, client, session = await open_session(team)
    stub_llm.script = [reply("Go on."), reply("Thanks, and your postcode?")]
    await speech_starts(session)
    await turn_ends(session)  # a pause after "my account number is"
    await asyncio.sleep(0.1)
    await speech_starts(session)  # ...and the caller carries on while the first part is recognised
    await asyncio.sleep(0.5)
    assert "Go on." not in client.said()
    await turn_ends(session)
    await client.until(lambda: "Thanks, and your postcode?" in client.said())
    assert "Go on." not in client.said()
    await session.close()


async def test_a_cough_while_the_agent_thinks_does_not_swallow_its_reply(team, stub_llm, speech, monkeypatch):
    from app.calls import service

    real = service.customer_turn

    async def slow_model(*args, **kwargs):
        await asyncio.sleep(0.6)
        return await real(*args, **kwargs)

    monkeypatch.setattr(service, "customer_turn", slow_model)
    speech(Recogniser(["Is there an outage?"], delay=0.05))
    c, client, session = await open_session(team)
    stub_llm.script = [reply("Let me check that for you.")]
    await speech_starts(session)
    await turn_ends(session)
    await asyncio.sleep(0.2)
    await speech_starts(session)  # a cough while it thinks
    await asyncio.sleep(0.4)
    await sound_fades(session)
    await client.until(lambda: "Let me check that for you." in client.said())
    await session.close()


async def test_the_caller_hears_the_supervisors_decision_without_speaking_again(team, stub_llm, speech):
    speech()
    await customer(team)
    c, client, session = await open_session(team)
    stub_llm.script = [reply("", [call("verify_identity", **ME)]), reply("Verified."),
                       reply("", [call("request_credit", amount="25.00", reason="Charged twice")]),
                       reply("A supervisor needs to approve that; please hold.")]  # fmt: skip
    await session.on_text("AB123456 ZZ1 1ZZ 1 February 1990")
    await client.until(lambda: "Verified." in client.said())
    await session.on_text("I was charged twice")
    await client.until(lambda: client.kinds().count("latency") >= 2)  # the second turn has been answered
    credit = (await team.supervisor.get("/api/credits")).json()["credits"][0]
    stub_llm.script = [reply("Good news: the supervisor approved your 25.00 credit.")]
    await team.supervisor.post(f"/api/credits/{credit['id']}/decide", json={"decision": "approved"})
    await client.until(lambda: "Good news: the supervisor approved your 25.00 credit." in client.said())
    await session.close()


async def test_a_take_over_while_the_agent_speaks_stops_its_audio(team, stub_llm, speech):
    speech()
    c, client, session = await open_session(team)
    stub_llm.script = [reply("First sentence. Second sentence. Third sentence.")]
    await session.on_text("Hello")
    await client.until(lambda: "audio_end" in client.kinds())
    await team.supervisor.post(f"/api/calls/{c['id']}/take-over")
    await client.until(lambda: {"type": "state", "state": "handed_off"} in client.messages)
    assert "clear" in client.kinds()
    await session.close()


async def test_a_failure_in_a_voice_turn_is_apologised_for_and_the_session_listens_again(team, stub_llm, speech):
    speech(Recogniser([], error=RuntimeError("recogniser crashed")))
    c, client, session = await open_session(team)
    await speech_starts(session)
    await turn_ends(session)
    await client.until(lambda: any("say that again" in s for s in client.said()))
    await client.until(lambda: client.messages[-1] == {"type": "state", "state": "listening"})
    await session.close()


async def test_speaking_over_queued_replies_cancels_them_all(team, stub_llm, speech):
    speech()
    c, client, session = await open_session(team)
    stub_llm.script = [reply("One. Two."), reply("Three. Four.")]
    await session.on_text("first")
    await session._queue(session._respond("second", {}, 0.0))  # a second answer queued behind the first
    await client.until(lambda: "audio_end" in client.kinds())
    await speech_starts(session)
    await asyncio.sleep(0.5)
    assert "Three. Four." not in client.said()
    await session.close()


async def test_a_reply_cut_off_before_its_first_sentence_is_stored_as_not_heard(team, stub_llm, speech, monkeypatch):
    """Nothing reached the caller, so the transcript keeps no words for the agent's reply (marked interrupted). What
    the agent decided is kept in the call's event log."""

    class SlowFirstSentence:
        async def synthesize(self, text):
            await asyncio.sleep(0.5)  # the caller speaks while the first sentence is still being prepared
            return await InstantSynth().synthesize(text)

    speech()
    monkeypatch.setattr("app.voice.session.synthesizer", lambda: SlowFirstSentence())
    c, client, session = await open_session(team)
    stub_llm.script = [reply("Our shop opens at nine in the morning.")]
    await session.on_text("When are you open?")
    await client.until(lambda: "agent_text" in client.kinds())
    await asyncio.sleep(0.1)
    await speech_starts(session)
    await client.until(lambda: "clear" in client.kinds())
    agent = await last_agent_turn(team, c["id"])
    assert agent.interrupted and agent.text == ""
    events = await rows(
        team.org_id, "SELECT data FROM call_events WHERE call_id = :c AND kind = 'reply_not_heard'", c=c["id"]
    )
    assert events[0][0]["decided"] == "Our shop opens at nine in the morning."
    await session.close()


async def test_a_short_real_answer_reaches_the_agent_but_a_hallucinated_one_from_quiet_does_not(team, stub_llm, speech):
    """Whisper says "Thank you." or "Bye." for breath and noise. Those phrases are dropped only when the turn is very
    short or quiet; a clear 0.8 s "Thank you." is the caller's answer."""
    rng = np.random.default_rng(3)
    loud = (rng.standard_normal(int(0.8 * MIC_RATE)) * 0.2).astype(np.float32)
    quiet = (rng.standard_normal(int(0.8 * MIC_RATE)) * 0.001).astype(np.float32)

    speech(Recogniser(["Thank you.", "Thank you."]))
    c, client, session = await open_session(team)
    stub_llm.script = [reply("You're welcome.")]
    session.detector.events = [Event("turn", audio=loud)]
    await session.on_audio(b"")
    await client.until(lambda: "You're welcome." in client.said())

    session.detector.events = [Event("turn", audio=quiet)]
    await session.on_audio(b"")
    await asyncio.sleep(0.5)
    assert client.said().count("You're welcome.") == 1
    assert len(stub_llm.calls) == 1  # the quiet one never reached the model
    await session.close()


async def test_audio_faster_than_real_time_is_capped_so_one_call_cannot_flood_the_detector(team, speech):
    speech()
    c, client, session = await open_session(team)
    fed = []
    session.detector.feed = lambda pcm: (fed.append(len(pcm)), [])[1]
    for _ in range(100):  # ten seconds of audio sent at once
        await session.on_audio(b"\0" * 3200)
    assert sum(fed) <= 2.2 * MIC_RATE * 2  # about two seconds of allowance, plus one frame
    await session.close()


def test_the_audio_budget_refills_at_real_time():
    from app.voice.session import AudioBudget

    budget = AudioBudget(allowance_s=2.0)
    admitted = sum(1 for _ in range(100) if budget.admit(0.1, now=0.0))
    assert admitted == 20
    assert budget.admit(0.1, now=1.0)  # a second of real time has passed: a second of room is back


async def test_releasing_press_to_talk_answers_the_turn_without_any_silence(team, stub_llm, speech):
    """Press to talk sends audio only while held, so no silence arrives to end the turn: releasing ends it."""
    speech(Recogniser(["Is my broadband down?"]))
    c, client, session = await open_session(team)
    stub_llm.script = [reply("Let me check.")]
    session.detector.in_speech = True
    session.detector.released = [Event("turn", audio=np.zeros(MIC_RATE, np.float32))]
    await session.on_end_turn()
    await client.until(lambda: "Let me check." in client.said())
    await session.close()


def test_releasing_the_talk_button_ends_a_turn_in_progress_at_once(monkeypatch):
    from app.speech.audio import float_to_pcm16
    from app.speech.vad import TurnDetector

    monkeypatch.setattr(TurnDetector, "probability", lambda self, window: 0.9 if np.any(window) else 0.0)
    detector = TurnDetector(min_speech_ms=250)
    second = np.ones(MIC_RATE, np.float32) * 0.2
    assert [e.kind for e in detector.feed(float_to_pcm16(second))] == ["speech_start"]
    assert detector.in_speech and detector.end_turn()[0].kind == "turn"
    assert not detector.in_speech and detector.end_turn() == []
