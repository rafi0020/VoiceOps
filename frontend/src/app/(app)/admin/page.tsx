"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Page } from "@/components/Shell";
import { Empty, ErrorState, Loading, StatusChip, useToast } from "@/components/ui";
import { api, ApiError, useApi, useMe } from "@/lib/api";
import { initials, when } from "@/lib/format";
import type { Role } from "@/lib/types";

interface Member { id: string; email: string; name: string; role: Role; is_active: boolean; created_at: string }
interface LLM { provider: string; model: string; base_url: string; fallback_model: string; price_input_per_mtok: number; price_output_per_mtok: number; api_key_set: boolean; source: string }
interface AuditEntry { id: number; at: string; user: string | null; action: string; target: string | null; detail: Record<string, unknown> | null; ip: string | null }
const TABS = [["users", "People"], ["limits", "Credit limit"], ["model", "Model"], ["audit", "Audit log"]] as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work.");

function Users() {
  const { user: me } = useMe();
  const toast = useToast();
  const { data, error, isLoading, mutate } = useApi<{ users: Member[] }>("/api/users");
  const [form, setForm] = useState({ email: "", name: "", role: "agent" as Role, password: "" });
  const [problem, setProblem] = useState("");
  const patch = async (id: string, json: Partial<Member>, done: string) => {
    try { await api(`/api/users/${id}`, { method: "PATCH", json }); toast(done); } catch (e) { toast(message(e), "bad"); }
    await mutate();
  };
  const add = async (event: FormEvent) => {
    event.preventDefault();
    setProblem("");
    try {
      await api("/api/users", { method: "POST", json: form });
      toast(`${form.email} can now sign in.`);
      setForm({ email: "", name: "", role: "agent", password: "" });
      await mutate();
    } catch (e) { setProblem(message(e)); }
  };
  return (
    <div className="stack stack--loose">
      <section className="setting" aria-labelledby="people-heading">
        <div className="setting__explain">
          <h2 id="people-heading">People and roles</h2>
          <p>Who can sign in, and what each role may use. Deactivating someone signs them out at once. You cannot change your own account here.</p>
        </div>
        <div className="stack">
          {isLoading && <div className="setting__card"><Loading /></div>}
          {error && <div className="setting__card"><ErrorState error={error} retry={() => mutate()} /></div>}
          {data && (
            <ul className="people">
              {data.users.map((u) => (
                <li key={u.id}>
                  <article className="person">
                    <div className="person__top">
                      <span className="avatar" aria-hidden>{initials(u.name || u.email)}</span>
                      <div>
                        <strong>{u.name}</strong>
                        <small className="measured">{u.email}</small>
                      </div>
                    </div>
                    <div className="person__foot">
                      <div className="row-between">
                        <StatusChip status={u.is_active ? "active" : "rejected"} label={u.is_active ? "active" : "deactivated"} />
                        <span className="hint">Added {when(u.created_at)}</span>
                      </div>
                      <span className="label">Role</span>
                      <select className="select" aria-label={`Role of ${u.email}`} value={u.role} onChange={(e) => patch(u.id, { role: e.target.value as Role }, `${u.email} is now ${e.target.value}.`)}>
                        <option value="viewer">viewer</option><option value="agent">agent</option><option value="supervisor">supervisor</option><option value="admin">admin</option>
                      </select>
                      {u.id !== me?.id && (
                        <button className={`btn btn--sm ${u.is_active ? "btn--danger" : ""}`} onClick={() => patch(u.id, { is_active: !u.is_active }, u.is_active ? `${u.email} was signed out and deactivated.` : `${u.email} can sign in again.`)}>
                          {u.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                    </div>
                  </article>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      <section className="setting" aria-labelledby="add-heading">
        <div className="setting__explain">
          <h2 id="add-heading">Add a person</h2>
          <p>Give each person the lowest role that does their job. The role decides what they can see and do, and the password is the one they start with.</p>
        </div>
        <form className="setting__card" onSubmit={add}>
          <div className="form-grid">
            <label className="field"><span className="label">Name</span><input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label className="field"><span className="label">E-mail</span><input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label className="field span-all"><span className="label">Role</span>
              <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                <option value="viewer">viewer: reads</option><option value="agent">agent: takes calls over from the assistant</option><option value="supervisor">supervisor: decides credits above the limit</option><option value="admin">admin: all of that, and manages people, policies and limits</option>
              </select>
            </label>
            <label className="field span-all"><span className="label">Initial password</span><input className="input" type="password" required autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><span className="hint">At least 10 characters, with a letter and a number.</span></label>
          </div>
          {problem && <p className="hint hint--bad" role="alert">{problem}</p>}
          <div><button className="btn btn--primary">Add person</button></div>
        </form>
      </section>
    </div>
  );
}

function Model() {
  const toast = useToast();
  const { data, error, isLoading, mutate } = useApi<LLM>("/api/settings/llm");
  const [form, setForm] = useState<LLM | null>(null);
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setForm(data); }, [data]);
  if (isLoading || !form) return error ? <ErrorState error={error} retry={() => mutate()} /> : <div className="setting__card"><Loading /></div>;
  const set = <K extends keyof LLM>(k: K, v: LLM[K]) => setForm({ ...form, [k]: v });
  const save = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const body = { ...form, api_key: key ? key : undefined };
      await mutate(await api<LLM>("/api/settings/llm", { method: "PUT", json: body }), false);
      setKey("");
      toast("Model settings saved.");
    } catch (e) { toast(message(e), "bad"); }
  };
  const test = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api<{ ok: boolean; error?: string; model?: string; latency_ms?: number }>("/api/settings/llm/test", { method: "POST" });
      setResult(r.ok ? { ok: true, text: `Connected to ${r.model} in ${r.latency_ms} ms.` } : { ok: false, text: r.error ?? "The test failed." });
    } catch (e) { setResult({ ok: false, text: message(e) }); }
    setBusy(false);
  };
  return (
    <section className="setting" aria-labelledby="model-heading">
      <div className="setting__explain">
        <h2 id="model-heading">Model provider</h2>
        <p>The model that answers callers, and where it is reached. Prices are used to estimate cost and enforce budgets, so set them to what your provider charges.</p>
        <span className="chip">{form.source === "organisation" ? "Set for this organisation" : "Using the server default"}</span>
      </div>
      <form className="setting__card" onSubmit={save}>
        <div className="form-grid">
          <label className="field span-all"><span className="label">Provider</span>
            <select className="select" value={form.provider} onChange={(e) => set("provider", e.target.value)}>
              <option value="openai_compat">OpenAI-compatible (OpenAI, Gemini, Groq, 9Router, any gateway)</option>
              <option value="anthropic">Anthropic</option><option value="ollama">Ollama (local)</option><option value="stub">Built-in demonstration script (no model)</option>
            </select>
          </label>
          <label className="field"><span className="label">Model</span><input className="input measured" required value={form.model} onChange={(e) => set("model", e.target.value)} /></label>
          <label className="field"><span className="label">Fallback model (optional)</span><input className="input measured" value={form.fallback_model} onChange={(e) => set("fallback_model", e.target.value)} /></label>
          <label className="field span-all"><span className="label">Base URL</span><input className="input measured" value={form.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder={form.provider === "ollama" ? "http://host.docker.internal:11434/v1" : "https://api.example.com/v1"} /></label>
          <label className="field span-all"><span className="label">API key</span>
            <input className="input measured" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={form.api_key_set ? "A key is stored. Type a new one to replace it." : "No key stored"} />
            <span className="hint">Stored encrypted. It is never shown again and never sent to the browser.</span>
          </label>
          <label className="field"><span className="label">Price per million input tokens, USD</span><input className="input measured" type="number" min={0} step="0.01" value={form.price_input_per_mtok} onChange={(e) => set("price_input_per_mtok", Number(e.target.value))} /></label>
          <label className="field"><span className="label">Price per million output tokens, USD</span><input className="input measured" type="number" min={0} step="0.01" value={form.price_output_per_mtok} onChange={(e) => set("price_output_per_mtok", Number(e.target.value))} /></label>
        </div>
        <div className="page__actions row-center">
          <button className="btn btn--primary">Save</button>
          <button type="button" className="btn" onClick={test} disabled={busy} aria-busy={busy}>Test the saved settings</button>
          {result && <span className={result.ok ? "ok" : "bad"} role="status">{result.text}</span>}
        </div>
      </form>
    </section>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const { data, error, isLoading, mutate } = useApi<{ entries: AuditEntry[]; next_before: number | null }>(`/api/audit?limit=50&action=${encodeURIComponent(action)}${before ? `&before=${before}` : ""}`, { keepPreviousData: true });
  return (
    <section className="setting" aria-labelledby="audit-heading">
      <div className="setting__explain">
        <h2 id="audit-heading">Audit log</h2>
        <p>Who did what, newest first: sign-ins, changes to people, calls, credits, policies and settings. Filter by kind to see one part of it.</p>
      </div>
      <div className="stack">
        <div className="page__actions">
          <select className="select select--auto" value={action} onChange={(e) => { setAction(e.target.value); setBefore(null); }} aria-label="Filter by kind">
            <option value="">Everything</option><option value="auth.">Sign-ins</option><option value="user.">People</option><option value="call.">Calls</option><option value="credit.">Credits</option><option value="policy.">Policies</option><option value="settings.">Settings</option>
          </select>
          {before && <button className="btn" onClick={() => setBefore(null)}>Back to newest</button>}
        </div>
        <div className="setting__card">
          {isLoading && !data && <Loading />}
          {error && <ErrorState error={error} retry={() => mutate()} />}
          {data?.entries.length === 0 && <Empty title="No entries">Nothing of this kind has been recorded.</Empty>}
          {!!data?.entries.length && (
            <ol className="audit">{data.entries.map((e) => (
              <li key={e.id}>
                <span className="audit__head"><strong className="measured">{e.action}</strong><span className="hint measured">{when(e.at)}</span></span>
                <span className="ink-2">{e.user ?? "Deleted user"}{e.ip ? `, from ${e.ip}` : ""}</span>
                {e.detail && <span className="audit__detail measured">{JSON.stringify(e.detail).slice(0, 160)}</span>}
              </li>
            ))}</ol>
          )}
        </div>
        {data?.next_before && <div><button className="btn" onClick={() => setBefore(data.next_before)}>Older entries</button></div>}
      </div>
    </section>
  );
}

function Limits() {
  const toast = useToast();
  const { data, error, mutate } = useApi<{ credit_limit: string }>("/api/call-settings");
  const [value, setValue] = useState<string | null>(null);
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <div className="setting__card"><Loading /></div>;
  const save = async (event: FormEvent) => {
    event.preventDefault();
    try { await mutate(await api<{ credit_limit: string }>("/api/call-settings", { method: "PUT", json: { credit_limit: value ?? data.credit_limit } }), false); toast("Saved. It applies to the next credit."); }
    catch (e) { toast(message(e), "bad"); }
  };
  return (
    <section className="setting" aria-labelledby="limit-heading">
      <div className="setting__explain">
        <h2 id="limit-heading">Credit limit</h2>
        <p>The most the assistant may credit on one call without a supervisor. Above it, the call waits for a supervisor&apos;s decision, or the customer is told they will hear back.</p>
      </div>
      <form className="setting__card" onSubmit={save}>
        <label className="field"><span className="label">Credits the assistant may apply on one call without a supervisor</span>
          <input className="input" type="number" min={0} max={500} step="0.01" value={value ?? data.credit_limit} onChange={(e) => setValue(e.target.value)} /></label>
        <p className="hint">It applies to the next credit.</p>
        <div><button className="btn btn--primary">Save</button></div>
      </form>
    </section>
  );
}

function AdminPage() {
  const router = useRouter();
  const tab = useSearchParams().get("tab") ?? "users";
  const { user } = useMe();
  if (user && user.role !== "admin") return <Page title="Administration"><div className="panel"><Empty title="Administrators only">Ask an administrator of your organisation for access.</Empty></div></Page>;
  return (
    <Page title="Administration" lede="People and roles, the credit limit, the model the assistant uses, and the record of who did what.">
      <div className="tabs" role="tablist" aria-label="Administration">
        {TABS.map(([value, label]) => (<button key={value} className="tab" role="tab" aria-selected={tab === value} onClick={() => router.replace(`/admin/?tab=${value}`)}>{label}</button>))}
      </div>
      {tab === "users" && <Users />}
      {tab === "limits" && <Limits />}
      {tab === "model" && <Model />}
      {tab === "audit" && <Audit />}
    </Page>
  );
}

export default function AdminRoute() {
  return (<Suspense fallback={<Loading />}><AdminPage /></Suspense>);
}
