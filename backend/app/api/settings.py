"""Model provider settings for an organisation (administrators only). The API key is write-only."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import audit, require_role
from app.db import tenant_session
from app.llm.base import LLMError
from app.llm.factory import get_client, load_config, validate_base_url
from app.llm.types import Message
from app.models.llm import LLMSettings
from app.security.crypto import encrypt
from app.security.ratelimit import rate_limit
from app.security.sessions import Principal

router = APIRouter(prefix="/api/settings", tags=["settings"])
log = logging.getLogger("voiceops.settings")


class LLMSettingsIn(BaseModel):
    provider: Literal["openai_compat", "anthropic", "ollama", "stub"]
    model: str = Field(min_length=1, max_length=120)
    base_url: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=400, description="Omit to keep the stored key; '' clears it.")
    fallback_model: str = Field(default="", max_length=120)
    price_input_per_mtok: float = Field(default=3.0, ge=0, le=1000)
    price_output_per_mtok: float = Field(default=15.0, ge=0, le=1000)


async def _view(user: Principal) -> dict:
    c = await load_config(user.org_id)
    return {
        "provider": c.provider, "model": c.model, "base_url": c.base_url, "fallback_model": c.fallback_model,
        "price_input_per_mtok": c.price_in, "price_output_per_mtok": c.price_out,
        "api_key_set": bool(c.api_key), "source": c.source, "key_unreadable": c.key_unreadable,
    }  # fmt: skip


@router.get("/llm")
async def get_llm(admin: Principal = Depends(require_role("admin"))) -> dict:
    return await _view(admin)


@router.put("/llm")
async def put_llm(body: LLMSettingsIn, request: Request, admin: Principal = Depends(require_role("admin"))) -> dict:
    if body.provider == "openai_compat" and not body.base_url:
        raise HTTPException(422, "An OpenAI-compatible provider needs a base URL.")
    if body.base_url:
        try:
            await asyncio.to_thread(validate_base_url, body.base_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    async with tenant_session(admin.org_id) as db:
        row = await db.get(LLMSettings, admin.org_id)
        if row is None:
            row = LLMSettings(org_id=admin.org_id, provider=body.provider, model=body.model)
            db.add(row)
        row.provider, row.model, row.base_url = body.provider, body.model.strip(), body.base_url.strip()
        row.fallback_model = body.fallback_model.strip()
        row.price_input_per_mtok, row.price_output_per_mtok = body.price_input_per_mtok, body.price_output_per_mtok
        row.updated_by = admin.id
        if body.api_key is not None:
            row.api_key_enc = encrypt(body.api_key) if body.api_key else ""
        audit(
            db,
            admin,
            "settings.llm_updated",
            detail=body.model_dump(exclude={"api_key"}) | {"api_key_changed": body.api_key is not None},
            request=request,
        )
    return await _view(admin)


@router.post("/llm/test", dependencies=[Depends(rate_limit("llm_test", 6, 60))])
async def test_llm(admin: Principal = Depends(require_role("admin"))) -> dict:
    """Send one tiny request with the saved settings and report whether it worked."""
    try:
        client = await get_client(admin.org_id)
        response, _ = await client.complete([Message("user", "Reply with the single word: ok")], [], max_tokens=16)
    except (LLMError, ValueError) as exc:
        log.info("llm test failed", extra={"error": str(exc)})
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True, "model": response.model, "latency_ms": response.latency_ms, "reply": response.text[:80]}
