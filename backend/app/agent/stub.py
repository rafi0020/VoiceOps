"""A rule-based stand-in for a model (LLM_PROVIDER=stub): enough to run a call end to end with no provider, for the
demo, the journeys and load tests. It reads the last customer turn and the tool results; it is not an evaluation
of anything."""

import json
import re
import uuid

from app.llm.stub import reply
from app.llm.types import LLMResponse, Message, ToolCall, ToolSpec


def _call(name: str, args: dict) -> LLMResponse:
    return reply("", [ToolCall(id=f"stub-{uuid.uuid4().hex[:8]}", name=name, arguments=args)])


def demo_responder(messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
    last = messages[-1]
    if last.role == "tool":
        result = json.loads(last.content or "{}")
        if "error" in result and "not verified" in result["error"]:
            return reply(
                "I need to check who you are first. Please tell me your account number, postcode and date of birth."
            )
        if "error" in result:
            return reply(result["error"].split(". ")[0] + ".")
        if "verified" in result:
            return reply(
                f"Thank you {result['first_name']}, you're verified. How can I help?"
                if result["verified"]
                else result["say"]
            )
        if "bills" in result and result["bills"]:
            b = result["bills"][0]
            return reply(f"Your latest bill, issued {b['issued_on']}, is {b['total']} and it is {b['status']}.")
        if "services" in result and result["services"] and "outages" in result["services"][0]:
            ongoing = [o for s in result["services"] for o in s["outages"] if o["ongoing"]]
            return reply(
                f"There is a known problem in your area: {ongoing[0]['title']}."
                if ongoing
                else "I can't see any outage affecting you."
            )
        if "passages" in result:
            p = (result["passages"] or [{"text": "I don't have a policy on that.", "cite": ""}])[0]
            return reply(f"{p['text'].split('. ')[0]}. {p['cite']}".strip())
        if "ticket_reference" in result:
            return reply(f"I've opened a {result['category']} ticket, reference {result['ticket_reference']}.")
        if "status" in result:
            return reply(
                f"I've applied a credit of {result['amount']}."
                if result["status"] == "applied"
                else "A supervisor needs to approve that credit; I've asked them."
            )
        if result.get("handed_off"):
            return reply("I'm passing you to a colleague who can see everything so far.")
        return reply("Done.")
    if last.content.startswith("[Note from the system"):  # a supervisor's decision on a credit
        return reply(last.content.split("] ", 1)[1].split(". Tell")[0].replace("A supervisor", "My supervisor") + ".")
    text = last.content.lower()
    account = re.search(r"\b(lt|fe)\s*-?\s*(\d{6})\b", text)
    born = re.search(r"\b(\d{1,2} [a-z]+ \d{4}|\d{4}-\d{2}-\d{2})\b", text)
    postcode = re.search(r"\b([a-z]{1,2}\d{1,2}[a-z]?\s*\d[a-z]{2})\b", text)
    if account and born and postcode:
        return _call(
            "verify_identity",
            {
                "account_number": account.group(1) + account.group(2),
                "postcode": postcode.group(1),
                "date_of_birth": born.group(1),
            },
        )
    if re.search(r"\b(person|human|someone|agent|manager)\b", text):
        return _call("hand_off", {"reason": "The caller asked for a person."})
    if re.search(r"\b(down|outage|not working|no internet)\b", text):
        return _call("service_status", {})
    if "bill" in text:
        return _call("recent_bills", {"count": 1})
    if m := re.search(r"credit of (\d+(?:\.\d\d)?)", text):
        return _call("request_credit", {"amount": m.group(1), "reason": "Requested by the caller on the demo line."})
    if re.search(r"\b(ticket|fault|report)\b", text):
        return _call("open_ticket", {"category": "fault", "summary": last.content[:200]})
    if "?" in text or re.search(r"\b(how|what|can i|policy)\b", text):
        return _call("search_policies", {"query": last.content[:200]})
    return reply(
        "I can help with bills, faults, outages and your account. Please tell me your account number, postcode and date of birth first."
    )
