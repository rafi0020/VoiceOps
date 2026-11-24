"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { BASE, api, ApiError, setCsrf } from "@/lib/api";
import { OrbShape } from "./Orb";

// The demo organisation seeded on this installation (public demo accounts on a local development app).
const DEMO = [
  ["Agent", "agent@larkspur.demo", "Agent#Demo2026"],
  ["Supervisor", "supervisor@larkspur.demo", "Supervisor#Demo2026"],
  ["Viewer", "viewer@larkspur.demo", "Viewer#Demo2026"],
  ["Administrator", "admin@larkspur.demo", "Admin#Demo2026"],
];

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const [form, setForm] = useState({ email: "", password: "", name: "", org_name: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = mode === "login" ? { email: form.email, password: form.password } : form;
      const result = await api<{ csrf_token: string }>(`/api/auth/${mode}`, { method: "POST", json: body });
      setCsrf(result.csrf_token);
      window.location.href = `${BASE}/call/`;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <section className="auth__stage" aria-label="About VoiceOps AI">
        <OrbShape voice="assistant" />
        <h2>Calls answered by a voice agent, with a person one tap away.</h2>
        <p>Who is calling is checked before any account is discussed. Policies are cited, credits above the limit wait for a supervisor, and a colleague can take the line.</p>
      </section>
      <section className="auth__card" aria-labelledby="auth-title">
        <span className="brand"><span className="brand__orb" aria-hidden />VoiceOps AI</span>
        <h1 id="auth-title">{mode === "login" ? "Sign in" : "Create your organisation"}</h1>
        <form className="auth__form" onSubmit={submit} noValidate>
          {mode === "signup" && (
            <>
              <label className="field"><span className="label">Organisation name</span><input className="input" required value={form.org_name} onChange={set("org_name")} autoComplete="organization" /></label>
              <label className="field"><span className="label">Your name</span><input className="input" required value={form.name} onChange={set("name")} autoComplete="name" /></label>
            </>
          )}
          <label className="field"><span className="label">E-mail</span><input className="input" type="email" required value={form.email} onChange={set("email")} autoComplete="email" aria-invalid={!!error} /></label>
          <label className="field">
            <span className="label">Password</span>
            <input className="input" type="password" required value={form.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} aria-invalid={!!error} />
            {mode === "signup" && <span className="hint">At least 10 characters, with a letter and a number.</span>}
          </label>
          {error && <p className="hint hint--bad" role="alert">{error}</p>}
          <button className="btn btn--primary btn--lg btn--block" disabled={busy} aria-busy={busy}>{mode === "login" ? "Sign in" : "Create organisation"}</button>
        </form>
        <p className="hint">
          {mode === "login" ? <>New here? <Link href="/signup/">Create an organisation</Link></> : <>Already have an account? <Link href="/login/">Sign in</Link></>}
        </p>
        {mode === "login" && (
          <div className="demo">
            <span className="label">Demo accounts, Larkspur Telecom (generated data)</span>
            {DEMO.map(([role, email, password]) => (
              <div key={email} className="demo__row">
                <div><strong>{role}</strong><small>{email}</small></div>
                <button type="button" className="btn btn--sm" onClick={() => setForm({ ...form, email, password })}>Fill in</button>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
