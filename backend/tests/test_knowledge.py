"""Policy search: a customer's question finds the passage that answers it, citable by document and section."""

import pytest

from app.db import tenant_session

CASES = [
    ("how much do I get if the engineer did not turn up", "outages-and-compensation", "3"),
    ("can I pay my overdue bill in instalments", "billing-and-payments", "3"),
    ("what does it cost to use my phone in Spain", "roaming", "1"),
    ("I want to cancel my contract early, is there a fee", "contracts-and-cancellation", "2"),
    ("my broadband has been down for three days, do I get money back", "outages-and-compensation", "2"),
    ("I was charged twice for the same thing", "credits-and-refunds", "2"),
]


@pytest.mark.parametrize(("question", "slug", "section"), CASES)
async def test_a_question_finds_the_passage_that_answers_it(demo, question, slug, section):
    from app.knowledge.search import search
    from seed.demo_users import LARKSPUR

    async with tenant_session(LARKSPUR) as db:
        found = await search(db, question, k=3)
    assert (slug, section) in [(p.doc_slug, p.section) for p in found], [p.citation for p in found]
    assert found[0].citation.startswith("[") and "§" in found[0].citation


async def test_another_organisations_policies_never_appear(demo):
    from app.knowledge.search import search
    from seed.demo_users import FERNHILL

    async with tenant_session(FERNHILL) as db:
        found = await search(db, "roaming charges abroad engineer appointment", k=5)
    assert all(p.doc_slug != "roaming" and p.doc_slug != "engineer-visits" for p in found)


async def test_a_question_with_no_matching_words_returns_nothing_rather_than_noise(demo):
    from app.knowledge.search import search
    from seed.demo_users import LARKSPUR

    async with tenant_session(LARKSPUR) as db:
        assert await search(db, "xylophone quantum zebra", k=3) == []


async def test_an_administrator_adds_a_policy_and_it_is_found_at_once(team):
    body = (
        "## 1. Pets\nAssistance dogs are welcome in our shops at all times.\n\n## 2. Opening hours\nShops open at nine."
    )
    assert (await team.agent.put("/api/knowledge/shops", json={"title": "Shops", "body": body})).status_code == 403
    saved = await team.admin.put("/api/knowledge/shops", json={"title": "Shops", "body": body})
    assert saved.status_code == 200 and saved.json()["passages"] == 2
    found = (await team.viewer.get("/api/knowledge/search", params={"q": "can I bring my assistance dog"})).json()[
        "passages"
    ]
    assert found[0]["citation"] == "[shops §1]"
    bad = await team.admin.put(
        "/api/knowledge/shops", json={"title": "Shops", "body": "No headings in this text at all."}
    )
    assert bad.status_code == 422
