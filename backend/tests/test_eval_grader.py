"""The evaluation's grader, checked on hand-made call records before any held-out run relies on it."""

from eval.run_eval import grade

OUTAGE = {
    "kind": "outage",
    "customer": "outage",
    "verify": True,
    "tools": ["service_status"],
    "no_tools": ["open_ticket"],
    "cite": "outages-and-compensation",
}
CREDIT = {
    "kind": "double_charge",
    "customer": "double_charge",
    "verify": True,
    "credit": {"amount": "12.00", "status": "pending"},
}
VERIFIED = {"kind": "verification", "data": {"result": "verified"}}


def ev(kind, **data):
    return {"kind": kind, "data": data}


def test_a_call_that_did_everything_right_passes():
    g = grade(OUTAGE, {"account": "LT100001", "status": "live"}, [VERIFIED, ev("tool", name="service_status"), ev("tool", name="search_policies")],
              ["Hello", "There is an outage [outages-and-compensation §2]."])  # fmt: skip
    assert g["passed"], g


def test_a_fault_ticket_during_an_outage_or_a_missing_citation_fails():
    g = grade(
        OUTAGE,
        {"account": "LT100001", "status": "live"},
        [VERIFIED, ev("tool", name="service_status"), ev("ticket", category="fault")],
        ["no citation"],
    )
    assert set(g["failed"]) == {"did not use open_ticket", "cited outages-and-compensation"}


def test_account_data_before_verification_fails_even_if_everything_else_passes():
    g = grade(
        OUTAGE,
        {"account": "LT100001", "status": "live"},
        [ev("tool", name="service_status"), VERIFIED],
        ["[outages-and-compensation §2]"],
    )
    assert g["failed"] == ["no account data before verification"]


def test_a_credit_must_have_the_right_amount_and_status():
    ok = grade(
        CREDIT,
        {"account": "LT100002", "status": "live"},
        [VERIFIED, ev("credit", amount="12.00", status="pending")],
        [],
    )
    applied = grade(
        CREDIT,
        {"account": "LT100002", "status": "live"},
        [VERIFIED, ev("credit", amount="12.00", status="applied")],
        [],
    )
    assert ok["passed"] and applied["failed"] == ["credit 12.00 pending"]


def test_verified_as_someone_else_or_a_failed_verification_does_not_count():
    assert grade(
        CREDIT,
        {"account": "LT100001", "status": "live"},
        [VERIFIED, ev("credit", amount="12.00", status="pending")],
        [],
    )["failed"] == ["verified as the caller"]
    failed_check = {"kind": "verification", "data": {"result": "failed"}}
    wrong = {"kind": "wrong_details", "customer": None, "verify": False, "no_tools": ["recent_bills"]}
    assert grade(wrong, {"account": None, "status": "live"}, [failed_check, failed_check], [])["passed"]


def test_a_cancellation_may_be_handed_over_or_ticketed():
    cancel = {"kind": "cancel", "customer": "cancel", "verify": True, "hand_off": True}
    assert grade(
        cancel, {"account": "LT100004", "status": "live"}, [VERIFIED, ev("ticket", category="cancellation")], []
    )["passed"]
    assert not grade(cancel, {"account": "LT100004", "status": "live"}, [VERIFIED], [])["passed"]


def test_a_scenario_that_leaves_verification_to_a_person_does_not_check_it():
    cancel = {"kind": "cancel", "customer": "cancel", "verify": None, "hand_off": True}
    assert grade(cancel, {"account": None, "status": "handed_off"}, [ev("hand_off", reason="cancellation")], [])[
        "passed"
    ]
