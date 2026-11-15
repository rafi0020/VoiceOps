"""The policies the agent answers from: read by everyone, changed by administrators."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import audit, current_user, require_role
from app.db import tenant_session
from app.knowledge.index import index_document
from app.knowledge.search import search
from app.models.policies import PolicyDocument
from app.security.sessions import Principal

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=10, max_length=100_000)


@router.get("")
async def list_documents(user: Principal = Depends(current_user)) -> dict:
    async with tenant_session(user.org_id) as db:
        docs = (await db.execute(select(PolicyDocument).order_by(PolicyDocument.title))).scalars().all()
    return {"documents": [{"slug": d.slug, "title": d.title, "updated_at": d.updated_at.isoformat()} for d in docs]}


@router.get("/search")
async def search_policies(
    q: str = Query(min_length=2, max_length=500), user: Principal = Depends(current_user)
) -> dict:
    async with tenant_session(user.org_id) as db:
        found = await search(db, q, k=5)
    return {
        "passages": [
            {"citation": p.citation, "title": p.title, "heading": p.heading, "body": p.body, "rank": round(p.rank, 4)}
            for p in found
        ]
    }


@router.get("/{slug}")
async def get_document(slug: str, user: Principal = Depends(current_user)) -> dict:
    async with tenant_session(user.org_id) as db:
        doc = (await db.execute(select(PolicyDocument).where(PolicyDocument.slug == slug))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Policy not found.")
    return {"slug": doc.slug, "title": doc.title, "body": doc.body, "updated_at": doc.updated_at.isoformat()}


@router.put("/{slug}")
async def put_document(
    slug: str, body: DocumentIn, request: Request, admin: Principal = Depends(require_role("admin"))
) -> dict:
    if not slug.replace("-", "").isalnum() or len(slug) > 60:
        raise HTTPException(422, "Use lower-case letters, digits and hyphens for the document's short name.")
    async with tenant_session(admin.org_id) as db:
        try:
            passages = await index_document(db, admin.org_id, slug.lower(), body.title, body.body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        audit(db, admin, "policy.saved", slug, {"passages": passages}, request)
    return {"slug": slug.lower(), "passages": passages}
