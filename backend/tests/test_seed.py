"""Demo data: both organisations, the planted customers with their details, policies split into citable passages."""

from tests.conftest import rows


async def test_demo_data_has_the_planted_customers_bills_outages_and_policies(demo):
    from seed.demo_users import FERNHILL, LARKSPUR
    from seed.generate import PLANTED

    accounts = {r[0] for r in await rows(LARKSPUR, "SELECT account_number FROM customers")}
    assert {p.account_number for p in PLANTED.values()} <= accounts and len(accounts) == 20 + len(PLANTED)
    double = await rows(
        LARKSPUR,
        """SELECT count(*) FROM bill_lines l JOIN bills b ON b.id = l.bill_id JOIN customers c ON c.id = b.customer_id
                                    WHERE c.account_number = 'LT100002' AND l.description = 'Sports add-on'""",
    )
    assert double[0][0] == 2
    live = await rows(LARKSPUR, "SELECT area FROM outages WHERE resolved_at IS NULL")
    assert [r[0] for r in live] == ["NG4"]
    passages = await rows(
        LARKSPUR,
        "SELECT p.section, p.heading FROM policy_passages p JOIN policy_documents d ON d.id = p.document_id WHERE d.slug = 'credits-and-refunds'",
    )
    assert ("1", "Goodwill credits") in [tuple(r) for r in passages]
    assert not await rows(FERNHILL, "SELECT 1 FROM customers WHERE account_number LIKE 'LT%'")
