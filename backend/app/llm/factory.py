"""Chooses the model provider for an organisation: its saved settings if any, otherwise the environment."""

import asyncio
import hashlib
import importlib
import ipaddress
import socket
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from app.config import LLM_PROVIDERS, get_settings
from app.db import tenant_session
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMError, LLMProvider, call_with_retry
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.pricing import cost_usd
from app.llm.stub import StubProvider
from app.llm.types import LLMResponse, Message, ToolSpec
from app.models.llm import LLMSettings
from app.security.crypto import decrypt

PROVIDERS = LLM_PROVIDERS
OLLAMA_DEFAULT = "http://localhost:11434/v1"


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    fallback_model: str = ""
    price_in: float = 3.0
    price_out: float = 15.0
    source: str = "environment"
    key_unreadable: bool = False  # saved under another SECRET_KEY: the key must be saved again


@dataclass
class LLMClient:
    """A provider bound to one organisation's model, fallback and prices."""

    provider: LLMProvider
    config: LLMConfig

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], max_tokens: int | None = None, temperature: float = 0.0
    ) -> tuple[LLMResponse, Decimal]:
        response = await call_with_retry(
            self.provider,
            messages,
            tools,
            model=self.config.model,
            max_tokens=max_tokens or get_settings().llm_max_output_tokens,
            fallback_model=self.config.fallback_model or None,
            temperature=temperature,
        )
        return response, cost_usd(response.usage, self.config.price_in, self.config.price_out)


def validate_base_url(url: str) -> None:
    """Refuse URLs the server should not be made to call. Raises ValueError with the reason."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Base URL must start with http:// or https:// and include a host.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("Base URL host cannot be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:  # includes cloud metadata 169.254.169.254
            raise ValueError("Base URL points to an address that is not allowed.")
        if not get_settings().allow_private_llm_urls and (ip.is_private or ip.is_loopback):
            raise ValueError("Base URLs on private networks are disabled on this deployment.")


_providers: dict[str, LLMProvider] = {}
_override: LLMProvider | None = None


def set_override(provider: LLMProvider | None) -> None:
    """Tests and load runs swap in a stub for every organisation."""
    global _override
    _override = provider


def overridden() -> bool:
    """Whether tests or a load run have replaced the model for everyone."""
    return _override is not None


def build_provider(config: LLMConfig) -> LLMProvider:
    """One provider instance (and so one HTTP connection pool) per distinct endpoint and key."""
    fingerprint = hashlib.sha256(f"{config.provider}|{config.base_url}|{config.api_key}".encode()).hexdigest()
    if fingerprint not in _providers:
        if config.provider == "anthropic":
            _providers[fingerprint] = AnthropicProvider(config.api_key, config.base_url)
        elif config.provider == "ollama":
            _providers[fingerprint] = OpenAICompatProvider(config.base_url or OLLAMA_DEFAULT, config.api_key)
        elif config.provider == "openai_compat":
            if not config.base_url:
                raise ValueError("LLM_BASE_URL is required for an OpenAI-compatible provider.")
            _providers[fingerprint] = OpenAICompatProvider(config.base_url, config.api_key)
        else:
            module, _, attribute = get_settings().stub_responder.partition(":")
            _providers[fingerprint] = StubProvider(responder=getattr(importlib.import_module(module), attribute))
    return _providers[fingerprint]


def environment_config() -> LLMConfig:
    s = get_settings()
    if s.llm_provider not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}; got {s.llm_provider!r}")
    return LLMConfig(
        provider=s.llm_provider,
        model=s.llm_model or "stub",
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        fallback_model=s.llm_fallback_model,
        price_in=s.llm_price_input_per_mtok,
        price_out=s.llm_price_output_per_mtok,
    )


async def load_config(org_id: UUID) -> LLMConfig:
    async with tenant_session(org_id) as db:
        row = await db.get(LLMSettings, org_id)
    if row is None:
        return environment_config()
    return LLMConfig(
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        api_key=_read_key(row.api_key_enc),
        fallback_model=row.fallback_model,
        price_in=float(row.price_input_per_mtok),
        price_out=float(row.price_output_per_mtok),
        source="organisation",
        key_unreadable=bool(row.api_key_enc) and not _key_readable(row.api_key_enc),
    )


def _key_readable(stored: str) -> bool:
    try:
        decrypt(stored)
    except ValueError:
        return False
    return True


def _read_key(stored: str | None) -> str:
    if not stored:
        return ""
    try:
        return decrypt(stored)
    except ValueError:
        return ""  # reported as key_unreadable; never a crash on the settings screen or in a call


async def get_client(org_id: UUID) -> LLMClient:
    config = await load_config(org_id)
    if config.key_unreadable:
        raise LLMError(
            "The saved model key cannot be read with this deployment's SECRET_KEY; an administrator must save the key again.",
            retryable=False,
        )
    if _override is not None:
        return LLMClient(_override, config)
    if config.base_url:
        await asyncio.to_thread(validate_base_url, config.base_url)
    return LLMClient(build_provider(config), config)
