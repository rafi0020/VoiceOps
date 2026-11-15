"""Real calls through the local 9Router gateway. Skipped when no key is configured."""

import os

import pytest

from app.llm.openai_compat import OpenAICompatProvider
from app.llm.types import Message, ToolSpec

pytestmark = pytest.mark.live
TOOLS = [
    ToolSpec(
        "run_sql",
        "Run one read-only SQL query against the analytics schema.",
        {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    )
]
ASK = [
    Message("system", "You answer finance questions by calling run_sql. Table order_lines(region, revenue_usd)."),
    Message("user", "What is total revenue for the West region?"),
]


@pytest.mark.parametrize("model", ["cx/gpt-6-luna", "cc/claude-sonnet-5-5", "ag/gemini-3.8-flash"])
async def test_gateway_models_return_a_tool_call(model):
    provider = OpenAICompatProvider(os.environ["NINEROUTER_BASE_URL"], os.environ["NINEROUTER_API_KEY"])
    r = await provider.complete(ASK, TOOLS, model=model, max_tokens=400)
    assert r.tool_calls and r.tool_calls[0].name == "run_sql" and not r.tool_calls[0].invalid
    assert "west" in r.tool_calls[0].arguments["sql"].lower()
    assert r.usage.input_tokens > 0
