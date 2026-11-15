import type { Turn } from "@/lib/types";

const WHO = { customer: "customer", agent: "assistant", person: "colleague", system: "system" } as const;

/** A call's turns, with each customer turn's latency as a mono readout. */
export function Transcript({ turns }: { turns: Turn[] }) {
  if (!turns.length) return <p className="muted p-4">Nothing has been said yet.</p>;
  return (
    <div className="transcript">
      {turns.map((t) => (
        <div key={t.idx} className="bubble" data-speaker={t.speaker} data-interrupted={t.interrupted ? "true" : undefined}>
          <span className="who">{WHO[t.speaker]}{t.interrupted ? ", cut off by the customer" : ""}{t.timings?.input === "typed" ? ", typed" : ""}</span>
          {t.text || <span className="muted">(nothing was spoken)</span>}
          {t.timings?.first_audio_ms != null && <span className="readout block">first sound back <strong>{t.timings.first_audio_ms} ms</strong>, recognition {t.timings.stt_ms} ms, agent {t.timings.agent_ms} ms</span>}
        </div>
      ))}
    </div>
  );
}
