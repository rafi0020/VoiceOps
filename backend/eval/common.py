"""Shared by the evaluation scripts: the model under test, and placing a scripted call."""

import os
import time
from uuid import UUID

from sqlalchemy import select

from app.calls import service
from app.config import get_settings
from app.db import tenant_session
from app.llm import factory
from app.llm.openai_compat import OpenAICompatProvider
from app.models.identity import User


def configure_model(model: str) -> None:
    """Every model call goes to `model` through an OpenAI-compatible endpoint: EVAL_BASE_URL / EVAL_API_KEY, or the
    local gateway's NINEROUTER_BASE_URL / NINEROUTER_API_KEY. Whatever an organisation saved is ignored."""
    base = os.environ.get("EVAL_BASE_URL") or os.environ["NINEROUTER_BASE_URL"]
    key = os.environ.get("EVAL_API_KEY") or os.environ["NINEROUTER_API_KEY"]
    settings = get_settings()
    settings.llm_provider, settings.llm_model = "openai_compat", model
    settings.org_daily_cost_usd, settings.call_max_cost_usd, settings.global_daily_cost_usd = 10_000.0, 50.0, 10_000.0
    settings.org_max_live_calls = 1000
    factory.set_override(OpenAICompatProvider(base, key))

    async def evaluation_config(org_id):
        return factory.environment_config()

    factory.load_config = evaluation_config


async def demo_user(org: UUID, role: str = "agent") -> UUID:
    async with tenant_session(org) as db:
        return (await db.execute(select(User.id).where(User.role == role).limit(1))).scalar_one()


async def place_call(org: UUID, user: UUID, turns: list[str]) -> tuple[UUID, list[str], float]:
    """Run a call turn by turn through the real service and graph; returns the call, the agent's replies, seconds."""
    call, greeting = await service.start_call(org, user, "text")
    replies, started = [greeting], time.perf_counter()
    for said in turns:
        result = await service.customer_turn(org, call.id, said)
        replies.append(result["reply"])
    seconds = time.perf_counter() - started
    await service.end_call(org, call.id)  # the CRM note is written by the model under test too
    return call.id, replies, seconds
