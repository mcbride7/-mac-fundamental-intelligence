"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import CbShortcuts from "@/components/CbShortcuts";
import QuickEdit from "@/components/QuickEdit";
import StatementCompare, { StatementReader } from "@/components/StatementCompare";
import { Button, Empty, ErrorBox, Loading, PageTitle, Panel, PolicyDial, Stat, StatusBadge } from "@/components/ui";
import { patch, post, useApi } from "@/lib/api";
import { date, dateTime, num, signed, toneClass } from "@/lib/format";

const TABS = ["Overview", "Policy", "Statement comparison", "Projections", "Forecast accuracy", "Where are we now",
  "Market expectations", "History"] as const;

export default function Bank() {
  const { code } = useParams<{ code: string }>();
  const { data: d, error, loading, reload } = useApi<any>(`/api/central-banks/${code}`);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [ver, setVer] = useState(0); // bumped after a fetched document is saved, so the tabs reload
  if (loading && !d) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!d) return null;
  const p = d.policy;
  return (
    <>
      <PageTitle title={d.name} subtitle={`${d.currency}, inflation target ${num(d.inflation_target, 1, "%")}`}>
        <div className="w-full max-w-sm"><PolicyDial score={p?.score} previous={p?.previous_score} /></div>
      </PageTitle>
      <div role="tablist" className="mb-5 flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-verify text-text" : "border-transparent text-muted hover:text-text"}`}>
            {t}
          </button>
        ))}
      </div>
      <div key={ver}>
      {tab === "Overview" && <Overview d={d} onSaved={reload} />}
      {tab === "Policy" && <Policy d={d} />}
      {tab === "Statement comparison" && <StatementCompare code={code} onAdded={reload} />}
      {tab === "Projections" && <Projections code={code} />}
      {tab === "Forecast accuracy" && <Accuracy acc={d.forecast_accuracy} />}
      {tab === "Where are we now" && <WhereAreWe w={d.where_are_we} />}
      {tab === "Market expectations" && <Expectations d={d} />}
      {tab === "History" && <History code={code} />}
      {(tab === "Overview" || tab === "Statement comparison" || tab === "Projections") && (
        <div className="mt-6"><CbShortcuts code={d.code || code} names={{ [d.code || code]: d.name }} onSaved={() => { reload(); setVer((v) => v + 1); }} /></div>
      )}
      </div>
    </>
  );
}

function Overview({ d, onSaved }: { d: any; onSaved: () => void }) {
  const p = d.policy;
  const edit = async (field: string, value: string | null, extra: Record<string, unknown> = {}) => {
    await patch(`/api/central-banks/${d.code}/overview`, { field, value, ...extra });
    onSaved();
  };
  const src = (label: string) => d.data_status.sources.find((s: any) => s.label === label);
  const thisMonth = new Date().toISOString().slice(0, 7);
  const lastQuarter = (() => {
    const t = new Date(); const q = Math.floor(t.getMonth() / 3);
    return q === 0 ? `${t.getFullYear() - 1}Q4` : `${t.getFullYear()}Q${q}`;
  })();
  const nb = (v: any) => (v === null || v === undefined ? "" : String(v));
  const rateSrc = src("Policy rate");
  const inflSrc = src("Headline inflation");
  const gdpSrc = src("GDP");
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-6">
        <Panel>
          <p className="mb-4 text-xs text-muted">Click a number with a dotted underline to change it. Enter saves, Esc cancels.
            Values you type are saved as unverified until the official source confirms them.</p>
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label="Current rate"
              value={<QuickEdit label="Current rate" display={num(d.current_rate, 2, "%")} initial={nb(d.current_rate)}
                period={d.rate_from_indicator ? { value: rateSrc?.period || thisMonth } : undefined}
                onSave={(v, per, reason) => edit("current_rate", v, { period: per, reason })} />}
              sub={d.rate_from_indicator
                ? <span title="Worked out from the rate history">Previous {num(d.previous_rate, 2, "%")}</span>
                : <>Previous <QuickEdit label="Previous rate" display={num(d.previous_rate, 2, "%")} initial={nb(d.previous_rate)}
                    onSave={(v) => edit("previous_rate", v)} /></>} />
            <Stat label="Last decision"
              value={d.rate_from_indicator
                ? <span title="Worked out from the rate history: change the current rate to update it">{d.last_decision || "—"}</span>
                : <QuickEdit label="Last decision" kind="decision" display={d.last_decision || "—"} initial={d.last_decision || "HOLD"}
                    onSave={(v) => edit("last_decision", v)} />}
              sub={d.last_change_bps ? `${signed(d.last_change_bps, 0)} bp` : undefined} />
            <Stat label="Next meeting"
              value={<QuickEdit label="Next meeting" kind="date" display={date(d.next_meeting)} initial={nb(d.next_meeting).slice(0, 10)}
                onSave={(v) => edit("next_meeting", v)} />}
              sub={d.next_meeting
                ? <>Expected: <QuickEdit label="Expected decision" kind="decision" allowEmpty
                    display={d.expected_decision || "not set"} initial={d.expected_decision || ""}
                    onSave={(v) => edit("expected_decision", v)} /></>
                : "Set the date first"} />
            <Stat label="Policy" value={p ? `${num(p.score, 0)}/100` : "—"} tone={toneClass(p?.classification)}
              sub={p ? `${p.classification}, ${p.direction.toLowerCase()}` : undefined} />
            <Stat label="Momentum" value={d.momentum || "—"} tone={toneClass(d.momentum)} />
            <Stat label="Inflation"
              value={d.edit_codes?.inflation
                ? <QuickEdit label="Inflation" display={num(d.inflation, 1, "%")} initial={nb(d.inflation)}
                    period={{ value: inflSrc?.period || thisMonth }}
                    onSave={(v, per, reason) => edit("release", v, { indicator_code: d.edit_codes.inflation, period: per, reason })} />
                : num(d.inflation, 1, "%")}
              sub={<>Target <QuickEdit label="Inflation target" display={num(d.inflation_target, 1, "%")} initial={nb(d.inflation_target)}
                onSave={(v) => edit("inflation_target", v)} /></>} />
            <Stat label="GDP (latest)"
              value={d.edit_codes?.gdp
                ? <QuickEdit label="GDP" display={num(d.growth, 1, "%")} initial={nb(d.growth)}
                    period={{ value: gdpSrc?.period || lastQuarter, quarterly: true }}
                    onSave={(v, per, reason) => edit("release", v, { indicator_code: d.edit_codes.gdp, period: per, reason })} />
                : num(d.growth, 1, "%")} />
            <Stat label="Unemployment, 6m change" value={<span title="Worked out from the unemployment rate history">{signed(d.unemployment_change_6m, 2, " pp")}</span>} />
          </div>
        </Panel>
        <Panel title="Current fundamental implication">
          {d.where_are_we.table.length ? (
            <>
              <p className={`text-lg ${toneClass(d.where_are_we.policy_implication.overall)}`}>{d.where_are_we.policy_implication.overall}</p>
              {d.where_are_we.policy_implication.explanation.map((e: string, i: number) => <p key={i} className="note mt-2">{e}</p>)}
            </>
          ) : <Empty href="/data-input" cta="Add a projection table">No projections stored yet, so actuals cannot be compared with what {d.short_name} expected.</Empty>}
        </Panel>
        <Panel title="Latest statement">
          {d.latest_statement ? (
            <>
              <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                <span>{d.latest_statement.title}</span><span className="text-muted">{date(d.latest_statement.published_at)}</span>
                <StatusBadge status={d.latest_statement.verification_status} />
                <span className={toneClass(d.latest_statement.tone_label)}>Tone {signed(d.latest_statement.tone_score, 0)}</span>
              </div>
              <p className="note text-sm text-muted">{d.latest_statement.excerpt}…</p>
              <ReadFull code={d.code} id={d.latest_statement.id} />
              {d.statement_changes && (
                <p className="mt-3 text-sm">{d.statement_changes.changed} changes vs previous statement:{" "}
                  <span className={toneClass(d.statement_changes.direction)}>{d.statement_changes.direction}</span></p>
              )}
            </>
          ) : <Empty href="/data-input" cta="Paste or upload a statement">No statement stored yet.</Empty>}
        </Panel>
      </div>
      <Panel title="Data behind this page">
        <p className="mb-3 text-sm text-muted">Evidence quality {num(d.data_status.evidence_quality, 0)}/100</p>
        <ul className="space-y-2 text-sm">
          {d.data_status.sources.map((s: any) => (
            <li key={`${s.id}-${s.label}`} className="flex items-start justify-between gap-2">
              <span>{s.label}<span className="block text-xs text-muted">
                {s.indicator ? <QuickEdit label={s.label} display={String(s.value)} initial={String(s.value)}
                  onSave={(v, _per, reason) => edit("release", v, { indicator_code: s.indicator, period: s.period, reason })} />
                  : s.value} ({s.period}), {s.source || s.input_method}</span></span>
              <StatusBadge status={s.status} />
            </li>
          ))}
          {d.data_status.sources.length === 0 && <li className="text-muted">No data yet.</li>}
        </ul>
      </Panel>
    </div>
  );
}

function ReadFull({ code, id }: { code: string; id: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="mt-2"><Button kind="ghost" onClick={() => setOpen(true)}>Read the full statement</Button></div>
      {open && <StatementReader code={code} id={id} onClose={() => setOpen(false)} />}
    </>
  );
}

function Policy({ d }: { d: any }) {
  const p = d.policy;
  if (!p) return <Empty>No policy score yet. Add data and run a recompute.</Empty>;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title="Score components">
        <p className="mb-4 text-sm text-muted">Each component runs from −1 (dovish) to +1 (hawkish). Confidence {num(p.confidence, 0)}%.</p>
        <ul className="space-y-2">
          {Object.entries(p.components).map(([k, v]: any) => (
            <li key={k} className="grid grid-cols-[minmax(0,9rem)_1fr_2.5rem] items-center gap-2 text-sm sm:grid-cols-[11rem_1fr_3rem] sm:gap-3">
              <span className="capitalize">{k.replaceAll("_", " ")}</span>
              <span className="relative h-2 rounded bg-panel-2">
                <span className={`absolute top-0 h-2 rounded ${v >= 0 ? "bg-hawk" : "bg-dove"}`}
                  style={{ left: v >= 0 ? "50%" : `${50 + v * 50}%`, width: `${Math.abs(v) * 50}%` }} />
                <span className="absolute left-1/2 top-[-3px] h-3.5 w-px bg-muted" />
              </span>
              <span className={`text-right ${toneClass(v)}`}>{signed(v, 2)}</span>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Policy shift">
        <p className={`text-lg ${toneClass(p.shift_classification)}`}>{p.shift_classification}</p>
        <p className="text-sm text-muted">{num(p.previous_score, 0)} → {num(p.score, 0)} ({signed(p.shift, 0)})</p>
        <ul className="note mt-3 list-disc space-y-1 pl-5 text-sm">{p.explanation.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
      </Panel>
    </div>
  );
}

function Projections({ code }: { code: string }) {
  const { data } = useApi<any>(`/api/central-banks/${code}/projections`);
  if (!data) return <Loading />;
  if (!data.vintages.length) return <Empty href="/data-input" cta="Upload a projection table">No projection vintages stored. Every new round is kept as a separate vintage.</Empty>;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title="Revision paths">
        <table className="grid-table">
          <thead><tr><th>Variable</th><th>For</th><th>Path</th><th>Momentum</th></tr></thead>
          <tbody>
            {data.revisions.map((r: any) => (
              <tr key={r.id}><td className="capitalize">{r.variable.replaceAll("_", " ")}</td><td>{r.target_period}</td>
                <td>{r.path.map((x: any) => x.value.toFixed(1)).join(" → ")}</td>
                <td title={r.interpretation}>{r.momentum}</td></tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="Vintages">
        <ul className="space-y-3 text-sm">
          {data.vintages.map((v: any) => (
            <li key={v.id}>
              <div className="flex items-center gap-2"><span className="font-medium">{v.label}</span><StatusBadge status={v.verification_status} /></div>
              <div className="text-muted">{v.projections.map((p: any) => `${p.variable.replaceAll("_", " ")} ${p.target_period}: ${p.value}`).join("; ")}</div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function Accuracy({ acc }: { acc: any }) {
  const vars = Object.keys(acc.central_bank);
  if (!vars.length) return <Empty>Not enough stored projections and outcomes yet. Scores are calculated from real forecast errors only.</Empty>;
  return (
    <Panel title={`Forecast accuracy (${acc.window}, ${acc.basis.replace("_", "-")})`}>
      <table className="grid-table">
        <thead><tr><th>Variable</th><th>Central bank</th><th>Market</th><th>Most accurate</th><th>Bias</th></tr></thead>
        <tbody>
          {vars.map((v) => (
            <tr key={v}>
              <td className="capitalize">{v.replaceAll("_", " ")}</td>
              <td>{num(acc.central_bank[v]?.score, 0)}/100 <span className="text-xs text-muted">MAE {num(acc.central_bank[v]?.mae, 2)}, n={acc.central_bank[v]?.n}</span></td>
              <td>{acc.market[v] ? <>{num(acc.market[v].score, 0)}/100 <span className="text-xs text-muted">MAE {num(acc.market[v].mae, 2)}</span></> : "—"}</td>
              <td>{acc.most_accurate[v]?.replace("_", " ")}</td>
              <td title={acc.bias[v]?.explanation}>{acc.bias[v]?.classification || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-sm">Overall: {num(acc.overall, 0)}/100</p>
    </Panel>
  );
}

function WhereAreWe({ w }: { w: any }) {
  if (!w.table.length) return <Empty href="/data-input" cta="Add projections">No projection to compare with.</Empty>;
  return (
    <Panel title="Where are we now?">
      <table className="grid-table">
        <thead><tr><th>Indicator</th><th>Projection</th><th>Current</th><th>Difference</th><th>Reading</th><th>Data</th></tr></thead>
        <tbody>
          {w.table.map((r: any) => (
            <tr key={r.indicator}><td>{r.indicator}<span className="block text-xs text-muted">{r.projection_vintage}</span></td>
              <td>{num(r.projection, 1, "%")}</td><td>{num(r.current, 1, "%")} <span className="text-xs text-muted">{r.period}</span></td>
              <td>{signed(r.difference, 2, " pp")}</td><td>{r.interpretation}</td><td><StatusBadge status={r.data_status} /></td></tr>
          ))}
        </tbody>
      </table>
      <p className={`mt-4 ${toneClass(w.policy_implication.overall)}`}>{w.policy_implication.overall}</p>
      {w.policy_implication.explanation.map((e: string, i: number) => <p key={i} className="note mt-1 text-sm">{e}</p>)}
    </Panel>
  );
}

function Expectations({ d }: { d: any }) {
  const m = d.market_rate_expectations;
  const [f, setF] = useState({ prob_cut: "", prob_hold: "", prob_hike: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const save = async () => {
    try {
      const r = await post("/api/rates/expectations", { central_bank_code: d.code, prob_cut: +f.prob_cut, prob_hold: +f.prob_hold, prob_hike: +f.prob_hike });
      setMsg(r.recompute?.message);
    } catch (e: any) { setMsg(e.message); }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title="Market pricing for the next meeting">
        {m ? (
          <div className="grid grid-cols-3 gap-4">
            <Stat label="Cut" value={num(m.prob_cut, 0, "%")} /><Stat label="Hold" value={num(m.prob_hold, 0, "%")} />
            <Stat label="Hike" value={num(m.prob_hike, 0, "%")} />
            <Stat label="Implied 12m change" value={signed(m.implied_12m_change_bps, 0, " bp")} sub={m.proxy ? "Proxy: 2Y yield minus policy rate" : m.source} />
            {m.as_of && <Stat label="As of" value={dateTime(m.as_of)} />}
          </div>
        ) : <p className="text-sm text-muted">No pricing stored.</p>}
      </Panel>
      <Panel title="Enter today's pricing">
        <div className="grid grid-cols-3 gap-3">
          {(["prob_cut", "prob_hold", "prob_hike"] as const).map((k) => (
            <label key={k} className="text-sm">{k.replace("prob_", "").replace(/^\w/, (c) => c.toUpperCase())} %
              <input inputMode="decimal" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}
                className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3"><Button onClick={save}>Save and re-analyse</Button>
          {msg && <span className="text-sm text-muted">{msg}</span>}</div>
      </Panel>
    </div>
  );
}

function History({ code }: { code: string }) {
  const { data } = useApi<any[]>(`/api/central-banks/${code}/policy-history?limit=60`);
  if (!data) return <Loading />;
  if (!data.length) return <Empty>No history yet.</Empty>;
  const pts = [...data].reverse();
  const w = 640, h = 160;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${(i / Math.max(1, pts.length - 1)) * w},${h - (p.score / 100) * h}`).join(" ");
  return (
    <Panel title="Policy score history">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-44 w-full" role="img" aria-label="Policy score over time">
        <line x1="0" x2={w} y1={h / 2} y2={h / 2} stroke="var(--color-line)" strokeDasharray="4 4" />
        <path d={path} fill="none" stroke="var(--color-verify)" strokeWidth="2" />
      </svg>
      <table className="grid-table mt-4">
        <thead><tr><th>When</th><th>Score</th><th>Classification</th><th>Shift</th></tr></thead>
        <tbody>{data.slice(0, 15).map((p) => (
          <tr key={p.id}><td>{dateTime(p.as_of)}</td><td>{num(p.score, 0)}</td><td className={toneClass(p.classification)}>{p.classification}</td>
            <td className={toneClass(p.shift)}>{signed(p.shift, 0)}</td></tr>))}</tbody>
      </table>
    </Panel>
  );
}
