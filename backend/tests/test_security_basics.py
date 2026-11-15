from app.security.crypto import decrypt, encrypt
from app.security.passwords import hash_password, verify_password
from app.security.redact import redact


async def test_security_headers_on_every_response(client):
    h = (await client.get("/api/auth/me")).headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert h["Cache-Control"] == "no-store"


def test_password_hash_verifies_and_is_salted():
    a, b = hash_password("Correct-Horse-9"), hash_password("Correct-Horse-9")
    assert a != b and a.startswith("scrypt$")
    assert verify_password("Correct-Horse-9", a) and not verify_password("correct-horse-9", a)
    assert not verify_password("anything", "not-a-hash")


def test_redact_masks_sensitive_keys_and_secret_looking_values():
    out = redact(
        {
            "model": "gpt",
            "config": {"api_key": "abc", "Authorization": "Bearer x", "timeout": 5},
            "note": "the key is sk-test0000000000000abcdefgh and more",
            "items": [{"password": "p"}, "plain"],
            "empty_token": "",
        }
    )
    assert out["config"] == {"api_key": "[redacted]", "Authorization": "[redacted]", "timeout": 5}
    assert out["note"] == "the key is [redacted] and more"
    assert out["items"] == [{"password": "[redacted]"}, "plain"]
    assert out["model"] == "gpt" and out["empty_token"] == ""


def test_encrypt_round_trips_and_is_not_plaintext():
    token = encrypt("sk-live-value")
    assert "sk-live-value" not in token and decrypt(token) == "sk-live-value"


def test_counts_named_like_secrets_are_not_masked():
    """Found by the VoiceOps evaluation: input_tokens and output_tokens came back as [redacted]."""
    out = redact({"input_tokens": 120, "max_tokens": 4096, "tokens": 9, "api_key": "x", "access_token": "y", "Authorization": "z",
                  "client_secret": "s", "password": "p", "monkey": "banana", "cookie": "c", "key": "k"})  # fmt: skip
    assert out == {"input_tokens": 120, "max_tokens": 4096, "tokens": 9, "api_key": "[redacted]", "access_token": "[redacted]",
                   "Authorization": "[redacted]", "client_secret": "[redacted]", "password": "[redacted]", "monkey": "banana",
                   "cookie": "[redacted]", "key": "[redacted]"}  # fmt: skip


def test_a_voice_socket_without_an_origin_header_is_refused():
    """Browsers always send Origin on a WebSocket; a request without one is not from this deployment's pages."""
    import pytest
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.main import create_app

    with pytest.raises(WebSocketDisconnect) as closed:
        with TestClient(create_app()).websocket_connect("/api/voice/00000000-0000-0000-0000-000000000000"):
            pass
    assert closed.value.code == 4403


def test_a_frame_with_an_odd_number_of_bytes_is_dropped_not_fatal():
    """PCM16 is whole samples. An odd-length binary frame used to raise inside the detector and end the socket."""
    from app.speech.vad import TurnDetector

    assert TurnDetector().feed(b"\x01") == []  # a broken frame: nothing to judge, nothing raised
    assert TurnDetector().feed(b"\x01\x00\x02") == []  # whole samples only: the stray byte is left out


def test_a_text_frame_that_is_not_a_json_object_is_ignored():
    """A JSON array, number or string used to raise on .get() and end the socket."""
    from app.api.voice import parse_command

    assert parse_command("[1, 2]") is None
    assert parse_command('"hello"') is None
    assert parse_command("42") is None
    assert parse_command("not json") is None
    assert parse_command('{"type": "ping"}') == {"type": "ping"}
    assert parse_command("x" * 9000) is None  # oversized commands are dropped unread
    from app.api.voice import audio_frame_ok

    assert audio_frame_ok(b"\x00\x01") and not audio_frame_ok(b"\x00\x01\x02")  # an odd frame is dropped whole


async def test_an_out_of_range_paging_value_is_a_422_not_a_500(team):
    """A paging value the database cannot hold used to fail inside the query (a 500)."""
    r = await team.admin.get("/api/audit", params={"before": 99999999999999999999})
    assert r.status_code == 422
    assert (await team.admin.get("/api/audit", params={"before": "abc"})).status_code == 422


async def test_signed_in_requests_survive_a_redis_outage(team, monkeypatch):
    """Sessions are cached in Redis. When Redis is down they are read from PostgreSQL, not a 500."""
    import redis.exceptions

    class Down:
        async def get(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("redis is down")

        async def set(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("redis is down")

        async def delete(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("redis is down")

    monkeypatch.setattr("app.security.sessions.get_redis", lambda: Down())
    r = await team.agent.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["user"]["role"] == "agent"


async def test_a_rate_limited_route_during_a_redis_outage_says_when_to_retry(team, monkeypatch):
    import redis.exceptions

    class Down:
        def pipeline(self):
            raise redis.exceptions.ConnectionError("redis is down")

        async def get(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("redis is down")

        async def set(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("redis is down")

        async def delete(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("redis is down")

    monkeypatch.setattr("app.security.sessions.get_redis", lambda: Down())
    monkeypatch.setattr("app.security.ratelimit.get_redis", lambda: Down())
    r = await team.agent.post("/api/calls", json={"channel": "text"})
    assert r.status_code == 503 and r.headers.get("retry-after")
