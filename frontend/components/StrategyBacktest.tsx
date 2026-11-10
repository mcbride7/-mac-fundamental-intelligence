"use client";

import { Fragment, useMemo, useState } from "react";

import { GradeBadge, Panel, Stat } from "@/components/ui";
import { num, signed } from "@/lib/format";
import backtest from "@/lib/strategy-backtest.json";

type Trade = {
  opened: string; closed: string; direction: "LONG" | "SHORT"; grade: string | null;
  entry: number; stop: number; target: number; result_r: number; outcome: "target" | "stop" | "expired";
  chart?: string | null;
};
type Period = { label: string; trades: number; win_rate: number | null; avg_r: number | null };
type Strategy = {
  id: string; name: string; market: string; timeframe: string; data_from: string; data_to: string; target: string;
  rules: string[];
  summary: { trades: number; per_year: number; win_rate: number; avg_r: number; total_r: number;
    max_drawdown_r: number; longest_losing_run: number };
  periods: Period[];
  yearly: { year: number; trades: number; win_rate: number | null; total_r: number }[];
  by_grade?: { grade: string; label: string; risk: string; trades: number; win_rate: number | null;
    avg_r: number | null; total_r: number }[];
  equity: [string, number][];
  trades: Trade[];
};

const DATA = backtest as unknown as { generated: string; note: string; strategies: Strategy[] };
const OUTCOME: Record<string, [string, string]> = {
  target: ["Target hit", "bg-up/20 text-up"], stop: ["Stopped out", "bg-bear-soft/20 text-bear-soft"],
  expired: ["Time exit", "bg-panel-2 text-muted"],
};
const rCls = (v: number | null | undefined) => (v == null ? "text-muted" : v > 0 ? "text-dove" : v < 0 ? "text-hawk" : "");
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(0)}%`);
const day = (s: string) => new Date(s.replace(" ", "T")).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** Cumulative result in R, one point per closed trade. The line stretches to the width;
 *  labels are HTML so they stay readable on phones. */
function EquityCurve({ points, split }: { points: [string, number][]; split?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const pts: [string, number][] = [[points[0]?.[0] ?? "", 0], ...points];
  const ys = pts.map((p) => p[1]);
  const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const pad = (hi - lo) * 0.08 || 1;
  const y0 = lo - pad, y1 = hi + pad;
  const fx = (i: number) => i / Math.max(1, pts.length - 1);          // 0..1 across
  const fy = (v: number) => 1 - (v - y0) / (y1 - y0);                  // 0..1 down
  const path = pts.map((p, i) => `${i ? "L" : "M"}${(fx(i) * 1000).toFixed(1)},${(fy(p[1]) * 100).toFixed(2)}`).join("");
  const step = Math.max(1, Math.ceil((y1 - y0) / 5));
  const ticks: number[] = [];
  for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) ticks.push(v);
  const splitIdx = split ? pts.findIndex((p, i) => i > 0 && p[0] >= split) : -1;
  const years = pts.map((p, i) => [p[0].slice(0, 4), i] as const).filter((p, i, a) => i > 0 && p[0] !== a[i - 1][0]);
  const h = hover != null ? pts[hover] : null;
  const pct = (f: number) => `${(f * 100).toFixed(2)}%`;
  return (
    <div className="relative h-60 select-none text-[11px] text-muted"
      role="img" aria-label={`Cumulative result: ${signed(ys[ys.length - 1], 1)}R over ${points.length} trades`}>
      {/* y-axis labels */}
      <div className="absolute bottom-6 left-0 top-2 w-10">
        {ticks.map((v) => (
          <span key={v} className="absolute right-1 -translate-y-1/2" style={{ top: pct(fy(v)) }}>{v > 0 ? `+${v}` : v}R</span>
        ))}
      </div>
      {/* plot area */}
      <div className="absolute bottom-6 left-11 right-2 top-2"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover(Math.max(1, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1)))));
        }}>
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible">
          {splitIdx > 0 && <rect x={fx(splitIdx) * 1000} y={0} width={1000 - fx(splitIdx) * 1000} height={100} fill="var(--color-panel-2)" opacity={0.55} />}
          {ticks.map((v) => (
            <line key={v} x1={0} x2={1000} y1={fy(v) * 100} y2={fy(v) * 100} stroke="var(--color-line)" vectorEffect="non-scaling-stroke"
              strokeWidth={v === 0 ? 1.2 : 0.6} strokeDasharray={v === 0 ? undefined : "2 4"} />
          ))}
          <path d={path} fill="none" stroke="var(--color-verify)" strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          {hover != null && <line x1={fx(hover) * 1000} x2={fx(hover) * 1000} y1={0} y2={100} stroke="var(--color-muted)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
        </svg>
        {splitIdx > 0 && <span className="absolute top-1 pl-1.5" style={{ left: pct(fx(splitIdx)) }}>unseen period</span>}
        {h && hover != null && (
          <>
            <span className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-verify"
              style={{ left: pct(fx(hover)), top: pct(fy(h[1])) }} />
            <div className="pointer-events-none absolute top-5 z-10 whitespace-nowrap rounded border border-line bg-ink px-2 py-1 text-xs text-text"
              style={fx(hover) > 0.6 ? { right: pct(1 - fx(hover)), marginRight: 8 } : { left: pct(fx(hover)), marginLeft: 8 }}>
              <div className="text-muted">{day(h[0])} · trade {hover}</div>
              <div className={rCls(h[1])}>{signed(h[1], 1)}R total</div>
            </div>
          </>
        )}
        {/* x-axis: first trade of each year, skipping labels that would sit too close together */}
        <div className="absolute -bottom-6 left-0 right-0 h-5">
          {years.reduce<(readonly [string, number])[]>((kept, y) =>
            (!kept.length || fx(y[1]) - fx(kept[kept.length - 1][1]) >= 0.11 ? [...kept, y] : kept), []).map(([yr, i]) => (
            <span key={yr} className="absolute -translate-x-1/2" style={{ left: pct(fx(i)) }}>{yr}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function StrategyBacktest() {
  const [id, setId] = useState(DATA.strategies[0].id);
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const s = DATA.strategies.find((x) => x.id === id) || DATA.strategies[0];
  const trades = useMemo(() => [...s.trades].reverse(), [s]);
  const shown = showAll ? trades : trades.slice(0, 15);
  const unseen = s.id === "ustec-h4" ? "2022-01-01" : "2025-01-01";
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {DATA.strategies.map((x) => (
          <button key={x.id} onClick={() => { setId(x.id); setShowAll(false); setOpen(null); }} aria-pressed={x.id === s.id}
            className={`rounded border px-3 py-1.5 text-sm ${x.id === s.id ? "border-verify bg-verify/15 text-verify" : "border-line text-muted hover:bg-panel-2"}`}>
            {x.name}
          </button>
        ))}
      </div>

      <p className="mb-4 rounded border border-amber/50 bg-amber/10 px-3 py-2 text-sm">
        Backtest, not live trading: these are hypothetical trades from historical {s.market} data
        ({day(s.data_from)} – {day(s.data_to)}). Past results do not guarantee future results.
      </p>

      <Panel title={`${s.name}`} action={<span className="text-xs text-muted">{s.market} · {s.timeframe} · target {s.target}</span>}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Trades" value={s.summary.trades} sub={`${num(s.summary.per_year, 1)} per year`} />
          <Stat label="Win rate" value={pct(s.summary.win_rate)} />
          <Stat label="Average result" value={`${signed(s.summary.avg_r, 2)}R`} tone={rCls(s.summary.avg_r)} sub="per trade" />
          <Stat label="Total" value={`${signed(s.summary.total_r, 1)}R`} tone={rCls(s.summary.total_r)} sub="at 1R risk per trade" />
          <Stat label="Worst drawdown" value={`${num(s.summary.max_drawdown_r, 1)}R`} tone="text-hawk" />
          <Stat label="Longest losing run" value={s.summary.longest_losing_run} sub="trades" />
        </div>
        <div className="mt-5"><EquityCurve points={s.equity} split={unseen} /></div>
        <p className="mt-1 text-xs text-muted">Cumulative result in R after each closed trade. The shaded part is the later period, which was not used to choose the rules.</p>
      </Panel>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel title="Rules chosen vs unseen period">
          <table className="grid-table">
            <thead><tr><th>Period</th><th>Trades</th><th>Win rate</th><th>Avg result</th></tr></thead>
            <tbody>
              {s.periods.map((p) => (
                <tr key={p.label}><td>{p.label}</td><td>{p.trades}</td><td>{pct(p.win_rate)}</td>
                  <td className={rCls(p.avg_r)}>{p.avg_r == null ? "—" : `${signed(p.avg_r, 2)}R`}</td></tr>
              ))}
            </tbody>
          </table>
          {s.by_grade && (
            <table className="grid-table mt-4">
              <thead><tr><th>Grade</th><th>Setup</th><th>Risk</th><th>Trades</th><th>Win rate</th><th>Avg result</th></tr></thead>
              <tbody>
                {s.by_grade.map((g) => (
                  <tr key={g.grade}><td><GradeBadge grade={g.grade} /></td><td>{g.label}</td><td>{g.risk}</td><td>{g.trades}</td>
                    <td>{pct(g.win_rate)}</td><td className={rCls(g.avg_r)}>{g.avg_r == null ? "—" : `${signed(g.avg_r, 2)}R`}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title="By year">
          <table className="grid-table">
            <thead><tr><th>Year</th><th>Trades</th><th>Win rate</th><th>Result</th></tr></thead>
            <tbody>
              {s.yearly.map((y) => (
                <tr key={y.year}><td>{y.year}</td><td>{y.trades}</td><td>{pct(y.win_rate)}</td>
                  <td className={rCls(y.total_r)}>{signed(y.total_r, 1)}R</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <div className="mt-6">
        <Panel title="Rules" collapseId="sd-backtest-rules">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {s.rules.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </Panel>
      </div>

      <div className="mt-6">
        <Panel title={`Trades (${s.trades.length})`} action={
          trades.length > 15 && (
            <button onClick={() => setShowAll((v) => !v)} className="rounded border border-line px-2 py-0.5 text-xs hover:bg-panel-2">
              {showAll ? "Show latest 15" : `Show all ${trades.length}`}
            </button>
          )}>
          <table className="grid-table">
            <thead><tr><th>Opened</th><th>Call</th>{s.by_grade && <th>Grade</th>}<th>Entry</th><th>Stop loss</th><th>Take profit</th><th>Result</th><th>Closed</th><th>Setup</th></tr></thead>
            <tbody>
              {shown.map((t) => {
                const key = t.opened + t.direction;
                const isOpen = open === key;
                return (
                  <Fragment key={key}>
                    <tr>
                      <td className="whitespace-nowrap">{day(t.opened)}</td>
                      <td>{t.direction === "LONG" ? "Buy" : "Sell"}</td>
                      {s.by_grade && <td><GradeBadge grade={t.grade} /></td>}
                      <td>{num(t.entry, 2)}</td><td>{num(t.stop, 2)}</td><td>{num(t.target, 2)}</td>
                      <td className="whitespace-nowrap">
                        <span className={`rounded px-2 py-0.5 text-xs font-semibold ${OUTCOME[t.outcome][1]}`}>
                          {OUTCOME[t.outcome][0]} {signed(t.result_r, 2)}R</span>
                      </td>
                      <td className="whitespace-nowrap text-muted">{day(t.closed)}</td>
                      <td>
                        {t.chart && (
                          <button onClick={() => setOpen(isOpen ? null : key)} aria-expanded={isOpen}
                            className={`whitespace-nowrap rounded border px-2 py-0.5 text-xs ${isOpen ? "border-verify text-verify" : "border-line hover:bg-panel-2"}`}>
                            {isOpen ? "Hide chart" : "View chart"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {isOpen && t.chart && (
                      <tr>
                        <td colSpan={s.by_grade ? 9 : 8} style={{ padding: 0 }}>
                          <div className="sticky left-0 max-w-[1000px] p-3" style={{ width: "min(100%, calc(100vw - 4.5rem))" }}>
                            <a href={t.chart} target="_blank" rel="noreferrer" title="Open full size">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img src={t.chart} loading="lazy" width={1000} height={520}
                                alt={`${s.name}: ${t.direction === "LONG" ? "buy" : "sell"} ${day(t.opened)}, ${OUTCOME[t.outcome][0].toLowerCase()} ${signed(t.result_r, 2)}R. Chart of the zone, entry, stop loss and take profit.`}
                                className="h-auto w-full rounded border border-line" />
                            </a>
                            <p className="mt-2 text-xs text-muted">
                              Shaded box = the {t.direction === "LONG" ? "demand" : "supply"} zone. White box = the candle that confirmed the entry.
                              Green / red areas = take profit / stop loss. Click the chart to open it full size.
                            </p>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-muted">{DATA.note}</p>
        </Panel>
      </div>
    </>
  );
}
