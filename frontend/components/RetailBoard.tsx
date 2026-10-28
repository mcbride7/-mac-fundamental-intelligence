"use client";

import { useState } from "react";

import QuickEdit from "@/components/QuickEdit";
import { ErrorBox, Loading, Panel } from "@/components/ui";
import { put, useApi } from "@/lib/api";

const BLUE = "var(--color-bull)", RED = "var(--color-bear)";
const GROUPS: [string, (s: string) => boolean][] = [
  ["Majors", (s) => s.includes("USD") && !["USDZAR", "USDMXN", "XAUUSD", "XAGUSD"].includes(s)],
  ["Crosses", (s) => !s.includes("USD")],
  ["Emerging & metals", (s) => ["USDZAR", "USDMXN", "XAUUSD", "XAGUSD"].includes(s)],
];

function History({ points }: { points: { d: string; long_pct: number }[] }) {
  if (points.length < 2) return <p className="text-xs text-muted">The history line appears once there are readings on two or more days.</p>;
  const W = 640, H = 170, L = 34, R = 10, T = 10, B = 24;
  const x = (i: number) => L + (i / (points.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.long_pct).toFixed(1)}`).join(" ");
  const ticks = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-3xl" role="img" aria-label="Retail long percentage over time">
      <rect x={L} y={y(100)} width={W - L - R} height={y(70) - y(100)} fill={RED} opacity="0.08" />
      <rect x={L} y={y(30)} width={W - L - R} height={y(0) - y(30)} fill={BLUE} opacity="0.08" />
      {[0, 30, 50, 70, 100].map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="currentColor" opacity={v === 50 ? 0.35 : 0.12} strokeDasharray={v === 50 ? "4 3" : undefined} />
          <text x={L - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.6">{v}%</text>
        </g>
      ))}
      <path d={path} fill="none" stroke={BLUE} strokeWidth="2" />
      {points.map((p, i) => <circle key={p.d} cx={x(i)} cy={y(p.long_pct)} r="2.5" fill={BLUE}><title>{`${p.d}: ${p.long_pct}% long`}</title></circle>)}
      {ticks.map((i) => <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} fontSize="10" fill="currentColor" opacity="0.6">{points[i].d.slice(5)}</text>)}
    </svg>
  );
}

export default function RetailBoard() {
  const { data, error, loading, reload } = useApi<any>("/api/setups/retail?days=60");
  const [sel, setSel] = useState("EURUSD");
  const [all, setAll] = useState(false);
  if (error) return <Panel title="Retail sentiment"><ErrorBox error={error} /></Panel>;
  if (loading && !data) return <Panel title="Retail sentiment"><Loading /></Panel>;
  if (!data) return null;
  const every: any[] = data.symbols;
  const withData = every.filter((s) => s.long_pct != null);
  const syms = all ? every : withData;
  const job = data.job;
  const cur = every.find((s) => s.symbol === sel && s.long_pct != null) || withData[0] || every[0];
  const save = (sym: string) => async (v: string | null) => { await put(`/api/setups/retail/${sym}`, { long_pct: Number(v) }); reload(); };
  return (
    <Panel title="Retail sentiment" collapseId="cot-retail" action={<span className="text-xs text-muted">Share of retail traders long vs short · tap a row for its history · tap a % to type one in</span>}>
      {!data.live && (
        <div className="mb-3 rounded border-l-4 border-amber bg-panel-2/60 px-3 py-2 text-sm">
          <p className="font-medium">No live retail data yet.</p>
          {!data.myfxbook ? (
            <p className="mt-1">The <b>api</b> service can&rsquo;t see your Myfxbook login. In Railway, check that <code>MYFXBOOK_EMAIL</code> and <code>MYFXBOOK_PASSWORD</code> are on <b>api</b> (and <b>worker</b>), spelled exactly like that, then redeploy api and press Run now on Data health.</p>
          ) : job?.last_error ? (
            <p className="mt-1">Myfxbook&rsquo;s last run failed: <span className="text-amber">{job.last_error}</span></p>
          ) : (
            <p className="mt-1">Myfxbook login is set. Press <b>Run now</b> next to Myfxbook on Data health (it also runs every 2 hours).</p>
          )}
          {job?.last_attempt_at && <p className="mt-1 text-xs text-muted">Last run {new Date(job.last_attempt_at).toLocaleString()} · {job.records_last_run} symbols saved · status {job.status}</p>}
          <p className="mt-1 text-xs text-muted">Or tap &ldquo;no data&rdquo; next to a pair (press &ldquo;Show all&rdquo;) to type a long % in yourself.</p>
        </div>
      )}
      <div className="grid gap-x-8 gap-y-4 lg:grid-cols-3">
        {GROUPS.filter(([, f]) => syms.some((s) => f(s.symbol))).map(([g, f]) => (
          <div key={g}>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-muted">{g}</h3>
            <ul className="space-y-1.5">
              {syms.filter((s) => f(s.symbol)).map((s) => (
                <li key={s.symbol} onClick={() => setSel(s.symbol)}
                  className={`cursor-pointer rounded px-1.5 py-1 hover:bg-panel-2/60 ${s.symbol === cur?.symbol ? "bg-panel-2/60" : ""}`}>
                  <div className="mb-0.5 flex items-center justify-between text-xs">
                    <span className="font-semibold">{s.name}</span>
                    <span className="text-muted" onClick={(e) => e.stopPropagation()}>
                      <QuickEdit label={`${s.name} retail long %`} initial={s.long_pct != null ? String(s.long_pct) : ""} onSave={save(s.symbol)}
                        display={s.long_pct == null ? "no data" : <>{s.long_pct}% long{s.change_week != null && <span className={s.change_week > 0 ? "text-up" : s.change_week < 0 ? "text-bear-soft" : ""}> ({s.change_week > 0 ? "+" : ""}{s.change_week} wk)</span>}{s.stale && " · old"}</>} />
                    </span>
                  </div>
                  <div className={`flex h-4 overflow-hidden rounded text-[0.65rem] font-semibold leading-4 text-white ${s.stale ? "opacity-50" : ""}`}>
                    {s.long_pct == null ? <div className="w-full bg-panel-2" /> : <>
                      <div style={{ width: `${s.long_pct}%`, background: BLUE }} className="pl-1">{s.long_pct >= 15 ? `${Math.round(s.long_pct)}%` : ""}</div>
                      <div style={{ width: `${s.short_pct}%`, background: RED }} className="pr-1 text-right">{s.short_pct >= 15 ? `${Math.round(s.short_pct)}%` : ""}</div>
                    </>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {withData.length < every.length && (
        <button className="mt-3 rounded border border-line px-2 py-1 text-xs hover:bg-panel-2" onClick={() => setAll(!all)}>
          {all ? `Show only the ${withData.length} with data` : `Show all ${every.length} pairs and metals`}</button>
      )}
      {cur && cur.long_pct != null && (
        <div className="mt-5 border-t border-line pt-4">
          <h3 className="mb-1 font-medium">{cur.name}: retail long % over 60 days</h3>
          {cur.long_pct != null && <p className="mb-2 text-sm text-muted">{cur.long_pct}% long / {cur.short_pct}% short · {cur.read} · {cur.source}, {new Date(cur.as_of).toLocaleString()}</p>}
          <History points={cur.history} />
        </div>
      )}
      <p className="mt-3 text-xs text-muted">Blue = long, red = short. Retail sentiment is read contrarian: when 60%+ of retail traders are long it leans bearish, 40% or less leans bullish (70% / 30% is a strong signal).
        Readings older than 3 days are faded and don&rsquo;t count in Top setups. Source: Myfxbook Community Outlook or values typed in.</p>
    </Panel>
  );
}
