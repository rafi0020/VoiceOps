"""The rule-based demo model used when no provider is configured (and by the browser journeys)."""

import json

from app.agent.stub import demo_responder
from app.llm.types import Message


def test_a_refusal_for_an_unverified_caller_asks_for_their_details():
    refused = {
        "error": "The caller is not verified yet. Ask for the account number or phone number, the postcode and the date of birth, then call verify_identity."
    }
    answer = demo_responder(
        [Message("user", "What's my latest bill?"), Message("tool", json.dumps(refused), [], "t1")], []
    )
    assert "account number" in answer.text and "postcode" in answer.text and "verify_identity" not in answer.text
