export type Role = "viewer" | "agent" | "supervisor" | "admin";
export interface User { id: string; org_id: string; email: string; name: string; role: Role }
export type CallStatus = "live" | "handed_off" | "ended";
export interface Summary { reason: string; outcome: string; follow_up: string; sentiment: string; unsupported?: string[]; written_by?: string }
export interface Call {
  id: string; status: CallStatus; channel: "voice" | "text"; started_at: string; ended_at: string | null; verified: boolean; customer: string | null;
  handled_by: string | null; handed_off_reason: string | null; summary: Summary | null; model_calls: number; cost_usd: number;
}
export interface Timings { stt_ms?: number; stt_wait_ms?: number; audio_ms?: number; agent_ms?: number; reply_ready_ms?: number; tts_first_ms?: number; first_audio_ms?: number; input?: string }
export interface Turn { idx: number; speaker: "customer" | "agent" | "person" | "system"; text: string; interrupted: boolean; timings: Timings; at: string }
export interface CallDetail extends Call {
  customer_account: string | null; turns: Turn[]; events: { kind: string; data: Record<string, unknown>; at: string }[];
  credits: { id: string; amount: string; status: string; reason: string }[];
}
export interface Credit {
  id: string; amount: string; reason: string; status: string; customer: string; account_number: string; call_id: string | null; call_status: string | null;
  requested_at: string; decided_at: string | null; decision_reason: string | null;
}
