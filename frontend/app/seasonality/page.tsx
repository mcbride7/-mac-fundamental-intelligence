"use client";

import { useEffect, useState } from "react";

import { Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const GREEN = "#43a047", RED = "#e53935";

function mv(v: number | null | undefined, mode: string, dp = 2): string {
  if (v === null || v === undefined) return "—";
  const s = v > 0 ? "+" : "";
  return mode === "bp" ? `${s}${v.toFixed(0)} bp` : `${s}${v.toFixed(dp)}%`;
}

/** Cell colour from the win rate: deeper green the more often it rose, deeper red the more often it fell. */
function cellStyle(s: any): React.CSSProperties {
  if (!s || !s.n || s.win_rate === null) return {};
  const t = (s.win_rate - 50) / 50; // -1..1
  const a = Math.min(0.85, Math.abs(t) * 0.95);
  if (Math.abs(t) < 0.1) return {};
  return { background: `${t > 0 ? GREEN : RED}${Math.round(a * 255).toString(16).padStart(2, "0")}`, color: a > 0.45 ? "#fff" : undefined };
}

function Leaders({ data, title, groupOf, group }: { data: any; title: string; groupOf: Record<string, string>; group: string }) {
  const box = (title: string, items: any[], colour: string) => (
    <div className="flex min-w-0 flex-col">
      <div className="mb-1 text-center text-sm font-semibold">{title}</div>
      <div className="flex min-h-[8rem] flex-1 flex-col justify-center gap-1 rounded px-3 py-3 text-white" style={{ background: colour }}>
        {items.length ? items.map((i) => (
          <div key={i.key} className="flex flex-wrap items-baseline justify-between gap-x-2 text-sm">
            <span className="font-semibold">{i.name}</span>
            <span className="whitespace-nowrap opacity-95">{mv(i.avg, i.mode)} · up {i.win_rate}% of years</span>
          </div>
        )) : <span className="text-center text-sm opacity-85">No strong pattern</span>}
      </div>
    </div>
  );
  return (
    <div>
      <h3 className="mb-2 text-lg font-medium">{title}: {data.name}</h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {box("Seasonally bullish", data.bullish.filter((i: any) => group === "All" || groupOf[i.key] === group), GREEN)}
        {box("Seasonally bearish", data.bearish.filter((i: any) => group === "All" || groupOf[i.key] === group), RED)}
      </div>
    </div>
  );
}

function MonthBars({ months, mode, current, thisYear, latest, latestDate }: {
  months: any[]; mode: string; current: number; thisYear?: (number | null)[]; latest?: number; latestDate?: string;
}) {
  const W = 780, H = 290, L = 50, T = 42, B = 36, ih = H - T - B, iw = W - L - 10;
  const ty = thisYear || [];
  const vals = [...months.map((m) => m.avg ?? 0), ...ty.filter((v): v is number => v !== null)];
  const lim = Math.max(0.0001, ...vals.map(Math.abs)) * 1.18;
  const y = (v: number) => T + ih / 2 - (Math.max(-lim, Math.min(lim, v)) / lim) * (ih / 2);
  const bw = iw / 12;
  const year = latestDate ? latestDate.slice(0, 4) : String(new Date().getFullYear());
  const label = (v: number | null | undefined) => (v === null || v === undefined ? "" : mv(v, mode, mode === "bp" ? 0 : 1));
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[36rem]" role="img" aria-label="Average move by month, with this year's moves and the current price">
        {latest !== undefined && (
          <text x={L} y={14} fontSize="12.5" fill="currentColor">
            <tspan fontWeight="600">Current price {fmtPrice(latest, mode)}</tspan>
            <tspan opacity="0.65">{latestDate ? `  ·  ${latestDate}` : ""}{ty[current - 1] != null ? `  ·  ${MONTHS[current - 1]} so far ${mv(ty[current - 1], mode)}` : ""}</tspan>
          </text>
        )}
        <line x1={L} x2={W - 10} y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.35" />
        {[lim, lim / 2, -lim / 2, -lim].map((t) => (
          <text key={t} x={L - 6} y={y(t) + 4} fontSize="10.5" textAnchor="end" fill="currentColor" opacity="0.55">{mv(t, mode, 1)}</text>
        ))}
        {months.map((m, i) => {
          const v = m.avg ?? 0, x0 = L + i * bw, x = x0 + bw * 0.18, w = bw * 0.64;
          const top = v >= 0;
          return (
            <g key={m.month}>
              {i + 1 === current && <rect x={x0 + 2} y={T - 12} width={bw - 4} height={ih + 24} fill="currentColor" opacity="0.07" rx="4" />}
              <rect x={x} width={w} y={Math.min(y(v), y(0))} height={Math.max(1, Math.abs(y(v) - y(0)))} fill={v >= 0 ? GREEN : RED} opacity="0.9">
                <title>{`${m.name}: average ${mv(m.avg, mode)}, median ${mv(m.median, mode)}, up in ${m.win_rate}% of ${m.n} years`}</title>
              </rect>
              {m.avg != null && (
                <text x={x + w / 2} y={top ? y(v) - 4 : y(v) + 11} fontSize="9.5" textAnchor="middle" fill="currentColor" opacity="0.9">{label(m.avg)}</text>
              )}
              <text x={x0 + bw / 2} y={H - 19} fontSize="11" textAnchor="middle" fill="currentColor" opacity="0.75">{m.name}</text>
              <text x={x0 + bw / 2} y={H - 6} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.55">{m.win_rate == null ? "" : `${m.win_rate}% up`}</text>
            </g>
          );
        })}
        {(() => {
          const pts = ty.map((v, i) => (v === null || v === undefined ? null : { i, v, x: L + i * bw + bw / 2, y: y(v) }))
            .filter((p): p is { i: number; v: number; x: number; y: number } => p !== null);
          if (!pts.length) return null;
          const d = pts.map((p, k) => `${k ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
          return (
            <g>
              <path d={d} fill="none" stroke="#f2f2f2" strokeWidth="2.4" strokeLinejoin="round" />
              {pts.map((p) => {
                const now = p.i + 1 === current;
                const above = p.v >= (months[p.i]?.avg ?? 0);
                return (
                  <g key={p.i}>
                    <circle cx={p.x} cy={p.y} r={now ? 5.5 : 4} fill={p.v >= 0 ? "#9ccc65" : "#ff7b7b"} stroke="#0f1726" strokeWidth="1.5" />
                    <text x={p.x} y={above ? p.y - 9 : p.y + 16} fontSize="10" textAnchor="middle" fontWeight="600"
                      fill={p.v >= 0 ? "#9ccc65" : "#ff7b7b"} paintOrder="stroke" stroke="#0f1726" strokeWidth="3">
                      {label(p.v)}{now ? " now" : ""}</text>
                    <title>{`${MONTHS[p.i]} ${year}${now ? " so far" : ""}: ${mv(p.v, mode)} (average ${mv(months[p.i]?.avg, mode)})`}</title>
                  </g>
                );
              })}
            </g>
          );
        })()}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: GREEN }} /><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: RED }} />Average move (number on the bar)</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "#f2f2f2" }} />{year} line: this year&rsquo;s move each month (current month = so far)</span>
        <span>Bottom row: how often the month rose</span>
      </figcaption>
    </figure>
  );
}

function PathChart({ path, mode }: { path: any; mode: string }) {
  const W = 760, H = 230, L = 46, R = 10, T = 12, B = 26, iw = W - L - R, ih = H - T - B;
  const avg: (number | null)[] = path.average, cur: (number | null)[] = path.current;
  const all = [...avg, ...cur].filter((v): v is number => v !== null);
  if (!all.length) return null;
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const n = avg.length;
  const x = (i: number) => L + (i / Math.max(1, n - 1)) * iw, y = (v: number) => T + ih - ((v - lo) / (hi - lo)) * ih;
  const d = (vs: (number | null)[]) => vs.map((v, i) => (v === null ? "" : `${i && vs[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join(" ");
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[34rem]" role="img" aria-label="Average path through the year versus this year">
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.3" />
        {[hi, (hi + lo) / 2, lo].map((t) => <text key={t} x={L - 6} y={y(t) + 4} fontSize="10.5" textAnchor="end" fill="currentColor" opacity="0.55">{mv(t, mode, 1)}</text>)}
        {MONTHS.map((m, i) => <text key={m} x={L + (i / 12) * iw + iw / 24} y={H - 6} fontSize="10.5" textAnchor="middle" fill="currentColor" opacity="0.6">{m}</text>)}
        <path d={d(avg)} fill="none" stroke="#5b8def" strokeWidth="2.4" />
        <path d={d(cur)} fill="none" stroke="#e2a03f" strokeWidth="2.2" />
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "#5b8def" }} />Average year ({path.years_used} years)</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "#e2a03f" }} />This year so far</span>
        <span>Move since the end of the previous year</span>
      </figcaption>
    </figure>
  );
}

function fmtPrice(v: number, mode: string): string {
  if (mode === "bp") return `${v.toFixed(2)}%`;
  const a = Math.abs(v);
  const dp = a >= 1000 ? 0 : a >= 10 ? 2 : 4;
  return v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/** This year's price against the price the seasonal pattern implies, and where the pattern points from today. */
function PriceChart({ pc, mode }: { pc: any; mode: string }) {
  const W = 760, H = 260, L = 64, R = 12, T = 14, B = 26, iw = W - L - R, ih = H - T - B;
  const seas: (number | null)[] = pc.seasonal, act: (number | null)[] = pc.actual, proj: (number | null)[] = pc.projection;
  const all = [...seas, ...act, ...proj].filter((v): v is number => v !== null);
  if (!all.length) return null;
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.01 || 1; lo -= pad; hi += pad;
  const n = seas.length;
  const x = (i: number) => L + (i / Math.max(1, n - 1)) * iw, y = (v: number) => T + ih - ((v - lo) / (hi - lo)) * ih;
  const d = (vs: (number | null)[]) => vs.map((v, i) => (v === null ? "" : `${i && vs[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join(" ");
  const at = pc.today_index;
  const ticks = [hi - pad, (hi + lo) / 2, lo + pad];
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[34rem]" role="img" aria-label="Price against its seasonal path">
        {ticks.map((t) => (
          <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="currentColor" opacity="0.08" />
            <text x={L - 6} y={y(t) + 4} fontSize="10.5" textAnchor="end" fill="currentColor" opacity="0.6">{fmtPrice(t, mode)}</text></g>
        ))}
        {MONTHS.map((m, i) => <text key={m} x={L + (i / 12) * iw + iw / 24} y={H - 6} fontSize="10.5" textAnchor="middle" fill="currentColor" opacity="0.6">{m}</text>)}
        {at >= 0 && <line x1={x(at)} x2={x(at)} y1={T} y2={T + ih} stroke="currentColor" opacity="0.25" strokeDasharray="3 3" />}
        <path d={d(seas)} fill="none" stroke="#5b8def" strokeWidth="2" opacity="0.9" />
        <path d={d(proj)} fill="none" stroke="#e2a03f" strokeWidth="2" strokeDasharray="6 4" />
        <path d={d(act)} fill="none" stroke="#f2f2f2" strokeWidth="2.4" />
        {at >= 0 && act[at] != null && <circle cx={x(at)} cy={y(act[at] as number)} r="4" fill="#f2f2f2" />}
        {at >= 0 && act[at] != null && <text x={Math.min(x(at) + 6, W - R - 60)} y={y(act[at] as number) - 8} fontSize="11" fill="currentColor">{fmtPrice(pc.latest, mode)}</text>}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "#f2f2f2" }} />Price this year</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "#5b8def" }} />Seasonal path (average year applied to last year&rsquo;s close)</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: "#e2a03f" }} />Seasonal pattern from today&rsquo;s price</span>
      </figcaption>
    </figure>
  );
}

function WeekBars({ weeks, mode, current }: { weeks: any[]; mode: string; current: number }) {
  const W = 900, H = 230, L = 46, T = 18, B = 34, ih = H - T - B, iw = W - L - 10;
  const vals = weeks.map((w) => w.avg ?? 0);
  const lim = Math.max(0.0001, ...vals.map(Math.abs)) * 1.15;
  const y = (v: number) => T + ih / 2 - (v / lim) * (ih / 2);
  const bw = iw / 52;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[44rem]" role="img" aria-label="Average move by week of the year">
      <line x1={L} x2={W - 10} y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.35" />
      {[lim, -lim].map((t) => <text key={t} x={L - 6} y={y(t) + 4} fontSize="10.5" textAnchor="end" fill="currentColor" opacity="0.55">{mv(t, mode, 1)}</text>)}
      {weeks.map((w, i) => {
        const v = w.avg ?? 0, x = L + i * bw;
        return (
          <g key={w.week}>
            {w.week === current && <rect x={x} y={T - 14} width={bw} height={ih + 30} fill="currentColor" opacity="0.1" rx="2" />}
            <rect x={x + bw * 0.12} width={bw * 0.76} y={Math.min(y(v), y(0))} height={Math.max(1, Math.abs(y(v) - y(0)))}
              fill={v >= 0 ? GREEN : RED} opacity={w.bias === "Bullish" || w.bias === "Bearish" ? 1 : 0.55}>
              <title>{`${w.name}: average ${mv(w.avg, mode)}, up in ${w.win_rate}% of ${w.n} years`}</title>
            </rect>
          </g>
        );
      })}
      {MONTHS.map((m, i) => <text key={m} x={L + (i * 52 / 12 + 2.2) * bw} y={H - 14} fontSize="11" textAnchor="middle" fill="currentColor" opacity="0.7">{m}</text>)}
      <text x={L + (current - 0.5) * bw} y={H - 2} fontSize="10" textAnchor="middle" fill="currentColor">W{current}</text>
    </svg>
  );
}

function Detail({ k, years, current, view, options, onPick }: {
  k: string; years: number; current: number; view: string; options: { key: string; name: string }[]; onPick: (k: string) => void;
}) {
  const { data: a, error, loading } = useApi<any>(`/api/seasonality/${k}?years=${years}`);
  if (error) return <ErrorBox error={error} />;
  if (loading && !a) return <Loading />;
  if (!a) return null;
  if (!a.months?.length) return <Empty>No price history stored for {a.name} yet.</Empty>;
  const weekly = view === "weekly";
  const tm = weekly ? a.this_week : a.this_month, nm = weekly ? a.next_week : a.next_month;
  const stat = (label: string, value: React.ReactNode, sub?: React.ReactNode) => (
    <div className="min-w-0 rounded-md border border-line bg-panel-2/50 px-3 py-2">
      <div className="text-xs text-muted">{label}</div><div className="text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
  const biasCol = (b: string) => (b === "Bullish" ? "text-[#9ccc65]" : b === "Bearish" ? "text-[#ff7b7b]" : "text-muted");
  const statFor = (label: string, x: any) => x
    ? stat(label, <span className={biasCol(x.bias)}>{x.bias}</span>, x.n ? `avg ${mv(x.avg, a.mode)}, up ${x.win_rate}% of ${x.n} yrs` : undefined)
    : stat(label, "—", "needs daily prices");
  return (
    <div className="space-y-5">
      <label className="flex flex-wrap items-center gap-2 text-sm text-muted">Asset
        <select value={k} onChange={(e) => onPick(e.target.value)} className="rounded border border-line bg-panel-2 px-2 py-1.5 text-text">
          {options.map((o) => <option key={o.key} value={o.key}>{o.name}</option>)}
        </select>
      </label>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {statFor(weekly ? `${tm?.name ?? "This week"} (this week)` : `${tm.name} (this month)`, tm)}
        {statFor(weekly ? `${nm?.name ?? "Next week"} (next week)` : `${nm.name} (next month)`, nm)}
        {stat("Next 30 days, from today's date", a.next_30 ? mv(a.next_30.avg, a.mode) : "—", a.next_30 ? `up in ${a.next_30.win_rate}% of ${a.next_30.n} years` : "needs daily prices")}
        {stat("Month to date", mv(a.month_to_date, a.mode))}
        {stat("Year to date", mv(a.year_to_date, a.mode), `latest ${a.last}`)}
      </div>
      {a.price_chart && (
        <div>
          <h3 className="mb-1 font-medium">Price vs its seasonal trend</h3>
          {a.price_chart.note && (
            <p className={`mb-2 rounded border-l-4 bg-panel-2/60 px-3 py-2 text-sm ${a.price_chart.gap > 0 ? "border-[#43a047]" : a.price_chart.gap < 0 ? "border-[#e53935]" : "border-line"}`}>{a.price_chart.note}</p>
          )}
          <div className="overflow-x-auto"><PriceChart pc={a.price_chart} mode={a.mode} /></div>
        </div>
      )}
      {weekly ? (
        a.weeks?.length ? (
          <div>
            <h3 className="mb-1 font-medium">Average move by week of the year <span className="text-sm text-muted">· faded bars = no clear pattern · hover a bar for details</span></h3>
            <div className="overflow-x-auto"><WeekBars weeks={a.weeks} mode={a.mode} current={a.week_now} /></div>
          </div>
        ) : <p className="text-sm text-muted">Weekly seasonality needs daily prices; {a.name} only has monthly prices.</p>
      ) : (
        <div>
          <h3 className="mb-1 font-medium">Average move by month vs this year <span className="text-sm text-muted">· win rate under each month</span></h3>
          <div className="overflow-x-auto"><MonthBars months={a.months} mode={a.mode} current={current} thisYear={a.this_year} latest={a.latest} latestDate={a.latest_date} /></div>
        </div>
      )}
      {a.path && (
        <div>
          <h3 className="mb-1 font-medium">The average year vs this year <span className="text-sm text-muted">· as % moves since the start of the year</span></h3>
          <div className="overflow-x-auto"><PathChart path={a.path} mode={a.mode} /></div>
        </div>
      )}
      <div>
        <h3 className="mb-1 font-medium">Year by month</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-xs tabular-nums">
            <thead><tr className="text-muted"><th className="px-1.5 py-1 text-left font-medium">Year</th>
              {MONTHS.map((m, i) => <th key={m} className={`px-1.5 py-1 text-right font-medium ${i + 1 === current ? "text-text" : ""}`}>{m}</th>)}</tr></thead>
            <tbody>
              {a.grid.map((r: any) => (
                <tr key={r.year} className="border-t border-line">
                  <td className="px-1.5 py-1 font-medium">{r.year}</td>
                  {r.months.map((v: number | null, i: number) => (
                    <td key={i} className="px-1.5 py-1 text-right"
                      style={v === null ? {} : { color: v > 0 ? "#9ccc65" : v < 0 ? "#ff7b7b" : undefined }}>{v === null ? "" : mv(v, a.mode, 1)}</td>
                  ))}
                </tr>
              ))}
              <tr className="border-t-2 border-line font-semibold">
                <td className="px-1.5 py-1">Average</td>
                {a.months.map((m: any) => <td key={m.month} className="px-1.5 py-1 text-right">{mv(m.avg, a.mode, 1)}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-xs text-muted">Source: {a.source}. History from {a.first}. {a.note && `${a.note}. `}Months are measured close to close; the current month is left out until it ends.</p>
    </div>
  );
}

export default function Seasonality() {
  const [years, setYears] = useState(10);
  const [view, setView] = useState<"monthly" | "weekly">("monthly");
  const [group, setGroup] = useState("All");
  const [sel, setSel] = useState<string>("XAUUSD");
  useEffect(() => {
    try {
      const s = localStorage.getItem("seas-asset"); if (s) setSel(s);
      const g = localStorage.getItem("seas-group"); if (g) setGroup(g);
      const v = localStorage.getItem("seas-view"); if (v === "weekly" || v === "monthly") setView(v);
    } catch { /* ignore */ }
  }, []);
  const remember = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } };
  const pick = (k: string) => { setSel(k); remember("seas-asset", k); };
  const { data: o, error, loading } = useApi<any>(`/api/seasonality?years=${years}&view=${view}`);
  const current = o ? Number(o.today.slice(5, 7)) : new Date().getMonth() + 1;
  const assets: any[] = o?.assets || [];
  const groupOf: Record<string, string> = Object.fromEntries(assets.map((a) => [a.key, a.group]));
  const shownAssets = assets.filter((a) => group === "All" || a.group === group);
  const shownGroups: string[] = (o?.groups || []).filter((g: string) => group === "All" || g === group);
  const chooseGroup = (g: string) => {
    setGroup(g); remember("seas-group", g);
    if (g !== "All" && groupOf[sel] !== g) { const first = assets.find((a) => a.group === g); if (first) pick(first.key); }
  };
  const selName = assets.find((a) => a.key === sel)?.name || sel;
  const hasData = assets.some((a) => (a.months?.length || a.weeks?.length));
  const options = shownAssets.map((a) => ({ key: a.key, name: a.name }));
  const seg = (label: string, value: string, opts: [string, string][], on: (v: string) => void) => (
    <div role="radiogroup" aria-label={label} className="flex overflow-hidden rounded border border-line">
      {opts.map(([k, t]) => (
        <button key={k} role="radio" aria-checked={value === k} onClick={() => on(k)}
          className={`px-3 py-1.5 ${value === k ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>{t}</button>
      ))}
    </div>
  );
  return (
    <>
      <PageTitle title="Seasonality" subtitle="How each asset has tended to move by month and by week of the year, and where price stands against its seasonal path. Seasonality is a tendency, not a forecast: use it alongside fundamentals, positioning and price." />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        {seg("View", view, [["monthly", "Monthly"], ["weekly", "Weekly"]], (v) => { setView(v as any); remember("seas-view", v); })}
        <label className="flex items-center gap-2 text-muted">Asset class
          <select value={group} onChange={(e) => chooseGroup(e.target.value)} className="rounded border border-line bg-panel-2 px-2 py-1.5 text-text">
            <option value="All">All asset classes</option>
            {(o?.groups || []).map((g: string) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <span className="text-muted">Look back</span>
        {seg("Years", String(years), (o?.lookbacks || [5, 10, 15, 20]).map((y: number) => [String(y), `${y} years`]), (v) => setYears(Number(v)))}
      </div>
      <ErrorBox error={error} />
      {(loading && !o) || (o && o.view !== view) ? <Loading /> : !hasData ? (
        <Empty href="/data-health" cta="Open Data health">No price history yet. On Data health, press Run now on &ldquo;Seasonality price histories&rdquo;. The first run downloads up to 25 years per asset and takes a few minutes.</Empty>
      ) : (
        <div className="space-y-6">
          <Panel title={`Seasonal leaders${group === "All" ? "" : `: ${group}`}`}>
            <div className="grid gap-6 lg:grid-cols-2">
              {view === "weekly" ? (<>
                <Leaders data={o.this_week} title="This week" groupOf={groupOf} group={group} />
                <Leaders data={o.next_week} title="Next week" groupOf={groupOf} group={group} />
              </>) : (<>
                <Leaders data={o.this_month} title="This month" groupOf={groupOf} group={group} />
                <Leaders data={o.next_month} title="Next month" groupOf={groupOf} group={group} />
              </>)}
            </div>
            <p className="mt-3 text-xs text-muted">Listed when the asset rose (or fell) in at least 65% of the last {years} years in that {view === "weekly" ? "week" : "month"}, with the average pointing the same way. Currencies are shown as quoted, e.g. USD/ZAR rising = rand weaker.</p>
          </Panel>

          {view === "weekly" ? (
            <Panel title={`The next four weeks · last ${years} years`} action={<span className="text-xs text-muted">Colour = how often it rose · number = average move · tap a row for detail</span>}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[40rem] text-xs tabular-nums">
                  <thead><tr className="text-muted"><th className="px-2 py-1 text-left font-medium">Asset</th>
                    {o.columns.map((c: string, i: number) => <th key={c} className={`px-1 py-1 text-center font-medium ${i === 0 ? "rounded-t bg-verify/25 text-text" : ""}`}>{i === 0 ? `This week · ${c}` : c}</th>)}</tr></thead>
                  <tbody>
                    {shownGroups.map((g: string) => [
                      <tr key={g}><td colSpan={5} className="px-2 pt-3 text-[0.7rem] uppercase tracking-wide text-muted">{g}</td></tr>,
                      ...shownAssets.filter((a) => a.group === g).map((a) => (
                        <tr key={a.key} onClick={() => pick(a.key)} className={`cursor-pointer border-t border-line/60 hover:bg-panel-2/60 ${a.key === sel ? "bg-panel-2/70" : ""}`}>
                          <td className="whitespace-nowrap px-2 py-1 font-medium">{a.name}{!a.daily && <span className="ml-1 font-normal text-muted">(monthly prices only)</span>}</td>
                          {(a.weeks.length ? a.weeks : o.columns.map(() => null)).map((st: any, i: number) => (
                            <td key={i} className="px-1 py-1 text-center" style={cellStyle(st)}
                              title={st && st.n ? `${a.name}, ${st.name}: average ${mv(st.avg, a.mode)}, up in ${st.win_rate}% of ${st.n} years` : undefined}>
                              {st && st.n ? `${mv(st.avg, a.mode, 2)} · ${st.win_rate}%` : ""}
                            </td>
                          ))}
                        </tr>
                      )),
                    ])}
                  </tbody>
                </table>
              </div>
            </Panel>
          ) : (
            <Panel title={`All assets by month · last ${years} years`} action={<span className="text-xs text-muted">Colour = how often it rose · number = average move · tap a row for detail</span>}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[60rem] text-xs tabular-nums">
                  <thead><tr className="text-muted"><th className="px-2 py-1 text-left font-medium">Asset</th>
                    {MONTHS.map((m, i) => <th key={m} className={`px-1 py-1 text-center font-medium ${i + 1 === current ? "rounded-t bg-verify/25 text-text" : ""}`}>{m}</th>)}</tr></thead>
                  <tbody>
                    {shownGroups.map((g: string) => [
                      <tr key={g}><td colSpan={13} className="px-2 pt-3 text-[0.7rem] uppercase tracking-wide text-muted">{g}</td></tr>,
                      ...shownAssets.filter((a) => a.group === g).map((a) => (
                        <tr key={a.key} onClick={() => pick(a.key)} className={`cursor-pointer border-t border-line/60 hover:bg-panel-2/60 ${a.key === sel ? "bg-panel-2/70" : ""}`}>
                          <td className="whitespace-nowrap px-2 py-1 font-medium">{a.name}{!a.months.length && <span className="ml-1 font-normal text-muted">(no data)</span>}</td>
                          {(a.months.length ? a.months : MONTHS.map(() => null)).map((st: any, i: number) => (
                            <td key={i} className={`px-1 py-1 text-center ${i + 1 === current ? "outline outline-1 outline-verify/60" : ""}`} style={cellStyle(st)}
                              title={st && st.n ? `${a.name}, ${MONTHS[i]}: average ${mv(st.avg, a.mode)}, up in ${st.win_rate}% of ${st.n} years` : undefined}>
                              {st && st.n ? mv(st.avg, a.mode, 1) : ""}
                            </td>
                          ))}
                        </tr>
                      )),
                    ])}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          <Panel title={`${selName}: ${view} seasonality · last ${years} years`}>
            <Detail k={sel} years={years} current={current} view={view} options={options.some((x) => x.key === sel) ? options : [{ key: sel, name: selName }, ...options]} onPick={pick} />
          </Panel>
          <p className="text-xs text-muted">Past seasonal patterns can fail in any given year. This is not financial advice.</p>
        </div>
      )}
    </>
  );
}
