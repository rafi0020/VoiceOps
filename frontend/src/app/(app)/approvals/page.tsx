"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { when } from "@/lib/format";
import type { Credit } from "@/lib/types";

/** How long a request has waited, in words. `now` is passed in so every card ticks together. */
function waiting(iso: string, now: number): string {
  const m = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  if (m < 1) return "Waiting under a minute";
  if (m < 60) return `Waiting ${m} min`;
  return `Waiting ${Math.floor(m / 60)} h ${m % 60} min`;
}

function CreditCard({ c, now, onDone }: { c: Credit; now: number; onDone: () => void }) {
  const toast = useToast();
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const decide = async (decision: "approved" | "refused") => {
    try {
      const r = await api<{ agent_said: string }>(`/api/credits/${c.id}/decide`, { method: "POST", json: { decision, reason: reason || null } });
      toast(decision === "approved" ? `Credit applied.${r.agent_said ? " The assistant told the customer." : ""}` : "Declined; the customer will be told.", "ok");
      onDone();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Could not record the decision.", "bad"); }
  };
  return (
    <article className="credit" aria-label={`Credit of ${c.amount} for ${c.customer}`}>
      <div className="credit__head">
        <div className="credit__amount">
          <span className="label">Credit requested</span>
          <span className="figure">{c.amount}</span>
        </div>
        <div className="credit__who">
          <strong>{c.customer}</strong>
          <span className="readout">{c.account_number}</span>
          <span className="hint">{waiting(c.requested_at, now)}, asked {when(c.requested_at)}</span>
        </div>
      </div>
      <p className="credit__reason">{c.reason}</p>
      <div className="credit__foot">
        <div className="credit__actions">
          {c.call_id ? <Link className="btn btn--sm btn--quiet" href={`/calls/?id=${c.call_id}`}>Open the call</Link> : <span className="hint">No call</span>}
          {c.call_status === "live" && <StatusChip status="live" label="On the line now" />}
        </div>
        {declining ? (
          <form className="credit__actions" onSubmit={(e) => { e.preventDefault(); void decide("refused"); }}>
            <input className="input input--short" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why" aria-label={`Reason for declining ${c.amount}`} autoFocus />
            <button className="btn btn--danger">Decline</button>
            <button type="button" className="btn btn--quiet" onClick={() => setDeclining(false)}>Cancel</button>
          </form>
        ) : (
          <div className="credit__actions">
            <button className="btn btn--primary" onClick={() => decide("approved")}>Approve</button>
            <button className="btn btn--quiet" onClick={() => setDeclining(true)}>Decline&hellip;</button>
          </div>
        )}
      </div>
    </article>
  );
}

export default function Approvals() {
  const credits = useApi<{ credits: Credit[] }>("/api/credits", { refreshInterval: 5000 });
  const approved = useApi<{ credits: Credit[] }>("/api/credits?status=approved");
  const declined = useApi<{ credits: Credit[] }>("/api/credits?status=refused");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(tick);
  }, []);
  const decided = [...(approved.data?.credits ?? []), ...(declined.data?.credits ?? [])]
    .sort((a, b) => (b.decided_at ?? "").localeCompare(a.decided_at ?? ""));
  const refresh = () => { void credits.mutate(); void approved.mutate(); void declined.mutate(); };
  return (
    <Page title="Credits to approve" lede="Credits above the limit the assistant may give. A customer still on the line hears your decision at once. You do not decide credits from calls you were on.">
      <section className="stack" aria-labelledby="waiting">
        <h2 id="waiting">Waiting for a decision</h2>
        {credits.error && <ErrorState error={credits.error} retry={() => credits.mutate()} />}
        {credits.isLoading && <div className="panel"><Loading rows={4} /></div>}
        {credits.data && !credits.data.credits.length && <div className="panel"><Empty title="Nothing waiting">No credits need a decision.</Empty></div>}
        {!!credits.data?.credits.length && (
          <div className="credits">{credits.data.credits.map((c) => <CreditCard key={c.id} c={c} now={now} onDone={refresh} />)}</div>
        )}
      </section>
      <section className="stack" aria-labelledby="decided">
        <h2 id="decided">Decided</h2>
        {(approved.error || declined.error) && <ErrorState error={(approved.error ?? declined.error)!} retry={refresh} />}
        {!!decided.length ? (
          <ul className="decided-list">{decided.map((c) => (
            <li key={c.id}>
              <span className="row-between">
                <span><strong>{c.customer}</strong> <span className="readout">{c.amount}</span></span>
                <StatusChip status={c.status} label={c.status === "refused" ? "declined" : "approved"} />
              </span>
              <span className="hint">{c.decided_at ? when(c.decided_at) : ""}{c.decision_reason ? `: ${c.decision_reason}` : ""}</span>
            </li>
          ))}</ul>
        ) : <p className="hint">Decisions you make appear here.</p>}
      </section>
    </Page>
  );
}
