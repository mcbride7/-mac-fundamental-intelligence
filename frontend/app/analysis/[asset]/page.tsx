"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import Scenarios from "@/components/Scenarios";
import { Button, Disclaimer, ErrorBox, GradeBadge, Loading, PageTitle, Panel, Stat, StatusBadge } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { biasClass, num, pair, signed } from "@/lib/format";

const WEIGHTS: Record<string, number> = { "Central Bank Divergence": 20, "Rate Differential": 18, "Inflation Differential": 12,
  "Growth Differential": 10, "Yield Differential": 12, "Economic Surprise": 8, "Risk Sentiment": 5,
  "Employment Differential": 5, "Forecast Deviation": 5, Positioning: 5 };

export default function Asset() {
  const { asset } = useParams<{ asset: string }>();
  const { data: a, error, loading } = useApi<any>(`/api/fundamental/${asset}`);
  const [watched, setWatched] = useState(false);
  if (loading && !a) return <Loading what={`Analysing ${pair(asset)}`} />;
  if (error) return <ErrorBox error={error} />;
  if (!a) return null;
  const r = a.report;
  return (
    <>
      <PageTitle title={pair(a.asset)} subtitle={`Time horizon ${a.time_horizon}. ${a.data_status}.`}>
        <Button kind="ghost" disabled={watched} onClick={async () => { await post("/api/watchlist", { asset: a.asset }); setWatched(true); }}>
          {watched ? "On watchlist" : "Add to watchlist"}</Button>
      </PageTitle>
      <section className="mb-6 grid gap-6 lg:grid-cols-[1fr_24rem]">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <span className={`text-3xl font-semibold ${biasClass(a.bias)}`}>{a.bias.toLowerCase().replace(/^\w/, (c: string) => c.toUpperCase())}</span>
            <GradeBadge grade={a.grade} />
            {a.direction !== "NONE" && <span className={biasClass(a.direction)}>{a.direction.toLowerCase()} bias</span>}
          </div>
          <p className="note mt-3 text-[1.05rem]">{r.conclusion}</p>
          {a.no_trade_reasons.length > 0 && (
            <div className="mt-4 rounded border border-line bg-panel p-3 text-sm">
              <p className="font-medium">Why NO TRADE</p>
              <ul className="mt-1 list-disc pl-5 text-muted">{a.no_trade_reasons.map((x: string) => <li key={x}>{x}</li>)}</ul>
            </div>
          )}
          {a.grade_cap_reason && <p className="mt-2 text-sm text-amber">Grade capped at {a.grade_cap}: {a.grade_cap_reason}</p>}
        </div>
        <Panel>
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Conviction" value={`${num(a.conviction, 0)}/100`} />
            <Stat label="Confluence" value={signed(a.confluence_total, 0)} sub={`${Math.round(a.agreement * 100)}% of factors agree`} />
            <Stat label="Evidence quality" value={`${num(a.evidence_quality, 0)}/100`} />
            <Stat label="Forecast confidence" value={`${num(a.forecast_confidence, 0)}/100`} />
            <Stat label="Scenario confidence" value={`${num(a.scenario_confidence, 0)}/100`} />
            <Stat label="Primary driver" value={<span className="text-sm">{a.primary_driver || "—"}</span>} />
          </div>
          <p className="mt-3 text-xs text-muted">Confidence describes the analysis, not the probability of a market outcome.</p>
        </Panel>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Trade confluence">
          <ul className="space-y-2">
            {Object.entries(a.factors).map(([k, v]: any) => {
              const w = WEIGHTS[k] || 10;
              return (
                <li key={k} className="grid grid-cols-[minmax(0,9rem)_1fr_2.5rem] items-center gap-2 text-sm sm:grid-cols-[11rem_1fr_3rem] sm:gap-3">
                  <span>{k}</span>
                  <span className="relative h-2 rounded bg-panel-2">
                    <span className={`absolute top-0 h-2 rounded ${v >= 0 ? "bg-dove" : "bg-hawk"}`}
                      style={{ left: v >= 0 ? "50%" : `${50 + (v / w) * 50}%`, width: `${(Math.abs(v) / w) * 50}%` }} />
                    <span className="absolute left-1/2 top-[-3px] h-3.5 w-px bg-muted" />
                  </span>
                  <span className={`text-right ${v > 0 ? "text-dove" : v < 0 ? "text-hawk" : "text-muted"}`}>{signed(v, 0)}</span>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 text-xs text-muted">Positive favours {a.asset.slice(0, 3)}, negative favours {a.asset.slice(3)}.
            {a.unavailable_factors.length > 0 && ` Not available: ${a.unavailable_factors.join(", ")}.`}</p>
        </Panel>
        <Panel title="Differentials">
          <table className="grid-table">
            <tbody>{Object.entries(a.differentials).map(([k, v]: any) => (
              <tr key={k}><td className="capitalize">{k.replaceAll("_", " ")}</td><td className="text-right">{signed(v, 2)}</td></tr>))}</tbody>
          </table>
          <div className="mt-4 text-sm">
            <p className="text-muted">Why it matters</p>
            <ul className="mt-1 list-disc pl-5">{r.why_it_matters.map((x: string) => <li key={x}>{x}</li>)}</ul>
          </div>
        </Panel>
        <Panel title="Scenarios" className="lg:col-span-2"><Scenarios scenarios={a.scenarios} /></Panel>
        <Panel title="Catalysts">
          {a.catalysts.length === 0 ? <p className="text-sm text-muted">No scheduled events in the next two weeks.</p> : (
            <ul className="space-y-1.5 text-sm">{a.catalysts.map((c: any, i: number) => (
              <li key={i} className="flex justify-between gap-3"><span>{c.name}</span><span className="text-muted">{c.date}</span></li>))}</ul>
          )}
        </Panel>
        <Panel title="Risks">
          <ul className="list-disc space-y-1 pl-5 text-sm">{a.risks.map((x: string) => <li key={x}>{x}</li>)}</ul>
          <p className="mt-3 text-sm"><span className="text-muted">Alternative: </span>{a.alternative}</p>
        </Panel>
        <Panel title="Evidence" className="lg:col-span-2">
          <table className="grid-table">
            <thead><tr><th>Data point</th><th>Value</th><th>Period</th><th>Source</th><th>Status</th></tr></thead>
            <tbody>{r.facts.map((f: any) => (
              <tr key={`${f.id}-${f.label}`}><td>{f.label} <span className="text-xs text-muted">{f.indicator}</span></td><td>{f.value}</td>
                <td>{f.period}</td><td className="text-muted">{f.source || f.input_method}</td><td><StatusBadge status={f.status} /></td></tr>))}</tbody>
          </table>
        </Panel>
      </div>
      <Disclaimer />
    </>
  );
}
