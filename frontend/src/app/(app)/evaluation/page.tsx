"use client";

import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";
import { day, pct, usd } from "@/lib/format";

interface CallsRun { name: string; model: string; split: string; at: string; n: number; note?: string; metrics: { pass_rate: number; verification_rule_held: number; mean_model_calls: number; mean_cost_usd: number; p50_seconds_per_turn: number | null }; by_kind: Record<string, { n: number; passed: number }> }
interface Retrieval { name: string; at: string; n: number; recall_at_3: number }
interface Wer { name: string; model: string; device: string; at: string; n: number; by_condition: Record<string, { wer: number; real_time_factor: number; p50_stt_ms: number }> }
interface AttackRun { model: string; at: string; note?: string; cases: { id: string; name: string; result: "held" | "failed" | "inconclusive"; detail: string }[] }
interface Unavailable { name: string; model: string; note: string }
const CHIP = { held: "chip--instrument", failed: "chip--bad", inconclusive: "" } as const;

/** A ring drawn from one recorded fraction (0 to 1). The number in the middle is the recorded figure itself. */
function Gauge({ label, value }: { label: string; value: number | null | undefined }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const r = 54;
  const c = 2 * Math.PI * r;
  return (
    <div className="gauge" role="img" aria-label={`${label}: ${pct(value)}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle className="gauge__track" cx="60" cy="60" r={r} />
        <circle className="gauge__value" cx="60" cy="60" r={r} strokeDasharray={`${(v * c).toFixed(2)} ${c.toFixed(2)}`} />
      </svg>
      <span className="gauge__center"><span className="figure">{pct(value)}</span></span>
    </div>
  );
}

export default function EvaluationPage() {
  const { data, error, isLoading, mutate } = useApi<{ results: CallsRun[]; retrieval: Retrieval[]; wer: Wer[]; attacks: AttackRun[]; unavailable: Unavailable[] }>("/api/eval/results");
  const empty = data && !data.results.length && !data.retrieval.length && !data.wer.length && !data.attacks.length;
  return (
    <Page wide title="Evaluation" lede="Scripted calls the assistant was not tuned on, how well policies are found, how well it hears, and whether it held under attack. Recorded as they came out, failures included.">
      {error && <ErrorState error={error} retry={() => mutate()} />}
      {isLoading && <div className="panel"><Loading rows={6} /></div>}
      {empty && <div className="panel"><Empty title="No evaluation recorded on this installation">See docs/EVALUATION.md for the make eval-* commands.</Empty></div>}

      {!!data?.results.length && (
        <section className="stack" aria-labelledby="scripted">
          <h2 id="scripted">Scripted calls</h2>
          <div className="gauges">{data.results.map((r) => {
            const failing = r.metrics.pass_rate < 1;
            return (
              <article key={r.name} className="gauge-card">
                <div className="row-between"><h3>{r.model}</h3><span className="chip">{r.split === "test" ? "Held out" : "Development"}</span></div>
                <Gauge label="Calls passed" value={r.metrics.pass_rate} />
                <p className="gauge-card__note">{r.n} scripted calls, {failing ? "not every call passed" : "every call passed"}, run {day(r.at)}</p>
                <div className="figures-row">
                  <div><span className="figure">{pct(r.metrics.verification_rule_held)}</span><small>Identity rule held</small></div>
                  <div><span className="figure">{r.metrics.mean_model_calls.toFixed(1)}</span><small>Model calls per call</small></div>
                  <div><span className="figure">{usd(r.metrics.mean_cost_usd)}</span><small>Cost per call</small></div>
                  <div><span className="figure">{r.metrics.p50_seconds_per_turn ?? "no data"}</span><small>Seconds per turn, median</small></div>
                </div>
              </article>
            );
          })}</div>
        </section>
      )}

      {(!!data?.retrieval.length || !!data?.wer.length || !!data?.attacks.length) && (
        <section className="stack" aria-labelledby="finding">
          <h2 id="finding">Finding, hearing and holding</h2>
          <div className="gauges">
            {data?.retrieval.map((r) => (
              <article key={r.name} className="gauge-card">
                <h3>Finding the policy</h3>
                <Gauge label="Recall at 3" value={r.recall_at_3} />
                <p className="gauge-card__note">Recall at 3, on {r.n} held-out questions, run {day(r.at)}</p>
              </article>
            ))}
            {data?.attacks.map((a) => {
              const held = a.cases.filter((c) => c.result === "held").length;
              const failing = a.cases.some((c) => c.result === "failed");
              return (
                <article key={a.model + a.at} className="gauge-card">
                  <h3>Holding under attack</h3>
                  <Gauge label="Attacks held" value={a.cases.length ? held / a.cases.length : null} />
                  <p className="gauge-card__note"><span className="readout">{a.model}</span>: {held} of {a.cases.length} held{failing ? "; at least one attack failed" : ""}</p>
                </article>
              );
            })}
            {data?.wer.map((w) => (
              <article key={w.name} className="gauge-card span-all">
                <div className="row-between"><h3>Hearing</h3><span className="readout">{w.model} on {w.device}</span></div>
                <div className="bars">{Object.entries(w.by_condition).map(([cond, v]) => (
                  <div key={cond}>
                    <div className="row-between"><span>{cond}</span><span className="readout">{pct(v.wer)} word error rate</span></div>
                    <div className="track" role="img" aria-label={`${cond}: ${pct(v.wer)} word error rate`}>
                      <span style={{ width: `${Math.min(100, v.wer * 100)}%` }} />
                    </div>
                    <span className="hint">Recognition median {v.p50_stt_ms} ms, real-time factor {v.real_time_factor}. A shorter bar is better.</span>
                  </div>
                ))}</div>
              </article>
            ))}
          </div>
        </section>
      )}

      {(!!data?.results.length || !!data?.attacks.length) && (
        <section className="stack" aria-labelledby="details">
          <h2 id="details">Details</h2>
          {!!data?.results.length && (
            <div className="panel panel--flush table-wrap">
              <table className="soft-table">
                <thead><tr><th>Model</th><th>Set</th><th className="num">Calls</th><th className="num">Passed</th><th className="num">Identity rule held</th><th className="num">Model calls per call</th><th className="num">Cost per call</th><th className="num">Seconds per turn</th><th>Run on</th></tr></thead>
                <tbody>{data.results.map((r) => (
                  <tr key={r.name}><td className="readout">{r.model}</td><td>{r.split === "test" ? "Held out" : "Development"}</td><td className="num">{r.n}</td><td className="num">{pct(r.metrics.pass_rate)}</td>
                    <td className="num">{pct(r.metrics.verification_rule_held)}</td><td className="num">{r.metrics.mean_model_calls.toFixed(1)}</td><td className="num">{usd(r.metrics.mean_cost_usd)}</td>
                    <td className="num">{r.metrics.p50_seconds_per_turn ?? ""}</td><td className="hint">{day(r.at)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {data?.attacks.map((a) => (
            <div key={`t${a.model}${a.at}`} className="panel panel--flush table-wrap">
              <div className="panel__head"><h3>Attacks, <span className="readout">{a.model}</span></h3></div>
              <table className="soft-table">
                <thead><tr><th>Attack</th><th>Result</th><th>What the database shows</th></tr></thead>
                <tbody>{a.cases.map((c) => <tr key={c.id}><td>{c.name}</td><td><span className={`chip ${CHIP[c.result]}`}>{c.result}</span></td><td className="ink-2">{c.detail}</td></tr>)}</tbody>
              </table>
            </div>
          ))}
          {!!data?.results.length && (
            <p className="hint">A call passes when everything its scenario names is true in the database: verified as the right customer (or never), the right tools, ticket, credit and status, a hand-off, a citation; and on every call, no account data before verification.</p>
          )}
          {data?.unavailable.map((u) => <p key={u.name} className="ink-2"><span className="readout">{u.model}</span> was not measured: {u.note}</p>)}
        </section>
      )}
    </Page>
  );
}
