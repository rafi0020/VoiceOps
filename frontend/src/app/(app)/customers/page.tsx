"use client";

import { Search as SearchIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Page } from "@/components/Shell";
import { Drawer, Empty, ErrorState, Loading, StatusChip } from "@/components/ui";
import { useApi } from "@/lib/api";
import { day, initials, when } from "@/lib/format";
import type { Summary } from "@/lib/types";

interface Row { id: string; name: string; account_number: string; postcode: string }
interface Detail {
  id: string; name: string; account_number: string; phone: string; postcode: string; email: string | null; vulnerable: boolean;
  services: { kind: string; plan: string; monthly_price: string; area: string; status: string; contract_ends: string | null }[];
  bills: { issued_on: string; total: string; status: string }[];
  tickets: { id: string; category: string; summary: string; status: string; opened_by: string; created_at: string }[];
  credits: { amount: string; status: string; reason: string; requested_at: string }[];
  calls: { id: string; status: string; started_at: string; summary: Summary | null }[];
}

/** One customer's account: details, services, bills, tickets and recent calls. It lives in the drawer. */
function Account({ id }: { id: string }) {
  const c = useApi<Detail>(`/api/customers/${id}`);
  if (c.error) return <ErrorState error={c.error} retry={() => c.mutate()} />;
  if (!c.data) return <Loading rows={6} />;
  const d = c.data;
  return (
    <>
      <div className="account-head">
        <span className="avatar avatar--lg" aria-hidden>{initials(d.name)}</span>
        <div className="stack">
          <h3>{d.name}</h3>
          <span className="readout">Account {d.account_number}</span>
        </div>
      </div>
      {d.vulnerable && <div className="banner banner--person" role="status">This customer needs extra support.</div>}
      <section className="drawer-section" aria-labelledby="contact">
        <h3 id="contact">Contact</h3>
        <dl className="facts">
          <div><dt>Phone</dt><dd className="readout">{d.phone}</dd></div>
          <div><dt>E-mail</dt><dd>{d.email ?? "None on file"}</dd></div>
          <div><dt>Postcode</dt><dd>{d.postcode}</dd></div>
        </dl>
      </section>
      <section className="drawer-section" aria-labelledby="services">
        <h3 id="services">Services</h3>
        {d.services.length ? (
          <ul className="rows rows--stack">{d.services.map((s, i) => (
            <li key={i}>
              <span><strong>{s.plan}</strong> <span className="hint">({s.kind})</span></span>
              <span className="readout">{s.monthly_price}</span>
              <span className="hint">{s.area}{s.contract_ends ? `, ends ${day(s.contract_ends)}` : ""}</span>
              <span className="chip">{s.status.replace(/_/g, " ")}</span>
            </li>
          ))}</ul>
        ) : <p className="hint">No services on this account.</p>}
      </section>
      <section className="drawer-section" aria-labelledby="bills">
        <h3 id="bills">Bills</h3>
        {d.bills.length ? (
          <ul className="rows">{d.bills.map((b, i) => (
            <li key={i}>
              <span>{day(b.issued_on)}</span>
              <span className="readout">{b.total}</span>
              <StatusChip status={b.status === "paid" ? "applied" : b.status === "overdue" ? "refused" : "pending"} label={b.status} />
            </li>
          ))}</ul>
        ) : <p className="hint">No bills yet.</p>}
      </section>
      <section className="drawer-section" aria-labelledby="tickets">
        <h3 id="tickets">Tickets</h3>
        {d.tickets.length ? (
          <ul className="rows rows--stack">{d.tickets.map((t) => (
            <li key={t.id}>
              <span><strong>{t.category}</strong> <span className="hint">{when(t.created_at)}, opened by {t.opened_by === "ai" ? "the assistant" : "a person"}</span></span>
              <span className="ink-2">{t.summary}</span>
            </li>
          ))}</ul>
        ) : <p className="hint">No tickets.</p>}
      </section>
      <section className="drawer-section" aria-labelledby="recent">
        <h3 id="recent">Recent calls and credits</h3>
        <ul className="rows rows--stack">
          {d.calls.map((k) => (
            <li key={k.id}>
              <Link href={`/calls/?id=${k.id}`}>{when(k.started_at)}</Link>
              <span className="ink-2">{k.summary?.reason ?? k.status}</span>
            </li>
          ))}
          {d.credits.map((cr, i) => <li key={`c${i}`} className="readout">Credit {cr.amount} {cr.status}: {cr.reason}</li>)}
          {!d.calls.length && !d.credits.length && <li className="hint">None yet.</li>}
        </ul>
      </section>
    </>
  );
}

function Search() {
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(useSearchParams().get("id"));
  const found = useApi<{ customers: Row[] }>(`/api/customers?q=${encodeURIComponent(q)}`, { keepPreviousData: true });
  return (
    <Page title="Customers" lede="Find a customer by name, account number or phone, then open the account for its services, bills and recent calls.">
      <div className="search">
        <SearchIcon aria-hidden />
        <input className="input input--search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, account number or phone" aria-label="Search customers" />
      </div>
      {found.error && <ErrorState error={found.error} />}
      {found.data && !found.data.customers.length && <div className="panel"><Empty title="No customer matches">Try part of a name, or the account number as it is printed on a bill.</Empty></div>}
      {!!found.data?.customers.length && (
        <ul className="customer-grid">
          {found.data.customers.map((c) => (
            <li key={c.id}>
              <button type="button" className="soft-button customer-card" aria-current={openId === c.id ? "true" : undefined} onClick={() => setOpenId(c.id)}>
                <span className="avatar" aria-hidden>{initials(c.name)}</span>
                <span className="customer-card__body">
                  <span className="customer-card__name">{c.name}</span>
                  <span className="customer-card__meta">
                    <span className="readout">{c.account_number}</span>
                    <span>{c.postcode}</span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {openId && (
        <Drawer title="Customer account" onClose={() => setOpenId(null)}>
          <Account key={openId} id={openId} />
        </Drawer>
      )}
    </Page>
  );
}

export default function Customers() {
  return <Suspense fallback={<Loading />}><Search /></Suspense>;
}
