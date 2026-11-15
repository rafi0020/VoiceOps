"""Storing a policy document and splitting it into citable passages (`## n. Heading` sections)."""

from sqlalchemy import delete, select

from app.models.policies import PolicyDocument, PolicyPassage


def sections(body: str) -> list[tuple[str, str, str]]:
    """(section number, heading, text) for each `## n. Heading` block."""
    out = []
    for block in body.strip().split("## ")[1:]:
        head, _, text = block.partition("\n")
        number, _, heading = head.partition(". ")
        out.append((number.strip(), heading.strip(), " ".join(text.split())))
    return out


async def index_document(db, org_id, slug: str, title: str, body: str) -> int:
    """Create or replace a document; its passages are rebuilt. Returns the number of passages."""
    parts = sections(body)
    if not parts:
        raise ValueError("A policy needs at least one section heading, written as '## 1. Heading'.")
    doc = (await db.execute(select(PolicyDocument).where(PolicyDocument.slug == slug))).scalar_one_or_none()
    if doc is None:
        doc = PolicyDocument(org_id=org_id, slug=slug, title=title, body=body.strip())
        db.add(doc)
        await db.flush()
    else:
        doc.title, doc.body = title, body.strip()
        await db.execute(delete(PolicyPassage).where(PolicyPassage.document_id == doc.id))
    for number, heading, text in parts:
        db.add(
            PolicyPassage(org_id=org_id, document_id=doc.id, section=number, title=title, heading=heading, body=text)
        )
    await db.flush()
    return len(parts)
