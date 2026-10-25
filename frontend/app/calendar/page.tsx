"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Empty, ErrorBox, Loading, PageTitle, StatusBadge } from "@/components/ui";
import { patch, useApi } from "@/lib/api";
import { num, signed, toneClass } from "@/lib/format";

const IMPORTANCE: Record<string, { mark: string; label: string; cls: string }> = {
  high: { mark: "●", label: "High", cls: "text-hawk" },
  medium: { mark: "●", label: "Medium", cls: "text-amber" },
  low: { mark: "●", label: "Low", cls: "text-dove" },
};

// A number you can click to change. Enter saves, Esc cancels. An actual goes through the same
// checks as Data input; if it looks unusual the API asks for a reason before saving it.
function EditableCell({ eventId, field, value, digits, unit, strong, onSaved }: {
  eventId: number; field: "actual" | "consensus" | "previous"; value: number | null; digits: number; unit: string;
  strong?: boolean; onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) input.current?.select(); }, [editing]);

  const open = () => { setText(value === null || value === undefined ? "" : String(value)); setErr(null); setNeedReason(null); setReason(""); setEditing(true); };
  const cancel = () => { setEditing(false); setErr(null); setNeedReason(null); };
  const save = async () => {
    const raw = text.trim().replace(/[%\s]/g, "").replace(",", ".").replace(/k$/i, "");
    const v = raw === "" ? null : Number(raw);
    if (v !== null && Number.isNaN(v)) { setErr("Type a number, like 3.1"); return; }
    if (v === value && !needReason) { cancel(); return; }
    setBusy(true); setErr(null);
    try {
      await patch(`/api/economic-events/${eventId}`, { field, value: v, reason: reason || null });
      setEditing(false); setNeedReason(null); onSaved();
    } catch (e: any) {
      const probs = e?.detail?.problems;
      if (probs?.length && probs.every((p: any) => p.needs === "override_reason")) {
        setNeedReason(probs.flatMap((p: any) => p.errors.map((w: any) => w.message)).join("; "));
      } else if (probs?.length) {
        setErr(probs.flatMap((p: any) => p.errors.map((w: any) => w.message)).join("; "));
      } else setErr(e?.message || String(e));
    } finally { setBusy(false); }
  };

  if (!editing) {
    return (
      <button type="button" onClick={open} title="Click to edit"
        className={`-mx-1 rounded px-1 text-left underline decoration-muted decoration-dotted decoration-2 underline-offset-4 hover:bg-panel-2 hover:outline hover:outline-1 hover:outline-line ${strong ? "font-medium" : ""}`}>
        {value === null || value === undefined ? <span className="text-muted">—</span> : num(value, digits, unit)}
      </button>
    );
  }
  return (
    <div className="min-w-[7rem]">
      <input ref={input} value={text} onChange={(e) => setText(e.target.value)} disabled={busy} inputMode="decimal"
        aria-label={`New ${field === "consensus" ? "forecast" : field}`}
        onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") cancel(); }}
        className="w-24 rounded border border-verify bg-ink px-2 py-1 text-sm text-text" />
      {needReason && (
        <div className="mt-1 text-xs text-amber">
          {needReason}. Give a reason to keep it:
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. checked on the official site"
            onKeyDown={(e) => { if (e.key === "Enter" && reason.trim()) save(); if (e.key === "Escape") cancel(); }}
            className="mt-1 block w-48 rounded border border-line bg-ink px-2 py-1 text-xs text-text" />
        </div>
      )}
      {err && <p className="mt-1 max-w-[14rem] text-xs text-hawk">{err}</p>}
      <div className="mt-1 flex gap-2 text-xs">
        <button type="button" onClick={save} disabled={busy || (!!needReason && !reason.trim())} className="text-verify disabled:opacity-50">{busy ? "Saving…" : "Save"}</button>
        <button type="button" onClick={cancel} disabled={busy} className="text-muted">Cancel</button>
      </div>
    </div>
  );
}

export default function Calendar() {
  const [f, setF] = useState({ currency: "", importance: "", category: "", status: "", days: "14" });
  const today = new Date();
  const end = new Date(today.getTime() + +f.days * 86400000).toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 7 * 86400000).toISOString().slice(0, 10);
  const qs = new URLSearchParams({ start, end, ...Object.fromEntries(Object.entries(f).filter(([k, v]) => v && k !== "days")) });
  const { data, error, loading, reload } = useApi<any[]>(`/api/economic-calendar?${qs}`);
  const sel = (k: keyof typeof f, opts: [string, string][]) => (
    <label className="text-sm text-muted">{k === "days" ? "Range" : k.replace(/^\w/, (c) => c.toUpperCase())}
      <select value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}
        className="ml-2 rounded border border-line bg-panel px-2 py-1 text-text">
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
  return (
    <>
      <PageTitle title="Economic calendar" subtitle="Market forecast, central-bank projection and actual side by side. Click any previous, forecast or actual number to change it; the analysis re-runs when you save." />
      <div className="mb-4 flex flex-wrap gap-4">
        {sel("currency", [["", "All"], ...["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY"].map((c) => [c, c] as [string, string])])}
        {sel("importance", [["", "All"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]])}
        {sel("category", [["", "All"], ["inflation", "Inflation"], ["employment", "Employment"], ["growth", "Growth"], ["business", "Business"], ["consumers", "Consumers"], ["monetary_policy", "Monetary policy"]])}
        {sel("status", [["", "All"], ["missing", "Missing"], ["unverified", "Unverified"], ["user_confirmed", "User-confirmed"], ["verified", "Verified"], ["scheduled", "Scheduled"]])}
        {sel("days", [["7", "Next 7 days"], ["14", "Next 14 days"], ["30", "Next 30 days"]])}
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !data?.length ? (
        <Empty href="/data-input" cta="Import a calendar">No events in this range. Import a calendar via Finnhub, a CSV, or a screenshot of any calendar.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-panel">
          <table className="grid-table">
            <thead><tr><th>Date</th><th>Time (UTC)</th><th>Ccy</th><th>Event</th><th></th><th>Previous</th><th>Forecast</th>
              <th>CB projection</th><th>Actual</th><th>Surprise</th><th>Data</th></tr></thead>
            <tbody>
              {data.map((e) => {
                const imp = IMPORTANCE[e.importance] || IMPORTANCE.low;
                const u = e.unit === "%" ? "%" : e.unit === "k" ? "k" : "";
                return (
                  <tr key={e.event_id}>
                    <td className="whitespace-nowrap">{e.date}</td><td>{e.time}</td><td>{e.currency}</td>
                    <td>{e.release_id ? <Link href={`/calendar/${e.event_id}`} className="hover:underline">{e.event}</Link> : e.event}
                      <span className="block text-xs text-muted">{e.reference_period}</span></td>
                    <td className={imp.cls} title={`${imp.label} importance`}><span aria-hidden>{imp.mark}</span><span className="sr-only">{imp.label}</span></td>
                    <td><EditableCell eventId={e.event_id} field="previous" value={e.previous} digits={2} unit={u} onSaved={reload} /></td>
                    <td><EditableCell eventId={e.event_id} field="consensus" value={e.market_forecast} digits={2} unit={u} onSaved={reload} /></td>
                    <td>{num(e.central_bank_projection, 1, u)}</td>
                    <td><EditableCell eventId={e.event_id} field="actual" value={e.actual} digits={2} unit={u} strong onSaved={reload} /></td>
                    <td className={toneClass(e.surprise_class)} title={e.surprise_class}>{signed(e.surprise, 2)}</td>
                    <td>{e.needs_manual_input ? (
                      <Link href={`/data-input?indicator=${e.indicator}&period=${e.reference_period}`}
                        className="whitespace-nowrap rounded border border-hawk/70 px-2 py-0.5 text-xs text-hawk hover:bg-hawk/10">Provide data</Link>
                    ) : <StatusBadge status={e.data_status} title={e.badge} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
