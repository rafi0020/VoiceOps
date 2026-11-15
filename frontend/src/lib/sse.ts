import { API } from "./api";

export interface LiveEvent { type: string; data: Record<string, unknown> }

/** Follow a server-sent event stream; the browser reconnects by itself and resumes after the last event id. */
export function follow(path: string, onEvent: (event: LiveEvent) => void, types: string[]): () => void {
  const source = new EventSource(`${API}${path}`, { withCredentials: true });
  const handler = (e: MessageEvent) => { try { onEvent({ type: e.type, data: JSON.parse(e.data) }); } catch { /* a malformed frame is skipped */ } };
  types.forEach((t) => source.addEventListener(t, handler as EventListener));
  return () => source.close();
}
