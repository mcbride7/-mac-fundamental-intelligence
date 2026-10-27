"use client";

import { useState } from "react";

import NewsNote from "@/components/NewsNote";
import { Button, Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { post, useApi } from "@/lib/api";

const CCYS = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY", "XAU", "OIL"];
const LABEL: Record<string, string> = { XAU: "Gold", OIL: "Oil" };
const TONE_CLS: Record<string, string> = {
  hawkish: "bg-[#3d4fd6]/25 text-[#9aa6ff]", dovish: "bg-[#e45d5d]/25 text-[#ff9b9b]",
  risk_on: "bg-[#43a047]/25 text-[#9ccc65]", risk_off: "bg-amber/20 text-amber",
};

function ago(iso: string) {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function Breakdown({ pick, data, onClose, onFilter }: { pick: string; data: any; onClose: () => void; onFilter: () => void }) {
  const risk = pick === "RISK";
  const t = risk ? null : data.tone[pick];
  const items: any[] = risk ? data.risk.items : t.breakdown;
  const counted = items.filter((b) => b.points !== 0);
  const ignored = items.filter((b) => b.points === 0);
  const name = risk ? "Risk mood" : LABEL[pick] || pick;
  const line = (b: any) => (
    <li key={b.id} className="flex items-start gap-2 py-1.5">
      <span className={`mt-0.5 inline-block w-8 shrink-0 rounded text-center text-xs font-semibold tabular-nums ${b.points > 0 ? (risk ? "bg-[#43a047] text-white" : "bg-[#3d4fd6] text-white") : b.points < 0 ? (risk ? "bg-[#c98a00] text-white" : "bg-[#e45d5d] text-white") : "bg-panel-2 text-muted"}`}>
        {b.points > 0 ? `+${b.points}` : b.points}</span>
      <span className="min-w-0">
        {b.url ? <a href={b.url} target="_blank" rel="noreferrer" className="hover:text-verify hover:underline">{b.title}</a> : b.title}
        <span className="block text-xs text-muted">{b.source} · {ago(b.published_at)}{risk ? ` · ${b.risk === "risk_on" ? "risk-on" : "risk-off"} wording` : ` · ${b.why}`}</span>
      </span>
    </li>
  );
  return (
    <div className="mt-4 rounded border border-verify/60 bg-panel-2/40 p-3">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-medium">{risk ? <>Risk mood: {data.risk.risk_on} risk-on − {data.risk.risk_off} risk-off headlines = {data.risk.risk_on - data.risk.risk_off > 0 ? "+" : ""}{data.risk.risk_on - data.risk.risk_off} → {data.risk.lean}</>
          : <>{name}: {t.hawkish} hawkish − {t.dovish} dovish = {t.net > 0 ? "+" : ""}{t.net} → {t.lean}</>}</h3>
        <span className="flex gap-2 text-xs">
          {!risk && <button onClick={onFilter} className="rounded border border-line px-2 py-1 hover:bg-panel-2">Show all {name} headlines below</button>}
          <button onClick={onClose} className="rounded border border-line px-2 py-1 hover:bg-panel-2">Close</button>
        </span>
      </div>
      <p className="mb-2 text-xs text-muted">Headlines from the last 3 days. {risk ? "Each risk-on headline counts +1 and each risk-off one −1." : "Each hawkish headline counts +1 and each dovish one −1."}</p>
      {counted.length ? <ul className="divide-y divide-line/60 text-sm">{counted.map(line)}</ul>
        : <p className="text-sm text-muted">No headline counted {risk ? "towards the risk mood" : `towards ${name}`} in the last 3 days.</p>}
      {ignored.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-xs text-muted">{ignored.length} more mention {name} but didn&rsquo;t count (tap to see why)</summary>
          <ul className="divide-y divide-line/60">{ignored.map(line)}</ul>
        </details>
      )}
    </div>
  );
}

export default function NewsPage() {
  const [ccy, setCcy] = useState("");
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [days, setDays] = useState(3);
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState("");  // tile whose scoring is shown ("RISK" for the risk mood)
  const qs = new URLSearchParams({ days: String(days), ...(ccy && { currency: ccy }), ...(topic && { topic }),
    ...(tone && { tone }), ...(kind && { kind }), ...(q && { q }) }).toString();
  const { data, error, loading, reload } = useApi<any>(`/api/news?${qs}`);
  const refresh = async () => { setBusy(true); try { await post("/api/news/refresh"); reload(); } finally { setBusy(false); } };
  const feeds = Object.entries<any>(data?.feeds || {});
  const failed = feeds.filter(([, f]) => !f.ok);
  const sel = (label: string, value: string, set: (v: string) => void, opts: [string, string][]) => (
    <label className="flex min-w-0 flex-col gap-1 text-xs text-muted">{label}
      <select value={value} onChange={(e) => set(e.target.value)} className="rounded border border-line bg-panel-2 px-2 py-1.5 text-sm text-text">
        {opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  );
  return (
    <>
      <PageTitle title="News"
        subtitle="Central bank press releases and FX headlines, tagged by currency, topic and tone. Hawkish news supports a currency, dovish news weighs on it; the last 3 days feed the News tone column on Top setups." />
      <div className="space-y-6">
        <Panel title="News tone by currency · last 3 days" collapseId="news-tone"
          action={<span className="text-xs text-muted">Tap a currency to see which headlines make up its score</span>}>
          <div className="flex flex-col-reverse gap-4 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
          {!data ? <Loading /> : (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
                {CCYS.map((c) => {
                  const t = data.tone[c];
                  const cls = t.lean === "Hawkish" ? "border-[#3d4fd6] bg-[#3d4fd6]/15" : t.lean === "Dovish" ? "border-[#e45d5d] bg-[#e45d5d]/15" : "border-line";
                  return (
                    <button key={c} onClick={() => setPick(pick === c ? "" : c)} aria-expanded={pick === c}
                      title={`See which headlines make up ${LABEL[c] || c}'s score`}
                      className={`rounded border px-3 py-2 text-left hover:bg-panel-2 ${cls} ${pick === c ? "ring-2 ring-verify" : ""}`}>
                      <div className="flex items-baseline justify-between"><span className="font-semibold">{LABEL[c] || c}</span>
                        <span className={`text-sm tabular-nums ${t.net > 0 ? "text-[#9aa6ff]" : t.net < 0 ? "text-[#ff9b9b]" : "text-muted"}`}>{t.net > 0 ? "+" : ""}{t.net}</span></div>
                      <div className="text-xs text-muted">{c === "XAU" || c === "OIL" ? `${t.articles} headlines` : `${t.lean} · ${t.hawkish}↑ ${t.dovish}↓`}</div>
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 text-sm">Risk mood in the headlines:{" "}
                <button onClick={() => setPick(pick === "RISK" ? "" : "RISK")} aria-expanded={pick === "RISK"} className="underline decoration-dotted underline-offset-2">
                  <b className={data.risk.lean === "Risk-off" ? "text-amber" : data.risk.lean === "Risk-on" ? "text-[#9ccc65]" : ""}>{data.risk.lean}</b>
                  <span className="text-muted"> ({data.risk.risk_on} risk-on, {data.risk.risk_off} risk-off)</span></button></p>
              {pick && <Breakdown pick={pick} data={data} onClose={() => setPick("")}
                onFilter={() => { if (pick !== "RISK") { setCcy(pick); setDays(3); } else { setTone(""); } setPick(""); }} />}
            </>
          )}
          </div>
          <div className="flex justify-end sm:shrink-0"><NewsNote /></div>
          </div>
        </Panel>

        <Panel title="Headlines" collapseId="news-list"
          action={<Button onClick={refresh} disabled={busy}>{busy ? "Fetching…" : "Refresh now"}</Button>}>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <label className="flex min-w-0 flex-col gap-1 text-xs text-muted">Search
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Powell, CPI" className="rounded border border-line bg-panel-2 px-2 py-1.5 text-sm text-text" />
            </label>
            {sel("Currency", ccy, setCcy, [["", "All"], ...CCYS.map((c) => [c, LABEL[c] || c] as [string, string])])}
            {sel("Topic", topic, setTopic, [["", "All topics"], ...(data?.topics || []).map((t: string) => [t, t] as [string, string])])}
            {sel("Tone", tone, setTone, [["", "Any"], ["hawkish", "Hawkish"], ["dovish", "Dovish"], ["neutral", "Neutral"], ["risk_on", "Risk-on"], ["risk_off", "Risk-off"]])}
            {sel("Source", kind, setKind, [["", "All"], ["central_bank", "Central banks only"], ["news", "News sites only"]])}
            {sel("Period", String(days), (v) => setDays(Number(v)), [["1", "Last 24 hours"], ["3", "Last 3 days"], ["7", "Last 7 days"], ["30", "Last 30 days"]])}
          </div>
          <ErrorBox error={error} />
          {loading && !data ? <Loading /> : !data?.articles?.length ? (
            <Empty>{data?.last_run ? "No headlines match these filters." : "No news fetched yet. Press Refresh now (it also updates every 20 minutes)."}</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {data.articles.map((a: any) => (
                <li key={a.id} className="py-3">
                  <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                    <span className={a.kind === "central_bank" ? "font-medium text-verify" : ""}>{a.source}</span>
                    <span>· {ago(a.published_at)}</span>
                    {a.importance === "high" && <span className="rounded bg-amber/20 px-1.5 py-px font-medium text-amber">High impact</span>}
                    {a.tone !== "neutral" && <span className={`rounded px-1.5 py-px ${TONE_CLS[a.tone]}`}>{a.tone === "hawkish" ? "Hawkish" : "Dovish"}</span>}
                    {a.risk && <span className={`rounded px-1.5 py-px ${TONE_CLS[a.risk]}`}>{a.risk === "risk_on" ? "Risk-on" : "Risk-off"}</span>}
                    {a.currencies.map((c: string) => <span key={c} className="rounded border border-line px-1.5 py-px">{LABEL[c] || c}</span>)}
                    {a.topics.map((t: string) => <span key={t} className="text-muted">#{t}</span>)}
                  </div>
                  {a.url ? <a href={a.url} target="_blank" rel="noreferrer" className="font-medium hover:text-verify hover:underline">{a.title}</a>
                    : <span className="font-medium">{a.title}</span>}
                  {a.summary && a.summary !== a.title && <p className="mt-1 max-w-[95ch] text-sm text-muted">{a.summary}</p>}
                </li>
              ))}
            </ul>
          )}
          {data && (
            <p className="mt-3 text-xs text-muted">
              {data.total > data.articles.length ? `Showing ${data.articles.length} of ${data.total}. ` : ""}
              {data.last_run ? `Last fetched ${ago(data.last_run)}. ` : ""}
              {feeds.length > 0 && `Feeds working: ${feeds.length - failed.length} of ${feeds.length}`}
              {failed.length > 0 && <> (not reachable: {failed.map(([, f]) => f.name).join(", ")})</>}.
              Tags are worked out from keywords, so treat them as a quick guide. Headlines link to the publisher for the full article.
            </p>
          )}
        </Panel>
      </div>
    </>
  );
}
