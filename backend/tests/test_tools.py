"""The agent's tools: identity checked by the server, account data only for the verified caller, credits within the
limit, and nothing from another organisation."""

from datetime import date

import pytest

from app.agent.tools import CallContext, run_tool, spoken_code, spoken_date
from tests.conftest import rows


async def new_call(org) -> CallContext:
    (call_id,) = (await rows(org, "INSERT INTO calls (org_id) VALUES (:o) RETURNING id", o=org))[0]
    return CallContext(org_id=org, call_id=call_id)


AMELIA = {"account_number": "LT100001", "postcode": "NG4 2AB", "date_of_birth": "14 March 1985"}


@pytest.mark.parametrize(
    ("said", "code"),
    [("L T one zero zero zero zero one", "LT100001"), ("lt-100 001", "LT100001"), ("double seven oh", "770")],
)
def test_codes_are_read_the_way_people_say_them(said, code):
    assert spoken_code(said) == code


@pytest.mark.parametrize(
    "said",
    [
        "1985-03-14",
        "14/03/1985",
        "14 March 1985",
        "March 14th, 1985",
        "the fourteenth of March 1985",
        "March the fourteenth, nineteen eighty five",
    ],
)
def test_dates_are_read_the_way_people_say_them(said):
    assert spoken_date(said) == date(1985, 3, 14)


async def test_account_data_needs_a_verified_caller_and_then_is_that_callers(demo):
    from seed.demo_users import LARKSPUR

    ctx = await new_call(LARKSPUR)
    assert "not verified" in (await run_tool(ctx, "recent_bills", {}))["error"]
    spoken = {
        "account_number": "L T one zero zero zero zero one",
        "postcode": "N G four two A B",
        "date_of_birth": "March 14th 1985",
    }
    assert (await run_tool(ctx, "verify_identity", spoken)) == {"verified": True, "first_name": "Amelia"}
    overview = await run_tool(ctx, "account_overview", {})
    assert overview["account_number"] == "LT100001" and overview["services"][0]["plan"] == "Fibre 150"
    status = await run_tool(ctx, "service_status", {})
    assert status["services"][0]["outages"][0]["ongoing"] is True


async def test_three_wrong_attempts_lock_verification_and_give_no_hint(demo):
    from seed.demo_users import LARKSPUR

    ctx = await new_call(LARKSPUR)
    for left in (2, 1, 0):
        r = await run_tool(ctx, "verify_identity", AMELIA | {"date_of_birth": "1 January 1980"})
        assert r["verified"] is False and r["attempts_left"] == left and "date" not in r["say"].lower()
    locked = await run_tool(ctx, "verify_identity", AMELIA)
    assert "locked" in locked["error"]
    assert (await rows(LARKSPUR, "SELECT verified_customer_id FROM calls WHERE id = :c", c=ctx.call_id))[0][0] is None


async def test_a_verified_call_cannot_switch_to_another_account(demo):
    from seed.demo_users import LARKSPUR

    ctx = await new_call(LARKSPUR)
    await run_tool(ctx, "verify_identity", AMELIA)
    tom = {"account_number": "LT100002", "postcode": "LS6 3HJ", "date_of_birth": "2 November 1979"}
    assert "already verified" in (await run_tool(ctx, "verify_identity", tom))["error"]


async def test_credits_up_to_the_limit_per_call_apply_and_beyond_wait_for_a_supervisor(demo):
    from seed.demo_users import LARKSPUR

    ctx = await new_call(LARKSPUR)
    await run_tool(ctx, "verify_identity", AMELIA)
    assert (await run_tool(ctx, "request_credit", {"amount": "6.00", "reason": "Outage goodwill"}))[
        "status"
    ] == "applied"
    second = await run_tool(ctx, "request_credit", {"amount": "£6.00", "reason": "More goodwill"})
    assert second["status"] == "needs_approval"  # 12.00 in one call is over the 10.00 limit
    statuses = await rows(
        LARKSPUR, "SELECT status FROM credits WHERE call_id = :c ORDER BY requested_at", c=ctx.call_id
    )
    assert [s[0] for s in statuses] == ["applied", "pending"]
    assert "error" in await run_tool(ctx, "request_credit", {"amount": "ten pounds", "reason": "Bad amount"})


async def test_another_organisations_customer_cannot_be_verified(demo):
    from seed.demo_users import FERNHILL

    ctx = await new_call(FERNHILL)
    assert (await run_tool(ctx, "verify_identity", AMELIA))["verified"] is False


async def test_tickets_hand_off_and_bad_arguments(demo):
    from seed.demo_users import LARKSPUR

    ctx = await new_call(LARKSPUR)
    await run_tool(
        ctx, "verify_identity", {"phone": "07700 900 003", "postcode": "M14 5RT", "date_of_birth": "21/07/1992"}
    )
    ticket = await run_tool(
        ctx, "open_ticket", {"category": "fault", "summary": "Broadband down since this morning, router restarted"}
    )
    assert len(ticket["ticket_reference"]) == 8
    assert (
        "Invalid arguments" in (await run_tool(ctx, "open_ticket", {"category": "teleport", "summary": "x"}))["error"]
    )
    assert (await run_tool(ctx, "hand_off", {"reason": "Customer asked for a person"}))["handed_off"] is True
    assert (await rows(LARKSPUR, "SELECT status FROM calls WHERE id = :c", c=ctx.call_id))[0][0] == "handed_off"


async def test_an_administrator_changes_the_credit_limit_and_the_agent_follows_it(team):
    from tests.test_calls_api import ME, customer

    await customer(team)
    assert (await team.supervisor.put("/api/call-settings", json={"credit_limit": "25.00"})).status_code == 403
    assert (await team.admin.put("/api/call-settings", json={"credit_limit": "25.00"})).json() == {
        "credit_limit": "25.00"
    }
    ctx = await new_call(team.org_id)
    await run_tool(ctx, "verify_identity", ME)
    assert (await run_tool(ctx, "request_credit", {"amount": "20.00", "reason": "Within the new limit"}))[
        "status"
    ] == "applied"


async def _jo(team):
    from tests.test_calls_api import customer

    await customer(team)
    return {"account_number": "AB123456", "postcode": "ZZ1 1ZZ", "date_of_birth": "1 February 1990"}


async def test_failed_checks_on_one_account_add_up_across_calls_and_then_lock_it(team):
    """Found by the final review: three attempts per call, ten calls a minute, was thirty guesses a minute."""
    jo = await _jo(team)
    for _ in range(5):
        result = await run_tool(
            await new_call(team.org_id), "verify_identity", jo | {"date_of_birth": "2 February 1990"}
        )
        assert result["verified"] is False
    locked = await run_tool(await new_call(team.org_id), "verify_identity", jo)
    assert "error" in locked and "too many" in locked["error"].lower()


async def test_credits_without_a_supervisor_are_capped_per_customer_over_thirty_days(team):
    jo = await _jo(team)
    for _ in range(2):
        ctx = await new_call(team.org_id)
        await run_tool(ctx, "verify_identity", jo)
        assert (await run_tool(ctx, "request_credit", {"amount": "10.00", "reason": "Goodwill"}))["status"] == "applied"
    ctx = await new_call(team.org_id)
    await run_tool(ctx, "verify_identity", jo)
    third = await run_tool(ctx, "request_credit", {"amount": "10.00", "reason": "Goodwill again"})
    assert third["status"] == "needs_approval"  # 30.00 in thirty days is over the 25.00 the agent may give alone


async def test_tools_that_change_the_account_refuse_once_a_person_has_the_call(team):
    jo = await _jo(team)
    ctx = await new_call(team.org_id)
    await run_tool(ctx, "verify_identity", jo)
    await rows(team.org_id, "UPDATE calls SET status = 'handed_off' WHERE id = :c RETURNING 1", c=ctx.call_id)
    for name, args in (("request_credit", {"amount": "5.00", "reason": "Goodwill"}),
                       ("open_ticket", {"category": "fault", "summary": "No service at all"})):  # fmt: skip
        assert "error" in await run_tool(ctx, name, args)
    assert await rows(team.org_id, "SELECT 1 FROM credits WHERE call_id = :c", c=ctx.call_id) == []


async def test_a_phone_number_shared_by_two_accounts_is_not_a_way_in(team):
    """Phone numbers are not unique. The lookup used to take the first account with the number; now a shared number
    cannot verify anyone, and the refusal is not counted as a failed check."""
    for account, name, born in (("LT555001", "Pat One", "1980-01-02"), ("LT555002", "Pat Two", "1981-03-04")):
        await rows(
            team.org_id,
            "INSERT INTO customers (org_id, account_number, name, phone, postcode, date_of_birth) "
            "VALUES (:o, :a, :n, '07111222333', 'M14 5RT', :d) RETURNING 1",
            o=team.org_id, a=account, n=name, d=born,
        )  # fmt: skip
    ctx = await new_call(team.org_id)
    by_phone = {"phone": "07111 222 333", "postcode": "M14 5RT", "date_of_birth": "2 January 1980"}
    result = await run_tool(ctx, "verify_identity", by_phone)
    assert result.get("verified") is not True
    assert "account number" in result["say"]
    counted = await rows(team.org_id, "SELECT verification_failures FROM calls WHERE id = :c", c=ctx.call_id)
    assert counted[0][0] == 0
    by_account = {"account_number": "LT555001", "postcode": "M14 5RT", "date_of_birth": "2 January 1980"}
    assert (await run_tool(ctx, "verify_identity", by_account)) == {"verified": True, "first_name": "Pat"}
