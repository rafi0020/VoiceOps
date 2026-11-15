"""One live voice call: audio in, turns found, recognised, answered, spoken back, with barge-in.

The session does not know about WebSockets: it is given two send functions, so the tests drive it with recorded
audio exactly as the browser does. Messages to the client:

    {"type": "state", "state": "listening" | "thinking" | "speaking" | "handed_off" | "ended"}
    {"type": "transcript", "text": ..., "cut": bool}          what the customer said
    {"type": "agent_text", "text": ..., "speaker": "agent" | "person"}
    {"type": "audio", "rate": 22050, "seq": n}  then binary PCM16 frames, then {"type": "audio_end"}
    {"type": "clear"}                                          drop queued audio (the customer spoke over it)
    {"type": "latency", ...}                                   this turn's timings in milliseconds

Audio is sent much faster than it plays, so the session keeps a playback clock: each sentence's start is when the
previous one finishes playing. Until the clock runs out the agent is still speaking, and the customer starting to
speak stops it (`clear`); the transcript keeps the sentences that had started playing.

A reply is spoken only if the customer has not started another turn since and is not speaking at that moment. If they
are speaking, the reply is held: dropped if what they say becomes a turn (that turn is answered instead), spoken if
it fades without one (a cough). Held or dropped replies stay in the record, marked as not spoken.
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

import numpy as np

from app.calls import service
from app.calls.events import call_stream
from app.config import get_settings
from app.redis import get_redis
from app.speech.audio import RATE, pcm16_to_float
from app.speech.stt import transcriber
from app.speech.text import sentences
from app.speech.tts import synthesizer
from app.speech.vad import TurnDetector

CHUNK = 8192  # bytes of PCM per binary frame
SORRY = "I'm sorry, something went wrong on my side. Could you say that again?"
log = logging.getLogger("voiceops.voice")
# What Whisper invents from breath and noise. Phrases that a real caller also says ("Thank you.", "Bye.") count as noise
# only when the turn is very short or quiet; these never are words.
NOISE_ALWAYS = {"", "you", "."}
NOISE_IF_SHORT_OR_QUIET = {"thank you.", "thanks for watching!", "bye."}
SHORT_TURN_S = 0.5  # a turn shorter than this is too brief to be a real "Thank you."
QUIET_RMS = 0.01  # a turn quieter than this (on the float scale of -1 to 1) is breath and room noise
MAX_AUDIO_AHEAD_S = 2.0  # audio may arrive this much faster than real time before it is dropped


class AudioBudget:
    """Audio arrives at the speed the caller speaks. Audio faster than that (a client sending a backlog) is dropped
    beyond a small allowance, so one call cannot keep the event loop busy with voice-activity inference."""

    def __init__(self, allowance_s: float = MAX_AUDIO_AHEAD_S):
        self.allowance, self.ahead, self.at = allowance_s, 0.0, None

    def admit(self, seconds: float, now: float | None = None) -> bool:
        now = time.perf_counter() if now is None else now
        if self.at is not None:
            self.ahead = max(0.0, self.ahead - (now - self.at))  # real time that has passed is room again
        self.at = now
        if self.ahead + seconds > self.allowance + 1e-9:  # float sums of frame lengths
            return False
        self.ahead += seconds
        return True


def _as_float(audio) -> np.ndarray:
    return pcm16_to_float(audio) if isinstance(audio, bytes) else np.asarray(audio, dtype=np.float32)


def is_noise(said: str, audio) -> bool:
    """Whether a recognised turn is noise rather than the caller speaking."""
    text = said.strip().lower()
    if text in NOISE_ALWAYS:
        return True
    if text not in NOISE_IF_SHORT_OR_QUIET:
        return False
    samples = _as_float(audio)
    seconds = len(samples) / RATE
    level = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
    return seconds < SHORT_TURN_S or level < QUIET_RMS


def ms_since(t: float) -> int:
    return round((time.perf_counter() - t) * 1000)


class VoiceSession:
    def __init__(
        self,
        org_id: UUID,
        call_id: UUID,
        send_json: Callable[[dict], Awaitable[None]],
        send_bytes: Callable[[bytes], Awaitable[None]],
    ):
        s = get_settings()
        self.org_id, self.call_id = org_id, call_id
        self.send_json, self.send_bytes = send_json, send_bytes
        self.detector = TurnDetector(
            silence_ms=s.vad_silence_ms, min_speech_ms=s.vad_min_speech_ms, max_turn_s=s.max_turn_seconds
        )
        self.task: asyncio.Task | None = None  # the last answer queued; answers run one after another
        self.speech_tasks: set[asyncio.Task] = set()  # queued speech only (a held reply, a person's words, a greeting)
        self.speaking_task: asyncio.Task | None = None
        self.phase = "listening"
        self.turns_heard = 0  # customer turns so far; a reply is for the turn it answers, not a later one
        self.held: dict | None = None  # a reply ready while the customer was speaking
        self.playing: dict | None = None  # {"idx", "sentences": [(text, starts_at)], "until": t}
        self.follower: asyncio.Task | None = None
        self.audio_budget = AudioBudget()

    async def start(self, greeting: str | None = None) -> None:
        self.follower = asyncio.create_task(self._follow_people())
        await self._state("listening")
        if greeting:
            await self._queue(self._say(greeting, None), speech=True)

    async def close(self) -> None:
        for task in (self.task, self.follower, *self.speech_tasks):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _state(self, state: str) -> None:
        self.phase = state if state in ("listening", "thinking", "speaking") else self.phase
        await self.send_json({"type": "state", "state": state})

    # --- input -----------------------------------------------------------------------------------------------

    async def on_audio(self, pcm16: bytes) -> None:
        if not self.audio_budget.admit(len(pcm16) / 2 / RATE):
            return  # faster than real time: dropped, so the voice detector keeps up with every call
        await self._handle(self.detector.feed(pcm16))

    async def on_end_turn(self) -> None:
        """Press to talk: the caller let go of the button, so the turn they were holding ends now."""
        await self._handle(self.detector.end_turn())

    async def _handle(self, events) -> None:
        for event in events:
            if event.kind == "speech_start":
                await self.barge_in()
            elif event.kind == "turn":
                self.turns_heard += 1
                await self._queue(self._audio_turn(event.audio, time.perf_counter(), event.cut, self.turns_heard))
        if self.held and not self.detector.in_speech:
            await self._release_held()

    async def on_text(self, said: str) -> None:
        await self.barge_in()
        self.turns_heard += 1
        await self._queue(self._respond(said, {"input": "typed"}, time.perf_counter(), self.turns_heard))

    async def _queue(self, coro, *, speech: bool = False) -> None:
        """One answer at a time: the next runs after the current one, without blocking the audio input (which must
        keep running so the customer can be heard speaking over the agent). A failure is logged and apologised for."""
        previous = self.task

        async def after_previous():
            try:
                if previous and not previous.done():
                    await asyncio.wait({previous})  # its outcome is its own; a cancellation lands here
            except asyncio.CancelledError:
                coro.close()  # cancelled before its turn: never awaited, so close it rather than warn
                raise
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the caller must hear something, and the session must keep listening
                log.exception("voice turn failed", extra={"call_id": str(self.call_id)})
                await self._apologise()

        task = asyncio.create_task(after_previous())
        self.task = task
        if speech:
            self.speech_tasks.add(task)
            task.add_done_callback(self.speech_tasks.discard)

    async def barge_in(self) -> None:
        """The customer started speaking. If the agent is still speaking (audio playing in the browser, or still being
        sent), stop it and drop any speech queued behind it; answers to earlier turns still run."""
        if not self._audible():
            return
        await self._stop_speaking()
        await self._state("listening")

    def _audible(self) -> bool:
        playing = self.playing is not None and time.perf_counter() < self.playing["until"]
        sending = self.speaking_task is not None and not self.speaking_task.done()
        return playing or sending

    async def _stop_speaking(self) -> None:
        current = asyncio.current_task()
        for task in {self.speaking_task, *self.speech_tasks} - {None, current}:
            if not task.done():
                task.cancel()
        await self.send_json({"type": "clear"})
        if self.playing and self.playing.get("idx") is not None:
            now = time.perf_counter()
            heard = " ".join(text for text, starts in self.playing["sentences"] if starts <= now)
            await service.mark_interrupted(self.org_id, self.call_id, self.playing["idx"], heard or None)
        self.playing, self.speaking_task = None, None

    async def _release_held(self) -> None:
        held, self.held = self.held, None
        if held["turn"] == self.turns_heard:  # the sound faded without a turn: say it now
            await self._queue(self._say(held["reply"], held["idx"]), speech=True)
        else:  # the customer said something new; that is answered instead
            await service.mark_interrupted(self.org_id, self.call_id, held["idx"], None)

    async def _apologise(self) -> None:
        with contextlib.suppress(Exception):
            await self.send_json({"type": "agent_text", "text": SORRY, "speaker": "agent"})
            await self._speak(SORRY, None, None, {})
            await self._play_out()
        with contextlib.suppress(Exception):
            await self._state("listening")

    # --- a turn ----------------------------------------------------------------------------------------------

    async def _audio_turn(self, audio, speech_end: float, cut: bool, turn: int) -> None:
        await self._state("thinking")
        said, timings = await transcriber().transcribe(audio)
        timings["audio_ms"] = round(len(audio) / 16)
        if is_noise(said, audio):
            if self.held and not self.detector.in_speech:
                self.turns_heard -= 1  # not a turn after all
                await self._release_held()
            await self._state("listening")
            return
        await self.send_json({"type": "transcript", "text": said, "cut": cut})
        await self._respond(said, timings, speech_end, turn)

    async def _respond(self, said: str, timings: dict, speech_end: float, turn: int | None = None) -> None:
        turn = self.turns_heard if turn is None else turn
        await self._state("thinking")
        result = await service.customer_turn(self.org_id, self.call_id, said, timings=timings)
        timings = result.get("timings", timings) | {"reply_ready_ms": ms_since(speech_end)}
        reply, idx, spoken = result["reply"], result.get("agent_idx"), False
        if reply and turn != self.turns_heard:  # the customer has started another turn; it will be answered
            await service.mark_interrupted(self.org_id, self.call_id, idx, None)
        elif reply and self.detector.in_speech:  # the customer is speaking: wait to see if it becomes a turn
            self.held = {"reply": reply, "idx": idx, "turn": turn}
        elif reply:
            spoken = True
        try:
            if spoken:
                await self._speak(reply, idx, speech_end, timings)
        finally:  # kept even when the customer speaks over the reply while it is being sent
            await asyncio.shield(self._record(result["customer_idx"], timings))
        if spoken:
            await self._play_out()
        status = result["status"]
        await self._state(status if status != "live" else "listening")

    async def _record(self, customer_idx: int, timings: dict) -> None:
        await service.set_timings(self.org_id, self.call_id, customer_idx, timings)
        await self.send_json({"type": "latency", **timings})

    async def _say(self, text: str, idx: int | None, speaker: str = "agent") -> None:
        await self._speak(text, idx, None, {}, speaker=speaker)
        await self._play_out()
        await self._state("listening")

    async def _speak(
        self, reply: str, agent_idx: int | None, speech_end: float | None, timings: dict, speaker: str = "agent"
    ) -> None:
        """Send the reply's audio, a sentence at a time, and start its playback clock."""
        self.speaking_task = asyncio.current_task()
        await self.send_json({"type": "agent_text", "text": reply, "speaker": speaker})
        self.playing = {"idx": agent_idx, "sentences": [], "until": time.perf_counter()}
        await self._state("speaking")
        for seq, sentence in enumerate(sentences(reply)):
            pcm, rate, synth_ms = await synthesizer().synthesize(sentence)
            if seq == 0:
                timings["tts_first_ms"] = synth_ms
                if speech_end is not None:
                    timings["first_audio_ms"] = ms_since(speech_end)  # end of the customer's speech to first sound
            await self.send_json({"type": "audio", "rate": rate, "seq": seq})
            for i in range(0, len(pcm), CHUNK):
                await self.send_bytes(pcm[i : i + CHUNK])
            starts = max(time.perf_counter(), self.playing["until"])
            self.playing["sentences"].append((sentence, starts))
            self.playing["until"] = starts + len(pcm) / 2 / rate
        await self.send_json({"type": "audio_end"})

    async def _play_out(self) -> None:
        """Wait while the browser plays what was sent; the customer can still stop it."""
        if self.playing:
            await asyncio.sleep(max(0.0, self.playing["until"] - time.perf_counter()))
        self.playing, self.speaking_task = None, None

    # --- a person who took the call over ---------------------------------------------------------------------

    async def _follow_people(self) -> None:
        """Speak what a person types after taking the call over, and the agent's words after a supervisor's decision;
        stop the agent when a person takes over; tell the client when the call ends."""
        redis, key, cursor = get_redis(), call_stream(self.call_id), "$"
        entries = await redis.xrevrange(key, count=1)
        cursor = entries[0][0] if entries else "0-0"
        while True:
            for event_id, fields in await redis.xrange(key, min=f"({cursor}", count=50):
                cursor = event_id
                data = json.loads(fields["data"])
                if fields["type"] == "turn" and data.get("speaker") == "person":
                    await self._queue(self._say(data["text"], None, speaker="person"), speech=True)
                elif fields["type"] == "agent_reply":  # the agent resumed after a supervisor's decision
                    await self._queue(self._say(data["text"], data.get("idx")), speech=True)
                elif fields["type"] == "call_state" and data.get("status") == "handed_off":
                    if self._audible():
                        await self._stop_speaking()  # a person has the call: the agent stops at once
                    await self.send_json({"type": "state", "state": "handed_off"})
                elif fields["type"] == "call_ended":
                    await self.send_json({"type": "state", "state": "ended"})
            await asyncio.sleep(0.3)
