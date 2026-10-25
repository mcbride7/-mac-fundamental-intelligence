"use client";

import Link from "next/link";
import { useState } from "react";

import { Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { dateTime, num } from "@/lib/format";

const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY"];
const BULL = "bg-[#3d4fd6] text-white";
const BEAR = "bg-[#e45d5d] text-white";
const NEUTRAL = "bg-panel-2 text-muted";
const cellFor = (call: string) => (call === "Bullish" ? BULL : call === "Bearish" ? BEAR : NEUTRAL);
const textFor = (call: string) => (call === "Bullish" ? "text-[#7d8cff]" : call === "Bearish" ? "text-[#ff7b7b]" : "");

function fmt(v: number | null | undefined, unit: string, signed = false): string {
  if (v === null || v === undefined) return "—";
  const sign = signed && v > 0 ? "+" : "";
  const trim = (x: number, d: number) => String(Number(x.toFixed(d)));
  if (unit === "%") return `${sign}${trim(v, 2)}%`;
  if (unit === "k") return `${sign}${trim(v, 1)}K`;
  if (unit === "m") return `${sign}${trim(v, 2)}M`;
  return `${sign}${trim(v, 2)}`;
}

function shortDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
}

/** Half-circle gauge: 0% (all bearish, left, red) to 100% (all bullish, right, blue). */
function Gauge({ pct, label, suffix = "%" }: { pct: number | null; label: string; suffix?: string }) {
  const p = pct === null ? 50 : Math.max(0, Math.min(100, pct));
  const a = Math.PI * (1 - p / 100);
  const x = 60 + 44 * Math.cos(a), y = 62 - 44 * Math.sin(a);
  return (
    <figure className="flex flex-col items-center">
      <svg viewBox="0 0 120 72" className="w-36" role="img" aria-label={`${label}: ${pct === null ? "no data" : `${num(pct, 0)}% bullish`}`}>
        <path d="M 10 62 A 50 50 0 0 1 60 12" fill="none" stroke="#e45d5d" strokeWidth="10" />
        <path d="M 60 12 A 50 50 0 0 1 110 62" fill="none" stroke="#3d4fd6" strokeWidth="10" />
        <line x1="60" y1="62" x2={x} y2={y} stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        <circle cx="60" cy="62" r="4" fill="currentColor" />
      </svg>
      <figcaption className="-mt-1 text-center text-sm"><span className="font-medium">{pct === null ? "—" : `${num(pct, 0)}${suffix}`}</span>
        <span className="block text-xs text-muted">{label}</span></figcaption>
    </figure>
  );
}

function Regime() {
  const { data, error, loading } = useApi<any>("/api/macro/regime");
  const [pick, setPick] = useState<string>("");
  const hist: any[] = data?.history || [];
  const cur = data?.current;
  const shown = pick ? hist.find((h) => String(h.id) === pick) : cur;
  return (
    <Panel title="Macro regime"
      action={hist.length > 0 ? (
        <label className="flex items-center gap-2 text-sm text-muted">Regime history
          <select value={pick} onChange={(e) => setPick(e.target.value)}
            className="max-w-[17rem] rounded border border-line bg-panel-2 px-2 py-1 text-text">
            <option value="">Current regime</option>
            {hist.map((h) => (
              <option key={h.id} value={h.id}>{shortDate(h.started_at)}{h.ended_at ? ` – ${shortDate(h.ended_at)}` : " – now"}: {h.primary}{h.secondary ? `, ${h.secondary.toLowerCase()}` : ""}</option>
            ))}
          </select>
        </label>
      ) : undefined}>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !shown ? <Empty>No regime computed yet. It appears once inflation, growth and market data are in.</Empty> : (
        <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
          <div>
            <div className="text-xs uppercase tracking-wide text-muted">{pick
              ? `${dateTime(shown.started_at)} to ${shown.ended_at ? dateTime(shown.ended_at) : "now"}`
              : `Current regime, updated ${dateTime(shown.as_of)}`}</div>
            <p className="font-serif text-2xl">{shown.primary}</p>
            <p className="text-sm text-muted">{shown.secondary || "No clear risk signal"}, confidence {num(shown.confidence, 0)}%</p>
            <ul className="note mt-3 list-disc pl-5 text-sm">{(shown.explanation || []).map((e: string) => <li key={e}>{e}</li>)}</ul>
          </div>
          <dl className="grid grid-cols-2 content-start gap-3 text-sm">{Object.entries(shown.signals || {}).map(([k, v]: any) => (
            <div key={k}><dt className="text-xs capitalize text-muted">{k.replaceAll("_", " ")}</dt><dd>{String(v)}</dd></div>))}</dl>
        </div>
      )}
    </Panel>
  );
}

function RiskChart({ hist, on, off }: { hist: { date: string; score: number }[]; on: number; off: number }) {
  if (hist.length < 2) return <p className="text-xs text-muted">The chart fills in as daily readings build up.</p>;
  const W = 600, H = 120, y = (v: number) => H - (v / 100) * H, x = (i: number) => (i / (hist.length - 1)) * W;
  const path = hist.map((h, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(h.score).toFixed(1)}`).join(" ");
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-32 w-full" preserveAspectRatio="none" role="img"
        aria-label={`Risk sentiment over the last ${hist.length} days, latest ${num(hist[hist.length - 1].score, 0)}`}>
        <rect x="0" y="0" width={W} height={y(on)} fill="#43a047" opacity="0.14" />
        <rect x="0" y={y(off)} width={W} height={H - y(off)} fill="#e53935" opacity="0.14" />
        <line x1="0" x2={W} y1={y(50)} y2={y(50)} stroke="currentColor" opacity="0.2" strokeDasharray="4 4" />
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-muted"><span>{shortDate(hist[0].date)}</span>
        <span>green band = risk-on (≥{on}), red band = risk-off (≤{off})</span><span>{shortDate(hist[hist.length - 1].date)}</span></figcaption>
    </figure>
  );
}

const GREEN = "#43a047", RED = "#e53935", MIXED = "#9aa5b5";

/** Round dial like a car gauge: Risk Off (red, left), Mixed (top), Risk On (green, right). */
function RiskDial({ score, on, off }: { score: number; on: number; off: number }) {
  // the dial sweeps 240 degrees, from bottom-left (0) over the top to bottom-right (100), like a car gauge
  const ang = (v: number) => ((210 - (v / 100) * 240) * Math.PI) / 180;
  const pt = (v: number, r: number) => [100 + r * Math.cos(ang(v)), 100 - r * Math.sin(ang(v))];
  const arc = (a: number, b: number, r: number) => {
    const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r);
    return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${(b - a) * 2.4 > 180 ? 1 : 0} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  };
  const v = Math.max(0, Math.min(100, score));
  const [nx, ny] = pt(v, 66);
  const tail = pt(v, -14);
  const major = [0, 25, 50, 75, 100];
  const minor = Array.from({ length: 21 }, (_, i) => i * 5).filter((t) => !major.includes(t));
  return (
    <svg viewBox="0 0 200 200" className="w-60 max-w-full drop-shadow-lg" role="img" aria-label={`Risk dial at ${Math.round(v)} out of 100`}>
      <defs>
        <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" /><stop offset="0.45" stopColor="#c7ccd3" /><stop offset="1" stopColor="#8d949e" />
        </linearGradient>
        <radialGradient id="face" cx="0.45" cy="0.4" r="0.7">
          <stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#dfe3e8" />
        </radialGradient>
        <radialGradient id="hub" cx="0.35" cy="0.35" r="0.7">
          <stop offset="0" stopColor="#6fb1ff" /><stop offset="1" stopColor="#1f6fd6" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="100" r="96" fill="url(#rim)" />
      <circle cx="100" cy="100" r="86" fill="url(#face)" stroke="#aeb5be" strokeWidth="1" />
      <path d={arc(0, off, 70)} fill="none" stroke={RED} strokeWidth="15" />
      <path d={arc(on, 100, 70)} fill="none" stroke={GREEN} strokeWidth="15" />
      <path d={arc(0, off, 77.5)} fill="none" stroke="#8a1f1c" strokeWidth="1" opacity="0.5" />
      <path d={arc(on, 100, 77.5)} fill="none" stroke="#2c6e2f" strokeWidth="1" opacity="0.5" />
      {minor.map((t) => { const [x1, y1] = pt(t, 82), [x2, y2] = pt(t, 78.5); return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#7b8490" strokeWidth="1" />; })}
      {major.map((t) => { const [x1, y1] = pt(t, 83), [x2, y2] = pt(t, 75); return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#3c4450" strokeWidth={t === 50 ? 3 : 2} />; })}
      <text x="100" y="47" fontSize="10" fill="#4f5966" textAnchor="middle">Mixed</text>
      <text x={pt(22, 50)[0]} y={pt(22, 50)[1] + 3} fontSize="10" fill="#4f5966" textAnchor="middle">R.Off</text>
      <text x={pt(78, 50)[0]} y={pt(78, 50)[1] + 3} fontSize="10" fill="#4f5966" textAnchor="middle">R.On</text>
      <text x={pt(2, 58)[0] + 6} y={pt(2, 58)[1] - 2} fontSize="8.5" fill="#6b7480" textAnchor="middle">R.Off−</text>
      <text x={pt(98, 58)[0] - 6} y={pt(98, 58)[1] - 2} fontSize="8.5" fill="#6b7480" textAnchor="middle">R.On+</text>
      <line x1={tail[0]} y1={tail[1]} x2={nx} y2={ny} stroke="#ef5a24" strokeWidth="3" strokeLinecap="round" />
      <circle cx="100" cy="100" r="12" fill="url(#hub)" stroke="#155bb5" strokeWidth="1" />
      <text x="100" y="168" fontSize="22" fontWeight="600" fill="#3a4350" textAnchor="middle">{Math.round(v)}</text>
    </svg>
  );
}

function Tile({ t }: { t: any }) {
  const chg = t.change_1d_pct;
  const dp = t.price >= 1000 ? 0 : t.price >= 100 ? 2 : 4;
  return (
    <div className="min-w-[9.5rem] flex-1 rounded-lg border border-line bg-panel-2/60 px-4 py-3" title={t.source ? `Source: ${t.source}` : undefined}>
      <div className="text-lg font-bold tracking-tight">{t.label}</div>
      <div className="mt-1 grid grid-cols-2 gap-2 text-[0.7rem] text-muted"><span>Market price</span><span>Change (1 day)</span></div>
      <div className="grid grid-cols-2 gap-2 text-lg tabular-nums">
        <span>{t.price.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}</span>
        <span className={chg == null ? "text-muted" : chg < 0 ? "text-[#ff7b7b]" : "text-[#9ccc65]"}>
          {chg == null ? "—" : `${chg > 0 ? "+" : ""}${chg.toFixed(2)}%`}</span>
      </div>
    </div>
  );
}

function EvalBox({ title, items, colour }: { title: string; items: string[]; colour: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <div className="mb-1 text-center text-sm font-semibold">{title}</div>
      <div className="flex min-h-[10rem] flex-1 flex-col items-center justify-center rounded px-3 py-4 text-center text-lg font-semibold leading-snug text-white"
        style={{ background: colour }}>
        {items.length ? items.map((i, n) => <span key={i}>{i}{n < items.length - 1 ? "," : ""}</span>)
          : <span className="text-sm font-normal opacity-80">None today</span>}
      </div>
    </div>
  );
}

function RiskSentiment() {
  const { data, error, loading } = useApi<any>("/api/macro/risk");
  const c = data?.current;
  const ev = data?.evaluation;
  const biasColour = c?.label === "Risk-On" ? "text-[#9ccc65]" : c?.label === "Risk-Off" ? "text-[#ff7b7b]" : "text-muted";
  return (
    <Panel title="Daily Risk ON / Risk OFF">
      <ErrorBox error={error} />
      {data?.tiles?.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-3">{data.tiles.map((t: any) => <Tile key={t.symbol} t={t} />)}</div>
      )}
      {loading && !data ? <Loading /> : !c || c.score === null ? (
        <Empty href="/data-health" cta="Open Data health">No risk reading yet. It is worked out from daily FRED data (VIX, credit spreads, S&amp;P 500, FX).
          On Data health, press Run now on &ldquo;Risk sentiment market series&rdquo;, or wait for the next automatic run.</Empty>
      ) : (
        <>
          <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
            <div className="flex flex-col items-center">
              <h3 className="mb-2 self-start text-2xl font-medium sm:text-3xl">Daily Bias: <span className={biasColour}>{ev?.bias}</span></h3>
              <RiskDial score={c.score} on={data.thresholds.risk_on} off={data.thresholds.risk_off} />
              <p className="mt-1 text-center text-xs text-muted">Score out of 100. Market data up to {shortDate(c.data_date)};
                {" "}{Math.round(c.coverage * 100)}% of signals available.</p>
            </div>
            <div className="min-w-0">
              <h3 className="mb-3 text-center text-2xl font-medium sm:text-3xl lg:mt-1">Daily Evaluation</h3>
              <div className="grid grid-cols-2 gap-1">
                <EvalBox title="Bullish/D" items={ev?.bullish || []} colour={GREEN} />
                <EvalBox title="Bearish/D" items={ev?.bearish || []} colour={RED} />
              </div>
              {ev?.basis && <p className="mt-2 text-xs text-muted">{ev.basis} Currencies are against the US dollar; USD itself is against the others.</p>}
            </div>
          </div>
          {(c.notes || []).map((n: string) => (
            <p key={n} className="mt-4 rounded border border-amber/50 bg-amber/10 px-3 py-2 text-sm text-amber">{n}</p>
          ))}
          <details className="mt-5 rounded border border-line p-3">
            <summary className="cursor-pointer text-sm font-medium">Why: the 8 signals behind the score, and its history</summary>
            <ul className="mt-4 space-y-3">
              {c.components.map((k: any) => (
                <li key={k.key} className="text-sm" title={k.reading}>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span>{k.label}</span><span className="text-xs text-muted">{k.reading}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-3">
                    <span className="relative h-2.5 flex-1 rounded bg-panel-2" aria-hidden>
                      <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                      <span className="absolute inset-y-0 rounded" style={{ background: k.score >= 0 ? GREEN : RED,
                        ...(k.score >= 0 ? { left: "50%", width: `${k.score / 2}%` } : { right: "50%", width: `${-k.score / 2}%` }) }} />
                    </span>
                    <span className={`w-10 text-right tabular-nums ${k.score >= 0 ? "text-[#9ccc65]" : "text-[#ff7b7b]"}`}>{k.score > 0 ? "+" : ""}{num(k.score, 0)}</span>
                  </div>
                </li>
              ))}
            </ul>
            {c.missing?.length > 0 && <p className="mt-3 text-xs text-muted">Not enough data yet: {c.missing.join(", ")}.</p>}
            <div className="mt-4"><RiskChart hist={data.history} on={data.thresholds.risk_on} off={data.thresholds.risk_off} /></div>
          </details>
        </>
      )}
    </Panel>
  );
}

function ScoreTable({ title, head, rows }: { title: string; head: string; rows: { name: string; score: number; note?: string }[] }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-md border border-line">
      <table className="w-full text-sm">
        <thead><tr className="bg-panel-2 text-xs text-muted"><th className="px-3 py-2 text-left font-medium">{title}</th>
          <th className="px-3 py-2 text-right font-medium">{head}</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.name} className={`border-t border-line ${r.score > 0 ? "bg-[#3d4fd6]/35" : r.score < 0 ? "bg-[#e45d5d]/30" : ""}`} title={r.note}>
            <td className="px-3 py-1.5 font-medium">{r.name}</td><td className="px-3 py-1.5 text-right tabular-nums">{r.score > 0 ? `+${r.score}` : r.score}</td>
          </tr>))}
          {!rows.length && <tr><td colSpan={2} className="px-3 py-2 text-muted">No other currency has data yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function Heatmap() {
  const [ccy, setCcy] = useState("USD");
  const { data: d, error, loading } = useApi<any>(`/api/macro/heatmap?currency=${ccy}`);
  const tabs: Record<string, any> = Object.fromEntries((d?.tabs || []).map((t: any) => [t.currency, t]));
  return (
    <Panel title={`${ccy} economic heatmap`}>
      <div role="tablist" aria-label="Currency" className="mb-4 flex flex-wrap gap-1">
        {CURRENCIES.map((c) => {
          const t = tabs[c];
          return (
            <button key={c} role="tab" aria-selected={ccy === c} onClick={() => setCcy(c)}
              className={`rounded border px-3 py-1.5 text-sm ${ccy === c ? "border-verify bg-panel-2 text-text" : "border-line text-muted hover:text-text"}`}>
              {c}{t && t.rows > 0 && <span className={`ml-1.5 text-xs ${t.score > 0 ? "text-[#7d8cff]" : t.score < 0 ? "text-[#ff7b7b]" : "text-muted"}`}>
                {t.score > 0 ? `+${t.score}` : t.score}</span>}
            </button>
          );
        })}
      </div>
      <ErrorBox error={error} />
      {loading && !d ? <Loading /> : !d?.rows?.length ? (
        <Empty href="/data-input" cta="Add data">No {ccy} releases stored yet. They appear here as soon as actuals come in from the feeds, the calendar or Data input.</Empty>
      ) : (
        <>
          <p className="mb-3 max-w-[80ch] text-xs text-muted">Surprise is actual minus forecast (or your own figure from the calendar). A hawkish surprise is
            bullish for {ccy}; stronger growth, jobs or spending is bullish for {d.stock_index}, while hotter inflation is bearish for it.</p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[56rem] border-separate border-spacing-y-1 text-sm">
              <thead><tr className="text-left text-xs text-muted">
                <th className="px-2 font-medium">{ccy} economic data</th><th className="px-2 font-medium">Date</th>
                <th className="px-2 text-center font-medium">Surprise</th><th className="px-2 text-center font-medium">Actual</th>
                <th className="px-2 text-center font-medium">Forecast</th><th className="px-2 text-center font-medium">Previous</th>
                <th className="px-2 text-center font-medium">{ccy} impact</th><th className="px-2 text-center font-medium">Stocks impact</th>
              </tr></thead>
              <tbody>
                {d.rows.map((r: any) => (
                  <tr key={r.indicator}>
                    <td className="max-w-[16rem] truncate px-2 py-1.5" title={`${r.name} (${r.period})`}>
                      {r.event_id ? <Link href={`/calendar/${r.event_id}`} className="hover:underline">{r.name}</Link> : r.name}
                      <span className="ml-1 text-xs text-muted">{r.period}</span></td>
                    <td className={`whitespace-nowrap px-2 ${r.new ? "font-medium text-amber" : "text-muted"}`} title={r.new ? "Released in the last 2 days" : undefined}>{shortDate(r.date)}</td>
                    <td className={`rounded px-2 text-center font-medium tabular-nums ${cellFor(r.currency_impact)}`}>{fmt(r.surprise, r.unit, true)}</td>
                    <td className={`px-2 text-center tabular-nums ${textFor(r.currency_impact)}`}>{fmt(r.actual, r.unit)}</td>
                    <td className="px-2 text-center tabular-nums">{fmt(r.forecast, r.unit)}</td>
                    <td className="px-2 text-center tabular-nums text-muted">{fmt(r.previous, r.unit)}</td>
                    <td className={`rounded px-2 py-1.5 text-center font-medium ${cellFor(r.currency_impact)}`}>{r.currency_impact}</td>
                    <td className={`rounded px-2 py-1.5 text-center font-medium ${cellFor(r.stocks_impact)}`}>{r.stocks_impact}</td>
                  </tr>
                ))}
                <tr>
                  <td colSpan={6} className="px-2 pt-2 text-right text-xs text-muted">Share of releases that are bullish</td>
                  <td className="px-2 pt-2 text-center font-medium">{d.currency_bullish_pct === null ? "—" : `${num(d.currency_bullish_pct, 2)}%`}</td>
                  <td className="px-2 pt-2 text-center font-medium">{d.stocks_bullish_pct === null ? "—" : `${num(d.stocks_bullish_pct, 2)}%`}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_1fr_auto]">
            <ScoreTable title="Asset" head="Macro / eco score"
              rows={d.assets.map((a: any) => ({ name: a.asset, score: a.score, note: a.basis }))} />
            <ScoreTable title="Pair" head="Eco score vs counter currency"
              rows={d.pairs.map((p: any) => ({ name: p.pair, score: p.score, note: `${p.pair.slice(0, 3)} ${p.base_score} vs ${p.pair.slice(3)} ${p.quote_score}` }))} />
            <div className="flex justify-center gap-4">
              <Gauge pct={d.currency_bullish_pct} label={`${ccy} bullish`} />
              <Gauge pct={d.stocks_bullish_pct} label={`${d.stock_index} bullish`} />
            </div>
          </div>
          <p className="mt-3 text-xs text-muted">Scores: +1 for each bullish release, −1 for each bearish one. A pair's score is the base currency's score minus the quote currency's
            {ccy === "USD" ? "; gold and silver lean against the dollar's score, oil follows the US growth (stocks) score" : ""}.</p>
        </>
      )}
    </Panel>
  );
}

export default function Macro() {
  return (
    <>
      <PageTitle title="Macro" subtitle="The global regime, the risk-on / risk-off mood, and each currency's latest economic releases scored against forecasts." />
      <div className="space-y-6">
        <Regime />
        <RiskSentiment />
        <Heatmap />
      </div>
    </>
  );
}
