"""Policy retrieval on questions written after the search was tuned (tests/test_knowledge.py holds the six it was
tuned on). Recall at 3: the passage that answers is among the first three found.

    python -m eval.run_retrieval            # against the database in DATABASE_URL (Larkspur's policies)
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.db import dispose_engines, tenant_session
from app.knowledge.search import search
from app.redis import close_redis
from seed.demo_users import LARKSPUR

HERE = Path(__file__).parent
QUESTIONS = [
    ("What details do you need before you can talk about my account?", "identity-and-privacy", "1"),
    ("I got my date of birth wrong three times, what now?", "identity-and-privacy", "2"),
    ("Can my wife ring up about my bill for me?", "identity-and-privacy", "3"),
    ("How do I find out if there's an outage near me?", "outages-and-compensation", "1"),
    ("Do you pay anything back if my internet is off for a week?", "outages-and-compensation", "2"),
    ("The technician cancelled on the morning of the visit, is that worth anything?", "outages-and-compensation", "3"),
    ("Can the person on the phone give me a goodwill gesture?", "credits-and-refunds", "1"),
    ("You billed me for a service I already cancelled, will I get it back?", "credits-and-refunds", "2"),
    ("Can you put the refund into my bank instead of my account?", "credits-and-refunds", "3"),
    ("When do my bills come out each month?", "billing-and-payments", "1"),
    ("What's the fee if I pay late?", "billing-and-payments", "2"),
    ("I've lost my job, can I pay off my balance bit by bit?", "billing-and-payments", "3"),
    ("What should I try before you send someone about my broadband?", "broadband-faults", "1"),
    ("How quickly will the network team look at my fault?", "broadband-faults", "2"),
    ("My speed is never what you promised, can I leave without paying?", "broadband-faults", "3"),
    ("How much notice do you need before I move?", "moving-home", "1"),
    ("What if you don't cover my new street?", "moving-home", "2"),
    ("I'm moving for the second time this year, does that cost anything?", "moving-home", "3"),
    ("How long is a mobile contract?", "contracts-and-cancellation", "1"),
    ("I changed my mind a week after signing up, can I get out?", "contracts-and-cancellation", "2"),
    ("My minimum term is over, how do I leave?", "contracts-and-cancellation", "3"),
    ("How much per day to use my plan in Portugal?", "roaming", "1"),
    ("I'm going to Thailand, what will data cost?", "roaming", "2"),
    ("How do I make a complaint?", "complaints", "1"),
    ("You haven't sorted my complaint in two months, who else can I go to?", "complaints", "2"),
    ("I have a disability, can you keep a note of that?", "vulnerable-customers", "1"),
    ("My dad has a medical alarm on his line and it's broken", "vulnerable-customers", "2"),
    ("What time slots can an engineer come?", "engineer-visits", "1"),
    ("Will I be charged if the engineer finds the problem is my own wiring?", "engineer-visits", "2"),
    ("When will you transfer me to a human?", "handing-over", "1"),
    ("Will the person you pass me to know what I've already said?", "handing-over", "2"),
    ("Is there a charge for roaming in Germany?", "roaming", "1"),
    ("Can I get compensation for no service?", "outages-and-compensation", "2"),
    ("I was overcharged on my bill", "credits-and-refunds", "2"),
    ("Will you cut me off if I can't pay?", "billing-and-payments", "2"),
    ("Do I need to be home when the engineer comes?", "engineer-visits", "1"),
]


async def main() -> None:
    rows, hits = [], 0
    async with tenant_session(LARKSPUR) as db:
        for question, slug, section in QUESTIONS:
            found = await search(db, question, k=3)
            hit = (slug, section) in [(p.doc_slug, p.section) for p in found]
            hits += hit
            rows.append(
                {
                    "question": question,
                    "expected": f"[{slug} §{section}]",
                    "found": [p.citation for p in found],
                    "hit": hit,
                }
            )
            print(f"  {'HIT ' if hit else 'MISS'} {question[:60]:<60} {[p.citation for p in found]}")
    result = {"name": "retrieval", "at": datetime.now(UTC).isoformat(timespec="seconds"), "n": len(QUESTIONS), "recall_at_3": round(hits / len(QUESTIONS), 4),
              "questions": rows}  # fmt: skip
    print(f"recall at 3: {result['recall_at_3']}")
    (HERE / "results" / "retrieval.json").write_text(json.dumps(result, indent=1))
    await close_redis()
    await dispose_engines()


if __name__ == "__main__":
    asyncio.run(main())
