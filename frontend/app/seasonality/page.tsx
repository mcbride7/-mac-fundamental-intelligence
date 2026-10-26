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

function Leaders({ data, mode }: { data: any; mode: "this" | "next" }) {
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
      <h3 className="mb-2 text-lg font-medium">{mode === "this" ? "This month" : "Next month"}: {data.name}</h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {box("Seasonally bullish", data.bullish, GREEN)}
        {box("Seasonally bearish", data.bearish, RED)}
      </div>
    </div>
  );
}

function MonthBars({ months, mode, current }: { months: any[]; mode: string; current: number }) {
  const W = 760, H = 230, L = 46, T = 18, B = 34, ih = H - T - B, iw = W - L - 10;
  const vals = months.map((m) => m.avg ?? 0);
  const lim = Math.max(0.0001, ...vals.map(Math.abs)) * 1.15;
  const y = (v: number) => T + ih / 2 - (v / lim) * (ih / 2);
  const bw = iw / 12;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[34rem]" role="img" aria-label="Average move by month">
      <line x1={L} x2={W - 10} y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.35" />
      {[lim, lim / 2, -lim / 2, -lim].map((t) => (
        <text key={t} x={L - 6} y={y(t) + 4} fontSize="10.5" textAnchor="end" fill="currentColor" opacity="0.55">{mv(t, mode, 1)}</text>
      ))}
      {months.map((m, i) => {
        const v = m.avg ?? 0, x = L + i * bw + bw * 0.15;
        return (
          <g key={m.month}>
            {i + 1 === current && <rect x={L + i * bw + 2} y={T - 14} width={bw - 4} height={ih + 30} fill="currentColor" opacity="0.06" rx="4" />}
            <rect x={x} width={bw * 0.7} y={Math.min(y(v), y(0))} height={Math.max(1, Math.abs(y(v) - y(0)))} fill={v >= 0 ? GREEN : RED} opacity="0.9">
              <title>{`${m.name}: average ${mv(m.avg, mode)}, median ${mv(m.median, mode)}, up in ${m.win_rate}% of ${m.n} years`}</title>
            </rect>
            <text x={L + i * bw + bw / 2} y={H - 18} fontSize="11" textAnchor="middle" fill="currentColor" opacity="0.75">{m.name}</text>
            <text x={L + i * bw + bw / 2} y={H - 5} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.55">{m.win_rate == null ? "" : `${m.win_rate}%`}</text>
          </g>
        );
      })}
    </svg>
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

function Detail({ k, years, current }: { k: string; years: number; current: number }) {
  const { data: a, error, loading } = useApi<any>(`/api/seasonality/${k}?years=${years}`);
  if (error) return <ErrorBox error={error} />;
  if (loading && !a) return <Loading />;
  if (!a) return null;
  if (!a.months?.length) return <Empty>No price history stored for {a.name} yet.</Empty>;
  const tm = a.this_month, nm = a.next_month;
  const stat = (label: string, value: React.ReactNode, sub?: React.ReactNode) => (
    <div className="min-w-0 rounded-md border border-line bg-panel-2/50 px-3 py-2">
      <div className="text-xs text-muted">{label}</div><div className="text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
  const biasCol = (b: string) => (b === "Bullish" ? "text-[#9ccc65]" : b === "Bearish" ? "text-[#ff7b7b]" : "text-muted");
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {stat(`${tm.name} (this month)`, <span className={biasCol(tm.bias)}>{tm.bias}</span>, tm.n ? `avg ${mv(tm.avg, a.mode)}, up ${tm.win_rate}% of ${tm.n} yrs` : undefined)}
        {stat(`${nm.name} (next month)`, <span className={biasCol(nm.bias)}>{nm.bias}</span>, nm.n ? `avg ${mv(nm.avg, a.mode)}, up ${nm.win_rate}% of ${nm.n} yrs` : undefined)}
        {stat("Next 30 days, from today's date", a.next_30 ? mv(a.next_30.avg, a.mode) : "—", a.next_30 ? `up in ${a.next_30.win_rate}% of ${a.next_30.n} years` : "needs daily prices")}
        {stat("Month to date", mv(a.month_to_date, a.mode))}
        {stat("Year to date", mv(a.year_to_date, a.mode), `latest ${a.last}`)}
      </div>
      <div>
        <h3 className="mb-1 font-medium">Average move by month <span className="text-sm text-muted">· win rate under each month</span></h3>
        <div className="overflow-x-auto"><MonthBars months={a.months} mode={a.mode} current={current} /></div>
      </div>
      {a.path && (
        <div>
          <h3 className="mb-1 font-medium">The average year vs this year</h3>
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
  const [sel, setSel] = useState<string>("XAUUSD");
  useEffect(() => { try { const s = localStorage.getItem("seas-asset"); if (s) setSel(s); } catch { /* ignore */ } }, []);
  const pick = (k: string) => { setSel(k); try { localStorage.setItem("seas-asset", k); } catch { /* ignore */ } };
  const { data: o, error, loading } = useApi<any>(`/api/seasonality?years=${years}`);
  const current = o ? Number(o.today.slice(5, 7)) : new Date().getMonth() + 1;
  const assets: any[] = o?.assets || [];
  const selName = assets.find((a) => a.key === sel)?.name || sel;
  const hasData = assets.some((a) => a.months?.length);
  return (
    <>
      <PageTitle title="Seasonality" subtitle="How each asset has tended to move in each calendar month. Seasonality is a tendency, not a forecast: use it alongside fundamentals, positioning and price." />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">Look back</span>
        <div role="radiogroup" aria-label="Years" className="flex overflow-hidden rounded border border-line">
          {(o?.lookbacks || [5, 10, 15, 20]).map((y: number) => (
            <button key={y} role="radio" aria-checked={years === y} onClick={() => setYears(y)}
              className={`px-3 py-1.5 ${years === y ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>{y} years</button>
          ))}
        </div>
      </div>
      <ErrorBox error={error} />
      {loading && !o ? <Loading /> : !hasData ? (
        <Empty href="/data-health" cta="Open Data health">No price history yet. On Data health, press Run now on &ldquo;Seasonality price histories&rdquo;. The first run downloads up to 25 years per asset and takes a few minutes.</Empty>
      ) : (
        <div className="space-y-6">
          <Panel title="Seasonal leaders">
            <div className="grid gap-6 lg:grid-cols-2">
              <Leaders data={o.this_month} mode="this" />
              <Leaders data={o.next_month} mode="next" />
            </div>
            <p className="mt-3 text-xs text-muted">Listed when the asset rose (or fell) in at least 65% of the last {years} years in that month, with the average pointing the same way. Currencies are shown as quoted, e.g. USD/ZAR rising = rand weaker.</p>
          </Panel>

          <Panel title={`All assets by month · last ${years} years`} action={<span className="text-xs text-muted">Colour = how often it rose · number = average move · tap a row for detail</span>}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[60rem] text-xs tabular-nums">
                <thead><tr className="text-muted"><th className="px-2 py-1 text-left font-medium">Asset</th>
                  {MONTHS.map((m, i) => <th key={m} className={`px-1 py-1 text-center font-medium ${i + 1 === current ? "rounded-t bg-verify/25 text-text" : ""}`}>{m}</th>)}</tr></thead>
                <tbody>
                  {o.groups.map((g: string) => [
                    <tr key={g}><td colSpan={13} className="px-2 pt-3 text-[0.7rem] uppercase tracking-wide text-muted">{g}</td></tr>,
                    ...assets.filter((a) => a.group === g).map((a) => (
                      <tr key={a.key} onClick={() => pick(a.key)} className={`cursor-pointer border-t border-line/60 hover:bg-panel-2/60 ${a.key === sel ? "bg-panel-2/70" : ""}`}>
                        <td className="whitespace-nowrap px-2 py-1 font-medium">{a.name}{!a.months.length && <span className="ml-1 font-normal text-muted">(no data)</span>}</td>
                        {(a.months.length ? a.months : MONTHS.map(() => null)).map((s: any, i: number) => (
                          <td key={i} className={`px-1 py-1 text-center ${i + 1 === current ? "outline outline-1 outline-verify/60" : ""}`} style={cellStyle(s)}
                            title={s && s.n ? `${a.name}, ${MONTHS[i]}: average ${mv(s.avg, a.mode)}, up in ${s.win_rate}% of ${s.n} years` : undefined}>
                            {s && s.n ? mv(s.avg, a.mode, 1) : ""}
                          </td>
                        ))}
                      </tr>
                    )),
                  ])}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title={`${selName}: seasonal detail · last ${years} years`}>
            <Detail k={sel} years={years} current={current} />
          </Panel>
          <p className="text-xs text-muted">Past seasonal patterns can fail in any given year. This is not financial advice.</p>
        </div>
      )}
    </>
  );
}
