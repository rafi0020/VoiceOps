"use client";

import { Search as SearchIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Page } from "@/components/Shell";
import { Drawer, Empty, ErrorState, Loading, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { day } from "@/lib/format";

interface Doc { slug: string; title: string; updated_at: string }
interface FullDoc extends Doc { body: string }
interface Passage { citation: string; title: string; heading: string; body: string; rank: number }
type Editing = { slug: string; title: string; body: string };

/** The first line of a policy that is not a section heading: what a card shows of the text. */
function firstLine(body: string | undefined): string {
  if (!body) return "";
  return body.split("\n").map((l) => l.trim()).find((l) => l && !l.startsWith("#")) ?? "";
}

/** A policy as a card: title and the first line of its text. Its text is fetched once and shared with the drawer. */
function PolicyCard({ doc, current, onOpen }: { doc: Doc; current: boolean; onOpen: () => void }) {
  const full = useApi<FullDoc>(`/api/knowledge/${doc.slug}`);
  return (
    <button type="button" className="soft-button policy-card" aria-current={current ? "true" : undefined} onClick={onOpen}>
      <span className="policy-card__title">{doc.title}</span>
      <span className="policy-card__line">{firstLine(full.data?.body)}</span>
      <span className="readout">{doc.slug}, updated {day(doc.updated_at)}</span>
    </button>
  );
}

export default function Knowledge() {
  const { user } = useMe();
  const toast = useToast();
  const docs = useApi<{ documents: Doc[] }>("/api/knowledge");
  const [slug, setSlug] = useState<string | null>(null);
  const doc = useApi<FullDoc>(slug ? `/api/knowledge/${slug}` : null);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Passage[] | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setFound((await api<{ passages: Passage[] }>(`/api/knowledge/search?q=${encodeURIComponent(q)}`)).passages);
  };
  const close = () => { setSlug(null); setEditing(null); };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    try {
      const r = await api<{ passages: number }>(`/api/knowledge/${editing.slug}`, { method: "PUT", json: { title: editing.title, body: editing.body } });
      toast(`Saved: ${r.passages} sections the assistant can cite.`, "ok");
      setSlug(editing.slug.toLowerCase());
      setEditing(null);
      await docs.mutate();
      await doc.mutate();
    } catch (err) { toast(err instanceof ApiError ? err.message : "Could not save.", "bad"); }
  };
  const drawerOpen = editing !== null || slug !== null;
  const drawerTitle = editing ? (editing.slug ? "Edit policy" : "New policy") : doc.data?.title ?? "Policy";
  return (
    <Page wide title="Knowledge" lede="The policies the assistant answers from. Each section can be cited as [document §section]."
      actions={user?.role === "admin" && <button className="btn btn--primary" onClick={() => setEditing({ slug: "", title: "", body: "## 1. First section\n" })}>New policy</button>}>
      <form className="ask" onSubmit={search}>
        <div className="search">
          <SearchIcon aria-hidden />
          <input className="input input--search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask the way a customer would, to see what the assistant would find" aria-label="Test a question" />
        </div>
        <button className="btn btn--primary btn--lg">Search</button>
      </form>
      {found && (
        <section className="soft-card" aria-labelledby="found">
          <h2 id="found">What the assistant would read</h2>
          {found.length ? (
            <ul className="plain-list">{found.map((p) => (
              <li key={p.citation} className="passage">
                <span className="passage__cite">{p.citation}</span>
                <strong>{p.heading}</strong>
                <span className="ink-2">{p.body}</span>
              </li>
            ))}</ul>
          ) : <p className="hint">Nothing matches; the assistant would offer a person rather than guess.</p>}
        </section>
      )}
      {docs.error && <ErrorState error={docs.error} retry={() => docs.mutate()} />}
      {docs.isLoading && <div className="panel"><Loading rows={4} /></div>}
      {docs.data && !docs.data.documents.length && <div className="panel"><Empty title="No policies yet">An administrator adds the policies the assistant answers from.</Empty></div>}
      {!!docs.data?.documents.length && (
        <ul className="policy-grid">{docs.data.documents.map((d) => (
          <li key={d.slug}><PolicyCard doc={d} current={slug === d.slug} onOpen={() => { setEditing(null); setSlug(d.slug); }} /></li>
        ))}</ul>
      )}
      {drawerOpen && (
        <Drawer title={drawerTitle} onClose={close}>
          {editing ? (
            <form className="sheet-form" onSubmit={save}>
              <div className="form-grid">
                <label className="field"><span className="label">Short name</span><input className="input" required pattern="[a-z0-9-]+" value={editing.slug} onChange={(e) => setEditing({ ...editing, slug: e.target.value })} /></label>
                <label className="field"><span className="label">Title</span><input className="input" required value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></label>
              </div>
              <label className="field"><span className="label">Text: each section starts with &ldquo;## 1. Heading&rdquo;</span><textarea className="textarea policy" rows={16} value={editing.body} onChange={(e) => setEditing({ ...editing, body: e.target.value })} /></label>
              <div className="page__actions"><button className="btn btn--primary">Save</button><button type="button" className="btn btn--quiet" onClick={() => setEditing(null)}>Cancel</button></div>
            </form>
          ) : doc.error ? (
            <ErrorState error={doc.error} retry={() => doc.mutate()} />
          ) : doc.data ? (
            <article className="reading-text">
              <div className="row-between">
                <span className="readout">{doc.data.slug}, updated {day(doc.data.updated_at)}</span>
                {user?.role === "admin" && <button className="btn btn--sm" onClick={() => setEditing({ slug: doc.data!.slug, title: doc.data!.title, body: doc.data!.body })}>Edit</button>}
              </div>
              <div className="policy">{doc.data.body}</div>
            </article>
          ) : <Loading rows={6} />}
        </Drawer>
      )}
    </Page>
  );
}
