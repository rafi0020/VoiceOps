"""The voice socket: one per call, for the person who placed it.

    ws(s)://host/api/voice/{call_id}

Signed in by the session cookie. A WebSocket is not covered by CORS, so the Origin header must be one of this
deployment's origins (cross-site WebSocket hijacking). Frames from the client: binary = 16 kHz mono PCM16; text =
JSON {"type": "text", "text": ...} for a typed turn, {"type": "end_turn"} when a press-to-talk caller lets go of the
button, {"type": "end"}, or {"type": "ping"}, which the page sends every minute so that a muted caller's socket is not
closed as idle.
"""

import asyncio
import contextlib
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.calls import service
from app.config import get_settings
from app.db import tenant_session
from app.models.calls import Turn
from app.security import sessions
from app.voice.session import VoiceSession

router = APIRouter()
MAX_FRAME = 64 * 1024
MAX_COMMAND = 8000  # characters of JSON; longer text frames are dropped unread
IDLE_SECONDS = 300


def audio_frame_ok(data: bytes) -> bool:
    """A binary frame is 16-bit samples of at most MAX_FRAME bytes. A broken one (an odd byte count) is dropped whole,
    so the samples after it stay aligned."""
    return len(data) <= MAX_FRAME and len(data) % 2 == 0


def parse_command(raw: str) -> dict | None:
    """A text frame is a JSON object. Anything else (a number, an array, not JSON, too long) is ignored, not fatal."""
    if len(raw) >= MAX_COMMAND:
        return None
    try:
        command = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return command if isinstance(command, dict) else None


@router.websocket("/api/voice/{call_id}")
async def voice(ws: WebSocket, call_id: UUID) -> None:
    if ws.headers.get("origin") not in get_settings().cors_origin_list:  # browsers always send it on a WebSocket
        await ws.close(code=4403, reason="origin not allowed")
        return
    token = ws.cookies.get(sessions.COOKIE)
    user = await sessions.resolve(token) if token else None
    if user is None:
        await ws.close(code=4401, reason="not signed in")
        return
    async with tenant_session(user.org_id) as db:
        try:
            call = await service.load(db, call_id)
        except Exception:  # noqa: BLE001 - not found, or another organisation's: the same answer
            await ws.close(code=4404, reason="call not found")
            return
    if call.started_by != user.id or call.status == "ended":
        await ws.close(code=4403, reason="not your call, or it has ended")
        return
    async with tenant_session(user.org_id) as db:
        turns = (
            await db.execute(select(Turn.speaker, Turn.text).where(Turn.call_id == call_id).order_by(Turn.idx))
        ).all()
    await ws.accept()
    session = VoiceSession(user.org_id, call_id, ws.send_json, ws.send_bytes)
    await session.start(greeting=turns[0].text if len(turns) == 1 and turns[0].speaker == "agent" else None)
    try:
        while True:
            message = await asyncio.wait_for(ws.receive(), timeout=IDLE_SECONDS)
            if message["type"] == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                if audio_frame_ok(data):
                    await session.on_audio(data)
            elif (raw := message.get("text")) is not None:
                command = parse_command(raw)
                if command is None:
                    continue
                if command.get("type") == "text" and str(command.get("text", "")).strip():
                    await session.on_text(str(command["text"])[:2000])
                elif command.get("type") == "end_turn":  # press to talk: the button was released
                    await session.on_end_turn()
                elif command.get("type") == "end":
                    await service.end_call(user.org_id, call_id)
                    await ws.send_json({"type": "state", "state": "ended"})
                    break
    except (WebSocketDisconnect, TimeoutError):
        pass
    finally:
        await session.close()
        # No reconnect: a socket that closes without "end" (a closed tab, a dropped network) ends the call, so it
        # does not stay live with nobody on it.
        with contextlib.suppress(Exception):
            await service.end_call(user.org_id, call_id)
        with contextlib.suppress(Exception):
            await ws.close()
