"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Page } from "@/components/Shell";
import { Transcript } from "@/components/Transcript";
import { Drawer, Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { when } from "@/lib/format";
import { follow } from "@/lib/sse";
import type { Call, CallDetail } from "@/lib/types";

const STATE = { live: "With the assistant", handed_off: "With a person", ended: "Ended" } as const;

/** One call, watched and taken over. It lives in the drawer, so the grid of calls stays in view. */
function LiveCall({ id }: { id: string }) {
  const { user } = useMe();
  const toast = useToast();
  const call = useApi<CallDetail>(`/api/calls/${id}`);
  const [reply, setReply] = useState("");
  useEffect(() => follow(`/api/calls/${id}/events`, () => void call.mutate(), ["turn", "turn_interrupted", "call_state", "call_ended", "approval_needed"]), [id, call]);
  if (call.error) return <ErrorState error={call.error} retry={() => call.mutate()} />;
  if (!call.data) return <Loading rows={6} />;
  const c = call.data;
  const mine = c.handled_by === user?.id;
  const act = async (path: string, json?: unknown, done?: string) => {
    try { await api(path, { method: "POST", json }); if (done) toast(done, "ok"); await call.mutate(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "That did not work.", "bad"); }
  };
  return (
    <>
      <div className="stack">
        <div className="row-between">
          <h2>{c.customer ?? "Unverified caller"}</h2>
          <StatusChip status={c.status} label={STATE[c.status]} />
        </div>
        <div className="page__actions">
          {c.status !== "ended" && !c.handled_by && <button className="btn btn--sm btn--primary" onClick={() => act(`/api/calls/${id}/take-over`, undefined, "You have the call. Type to speak to the customer.")}>Take over</button>}
          {c.status !== "ended" && <button className="btn btn--sm btn--danger" onClick={() => act(`/api/calls/${id}/end`, undefined, "Call ended; the note is written.")}>End call</button>}
          <Link className="btn btn--sm btn--quiet" href={`/calls/?id=${id}`}>Full record</Link>
        </div>
      </div>
      {c.handed_off_reason && <div className="banner banner--person" role="status">Handed over: {c.handed_off_reason}{c.status === "handed_off" && c.summary?.outcome ? <> {c.summary.outcome}</> : null}</div>}
      {c.credits.some((cr) => cr.status === "pending") && <div className="banner">A credit is waiting for a supervisor. <Link href="/approvals/">Open approvals</Link></div>}
      <Transcript turns={c.turns} />
      {c.status === "handed_off" && mine && (
        <form className="compose compose--bare" onSubmit={(e) => { e.preventDefault(); if (reply.trim()) { void act(`/api/calls/${id}/reply`, { text: reply.trim() }); setReply(""); } }}>
          <input className="input" value={reply} onChange={(e) => setReply(e.target.value)} placeholder="What you say is spoken to the customer" aria-label="Your reply" maxLength={2000} autoFocus />
          <button className="btn btn--primary">Say</button>
        </form>
      )}
      {c.status === "handed_off" && !mine && <p className="hint">Another person is handling this call.</p>}
    </>
  );
}

export default function Live() {
  const calls = useApi<{ calls: Call[] }>("/api/calls?status=open");
  const [openId, setOpenId] = useState<string | null>(null);
  useEffect(() => follow("/api/calls/live/events", () => void calls.mutate(), ["call_started", "call_state", "call_ended", "approval_needed"]), [calls]);
  const open = calls.data?.calls ?? [];
  const current = open.find((c) => c.id === openId) ?? null;
  return (
    <Page title="Live calls" lede="Calls in progress. Open one to watch it as it happens, take it over, or end it.">
      {calls.error && <ErrorState error={calls.error} retry={() => calls.mutate()} />}
      {calls.isLoading && <div className="panel"><Loading rows={4} /></div>}
      {calls.data && !open.length && <div className="panel"><Empty title="No calls in progress">Place one from the Call screen to see it here.</Empty></div>}
      {!!open.length && (
        <div className="tiles">
          {open.map((c) => (
            <article key={c.id} className="tile" aria-current={c.id === openId ? "true" : undefined}>
              <div className="tile__top">
                <h2 className="tile__name">{c.customer ?? "Unverified caller"}</h2>
                <StatusChip status={c.status} label={STATE[c.status]} />
              </div>
              <p className="readout">Since {when(c.started_at)}, {c.channel === "voice" ? "by voice" : "by text"}</p>
              <div className="tile__foot">
                <span className="hint">{c.handled_by ? "A person is on it" : "The assistant is on it"}</span>
                <button className="btn btn--sm btn--primary" onClick={() => setOpenId(c.id)}>Open call</button>
              </div>
            </article>
          ))}
        </div>
      )}
      {current && (
        <Drawer title="Live call" onClose={() => setOpenId(null)}>
          <LiveCall key={current.id} id={current.id} />
        </Drawer>
      )}
    </Page>
  );
}
