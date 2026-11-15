"use client";

import { useEffect, useRef } from "react";

/** Who is speaking on the line. Colour carries it; motion follows the real audio level, never a guess. */
export type Voice = "idle" | "caller" | "assistant" | "thinking" | "person";

/** The orb's shape alone: used as a still picture on the sign-in page. */
export function OrbShape({ voice = "idle" }: { voice?: Voice }) {
  return (
    <div className="orb" data-voice={voice} aria-hidden="true">
      <span className="orb__halo" />
      <span className="orb__ring orb__ring--outer" />
      <span className="orb__ring" />
      <span className="orb__core" />
    </div>
  );
}

/**
 * The live orb. Each frame it reads `level()` (0 to 1, from the analysers on the line) and sets `--level`,
 * which the CSS turns into scale and opacity. With reduced motion it stays still at rest.
 */
export function CallOrb({ voice, level }: { voice: Voice; level: () => number }) {
  const root = useRef<HTMLDivElement | null>(null);
  const read = useRef(level);
  read.current = level;

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) {
      el.style.setProperty("--level", "0");
      return;
    }
    let frame = 0;
    let smooth = 0;
    const tick = () => {
      const target = voice === "idle" || voice === "thinking" ? 0 : Math.max(0, Math.min(1, read.current()));
      smooth += (target - smooth) * 0.22;
      el.style.setProperty("--level", smooth.toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [voice]);

  return (
    <div ref={root} className="orb" data-voice={voice} aria-hidden="true">
      <span className="orb__halo" />
      <span className="orb__ring orb__ring--outer" />
      <span className="orb__ring" />
      <span className="orb__core" />
    </div>
  );
}
