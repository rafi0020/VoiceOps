"""Provider adapters, exercised against canned HTTP responses."""

import json

import httpx
import pytest

from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMError
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.pricing import cost_usd
from app.llm.types import Message, ToolCall, ToolSpec, Usage

TOOLS = [ToolSpec("run_sql", "Run SQL", {"type": "object", "properties": {"sql": {"type": "string"}}})]
ASK = [Message("system", "You are an agent."), Message("user", "Revenue for West?")]

PLAIN = {
    "model": "gpt-x",
    "choices": [
        {
            "finish_reason": "tool_calls",
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 120, "completion_tokens": 18, "prompt_tokens_details": {"cached_tokens": 100}},
}

STREAM = "\n\n".join(
    "data: " + json.dumps(chunk) if isinstance(chunk, dict) else "data: [DONE]"
    for chunk in [
        {"model": "gpt-x", "choices": [{"delta": {"role": "assistant", "content": ""}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call_1", "function": {"name": "run_sql", "arguments": '{"sq'}}
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'l": "SELECT 1"}'}}]}}]},
        {
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 18, "prompt_tokens_details": {"cached_tokens": 100}},
        },
        "DONE",
    ]
)


def openai(handler) -> OpenAICompatProvider:
    return OpenAICompatProvider("http://gateway.test/v1", "sk-test", transport=httpx.MockTransport(handler))


async def test_plain_and_streamed_responses_give_the_same_result():
    plain = openai(lambda r: httpx.Response(200, json=PLAIN))
    streamed = openai(lambda r: httpx.Response(200, text=STREAM, headers={"content-type": "text/event-stream"}))
    mislabelled = openai(lambda r: httpx.Response(200, text=STREAM, headers={"content-type": "application/json"}))
    results = [await p.complete(ASK, TOOLS, model="gpt-x", max_tokens=100) for p in (plain, streamed, mislabelled)]
    for r in results:
        assert r.tool_calls == [ToolCall("call_1", "run_sql", {"sql": "SELECT 1"})]
        assert r.usage == Usage(120, 18, 100) and r.stop_reason == "tool_use" and r.model == "gpt-x"


async def test_request_asks_for_no_stream_and_sends_tools_and_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["auth"], seen["url"] = (
            json.loads(request.content),
            request.headers["authorization"],
            str(request.url),
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]})

    r = await openai(handler).complete(ASK, TOOLS, model="m", max_tokens=50)
    assert seen["url"] == "http://gateway.test/v1/chat/completions" and seen["auth"] == "Bearer sk-test"
    assert seen["body"]["stream"] is False and seen["body"]["tools"][0]["function"]["name"] == "run_sql"
    assert r.text == "hi" and r.tool_calls == [] and r.usage.estimated


async def test_conversation_with_tool_results_is_sent_in_wire_format():
    seen = {}
    history = ASK + [
        Message("assistant", "", [ToolCall("c1", "run_sql", {"sql": "SELECT 1"})]),
        Message("tool", '{"rows": [[1]]}', tool_call_id="c1"),
    ]

    def handler(request):
        seen["messages"] = json.loads(request.content)["messages"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    await openai(handler).complete(history, TOOLS, model="m", max_tokens=50)
    assert seen["messages"][2]["tool_calls"][0]["function"] == {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'}
    assert seen["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": '{"rows": [[1]]}'}


@pytest.mark.parametrize("arguments", ['{"sql": "SELECT', "[1, 2]", "not json at all"])
async def test_malformed_tool_arguments_are_flagged_not_raised(arguments):
    body = {
        "choices": [{"message": {"tool_calls": [{"id": "c", "function": {"name": "run_sql", "arguments": arguments}}]}}]
    }
    r = await openai(lambda _: httpx.Response(200, json=body)).complete(ASK, TOOLS, model="m", max_tokens=50)
    assert r.tool_calls[0].invalid and r.tool_calls[0].arguments == {} and r.tool_calls[0].raw == arguments


async def test_unreadable_body_is_a_retryable_error():
    with pytest.raises(LLMError) as info:
        await openai(lambda _: httpx.Response(200, text="<html>bad gateway</html>")).complete(
            ASK, [], model="m", max_tokens=5
        )
    assert info.value.retryable


async def test_error_text_never_contains_the_key():
    def handler(request):
        return httpx.Response(401, text="invalid key sk-test0000000000000abcdefghij supplied")

    with pytest.raises(LLMError) as info:
        await openai(handler).complete(ASK, [], model="m", max_tokens=5)
    assert "sk-4010" not in str(info.value) and info.value.status == 401 and not info.value.retryable


async def test_anthropic_request_and_response_mapping():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["headers"] = json.loads(request.content), request.headers
        return httpx.Response(
            200,
            json={
                "model": "claude-x",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "toolu_1", "name": "run_sql", "input": {"sql": "SELECT 1"}},
                ],
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 9,
                    "cache_read_input_tokens": 400,
                    "cache_creation_input_tokens": 0,
                },
            },
        )

    history = ASK + [
        Message("assistant", "", [ToolCall("t1", "run_sql", {"sql": "a"}), ToolCall("t2", "run_sql", {"sql": "b"})]),
        Message("tool", "result a", tool_call_id="t1"),
        Message("tool", "result b", tool_call_id="t2"),
    ]
    provider = AnthropicProvider("sk-ant-test", transport=httpx.MockTransport(handler))
    r = await provider.complete(history, TOOLS, model="claude-x", max_tokens=200)

    body = seen["body"]
    assert seen["headers"]["x-api-key"] == "sk-ant-test" and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert body["system"][-1] == {
        "type": "text",
        "text": "You are an agent.",
        "cache_control": {"type": "ephemeral"},
    }
    assert (
        body["tools"][-1]["cache_control"] == {"type": "ephemeral"}
        and body["tools"][0]["input_schema"]["type"] == "object"
    )
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in body["messages"][2]["content"]] == ["t1", "t2"]  # parallel results, one turn
    assert r.text == "Let me check." and r.tool_calls == [ToolCall("toolu_1", "run_sql", {"sql": "SELECT 1"})]
    assert r.usage == Usage(input_tokens=420, output_tokens=9, cached_tokens=400) and r.stop_reason == "tool_use"


def test_cost_counts_cached_input_at_a_tenth():
    # 1,000,000 fresh input at $3 + 1,000,000 cached at $0.30 + 1,000,000 output at $15
    assert float(cost_usd(Usage(2_000_000, 1_000_000, 1_000_000), 3.0, 15.0)) == pytest.approx(18.3)
    assert cost_usd(Usage(0, 0, 0), 3.0, 15.0) == 0


async def test_temperature_zero_is_sent_to_every_provider():
    """Zero is a setting (deterministic output), not 'unset': the adapters used to leave it out of the request."""
    seen = []

    def openai(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=PLAIN)

    def anthropic(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 3, "output_tokens": 1}, "model": "m"})  # fmt: skip

    await OpenAICompatProvider("http://gateway.test/v1", transport=httpx.MockTransport(openai)).complete(
        ASK, [], model="gpt-x", max_tokens=5, temperature=0
    )
    await AnthropicProvider("key", transport=httpx.MockTransport(anthropic)).complete(
        ASK, [], model="claude-x", max_tokens=5, temperature=0
    )
    assert [body["temperature"] for body in seen] == [0, 0]
