"""Retry, back-off and fallback policy."""

import pytest

from app.llm.base import LLMError, LLMUnavailable, call_with_retry
from app.llm.stub import StubProvider, reply
from app.llm.types import Message

ASK = [Message("user", "hi")]


class Recorder:
    def __init__(self):
        self.delays = []

    async def __call__(self, seconds):
        self.delays.append(seconds)


def transient(status=503, retry_after=None):
    return LLMError("busy", status=status, retryable=True, retry_after=retry_after)


async def test_transient_error_is_retried_then_succeeds():
    stub, sleep = StubProvider([transient(429), reply("ok")]), Recorder()
    r = await call_with_retry(stub, ASK, [], model="m", max_tokens=5, sleep=sleep)
    assert r.text == "ok" and len(stub.calls) == 2 and len(sleep.delays) == 1


async def test_backoff_grows_and_retry_after_is_honoured():
    stub, sleep = StubProvider([transient(), transient(), transient(retry_after=7), reply("ok")]), Recorder()
    await call_with_retry(stub, ASK, [], model="m", max_tokens=5, sleep=sleep, base_delay=1.0)
    assert 0.8 <= sleep.delays[0] <= 1.2 and 1.6 <= sleep.delays[1] <= 2.4 and 5.6 <= sleep.delays[2] <= 8.4


async def test_fallback_model_is_used_after_the_primary_is_exhausted():
    used = []

    class Provider(StubProvider):
        async def complete(self, messages, tools, *, model, max_tokens, temperature=0):
            used.append(model)
            if model == "primary":
                raise transient()
            return reply("from fallback")

    r = await call_with_retry(
        Provider(), ASK, [], model="primary", max_tokens=5, fallback_model="backup", sleep=Recorder()
    )
    assert r.text == "from fallback" and used == ["primary"] * 4 + ["backup"]


async def test_gives_up_with_llm_unavailable_when_everything_fails():
    stub = StubProvider([transient()] * 4)
    with pytest.raises(LLMUnavailable):
        await call_with_retry(stub, ASK, [], model="m", max_tokens=5, sleep=Recorder())
    assert len(stub.calls) == 4


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_errors_that_cannot_succeed_are_not_retried(status):
    stub = StubProvider([LLMError("bad request", status=status, retryable=False), reply("never reached")])
    with pytest.raises(LLMError) as info:
        await call_with_retry(stub, ASK, [], model="m", max_tokens=5, sleep=Recorder())
    assert info.value.status == status and len(stub.calls) == 1


async def test_the_retry_wrapper_passes_temperature_through():
    seen = []

    class Provider(StubProvider):
        async def complete(self, messages, tools, *, model, max_tokens, temperature=0.7):
            seen.append(temperature)
            return reply("ok")

    await call_with_retry(Provider(), ASK, [], model="m", max_tokens=5, temperature=0, sleep=Recorder())
    assert seen == [0]
