"use client";

import { useState } from "react";

import { Button, Empty, ErrorBox, PageTitle, Panel } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { num } from "@/lib/format";

const QUESTIONS = ["Why is EUR/USD bearish?", "Is the Fed becoming more dovish?", "Did the Fed underestimate inflation?",
  "Which central bank has the best inflation forecast?", "Which currency has the strongest fundamentals?",
  "Which upcoming event has the highest potential market impact?", "What would make GBP/USD bullish?",
  "Is the market underpricing inflation?", "When inflation exceeded Fed projections, how did USD perform?"];

const SECTIONS: [string, string][] = [["market_expectation", "Market expectation"], ["central_bank_projection", "Central-bank projection"],
  ["forecast_accuracy", "Forecast accuracy"], ["what_changed", "What changed?"], ["why_it_matters", "Why it matters"],
  ["policy_implication", "Policy implication"], ["scenarios", "Scenarios"], ["confirmation", "Confirmation"],
  ["invalidation", "Invalidation"], ["trade_bias", "Trade bias"], ["risk", "Risk"]];

function Value({ v }: { v: any }) {
  if (v === null || v === undefined) return null;
  if (Array.isArray(v)) return <ul className="list-disc pl-5">{v.map((x, i) => <li key={i}>{typeof x === "object" ? (x.title ? `${x.title} (${x.probability}%)` : JSON.stringify(x)) : String(x)}</li>)}</ul>;
  if (typeof v === "object") return <pre className="overflow-auto whitespace-pre-wrap text-xs text-muted">{JSON.stringify(v, null, 2)}</pre>;
  return <p>{String(v)}</p>;
}

export default function Research() {
  const [q, setQ] = useState("");
  const [ans, setAns] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fc = useApi<any[]>("/api/forecastability");
  const rank = useApi<any>("/api/forecast-accuracy?variable=inflation");
  const ask = async (question: string) => {
    setQ(question); setBusy(true); setErr(null);
    try { setAns(await post("/api/ai/search", { question })); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <>
      <PageTitle title="AI research" subtitle="Ask in plain language. Answers are built from the platform's own stored evidence and cite it, including whether each data point is verified." />
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask(q); }} className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a macro question…" aria-label="Question"
          className="flex-1 rounded border border-line bg-panel px-3 py-2" />
        <Button type="submit" disabled={busy}>{busy ? "Thinking…" : "Ask"}</Button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {QUESTIONS.map((x) => <button key={x} onClick={() => ask(x)} className="rounded border border-line px-2.5 py-1 text-xs text-muted hover:text-text">{x}</button>)}
      </div>
      <div className="mt-4"><ErrorBox error={err} /></div>
      {ans && (
        <Panel title="Answer" className="mt-6">
          <p className="note text-[1.05rem]">{ans.conclusion_ai || ans.conclusion}</p>
          <div className="mt-4 grid gap-4 text-sm md:grid-cols-2">
            {SECTIONS.filter(([k]) => ans[k] !== undefined).map(([k, label]) => (
              <div key={k}><p className="mb-1 text-muted">{label}</p><Value v={ans[k]} /></div>))}
          </div>
          {ans.citations?.length > 0 && (
            <div className="mt-5 border-t border-line pt-3">
              <p className="mb-1 text-sm text-muted">Evidence</p>
              <ol className="list-decimal space-y-1 pl-5 text-sm">{ans.citations.map((c: any) => (
                <li key={c.ref}>{c.text} <span className="text-xs text-muted">({c.source || c.type}; {c.status})</span></li>))}</ol>
            </div>
          )}
        </Panel>
      )}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel title="Inflation forecast ranking (5 years, real-time data)">
          {!rank.data?.by_variable?.inflation?.length ? <Empty>Rankings appear once projections and outcomes have been stored.</Empty> : (
            <ol className="list-decimal space-y-1 pl-5 text-sm">{rank.data.by_variable.inflation.map((r: any) => (
              <li key={r.forecaster}>{r.forecaster}: {num(r.score, 0)}/100 <span className="text-xs text-muted">MAE {num(r.mae, 2)}, n={r.n}</span></li>))}</ol>
          )}
        </Panel>
        <Panel title="Forecastability">
          {!fc.data?.length ? <Empty>Needs consensus forecasts and outcomes for at least four releases per indicator.</Empty> : (
            <>
              <ul className="space-y-1 text-sm">{fc.data.map((f) => (
                <li key={f.indicator} className="flex justify-between"><span>{f.name}</span><span>{num(f.forecastability, 0)}/100</span></li>))}</ul>
              <p className="mt-3 text-xs text-muted">{fc.data[0].explanation}</p>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}
