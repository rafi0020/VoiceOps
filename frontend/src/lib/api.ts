"use client";

import useSWR, { type SWRConfiguration } from "swr";
import type { User } from "./types";

// Same origin in production (nginx proxies /api); set NEXT_PUBLIC_API_URL for local development.
export const API = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let csrf = "";
export function setCsrf(token: string) {
  csrf = token;
}

function detail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg).replace(/^Value error, /, "");
  return status >= 500 ? "The server had a problem. Try again." : `Request failed (${status}).`;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  // The session cookie is sent by the browser; this header is what proves the request came from our own page.
  if (rest.method && rest.method !== "GET") {
    if (!csrf && !path.startsWith("/api/auth/log") && !path.startsWith("/api/auth/signup")) {
      // An action fired before the session finished loading: fetch the token first rather than fail with 403.
      const me = await fetch(API + "/api/auth/me", { credentials: "include" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (me?.csrf_token) csrf = me.csrf_token;
    }
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  let response: Response;
  try {
    response = await fetch(API + path, { ...rest, headers, credentials: "include", body: json !== undefined ? JSON.stringify(json) : rest.body });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection.");
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, detail(body, response.status));
  return body as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

export function useApi<T>(path: string | null, config?: SWRConfiguration<T, ApiError>) {
  return useSWR<T, ApiError>(path, fetcher, { revalidateOnFocus: false, shouldRetryOnError: false, ...config });
}

export function useMe() {
  const { data, error, isLoading, mutate } = useApi<{ user: User; csrf_token: string }>("/api/auth/me", { onSuccess: (d) => setCsrf(d.csrf_token) });
  if (data) setCsrf(data.csrf_token);
  return { user: data?.user, signedOut: error?.status === 401, error: error && error.status !== 401 ? error : undefined, isLoading, mutate };
}
