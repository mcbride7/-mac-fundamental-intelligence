"use client";

import { useState } from "react";

import { Button, ErrorBox, Loading, Panel } from "@/components/ui";
import { del, post, useApi } from "@/lib/api";

function pct(v: number | null | undefined) {
  if (v === null || v === undefined) return <span className="text-muted">—</span>;
  return <span className={v > 0 ? "text-up" : v < 0 ? "text-bear-soft" : "text-muted"}>{v > 0 ? "+" : ""}{v.toFixed(2)}%</span>;
}

/** Where today's price sits between the day's low and high. */
function Range({ low, high, price }: { low?: number; high?: number; price?: number }) {
  if (low == null || high == null || price == null || high <= low) return <span className="text-muted">—</span>;
  const p = Math.max(0, Math.min(100, ((price - low) / (high - low)) * 100));
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted" title={`Day range ${low.toFixed(2)} – ${high.toFixed(2)}`}>
      {low.toFixed(2)}
      <span className="relative inline-block h-1.5 w-16 rounded bg-panel-2">
        <span className="absolute top-1/2 h-2.5 w-1 -translate-y-1/2 rounded bg-verify" style={{ left: `calc(${p}% - 2px)` }} />
      </span>
      {high.toFixed(2)}
    </span>
  );
}

function ago(iso: string | null) {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${Math.max(0, m)}m ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function EquitiesPanel() {
  const { data, error, loading, reload } = useApi<any>("/api/markets/equities");
  const [group, setGroup] = useState("US indices");
  const [sort, setSort] = useState<"list" | "best" | "worst">("list");
  const [sym, setSym] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = async () => {
    setBusy(true); setMsg(null);
    try { const r = await post("/api/markets/equities/refresh"); setMsg(r.status === "OK" ? "Updated." : r.error || "Failed"); reload(); }
    catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  const add = async () => {
    try { await post("/api/markets/equities", { symbol: sym }); setSym(""); setGroup("My list"); reload(); }
    catch (e: any) { setMsg(e.message); }
  };
  const remove = async (s: string) => { await del(`/api/markets/equities/${s}`); reload(); };
  let rows: any[] = (data?.rows || []).filter((r: any) => group === "All" || r.group === group);
  if (sort !== "list") rows = [...rows].sort((a, b) => ((b.change_pct ?? -999) - (a.change_pct ?? -999)) * (sort === "best" ? 1 : -1));
  return (
    <Panel title="Equities" collapseId="markets-equities"
      action={<span className="flex items-center gap-2 text-xs text-muted">
        {data && data.breadth.up + data.breadth.down > 0 && <span>{data.breadth.up} up · {data.breadth.down} down today</span>}
        <Button onClick={refresh} disabled={busy}>{busy ? "Fetching… (about a minute)" : "Refresh now"}</Button></span>}>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !data ? null : (
        <>
          {!data.has_key && (
            <p className="mb-3 rounded border-l-4 border-amber bg-panel-2/60 px-3 py-2 text-sm">
              Add <code>FINNHUB_API_KEY</code> (free from finnhub.io) on <b>api</b> and <b>worker</b> in Railway to load equity prices.</p>
          )}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div role="tablist" aria-label="Group" className="flex flex-wrap gap-1">
              {[...data.groups, "All"].map((g: string) => (
                <button key={g} role="tab" aria-selected={group === g} onClick={() => setGroup(g)}
                  className={`rounded border px-3 py-1.5 text-sm ${group === g ? "border-verify bg-panel-2 text-text" : "border-line text-muted hover:text-text"}`}>{g}</button>
              ))}
            </div>
            <select value={sort} onChange={(e) => setSort(e.target.value as any)} aria-label="Sort"
              className="rounded border border-line bg-panel-2 px-2 py-1.5 text-sm">
              <option value="list">Default order</option><option value="best">Best today first</option><option value="worst">Worst today first</option>
            </select>
          </div>
          <div className="overflow-x-auto">
            <table className="grid-table min-w-[48rem]">
              <thead><tr><th>Symbol</th><th>Name</th><th className="text-right">Price</th><th className="text-right">Today</th>
                <th>Day range</th><th className="text-right">1 week</th><th className="text-right">1 month</th><th>Updated</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol}>
                    <td className="font-semibold">{r.symbol}</td>
                    <td className="text-muted">{r.name}{r.currency && <span className="ml-1.5 rounded border border-line px-1 text-[0.65rem]">{r.currency}</span>}</td>
                    <td className="text-right tabular-nums">{r.price != null ? r.price.toFixed(2) : "—"}</td>
                    <td className="text-right tabular-nums">{pct(r.change_pct)}</td>
                    <td><Range low={r.low} high={r.high} price={r.price} /></td>
                    <td className="text-right tabular-nums">{pct(r.change_1w_pct)}</td>
                    <td className="text-right tabular-nums">{pct(r.change_1m_pct)}</td>
                    <td className="whitespace-nowrap text-xs text-muted">{ago(r.quote_time)}</td>
                    <td>{r.custom && <button onClick={() => remove(r.symbol)} title={`Remove ${r.symbol}`} className="text-xs text-muted hover:text-hawk">✕</button>}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={9} className="py-4 text-center text-muted">Nothing here yet.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <input value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} placeholder="Add a ticker, e.g. PLTR"
              onKeyDown={(e) => e.key === "Enter" && sym && add()}
              className="w-44 rounded border border-line bg-panel-2 px-2 py-1.5" />
            <Button onClick={add} disabled={!sym}>Add to my list</Button>
            {msg && <span className="text-xs text-muted">{msg}</span>}
          </div>
          <p className="mt-2 text-xs text-muted">Source: Finnhub, updated every 15 minutes (US stocks and ETFs, real-time on the free plan). Index levels need a paid plan, so
            indices and countries are shown through the ETFs that track them (SPY = S&amp;P 500, EWJ = Japan). The currency tag links a country fund to its
            currency. 1-week and 1-month changes fill in as prices build up.</p>
        </>
      )}
    </Panel>
  );
}
