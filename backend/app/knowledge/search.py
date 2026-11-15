"""Searching the organisation's policies. PostgreSQL full-text search over passages (title weighs most, then the
section heading, then the text). A spoken question rarely contains every word of the answer, so the question's
words are ORed and the passages ranked by how many and how heavily weighted the matches are; a question sharing
no word with any passage finds nothing rather than something arbitrary. Weights (body 0.4, heading 0.5, title
0.6) keep a document's title from outranking the passage that actually answers."""

import re
from dataclasses import dataclass

from sqlalchemy import text

SEARCH = text("""
    WITH q AS (SELECT replace(websearch_to_tsquery('english', :q)::text, ' & ', ' | ') AS terms)
    SELECT d.slug, p.title, p.section, p.heading, p.body, ts_rank('{0.1, 0.4, 0.5, 0.6}', p.tsv, to_tsquery('english', q.terms)) AS rank
    FROM policy_passages p JOIN policy_documents d ON d.id = p.document_id, q
    WHERE q.terms <> '' AND p.tsv @@ to_tsquery('english', q.terms)
    ORDER BY rank DESC, d.slug, p.section
    LIMIT :k
""")


# How customers say it, and the words the policies use. Lexical search cannot bridge these by itself; the list is
# deliberately small and general (it was written before the held-out retrieval questions, which measure it).
EVERYDAY = {
    r"money back|compensat|reimburs": "compensation",
    r"\bdown\b|not working|stopped working|no (internet|signal|connection)|cut off": "lost outage",
    r"did ?n.t (turn|show) up|no.?show|never (came|arrived)|missed": "missed appointment engineer",
    r"\bcancel": "cancellation cancelling",
    r"instal+ments|spread|pay (it )?(off )?(over|in)|can.?t (afford|pay)|struggl": "payment arrangement",
    r"abroad|holiday|travel+ing|overseas|spain|france|italy|europe": "roaming abroad europe",
    r"twice|double|charged (for|me) .* (again|wrong)|overcharg|wrong(ly)? charged": "billing error charged twice refund",
    r"\bslow\b|speed": "slow speeds",
    r"\bmov(e|ing) (house|home)|new address": "moving home",
    r"who am i|verify|security (check|question)|identity": "identity check",
}


def expand(query: str) -> str:
    lowered = query.lower()
    extra = [terms for pattern, terms in EVERYDAY.items() if re.search(pattern, lowered)]
    return " ".join([query, *extra])


@dataclass(frozen=True)
class Passage:
    doc_slug: str
    title: str
    section: str
    heading: str
    body: str
    rank: float

    @property
    def citation(self) -> str:
        return f"[{self.doc_slug} §{self.section}]"


async def search(db, query: str, k: int = 4) -> list[Passage]:
    rows = (await db.execute(SEARCH, {"q": expand(query[:500]), "k": k})).all()
    return [Passage(r.slug, r.title, r.section, r.heading, r.body, float(r.rank)) for r in rows]
