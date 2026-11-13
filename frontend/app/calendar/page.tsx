"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Empty, ErrorBox, Loading, PageTitle, StatusBadge } from "@/components/ui";
import { patch, useApi } from "@/lib/api";
import { num, signed, toneClass } from "@/lib/format";

const IMPORTANCE: Record<string, { mark: string; label: string; cls: string }> = {
  high: { mark: "●", label: "High", cls: "text-hawk" },
  medium: { mark: "●", label: "Medium", cls: "text-amber" },
  low: { mark: "●", label: "Low", cls: "text-dove" },
};

// Release times are stored in UTC and shown in the viewer's own time zone (Johannesburg = UTC+2).
function tzLabel() {
  const off = -new Date().getTimezoneOffset() / 60;
  return off === 0 ? "UTC" : `your time, UTC${off > 0 ? "+" : "−"}${Math.abs(off)}`;
}
const localTime = (iso: string | null | undefined, fallback: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false }) : fallback;
};

// A number you can click to change. Enter saves, Esc cancels. An actual goes through the same
// checks as Data input; if it looks unusual the API asks for a reason before saving it.
const FIELD_LABEL: Record<string, string> = { consensus: "forecast", cb_projection: "CB projection" };

function EditableCell({ eventId, field, value, digits, unit, strong, onSaved, signedValue, title }: {
  eventId: number; field: "actual" | "consensus" | "previous" | "cb_projection" | "surprise"; value: number | null;
  digits: number; unit: string; strong?: boolean; onSaved: () => void; signedValue?: boolean; title?: string;
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
      <button type="button" onClick={open} title={title ? `${title}. Click to edit` : "Click to edit"}
        className={`-mx-1 rounded px-1 text-left underline decoration-muted decoration-dotted decoration-2 underline-offset-4 hover:bg-panel-2 hover:outline hover:outline-1 hover:outline-line ${strong ? "font-medium" : ""}`}>
        {value === null || value === undefined ? <span className="text-muted">—</span>
          : signedValue ? signed(value, digits) : num(value, digits, unit)}
      </button>
    );
  }
  return (
    <div className="min-w-[7rem]">
      <input ref={input} value={text} onChange={(e) => setText(e.target.value)} disabled={busy} inputMode="decimal"
        aria-label={`New ${FIELD_LABEL[field] || field}`}
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

const IMP_DOTS: Record<string, [string, string, string]> = {
  high: ["●●●", "text-bear-soft", "High impact"], medium: ["●●○", "text-amber", "Medium impact"], low: ["●○○", "text-muted", "Low impact"],
};
const SPEECH = /speech|speaks|testimony|press conference|meeting|minutes|hearing|statement/i;
const LOWER_IS_GOOD = /unemploy|jobless|claims|deficit/i;
const fmtVal = (v: number | null | undefined, unit?: string | null) => {
  if (v == null) return "";
  const s = Math.abs(v) >= 100 ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : `${+v.toFixed(2)}`;
  return s + (unit === "%" ? "%" : unit === "B" || unit === "M" || unit === "K" ? unit : "");
};
const dayKey = (iso: string) => { const d = new Date(iso); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; };
const dayTitle = (iso: string) => new Date(iso).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });

/** Colour of an actual: green = better than forecast for the currency, red = worse. */
function beatClass(actual: number | null | undefined, forecast: number | null | undefined, higherIsGood: boolean) {
  if (actual == null || forecast == null || actual === forecast) return "text-text";
  return (actual > forecast) === higherIsGood ? "text-up" : "text-bear-soft";
}

export default function Calendar() {
  const [tz, setTz] = useState("your time");
  useEffect(() => { setTz(tzLabel()); }, []);
  const [f, setF] = useState({ currency: "", importance: "", category: "", status: "", days: "14" });
  const today = new Date();
  const end = new Date(today.getTime() + +f.days * 86400000).toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 7 * 86400000).toISOString().slice(0, 10);
  const qs = new URLSearchParams({ start, end, ...Object.fromEntries(Object.entries(f).filter(([k, v]) => v && k !== "days")) });
  const { data, error, loading, reload } = useApi<any[]>(`/api/economic-calendar?${qs}`);
  const feed = useApi<any>(`/api/economic-calendar/feed?start=${start}&end=${end}`);
  const [scope, setScope] = useState<"all" | "tracked">("all");
  // tracked events (editable) plus every other FMP event for these currencies (read-only)
  const rows = useMemo(() => {
    const tracked = (data || []).map((e: any) => ({ kind: "tracked", at: e.scheduled_at, e }));
    if (scope === "tracked" || f.category || f.status) return tracked;
    const have = new Set((data || []).map((e: any) => `${e.indicator}|${dayKey(e.scheduled_at)}`));
    const extra = ((feed.data?.items) || [])
      .filter((x: any) => !(x.indicator && have.has(`${x.indicator}|${dayKey(x.scheduled_at)}`)))
      .filter((x: any) => !f.currency || x.currency === f.currency)
      .filter((x: any) => !f.importance || x.impact === f.importance)
      .map((x: any) => ({ kind: "feed", at: x.scheduled_at, e: x }));
    return [...tracked, ...extra].sort((a, b) => +new Date(a.at) - +new Date(b.at));
  }, [data, feed.data, scope, f]);
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
      <PageTitle title="Economic calendar" subtitle="Every release for your currencies, by day in your time. Click any number on a tracked event to change it; the analysis re-runs when you save." />
      <div className="mb-4 flex flex-wrap gap-4">
        {sel("currency", [["", "All"], ...["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY"].map((c) => [c, c] as [string, string])])}
        {sel("importance", [["", "All"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]])}
        {sel("category", [["", "All"], ["inflation", "Inflation"], ["employment", "Employment"], ["growth", "Growth"], ["business", "Business"], ["consumers", "Consumers"], ["monetary_policy", "Monetary policy"]])}
        {sel("status", [["", "All"], ["missing", "Missing"], ["unverified", "Unverified"], ["user_confirmed", "User-confirmed"], ["verified", "Verified"], ["scheduled", "Scheduled"]])}
        {sel("days", [["7", "Next 7 days"], ["14", "Next 14 days"], ["30", "Next 30 days"]])}
        <div className="flex items-center gap-1 text-sm" role="group" aria-label="Which events">
          {([["all", "All events"], ["tracked", "Tracked only"]] as const).map(([v, l]) => (
            <button key={v} onClick={() => setScope(v)} aria-pressed={scope === v}
              className={`rounded border px-2 py-1 ${scope === v ? "border-verify bg-panel-2 text-text" : "border-line text-muted hover:text-text"}`}>{l}</button>
          ))}
        </div>
      </div>
      {feed.data?.error && scope === "all" && <p className="mb-3 text-xs text-muted">Untracked events from FMP aren&rsquo;t available right now ({feed.data.error}); showing tracked events.</p>}
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !rows.length ? (
        <Empty href="/data-input" cta="Import a calendar">No events in this range. Import a calendar via Finnhub, a CSV, or a screenshot of any calendar.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-panel">
          <table className="w-full min-w-[60rem] border-collapse text-sm tabular-nums">
            <thead><tr className="border-b border-line text-left text-xs font-semibold text-muted">
              <th className="px-3 py-2" title="Release times are shown in this device's time zone">Time ({tz})</th><th className="px-2 py-2">Ccy</th>
              <th className="px-2 py-2">Event</th><th className="px-2 py-2 text-center">Impact</th>
              <th className="px-2 py-2 text-right">Actual</th><th className="px-2 py-2 text-right">Forecast</th><th className="px-2 py-2 text-right">Previous</th>
              <th className="px-2 py-2 text-right">Surprise</th><th className="px-2 py-2 text-right">CB projection</th><th className="px-3 py-2">Data</th></tr></thead>
            <tbody>
              {rows.flatMap((r: any, i: number) => {
                const newDay = i === 0 || dayKey(rows[i - 1].at) !== dayKey(r.at);
                const head = newDay && (
                  <tr key={`d${i}`} className="bg-panel-2/70"><td colSpan={10} className="px-3 py-1.5 text-sm font-semibold text-text">{dayTitle(r.at)}</td></tr>
                );
                if (r.kind === "feed") {
                  const x = r.e, speech = SPEECH.test(x.event) && x.actual == null && x.forecast == null && x.previous == null;
                  const dots = IMP_DOTS[x.impact] || IMP_DOTS.low;
                  const surprise = x.actual != null && x.forecast != null ? x.actual - x.forecast : null;
                  const good = !LOWER_IS_GOOD.test(x.event);
                  return [head || null, (
                    <tr key={`f${i}`} className="border-b border-line/50 hover:bg-panel-2/40">
                      <td className="px-3 py-1.5 font-mono">{localTime(x.scheduled_at, "")}</td>
                      <td className="px-2 py-1.5 font-semibold">{x.currency}{x.country && !["US", "EU", "GB", "JP", "CH", "CA", "AU", "NZ", "CN", "ZA", "MX"].includes(x.country) ? <span className="ml-1 text-xs font-normal text-muted">{x.country}</span> : null}</td>
                      <td className={`px-2 py-1.5 ${speech ? "italic text-muted" : ""}`}>{x.event}</td>
                      <td className={`px-2 py-1.5 text-center ${dots[1]}`} title={dots[2]}><span aria-hidden>{dots[0]}</span><span className="sr-only">{dots[2]}</span></td>
                      <td className={`px-2 py-1.5 text-right font-semibold ${beatClass(x.actual, x.forecast, good)}`}>{fmtVal(x.actual, x.unit)}</td>
                      <td className="px-2 py-1.5 text-right text-muted">{fmtVal(x.forecast, x.unit)}</td>
                      <td className="px-2 py-1.5 text-right text-muted">{fmtVal(x.previous, x.unit)}</td>
                      <td className={`px-2 py-1.5 text-right ${beatClass(x.actual, x.forecast, good)}`}>{surprise == null ? "" : surprise === 0 ? "in line" : `${surprise > 0 ? "+" : ""}${+surprise.toFixed(2)}`}</td>
                      <td className="px-2 py-1.5" />
                      <td className="px-3 py-1.5"><span className="text-xs text-muted" title="In FMP's calendar but not one of the indicators the analysis tracks">not tracked</span></td>
                    </tr>
                  )];
                }
                const e = r.e;
                const imp = IMPORTANCE[e.importance] || IMPORTANCE.low;
                const dots = IMP_DOTS[e.importance] || IMP_DOTS.low;
                const u = e.unit === "%" ? "%" : e.unit === "k" ? "k" : "";
                const good = e.higher_is !== "dovish" && !LOWER_IS_GOOD.test(e.event);
                return [head || null, (
                  <tr key={e.event_id} className="border-b border-line/50 hover:bg-panel-2/40">
                    <td className="px-3 py-1.5 font-mono">{localTime(e.scheduled_at, e.time)}</td>
                    <td className="px-2 py-1.5 font-semibold">{e.currency}</td>
                    <td className="px-2 py-1.5">{e.release_id ? <Link href={`/calendar/${e.event_id}`} className="font-medium hover:underline">{e.event}</Link> : <span className="font-medium">{e.event}</span>}
                      <span className="ml-2 text-xs text-muted">{e.reference_period}</span></td>
                    <td className={`px-2 py-1.5 text-center ${dots[1]}`} title={`${imp.label} importance`}><span aria-hidden>{dots[0]}</span><span className="sr-only">{imp.label}</span></td>
                    <td className={`px-2 py-1.5 text-right font-semibold ${beatClass(e.actual, e.market_forecast, good)}`}><EditableCell eventId={e.event_id} field="actual" value={e.actual} digits={2} unit={u} strong onSaved={reload} /></td>
                    <td className="px-2 py-1.5 text-right"><EditableCell eventId={e.event_id} field="consensus" value={e.market_forecast} digits={2} unit={u} onSaved={reload} /></td>
                    <td className="px-2 py-1.5 text-right"><EditableCell eventId={e.event_id} field="previous" value={e.previous} digits={2} unit={u} onSaved={reload} /></td>
                    <td className={`px-2 py-1.5 text-right ${toneClass(e.surprise_class)}`}>
                      {e.actual != null
                        ? <EditableCell eventId={e.event_id} field="surprise" value={e.surprise} digits={2} unit="" signedValue onSaved={reload}
                            title={e.surprise_edited
                              ? `Your figure (calculated: ${signed(e.surprise_calculated, 2)})${e.surprise_reason ? ` – ${e.surprise_reason}` : ""}. Clear the box to go back to actual minus forecast`
                              : `${e.surprise_class || "Actual minus forecast"}`} />
                        : <span className="text-muted">—</span>}
                      {e.surprise_edited && <span className="ml-1 rounded border border-amber/60 px-1 text-[0.65rem] text-amber">edited</span>}
                    </td>
                    <td className="px-2 py-1.5 text-right">{e.projection_editable
                      ? <EditableCell eventId={e.event_id} field="cb_projection" value={e.central_bank_projection} digits={1} unit={u} onSaved={reload}
                          title="Saved as a new projection round for the central bank" />
                      : <span className="text-muted" title="No central bank publishes a projection for this indicator">{num(e.central_bank_projection, 1, u)}</span>}</td>
                    <td className="px-3 py-1.5">{e.needs_manual_input ? (
                      <Link href={`/data-input?indicator=${e.indicator}&period=${e.reference_period}`}
                        className="whitespace-nowrap rounded border border-hawk/70 px-2 py-0.5 text-xs text-hawk hover:bg-hawk/10">Provide data</Link>
                    ) : <StatusBadge status={e.data_status} title={e.badge} />}</td>
                  </tr>
                )];
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-xs text-muted">Green actual = better than forecast for the currency, red = worse. Speeches in italics. Tracked events (with a Data badge) feed the analysis and can be edited by clicking a number; &ldquo;not tracked&rdquo; events come straight from FMP&rsquo;s calendar.</p>
    </>
  );
}
