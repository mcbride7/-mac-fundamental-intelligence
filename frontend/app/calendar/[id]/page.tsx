"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Disclaimer, Empty, ErrorBox, Loading, PageTitle, Panel, Stat, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/api";
import { num, pair, signed, toneClass } from "@/lib/format";

export default function EventReport() {
  const { id } = useParams<{ id: string }>();
  const { data: r, error, loading } = useApi<any>(`/api/economic-events/${id}`);
  if (loading && !r) return <Loading what="Building the event report" />;
  if (error) return <ErrorBox error={error} />;
  if (!r) return null;
  if (r.actual === null) return <Empty href="/data-input" cta="Provide the data">{r.message}</Empty>;
  const u = r.unit === "%" ? "%" : r.unit === "k" ? "k" : "";
  return (
    <>
      <PageTitle title={`${r.event.name}, ${r.event.reference_period}`} subtitle={`${r.event.currency} ${r.event.importance} importance`}>
        <StatusBadge status={r.data_status.status} title={r.data_status.badge} />
      </PageTitle>
      <Panel>
        <div className="grid grid-cols-2 gap-5 sm:grid-cols-5">
          <Stat label="Previous" value={num(r.previous, 2, u)} />
          <Stat label="Market forecast" value={num(r.market_forecast, 2, u)} />
          <Stat label="Central-bank projection" value={num(r.central_bank_projection, 1, u)} />
          <Stat label="Actual" value={num(r.actual, 2, u)} />
          <Stat label="Surprise" value={r.classification || "—"} tone={toneClass(r.classification)}
            sub={r.historical_z != null ? `${signed(r.historical_z, 1)}σ, ${r.policy_direction}` : undefined} />
        </div>
      </Panel>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel title="What happened?">
          <p className="note">{r.narrative.what_happened}</p>
          <p className="note mt-3"><span className="text-muted">Was it expected? </span>{r.narrative.was_it_expected}</p>
          <p className="note mt-3"><span className="text-muted">Consistent with the projection? </span>{r.narrative.consistent_with_projection}</p>
        </Panel>
        <Panel title="Who forecast it best?">
          {r.three_way ? (
            <table className="grid-table">
              <thead><tr><th></th><th>Forecast</th><th>Error</th></tr></thead>
              <tbody>
                <tr><td>Central bank</td><td>{num(r.three_way.central_bank, 2, u)}</td><td>{signed(r.three_way.cb_error, 2)}</td></tr>
                <tr><td>Market</td><td>{num(r.three_way.market, 2, u)}</td><td>{signed(r.three_way.market_error, 2)}</td></tr>
                <tr><td>Actual</td><td className="font-medium">{num(r.three_way.actual, 2, u)}</td><td /></tr>
              </tbody>
            </table>
          ) : <p className="text-sm text-muted">No forecast to compare.</p>}
          {r.three_way?.more_accurate && <p className="mt-3 text-sm">More accurate: {r.three_way.more_accurate.replace("_", " ")}</p>}
          {r.revisions.length > 1 && (
            <p className="mt-3 text-sm text-muted">Revisions: {r.revisions.map((x: any) => `${x.value}${x.current ? " (current)" : ""}`).join(" → ")}</p>
          )}
        </Panel>
        {r.why_forecast_missed && (
          <Panel title="Why did the forecast miss?">
            <p className="note">{r.why_forecast_missed.narrative || r.why_forecast_missed.summary}</p>
            <ul className="mt-3 space-y-1 text-sm">
              {r.why_forecast_missed.evidence.map((e: any, i: number) => (
                <li key={i}><span className="text-muted">{e.factor}: </span>{e.observation}<span className="text-xs text-muted"> ({e.source})</span></li>
              ))}
            </ul>
          </Panel>
        )}
        <Panel title="Policy implication">
          {r.policy_implication ? (
            <>
              <p className={toneClass(r.policy_implication.classification)}>{r.policy_implication.central_bank}: {r.policy_implication.classification} ({num(r.policy_implication.score, 0)}/100)</p>
              <p className="text-sm text-muted">{r.policy_implication.shift_classification} ({signed(r.policy_implication.shift, 0)})</p>
              <ul className="mt-2 list-disc pl-5 text-sm">{r.policy_implication.explanation.slice(0, 5).map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
            </>
          ) : <p className="text-sm text-muted">No linked central bank.</p>}
          {r.rate_expectation_change && <p className="note mt-3 text-sm">{r.rate_expectation_change.explanation}</p>}
        </Panel>
        <Panel title="Market reaction">
          {r.bond_market_reaction && (
            <ul className="mb-3 text-sm">{Object.entries(r.bond_market_reaction).map(([k, v]: any) => (
              <li key={k}>{k}: {num(v.before, 2)}% → {num(v.after, 2)}% <span className={toneClass(v.change_bps)}>({signed(v.change_bps, 1)} bp)</span></li>))}</ul>
          )}
          {r.fx_and_asset_reaction ? (
            <table className="grid-table">
              <thead><tr><th>Asset</th>{Object.keys(r.fx_and_asset_reaction.windows).map((w) => <th key={w}>{w}</th>)}</tr></thead>
              <tbody>
                {Object.keys(Object.values(r.fx_and_asset_reaction.windows)[0] as object || {}).map((sym) => (
                  <tr key={sym}><td>{sym}</td>{Object.values(r.fx_and_asset_reaction.windows).map((w: any, i) => <td key={i}>{signed(w[sym], 2)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-sm text-muted">No intraday prices stored around the release time.</p>}
        </Panel>
        <Panel title="Scenarios and invalidation">
          {Object.entries(r.scenarios).map(([asset, sc]: any) => (
            <div key={asset} className="mb-3 text-sm">
              <Link href={`/analysis/${asset}`} className="font-medium hover:underline">{pair(asset)}</Link>
              <ul className="text-muted">{sc.map((s: any) => <li key={s.kind}>{s.kind}: {s.title} ({s.probability}%)</li>)}</ul>
            </div>
          ))}
          {r.invalidation.length > 0 && <><p className="mt-2 text-sm">Invalidation</p>
            <ul className="list-disc pl-5 text-sm text-muted">{r.invalidation.map((x: string) => <li key={x}>{x}</li>)}</ul></>}
        </Panel>
      </div>
      <Disclaimer />
    </>
  );
}
