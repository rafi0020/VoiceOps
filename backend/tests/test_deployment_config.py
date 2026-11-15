"""Every setting an operator is told about in .env.example reaches the containers.

Found by the final review: Compose substitutes only the variables docker-compose.yml names, so a setting written
in .env but missing there (ALLOW_PRIVATE_TARGETS, METRICS_TOKEN, the judge thresholds...) silently did nothing."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_documented_setting_is_passed_to_the_containers():
    names = re.findall(r"^([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.MULTILINE)
    compose = (ROOT / "docker-compose.yml").read_text()
    missing = [n for n in names if "${" + n not in compose]
    assert not missing, f"in .env.example but not passed through by docker-compose.yml: {missing}"
    for hardening in (
        "METRICS_TOKEN",
        "ORG_MAX_LIVE_CALLS",
        "ALLOW_PRIVATE_LLM_URLS",
        "GLOBAL_DAILY_COST_USD",
        "CREDIT_LIMIT",
        "CALL_MAX_MINUTES",
    ):
        assert hardening in names, f"{hardening} is a setting operators need; document it in .env.example"


def test_every_published_port_is_bound_to_this_machine_unless_the_operator_says_otherwise():
    """The site is plain HTTP; on another interface it would serve sign-in over the network unencrypted."""
    compose = (ROOT / "docker-compose.yml").read_text()
    for spec in re.findall(r'ports: \["([^"]+)"\]', compose):
        assert spec.startswith(("127.0.0.1:", "${WEB_BIND:-127.0.0.1}:")), spec
