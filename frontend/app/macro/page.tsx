"use client";

import Link from "next/link";
import { useState } from "react";

import SurveysPanel from "@/components/SurveysPanel";
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
      <PageTitle title="Macro" subtitle="The global regime, and each currency's latest economic releases scored against forecasts. The risk-on / risk-off mood has its own page: Risk sentiment." />
      <div className="space-y-6">
        <Regime />
        <SurveysPanel />
        <Heatmap />
      </div>
    </>
  );
}
