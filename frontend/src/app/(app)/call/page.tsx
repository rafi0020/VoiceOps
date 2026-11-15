"use client";

import { Mic, MicOff, PhoneOff, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Page } from "@/components/Shell";
import { CallOrb, type Voice } from "@/components/Orb";
import { useToast } from "@/components/ui";
import { api, API, ApiError } from "@/lib/api";
import type { Summary, Timings } from "@/lib/types";

type Line = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "handed_off" | "ended";
interface Said { speaker: "customer" | "agent" | "person"; text: string; timings?: Timings; interrupted?: boolean }

const LINE: Record<Line, string> = {
  idle: "Not connected", connecting: "Connecting", listening: "Listening", thinking: "Thinking", speaking: "Speaking",
  handed_off: "With a colleague", ended: "Call ended",
};
const VOICE: Record<Line, Voice> = {
  idle: "idle", connecting: "idle", listening: "caller", thinking: "thinking", speaking: "assistant", handed_off: "person", ended: "idle",
};

function socketUrl(callId: string) {
  const base = API || window.location.origin;
  return `${base.replace(/^http/, "ws")}/api/voice/${callId}`;
}

/** The loudness of what an analyser is hearing, 0 to 1, from its time-domain samples. */
function loudness(a: AnalyserNode | null | undefined): number {
  if (!a) return 0;
  const bytes = new Uint8Array(a.fftSize);
  a.getByteTimeDomainData(bytes);
  let sum = 0;
  for (let i = 0; i < bytes.length; i++) {
    const x = (bytes[i] - 128) / 128;
    sum += x * x;
  }
  return Math.min(1, Math.sqrt(sum / bytes.length) * 3);
}

/** Plays 16-bit PCM as it arrives, back to back; `clear` drops everything queued (the caller spoke over it). */
class Player {
  private next = 0;
  private sources: AudioBufferSourceNode[] = [];
  rate = 22050;
  /** Read-only tap on what is played, for the orb. It passes the sound straight on to the speakers. */
  readonly analyser: AnalyserNode;
  constructor(private ctx: AudioContext) {
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.connect(ctx.destination);
  }
  play(chunk: ArrayBuffer) {
    const pcm = new Int16Array(chunk);
    const buffer = this.ctx.createBuffer(1, pcm.length, this.rate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) data[i] = pcm[i] / 32768;
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser);
    const at = Math.max(this.ctx.currentTime + 0.02, this.next);
    source.start(at);
    this.next = at + buffer.duration;
    this.sources.push(source);
    source.onended = () => { this.sources = this.sources.filter((s) => s !== source); };
  }
  clear() {
    this.sources.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
    this.sources = [];
    this.next = 0;
  }
}

export default function CallPage() {
  const toast = useToast();
  const [callId, setCallId] = useState<string | null>(null);
  const [line, setLine] = useState<Line>("idle");
  const [said, setSaid] = useState<Said[]>([]);
  const [typed, setTyped] = useState("");
  const [muted, setMuted] = useState(false);
  const [micOn, setMicOn] = useState(false);
  // Open mic sends everything the microphone hears; press to talk sends only while the button (or Space) is held.
  const [mode, setMode] = useState<"open" | "press">("open");
  const [held, setHeld] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const player = useRef<Player | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const meter = useRef<AnalyserNode | null>(null);
  const mutedRef = useRef(false);
  const modeRef = useRef<"open" | "press">("open");
  const pressedRef = useRef(false);
  const lineRef = useRef<Line>("idle");
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => { mutedRef.current = muted; }, [muted]);
  useEffect(() => { lineRef.current = line; }, [line]);
  // Scroll the transcript box only: scrollIntoView would also move the whole page on every turn.
  useEffect(() => {
    const box = bottom.current?.parentElement;
    if (box) box.scrollTop = box.scrollHeight;
  }, [said]);
  useEffect(() => () => { ws.current?.close(); stream.current?.getTracks().forEach((t) => t.stop()); void ctx.current?.close(); }, []);

  const add = (s: Said) => setSaid((all) => [...all, s]);

  /** The orb's level: the assistant's voice while it speaks, the caller's microphone while the caller is heard. */
  const level = () => {
    if (lineRef.current === "speaking") return loudness(player.current?.analyser);
    if (lineRef.current === "listening" && !mutedRef.current) return loudness(meter.current);
    return 0;
  };

  /** Whether the microphone's frames go to the server now. */
  function sendingAudio() {
    return !mutedRef.current && (modeRef.current === "open" || pressedRef.current);
  }
  /** Press to talk: the button or Space went down. Open mic ignores it. */
  function press() {
    if (modeRef.current !== "press" || pressedRef.current || mutedRef.current) return;
    pressedRef.current = true;
    setHeld(true);
  }
  /** The button or Space came up: stop sending and tell the server the turn is over, without waiting for silence. */
  function release() {
    if (!pressedRef.current) return;
    pressedRef.current = false;
    setHeld(false);
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify({ type: "end_turn" }));
  }
  function chooseMode(next: "open" | "press") {
    release();
    (document.activeElement as HTMLElement | null)?.blur(); // so a Space press cannot also activate the focused toggle
    modeRef.current = next;
    setMode(next);
  }
  useEffect(() => {
    if (!micOn || mode !== "press") return;
    const typing = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    const down = (e: KeyboardEvent) => { if (e.code === "Space" && !e.repeat && !typing(e.target)) { e.preventDefault(); press(); } };
    const up = (e: KeyboardEvent) => { if (e.code === "Space") release(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); release(); };
  }, [micOn, mode]); // press and release use only refs and state setters, so the first render's handlers stay correct

  async function start(voice: boolean) {
    setSummary(null);
    setSaid([]);
    setLine("connecting");
    try {
      const call = await api<{ id: string; greeting: string }>("/api/calls", { method: "POST", json: { channel: voice ? "voice" : "text" } });
      setCallId(call.id);
      add({ speaker: "agent", text: call.greeting });
      ctx.current = new AudioContext();
      player.current = new Player(ctx.current);
      if (voice) await startMic();
      const socket = new WebSocket(socketUrl(call.id));
      socket.binaryType = "arraybuffer";
      socket.onmessage = (e) => {
        if (typeof e.data !== "string") { player.current?.play(e.data as ArrayBuffer); return; }
        const m = JSON.parse(e.data);
        if (m.type === "state") setLine(m.state as Line);
        else if (m.type === "transcript") add({ speaker: "customer", text: m.text });
        else if (m.type === "agent_text") setSaid((all) => (all.length === 1 && all[0].text === m.text ? all : [...all, { speaker: m.speaker, text: m.text }]));
        else if (m.type === "audio" && player.current) player.current.rate = m.rate;
        else if (m.type === "clear") { player.current?.clear(); setSaid((all) => all.map((s, i) => (i === all.length - 1 && s.speaker !== "customer" ? { ...s, interrupted: true } : s))); }
        else if (m.type === "latency") setSaid((all) => { const i = all.map((s) => s.speaker).lastIndexOf("customer"); return all.map((s, j) => (j === i ? { ...s, timings: m } : s)); });
      };
      // A muted caller sends no audio; a ping keeps the server from closing the socket as idle.
      const keepAlive = setInterval(() => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" })); }, 60_000);
      socket.onclose = () => { clearInterval(keepAlive); setLine((l) => (l === "ended" ? l : "ended")); };
      ws.current = socket;
    } catch (e) {
      setLine("idle");
      toast(e instanceof ApiError ? e.message : "Could not start the call.", "bad");
    }
  }

  async function startMic() {
    if (!ctx.current) return;
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      await ctx.current.audioWorklet.addModule("/capture-worklet.js");
      const source = ctx.current.createMediaStreamSource(stream.current);
      const node = new AudioWorkletNode(ctx.current, "capture");
      node.port.onmessage = (e) => { if (sendingAudio() && ws.current?.readyState === WebSocket.OPEN) ws.current.send(e.data as ArrayBuffer); };
      source.connect(node);
      // A read-only tap on the microphone, for the orb; the frames still go only to the worklet.
      meter.current = ctx.current.createAnalyser();
      meter.current.fftSize = 256;
      source.connect(meter.current);
      setMicOn(true);
    } catch {
      toast("The microphone is not available; you can type instead.", "bad");
    }
  }

  function send(e: React.FormEvent) {
    e.preventDefault();
    if (!typed.trim() || ws.current?.readyState !== WebSocket.OPEN) return;
    add({ speaker: "customer", text: typed.trim() });
    ws.current.send(JSON.stringify({ type: "text", text: typed.trim() }));
    setTyped("");
  }

  async function hangUp() {
    release();
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify({ type: "end" }));
    stream.current?.getTracks().forEach((t) => t.stop());
    meter.current = null;
    setMicOn(false);
    player.current?.clear();
    if (callId) {
      for (let i = 0; i < 20; i++) {
        const c = await api<{ summary: Summary | null; status: string }>(`/api/calls/${callId}`);
        if (c.status === "ended" && c.summary) { setSummary(c.summary); break; }
        await new Promise((r) => setTimeout(r, 500));
      }
    }
    setLine("ended");
  }

  const connected = line !== "idle" && line !== "ended";
  const last = [...said].reverse().find((s) => s.timings?.first_audio_ms != null || s.timings?.reply_ready_ms != null)?.timings;

  return (
    <Page wide title="Call" lede="You are the customer. Speak to the assistant, or type; it checks who you are before it talks about an account.">
      <div className="stage">
        <section className="stage__voice" aria-label="The voice">
          <CallOrb voice={VOICE[line]} level={level} />
          <p className="line-state" data-state={line} role="status" aria-live="polite">{LINE[line]}</p>
          {!connected ? (
            <div className="stage__start">
              <button className="btn btn--primary btn--lg" onClick={() => start(true)}><Mic aria-hidden />Call by voice</button>
              <button className="btn btn--lg" onClick={() => start(false)}>Call by text</button>
            </div>
          ) : (
            <div className="stage__controls">
              {micOn && <button className="btn talk" onClick={() => setMuted((m) => !m)} aria-pressed={muted}>{muted ? <MicOff aria-hidden /> : <Mic aria-hidden />}{muted ? "Unmute" : "Mute"}</button>}
              {micOn && <button className="btn talk" onClick={() => chooseMode(mode === "open" ? "press" : "open")} aria-pressed={mode === "press"}>{mode === "open" ? "Press to talk" : "Open mic"}</button>}
              <button className="btn btn--danger talk" onClick={hangUp}><PhoneOff aria-hidden />Hang up</button>
            </div>
          )}
          {micOn && mode === "press" && (
            <button
              className="btn btn--primary talk talk--hold"
              disabled={muted}
              aria-pressed={held}
              onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); press(); }}
              onPointerUp={release}
              onPointerCancel={release}
              onLostPointerCapture={release}
            ><Mic aria-hidden />{held ? "Talking" : "Hold to talk"}</button>
          )}
          <p className="hint stage__hint">
            {micOn && mode === "press"
              ? "Hold the button or the space bar while you speak; let go to send what you said. Nothing is sent otherwise."
              : "Speak naturally; a pause of about half a second ends your turn. You can talk over the assistant to stop it."}
          </p>
        </section>

        <section className="panel conversation" aria-label="Conversation">
          <div className="panel__head"><h2>The conversation</h2></div>
          <div className="transcript" aria-live="polite">
            {said.length === 0 && <p>Start a call by voice, or by text if you have no microphone. Try: &ldquo;my broadband is down&rdquo;, then give account LT100001, postcode NG4 2AB, born 14 March 1985.</p>}
            {said.map((s, i) => (
              <div key={i} className="bubble" data-speaker={s.speaker} data-interrupted={s.interrupted ? "true" : undefined}>
                <span className="who">{s.speaker === "customer" ? "You" : s.speaker === "person" ? "A colleague" : "Assistant"}{s.interrupted ? ", cut off" : ""}</span>
                {s.text}
                {s.timings?.first_audio_ms != null && <span className="readout">first sound back in <strong>{s.timings.first_audio_ms} ms</strong></span>}
              </div>
            ))}
            <div ref={bottom} />
          </div>
          {connected && (
            <form className="compose" onSubmit={send}>
              <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type instead of speaking" aria-label="Type a message" maxLength={2000} />
              <button className="btn btn--primary" aria-label="Send"><Send aria-hidden />Send</button>
            </form>
          )}
        </section>

        <aside className="stage__side">
          <section className="panel lastturn" aria-label="Latency of the last turn">
            <h2>The last turn</h2>
            {last ? (
              <div className="readout">
                {last.stt_ms != null && <span>Recognition <strong>{last.stt_ms} ms</strong>{last.stt_wait_ms ? ` (+${last.stt_wait_ms} ms queued)` : ""}</span>}
                {last.agent_ms != null && <span>Agent <strong>{last.agent_ms} ms</strong></span>}
                {last.tts_first_ms != null && <span>First sentence spoken in <strong>{last.tts_first_ms} ms</strong></span>}
                {last.first_audio_ms != null && <span>End of speech to first sound <strong>{last.first_audio_ms} ms</strong></span>}
              </div>
            ) : <p className="hint">Timings appear after your first turn.</p>}
          </section>
          {summary && (
            <section className="panel lastturn">
              <h2>The note for the CRM</h2>
              <p><strong>Reason:</strong> {summary.reason}</p>
              <p><strong>Outcome:</strong> {summary.outcome}</p>
              {summary.follow_up && <p><strong>Follow-up:</strong> {summary.follow_up}</p>}
              {!!summary.unsupported?.length && <p className="hint">Removed because their figures were not in the call: {summary.unsupported.join(" ")}</p>}
            </section>
          )}
        </aside>
      </div>
    </Page>
  );
}
