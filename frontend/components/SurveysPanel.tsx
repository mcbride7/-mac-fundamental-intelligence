"use client";

import Link from "next/link";
import { useState } from "react";

import QuickEdit from "@/components/QuickEdit";
import { ErrorBox, Loading, Panel } from "@/components/ui";
import { patch, useApi } from "@/lib/api";

const BLUE = "#3d4fd6", RED = "#e45d5d";
const KINDS: [string, string][] = [["mpmi", "Manufacturing PMI"], ["spmi", "Services PMI"], ["conf", "Consumer confidence"]];
const LEAN_CLS: Record<string, string> = {
  "Bullish": "bg-[#3d4fd6] text-white", "Leaning bullish": "bg-[#3d4fd6]/60 text-white",
  "Bearish": "bg-[#e45d5d] text-white", "Leaning bearish": "bg-[#e45d5d]/60 text-white",
};

function n(v: number | null | undefined, signed = false) {
  if (v === null || v === undefined) return "—";
  return `${signed && v > 0 ? "+" : ""}${Number(v.toFixed(2))}`;
}

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Small line of the last 12 readings; PMIs get the 50 line. */
function Spark({ pts, pmi }: { pts: { value: number }[]; pmi: boolean }) {
  if (!pts || pts.length < 2) return <span className="text-xs text-muted">—</span>;
  const vals = pts.map((p) => p.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (pmi) { lo = Math.min(lo, 50); hi = Math.max(hi, 50); }
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const W = 96, H = 26;
  const x = (i: number) => 2 + (i / (vals.length - 1)) * (W - 4);
  const y = (v: number) => 2 + (1 - (v - lo) / (hi - lo)) * (H - 4);
  const last = vals[vals.length - 1];
  const up = last >= vals[vals.length - 2];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[26px] w-24" role="img" aria-label={`Last ${vals.length} readings`}>
      {pmi && <line x1="0" x2={W} y1={y(50)} y2={y(50)} stroke="currentColor" opacity="0.3" strokeDasharray="3 2" />}
      <polyline points={vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} fill="none" stroke={up ? BLUE : RED} strokeWidth="1.6" />
      <circle cx={x(vals.length - 1)} cy={y(last)} r="2.2" fill={up ? BLUE : RED} />
    </svg>
  );
}

export default function SurveysPanel() {
  const { data, error, loading, reload } = useApi<any>("/api/macro/surveys");
  const [kind, setKind] = useState("mpmi");
  const [ccy, setCcy] = useState("");
  const [onlyData, setOnlyData] = useState(false);
  const k = data?.kinds?.[kind];
  const pmi = kind !== "conf";
  const rows: any[] = (k?.rows || []).filter((r: any) => (!ccy || r.currency === ccy) && (!onlyData || r.actual != null));
  const ccys: string[] = Array.from(new Set((k?.rows || []).map((r: any) => r.currency)));
  const save = (code: string) => async (v: string | null, per: string | undefined, reason: string | null) => {
    await patch(`/api/macro/surveys/${code}`, { value: v, period: per, reason });
    reload();
  };
  return (
    <Panel title="PMIs & consumer confidence" collapseId="macro-surveys"
      action={<span className="text-xs text-muted">Tap an actual to type the latest reading</span>}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Survey" className="flex flex-wrap gap-1">
          {KINDS.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={kind === key} onClick={() => setKind(key)}
              className={`rounded border px-3 py-1.5 text-sm ${kind === key ? "border-verify bg-panel-2 text-text" : "border-line text-muted hover:text-text"}`}>{label}</button>
          ))}
        </div>
        <select value={ccy} onChange={(e) => setCcy(e.target.value)} aria-label="Currency"
          className="rounded border border-line bg-panel-2 px-2 py-1.5 text-sm">
          <option value="">All currencies</option>
          {ccys.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={onlyData} onChange={(e) => setOnlyData(e.target.checked)} /> Only with data</label>
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !k ? null : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {pmi ? <>
              <Tile label="In expansion (above 50)" value={`${k.expanding} of ${k.with_data}`} cls="text-[#7d8cff]" />
              <Tile label="In contraction (below 50)" value={`${k.contracting} of ${k.with_data}`} cls="text-[#ff7b7b]" />
            </> : <Tile label="Surveys with data" value={`${k.with_data} of ${k.rows.length}`} />}
            <Tile label="Improving on last reading" value={String(k.improving)} cls="text-[#9ccc65]" />
            <Tile label="Worsening on last reading" value={String(k.worsening)} cls="text-[#ff7b7b]" />
          </div>
          <div className="overflow-x-auto">
            <table className="grid-table min-w-[60rem]">
              <thead><tr>
                <th>Ccy</th><th>Survey</th><th>Period</th><th className="text-right">Actual</th><th className="text-right">Forecast</th>
                <th className="text-right">Previous</th><th className="text-right">Change</th>{pmi && <th className="text-center">vs 50</th>}
                <th>Last 12</th><th className="text-center">Lean</th><th>Next</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.indicator}>
                    <td className="font-semibold">{r.currency}</td>
                    <td className="min-w-[15rem] max-w-[20rem]">
                      <div className="truncate" title={r.name}>{r.event_id ? <Link href={`/calendar/${r.event_id}`} className="hover:underline">{r.name}</Link> : r.name}</div>
                      <div className="text-xs text-muted">{r.read || (r.actual == null ? "No reading yet: tap “add”" : "")}</div></td>
                    <td className="whitespace-nowrap text-xs text-muted">{r.period || "—"}</td>
                    <td className="text-right tabular-nums">
                      <QuickEdit label={`${r.name} actual`} initial={r.actual != null ? String(r.actual) : ""}
                        period={{ value: r.next?.period && r.actual == null ? r.next.period : nextPeriod(r) , quarterly: r.frequency === "quarterly" }}
                        onSave={save(r.indicator)}
                        display={<span className={r.actual == null ? "text-muted" : pmi ? (r.actual > 50 ? "text-[#7d8cff]" : r.actual < 50 ? "text-[#ff7b7b]" : "") : ""}>{r.actual == null ? "add" : n(r.actual)}</span>} />
                    </td>
                    <td className="text-right tabular-nums">{n(r.forecast)}</td>
                    <td className="text-right tabular-nums text-muted">{n(r.previous)}</td>
                    <td className={`text-right tabular-nums ${r.change > 0 ? "text-[#9ccc65]" : r.change < 0 ? "text-[#ff7b7b]" : ""}`}>{n(r.change, true)}</td>
                    {pmi && <td className="text-center">{r.actual == null ? "—" :
                      <span className={`rounded px-1.5 py-0.5 text-xs ${r.actual > 50 ? "bg-[#3d4fd6]/25 text-[#9aa6ff]" : r.actual < 50 ? "bg-[#e45d5d]/25 text-[#ff9b9b]" : "bg-panel-2"}`}>
                        {r.actual > 50 ? "Expansion" : r.actual < 50 ? "Contraction" : "Flat"}</span>}</td>}
                    <td><Spark pts={r.history || []} pmi={pmi} /></td>
                    <td className="text-center">{r.lean ? <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-xs ${LEAN_CLS[r.lean] || "bg-panel-2 text-muted"}`}>{r.lean}</span> : "—"}</td>
                    
                    <td className="whitespace-nowrap text-xs text-muted">{r.next ? `${new Date(r.next.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })}${r.next.forecast != null ? ` · f ${n(r.next.forecast)}` : ""}` : "—"}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={11} className="py-4 text-center text-muted">Nothing to show with these filters.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">
            {pmi ? "PMIs: above 50 means the sector is growing, below 50 shrinking. " : "Consumer confidence: each survey has its own scale, so a reading is compared with its own last 12 readings. "}
            Lean adds up three signals (+1 / −1 each): {pmi ? "above or below 50" : "above or below its average"}, up or down on the previous reading, and beat or miss on the forecast.
            Stronger readings are bullish for the currency and its stocks. These also feed the mPMI, sPMI and Cnsmr conf columns in Top setups and the economic heatmap below.
          </p>
        </>
      )}
    </Panel>
  );
}

function nextPeriod(r: any): string {
  const p: string | undefined = r.period;
  if (!p) return thisMonth();
  if (/^\d{4}Q[1-4]$/.test(p)) {
    const y = Number(p.slice(0, 4)), q = Number(p.slice(5));
    return q === 4 ? `${y + 1}Q1` : `${y}Q${q + 1}`;
  }
  const m = /^(\d{4})-(\d{2})/.exec(p);
  if (!m) return thisMonth();
  const y = Number(m[1]), mo = Number(m[2]);
  return mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, "0")}`;
}

function Tile({ label, value, cls = "" }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded border border-line bg-panel-2/50 px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${cls}`}>{value}</div>
    </div>
  );
}
