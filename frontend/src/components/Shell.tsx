"use client";

import { BookOpen, ClipboardCheck, History, LogOut, Menu, Mic, Moon, Radio, Settings, ShieldCheck, Sun, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, useApi, useMe } from "@/lib/api";
import type { Role } from "@/lib/types";
import { Loading, ToastProvider } from "./ui";

const NAV: { href: string; label: string; icon: typeof Mic; roles: Role[] }[] = [
  { href: "/call/", label: "Call", icon: Mic, roles: ["viewer", "agent", "supervisor", "admin"] },
  { href: "/live/", label: "Live", icon: Radio, roles: ["agent", "supervisor", "admin"] },
  { href: "/approvals/", label: "Approvals", icon: ClipboardCheck, roles: ["supervisor", "admin"] },
  { href: "/calls/", label: "Calls", icon: History, roles: ["viewer", "agent", "supervisor", "admin"] },
  { href: "/customers/", label: "Customers", icon: Users, roles: ["agent", "supervisor", "admin"] },
  { href: "/knowledge/", label: "Knowledge", icon: BookOpen, roles: ["viewer", "agent", "supervisor", "admin"] },
  { href: "/evaluation/", label: "Evaluation", icon: ShieldCheck, roles: ["viewer", "agent", "supervisor", "admin"] },
  { href: "/admin/", label: "Administration", icon: Settings, roles: ["admin"] },
];

function useTheme() {
  const [theme, setTheme] = useState("dark");
  useEffect(() => setTheme(document.documentElement.dataset.theme ?? "dark"), []);
  return [theme, () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* private mode */ }
    setTheme(next);
  }] as const;
}

/** The menu drawer: every destination the role may use, opened from the strip. */
function MenuDrawer({ items, path, onClose, returnFocus }: { items: typeof NAV; path: string; onClose: () => void; returnFocus: () => void }) {
  const close = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    close.current?.focus();
    return () => returnFocus();
    // Focus goes back to the Menu button once, when the drawer closes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <>
      <div className="scrim" aria-hidden onClick={onClose} />
      <aside id="menu" className="sheet" role="dialog" aria-modal="true" aria-label="Menu" onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <div className="sheet__head">
          <span className="brand"><span className="brand__orb" aria-hidden />VoiceOps AI</span>
          <button ref={close} className="btn btn--quiet btn--sm" onClick={onClose} aria-label="Close menu"><X aria-hidden />Close</button>
        </div>
        <nav aria-label="Main" className="sheet__nav">
          {items.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className="sheet__link" aria-current={path.startsWith(href.slice(0, -1)) ? "page" : undefined}>
              <Icon aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
      </aside>
    </>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { user, signedOut, isLoading } = useMe();
  const router = useRouter();
  const path = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement | null>(null);
  const accountBox = useRef<HTMLDivElement | null>(null);
  const [theme, toggleTheme] = useTheme();
  const live = useApi<{ calls: unknown[] }>(user && user.role !== "viewer" ? "/api/calls?status=open" : null, { refreshInterval: 10_000 });
  const credits = useApi<{ credits: unknown[] }>(user && ["supervisor", "admin"].includes(user.role) ? "/api/credits" : null, { refreshInterval: 10_000 });
  const liveCount = live.data?.calls.length ?? 0;
  const creditCount = credits.data?.credits.length ?? 0;

  useEffect(() => { if (signedOut) router.replace("/login/"); }, [signedOut, router]);
  useEffect(() => { setMenuOpen(false); setAccountOpen(false); }, [path]);
  useEffect(() => {
    if (!accountOpen) return;
    const outside = (e: PointerEvent) => { if (!accountBox.current?.contains(e.target as Node)) setAccountOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setAccountOpen(false); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", key); };
  }, [accountOpen]);

  if (isLoading || !user) return <Loading rows={6} label="Signing in" />;
  const signOut = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login/";
  };
  const items = NAV.filter((n) => n.roles.includes(user.role));
  const initial = (user.name || user.email).trim().charAt(0).toUpperCase();
  return (
    <ToastProvider>
      <div className="app">
        <header className="strip">
          <Link href="/call/" className="brand"><span className="brand__orb" aria-hidden />VoiceOps AI</Link>
          <div className="counts" role="group" aria-label="Right now">
            {user.role !== "viewer" && (
              <Link href="/live/" className="count" data-hot={liveCount > 0 ? "true" : undefined}>live calls <b>{liveCount}</b></Link>
            )}
            {["supervisor", "admin"].includes(user.role) && (
              <Link href="/approvals/" className="count" data-hot={creditCount > 0 ? "true" : undefined}>credits waiting <b>{creditCount}</b></Link>
            )}
          </div>
          <div className="strip__end" ref={accountBox}>
            <button ref={menuButton} className="btn btn--sm" onClick={() => { setAccountOpen(false); setMenuOpen((o) => !o); }} aria-expanded={menuOpen} aria-controls="menu">
              <Menu aria-hidden />Menu
            </button>
            <button className="account" onClick={() => setAccountOpen((o) => !o)} aria-expanded={accountOpen} aria-controls="account" aria-label={`Account of ${user.name || user.email}`}>
              {initial}
            </button>
            {accountOpen && (
              <div className="account__pop" id="account">
                <div className="account__who">
                  <strong>{user.name || user.email}</strong>
                  <span className="readout">{user.email}</span>
                  <span className="chip">{user.role}</span>
                </div>
                <button className="btn btn--quiet" onClick={toggleTheme}>
                  {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
                  {theme === "dark" ? "Light theme" : "Dark theme"}
                </button>
                <button className="btn btn--quiet" onClick={signOut}><LogOut aria-hidden />Sign out</button>
              </div>
            )}
          </div>
        </header>
        {menuOpen && <MenuDrawer items={items} path={path} onClose={() => setMenuOpen(false)} returnFocus={() => menuButton.current?.focus()} />}
        <main className="main">{children}</main>
      </div>
    </ToastProvider>
  );
}

export function Page({ title, lede, actions, wide, children }: { title: string; lede?: string; actions?: ReactNode; wide?: boolean; children: ReactNode }) {
  return (
    <div className={wide ? "page page--wide" : "page"}>
      <header className="page__head">
        <div className="page__title">
          <h1>{title}</h1>
          {lede && <p className="lede">{lede}</p>}
        </div>
        {actions && <div className="page__actions">{actions}</div>}
      </header>
      {children}
    </div>
  );
}
