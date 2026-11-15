"""Model settings API: administrators only, key write-only, no cross-organisation access, no SSRF."""

import pytest
from sqlalchemy import text

from app.db import tenant_session
from app.llm.factory import load_config
from app.llm.stub import reply

BODY = {
    "provider": "openai_compat",
    "model": "gpt-x",
    "base_url": "http://localhost:20128/v1",
    "api_key": "sk-secret-value-1234567890",
}


async def test_defaults_come_from_the_environment(team):
    body = (await team.admin.get("/api/settings/llm")).json()
    assert body["source"] == "environment" and body["provider"] == "stub" and body["api_key_set"] is False


async def test_only_admins_can_read_or_change_settings(team):
    for client in (team.viewer, team.agent):
        assert (await client.get("/api/settings/llm")).status_code == 403
        assert (await client.put("/api/settings/llm", json=BODY)).status_code == 403


async def test_key_is_stored_encrypted_and_never_returned(team):
    r = await team.admin.put("/api/settings/llm", json=BODY)
    assert r.status_code == 200 and r.json()["api_key_set"] is True and r.json()["source"] == "organisation"
    assert "sk-secret" not in r.text and "sk-secret" not in (await team.admin.get("/api/settings/llm")).text
    async with tenant_session(team.org_id) as db:
        stored = (await db.execute(text("SELECT api_key_enc FROM llm_settings"))).scalar_one()
    assert stored and "sk-secret" not in stored
    assert (await load_config(team.org_id)).api_key == "sk-secret-value-1234567890"
    audit = (await team.admin.get("/api/audit", params={"action": "settings."})).text
    assert "sk-secret" not in audit and "api_key_changed" in audit


async def test_omitting_the_key_keeps_it_and_empty_string_clears_it(team):
    await team.admin.put("/api/settings/llm", json=BODY)
    kept = await team.admin.put(
        "/api/settings/llm", json={k: v for k, v in BODY.items() if k != "api_key"} | {"model": "gpt-y"}
    )
    assert kept.json()["api_key_set"] is True and kept.json()["model"] == "gpt-y"
    cleared = await team.admin.put("/api/settings/llm", json=BODY | {"api_key": ""})
    assert cleared.json()["api_key_set"] is False


async def test_settings_are_private_to_the_organisation(team, other_team):
    await team.admin.put("/api/settings/llm", json=BODY)
    assert (await other_team.admin.get("/api/settings/llm")).json()["source"] == "environment"


async def test_base_urls_the_server_must_not_call_are_refused(team):
    for url in ("http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://example.com", "http://"):
        r = await team.admin.put("/api/settings/llm", json=BODY | {"base_url": url})
        assert r.status_code == 422, url
    assert (await team.admin.put("/api/settings/llm", json=BODY | {"base_url": ""})).status_code == 422


async def test_connection_test_reports_success_and_failure(team, stub_llm):
    stub_llm.script = [reply("ok")]
    assert (await team.admin.post("/api/settings/llm/test")).json()["ok"] is True
    failed = (await team.admin.post("/api/settings/llm/test")).json()  # the script is now empty
    assert failed["ok"] is False and "no more scripted answers" in failed["error"]
    assert (await team.agent.post("/api/settings/llm/test")).status_code == 403


def test_an_unknown_llm_provider_is_a_configuration_error_not_the_stub():
    """A typo in LLM_PROVIDER used to fall back to the stub silently, so a deployment answered with canned replies."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings(llm_provider="opnai")


def test_environment_config_refuses_a_provider_it_does_not_know(monkeypatch):
    from app import config
    from app.llm import factory

    settings = config.Settings()
    settings.llm_provider = "opnai"  # bypasses validation, as a later change would
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        factory.environment_config()


async def test_an_unreadable_saved_key_is_a_clear_error_not_a_crash(team):
    """A key saved under another SECRET_KEY cannot be decrypted: the settings screen still loads, and the model call
    fails with a message an administrator can act on."""
    from app.llm import factory
    from app.llm.base import LLMError

    await team.admin.put("/api/settings/llm", json=BODY)
    async with tenant_session(team.org_id) as db:
        await db.execute(text("UPDATE llm_settings SET api_key_enc = 'not-encrypted-with-this-key'"))
    r = await team.admin.get("/api/settings/llm")
    assert r.status_code == 200 and r.json()["key_unreadable"] is True and r.json()["api_key_set"] is False
    with pytest.raises(LLMError, match="saved model key cannot be read"):
        await factory.get_client(team.org_id)
