"use client";

import { ArrowLeft, MessageSquare, Mic, Timer } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Page } from "@/components/Shell";
import { Transcript } from "@/components/Transcript";
import { Empty, ErrorState, Loading, StatusChip } from "@/components/ui";
import { useApi } from "@/lib/api";
import { day, initials, when } from "@/lib/format";
import type { Call, CallDetail } from "@/lib/types";

/** A short state for the chip. The summary's outcome sentence stays in the note. */
function outcome(c: Call): { label: string; chip: string } {
  if (c.status === "live") return { label: "In progress", chip: "chip--instrument" };
  if (c.status === "handed_off") return { label: "With a person", chip: "chip--hold" };
  if (c.handed_off_reason) return { label: "Handed to a person", chip: "chip--hold" };
  return { label: "Handled by the assistant", chip: "" };
}

function length(c: Call): string {
  if (!c.ended_at) return "In progress";
  const s = Math.max(0, Math.round((Date.parse(c.ended_at) - Date.parse(c.started_at)) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

function dayStart(iso: string): number {
  const d = new Date(iso);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function dayLabel(iso: string): string {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const key = dayStart(iso);
  if (key === dayStart(now.toISOString())) return "Today";
  if (key === dayStart(yesterday.toISOString())) return "Yesterday";
  return day(iso);
}

/** The calls arrive newest first, so each day is a run of neighbours. */
function byDay(calls: Call[]): { key: number; label: string; items: Call[] }[] {
  const groups: { key: number; label: string; items: Call[] }[] = [];
  for (const c of calls) {
    const key = dayStart(c.started_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(c);
    else groups.push({ key, label: dayLabel(c.started_at), items: [c] });
  }
  return groups;
}

function CallCard({ c }: { c: Call }) {
  const o = outcome(c);
  const Channel = c.channel === "voice" ? Mic : MessageSquare;
  const tone = c.status === "live" ? "live" : c.status === "handed_off" ? "person" : undefined;
  return (
    <Link href={`/calls/?id=${c.id}`} className="soft-link call-card">
      <span className="avatar" data-tone={tone} aria-hidden>{initials(c.customer ?? "Unverified caller")}</span>
      <span className="call-card__body">
        <span className="call-card__name">{c.customer ?? "Unverified caller"}</span>
        {c.summary?.reason && <span className="call-card__reason">{c.summary.reason}</span>}
        <span className="call-card__meta">
          <span><Channel aria-hidden />{c.channel === "voice" ? "Voice" : "Text"}</span>
          <span><Timer aria-hidden />{length(c)}</span>
        </span>
      </span>
      <span className="call-card__side">
        <span className="readout">{clock(c.started_at)}</span>
        <span className={`chip ${o.chip}`}>{o.label}</span>
      </span>
    </Link>
  );
}

function CallList() {
  const calls = useApi<{ calls: Call[] }>("/api/calls?limit=200");
  return (
    <Page title="Calls" lede="Every call, newest first: who called, how it went, and the note left for the CRM.">
      {calls.error && <ErrorState error={calls.error} retry={() => calls.mutate()} />}
      {calls.isLoading && <div className="panel"><Loading rows={8} /></div>}
      {calls.data && !calls.data.calls.length && <div className="panel"><Empty title="No calls yet">Start one from the Call screen and it will appear here.</Empty></div>}
      {!!calls.data?.calls.length && (
        <div className="timeline">
          {byDay(calls.data.calls).map((g) => (
            <section key={g.key} className="timeline__day" aria-label={g.label}>
              <h2 className="day-heading">{g.label}</h2>
              <ul className="call-list">
                {g.items.map((c) => <li key={c.id}><CallCard c={c} /></li>)}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Page>
  );
}

function CallRecord({ id }: { id: string }) {
  const call = useApi<CallDetail>(`/api/calls/${id}`);
  if (call.error) return <Page title="Call"><ErrorState error={call.error} /></Page>;
  if (!call.data) return <Page title="Call"><Loading rows={8} /></Page>;
  const c = call.data;
  const timed = c.turns.filter((t) => t.timings?.first_audio_ms != null);
  const o = outcome(c);
  return (
    <Page wide title={c.customer ? `Call with ${c.customer}` : "Call"} lede={`${when(c.started_at)}${c.customer_account ? `, account ${c.customer_account}` : ""}, ${c.model_calls} model calls`}
      actions={<><StatusChip status={c.status} label={c.status.replace("_", " ")} /><Link className="btn btn--sm btn--quiet" href="/calls/"><ArrowLeft aria-hidden />All calls</Link></>}>
      <div className="call-detail">
        <section className="soft-card" aria-labelledby="conversation">
          <h2 id="conversation">Conversation</h2>
          <Transcript turns={c.turns} />
        </section>
        <div className="call-detail__side">
          <section className="soft-card" aria-labelledby="note">
            <h2 id="note">The CRM note</h2>
            {c.summary ? (
              <dl className="facts">
                <div><dt>Reason</dt><dd>{c.summary.reason}</dd></div>
                <div><dt>Outcome</dt><dd>{c.summary.outcome}</dd></div>
                {c.summary.follow_up && <div><dt>Follow-up</dt><dd>{c.summary.follow_up}</dd></div>}
              </dl>
            ) : <p className="hint">No note was written for this call.</p>}
            {!!c.summary?.unsupported?.length && <p className="hint">Removed, figures not in the call: {c.summary.unsupported.join(" ")}</p>}
          </section>
          <section className="soft-card" aria-labelledby="handover">
            <div className="row-between"><h2 id="handover">Handover</h2><span className={`chip ${o.chip}`}>{o.label}</span></div>
            <p>{c.handed_off_reason ?? "The assistant handled this call without passing it to a person."}</p>
            {c.status === "handed_off" && c.summary?.follow_up && <p className="ink-2"><strong>Next step:</strong> {c.summary.follow_up}</p>}
          </section>
          {!!timed.length && (
            <section className="soft-card" aria-labelledby="latency">
              <h2 id="latency">Latency</h2>
              <div className="latency">
                {timed.map((t) => (
                  <div key={t.idx}>
                    <span className="figure">{t.timings.first_audio_ms} ms</span>
                    <small>Turn {t.idx}: end of speech to first sound</small>
                  </div>
                ))}
              </div>
            </section>
          )}
          <section className="soft-card" aria-labelledby="events">
            <h2 id="events">What happened</h2>
            <ul className="rows rows--stack">{c.events.map((e, i) => (
              <li key={i}>
                <strong>{e.kind.replace(/_/g, " ")}</strong>
                <span className="readout">{Object.entries(e.data).filter(([k]) => !k.endsWith("_id")).map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join("; ")}</span>
              </li>
            ))}</ul>
            {!!c.credits.length && <p className="ink-2">Credits: {c.credits.map((cr) => `${cr.amount} ${cr.status}`).join(", ")}</p>}
          </section>
        </div>
      </div>
    </Page>
  );
}

function CallsRoute() {
  const id = useSearchParams().get("id");
  return id ? <CallRecord key={id} id={id} /> : <CallList />;
}

export default function Calls() {
  return <Suspense fallback={<Loading />}><CallsRoute /></Suspense>;
}
