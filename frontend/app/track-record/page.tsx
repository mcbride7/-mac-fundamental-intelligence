"use client";

import { Fragment, useEffect, useState } from "react";

import CallSetup from "@/components/CallSetup";
import StrategyBacktest from "@/components/StrategyBacktest";
import { Button, Empty, ErrorBox, GradeBadge, Loading, PageTitle, Panel } from "@/components/ui";
import { patch, useApi } from "@/lib/api";
import { dateTime, num, pair, signed } from "@/lib/format";

type Row = { grade: string; signals: number; [k: string]: number | string | null };

const pct = (v: unknown) => (typeof v === "number" ? `${v.toFixed(0)}%` : "—");
const OUTCOME: Record<string, [string, string]> = {
  target: ["Target hit", "bg-up/20 text-up"], stop: ["Stopped out", "bg-bear-soft/20 text-bear-soft"], expired: ["Expired", "bg-panel-2 text-muted"],
};
const dec = (v: number | null | undefined) => (v == null ? 4 : v > 20 ? 3 : 5);

function TypeBadge({ t, why }: { t: string | null; why?: string }) {
  if (!t) return <span className="text-muted">—</span>;
  return <span title={why} className={`cursor-help whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium ${t === "day" ? "bg-amber/20 text-amber" : "bg-verify/20 text-verify"}`}>{t === "day" ? "Day trade" : "Swing"}</span>;
}

function PlanEditor({ r, onDone }: { r: any; onDone: () => void }) {
  const [tt, setTt] = useState(r.trade_type || "swing");
  const [sl, setSl] = useState(r.stop_loss ?? "");
  const [tp, setTp] = useState(r.take_profit ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async (levels: boolean) => {
    setBusy(true); setErr(null);
    try {
      await patch(`/api/track-record/${r.id}`, levels ? { trade_type: tt, stop_loss: sl, take_profit: tp } : { trade_type: tt });
      onDone();
    } catch (e: any) { setErr(e?.message || "Could not save"); } finally { setBusy(false); }
  };
  const inp = "mt-1 w-28 rounded border border-line bg-ink px-2 py-1 tabular-nums";
  return (
    <div className="flex flex-wrap items-end gap-3 rounded border border-line bg-panel-2/40 p-3 text-sm">
      <label className="flex flex-col text-xs text-muted">Trade type
        <select value={tt} onChange={(e) => setTt(e.target.value)} className="mt-1 rounded border border-line bg-ink px-2 py-1 text-sm text-text">
          <option value="swing">Swing</option><option value="day">Day trade</option></select></label>
      <label className="flex flex-col text-xs text-muted">Stop loss<input inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} className={inp} /></label>
      <label className="flex flex-col text-xs text-muted">Take profit<input inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} className={inp} /></label>
      <Button onClick={() => save(true)} disabled={busy}>Save</Button>
      {tt !== r.trade_type && <button onClick={() => save(false)} disabled={busy} className="rounded border border-line px-2 py-1 text-xs hover:bg-panel-2">Change type &amp; recalculate levels</button>}
      <button onClick={onDone} className="text-xs text-muted underline">Cancel</button>
      {err && <p className="w-full text-xs text-bear-soft">{err}</p>}
      <p className="w-full text-xs text-muted">Entry {num(r.entry_price, dec(r.entry_price))}. For a {r.direction === "LONG" ? "buy the stop goes below and the target above" : "sell the stop goes above and the target below"} the entry.</p>
    </div>
  );
}

const moveCls = (v: number | null) => (v === null || v === undefined ? "text-muted" : v > 0 ? "text-dove" : v < 0 ? "text-hawk" : "");

const VIEWS = [["live", "Live calls"], ["backtest", "S&D strategy backtest"]] as const;
type View = (typeof VIEWS)[number][0];

export default function TrackRecord() {
  const { data, error, loading, reload } = useApi<any>("/api/track-record");
  const [editing, setEditing] = useState<number | null>(null);
  const [showing, setShowing] = useState<number | null>(null);
  const [type, setType] = useState("");
  const [view, setView] = useState<View>("live");
  useEffect(() => { if (window.location.hash === "#backtest") setView("backtest"); }, []);
  const pick = (v: View) => {
    setView(v);
    try { window.history.replaceState(null, "", v === "backtest" ? "#backtest" : window.location.pathname); } catch { /* ignore */ }
  };
  const calls: any[] = (data?.recent || []).filter((r: any) => !type || r.trade_type === type);
  return (
    <>
      <PageTitle title="Track record"
        subtitle={view === "live"
          ? "Every graded call the app makes: swing or day trade, its stop loss and take profit, which was hit first, and what the price did 1, 5 and 20 days later. Moves are in the call's direction, before costs."
          : "The supply & demand strategy tested on historical data: every trade, its result in R, and how it did on the years that were not used to build the rules. Costs included."} />
      <div role="tablist" aria-label="Track record view" className="mb-5 flex gap-1 border-b border-line">
        {VIEWS.map(([v, label]) => (
          <button key={v} role="tab" aria-selected={view === v} onClick={() => pick(v)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${view === v ? "border-verify text-text" : "border-transparent text-muted hover:text-text"}`}>
            {label}
          </button>
        ))}
      </div>
      {view === "backtest" ? <StrategyBacktest /> : <>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (
        <>
          {!data.enough_data && (
            <p className="mb-4 rounded border border-amber/50 bg-amber/10 px-3 py-2 text-sm">
              Only {data.evaluated_5d} call{data.evaluated_5d === 1 ? "" : "s"} have a 5-day result so far. Treat the grades as
              research, not signals, until there are at least 30.
            </p>
          )}
          <Panel title="By grade">
            <div className="overflow-x-auto">
              <table className="grid-table">
                <thead>
                  <tr><th title="The call's fundamental grade">Call grade</th><th>Calls</th>
                    <th>Right after 1 day</th><th>Avg move 1d</th>
                    <th>Right after 5 days</th><th>Avg move 5d</th>
                    <th>Right after 20 days</th><th>Avg move 20d</th>
                    <th>Targets hit</th><th>Stopped out</th><th>Avg result</th></tr>
                </thead>
                <tbody>
                  {data.by_grade.map((g: Row) => (
                    <tr key={g.grade}>
                      <td><GradeBadge grade={g.grade} /></td><td>{g.signals}</td>
                      {[1, 5, 20].map((d) => (
                        <FragmentCells key={d} hit={g[`hit_rate_${d}d`]} n={g[`n_${d}d`]} avg={g[`avg_move_${d}d`] as number | null} />
                      ))}
                      <td className="text-up">{g.targets_hit ?? 0}</td><td className="text-bear-soft">{g.stopped_out ?? 0}</td>
                      <td className={moveCls(g.avg_r as number | null)}>{g.avg_r == null ? "—" : `${signed(g.avg_r as number, 2)}R`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted">{data.note}</p>
          </Panel>
          <div className="mt-6">
            <Panel title="Calls" action={
              <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Trade type" className="rounded border border-line bg-panel-2 px-2 py-1 text-sm">
                <option value="">Swing and day trades</option><option value="swing">Swing trades</option><option value="day">Day trades</option></select>}>
              {!calls.length ? (
                <Empty>No graded calls yet. They are recorded automatically each time the analysis gives a pair an A+, A, B or C.</Empty>
              ) : (
                <div className="overflow-x-auto">
                  <table className="grid-table">
                    <thead><tr><th>Given</th><th>Pair</th><th>Call</th><th title="The fundamental grade of the call (macro model), not the S&D setup">Call grade</th><th title="Your S&D strategy's technical setup for this call">S&amp;D setup</th><th>Entry</th><th>Stop loss</th><th>Take profit</th><th>Result</th><th>1 day</th><th>5 days</th><th>20 days</th><th></th><th></th><th></th></tr></thead>
                    <tbody>
                      {calls.map((r: any) => (<Fragment key={r.id}>
                        <tr onClick={() => setShowing(showing === r.id ? null : r.id)} className={`cursor-pointer ${showing === r.id ? "bg-panel-2/60" : ""}`} title="Click to see the setup">
                          <td className="whitespace-nowrap">{dateTime(r.opened_at)}</td><td>{pair(r.asset)}</td>
                          <td>{r.direction === "LONG" ? "Buy" : "Sell"}</td><td><GradeBadge grade={r.grade} /></td>
                          <td>{r.method === "sd"
                            ? <span title={r.type_reason} className="cursor-help whitespace-nowrap rounded bg-verify/20 px-2 py-0.5 text-xs font-medium text-verify">{r.sd?.grade ? `Setup ${r.sd.grade}` : "4-hour swing"}</span>
                            : <TypeBadge t={r.trade_type} why={r.type_reason} />}</td>
                          <td className="whitespace-nowrap">{r.method === "sd" && r.sd?.entry != null
                            ? <span title={`Call given at ${num(r.entry_price, dec(r.entry_price))}`}>{num(r.sd.entry, dec(r.sd.entry))} <span className="text-xs text-muted">{dateTime(r.sd.entry_at)}</span></span>
                            : r.method === "sd" ? <span className="text-xs text-muted" title={r.sd?.message}>{r.sd?.state === "none" ? "No setup" : r.sd?.state === "later" ? "Taken under later call" : "Waiting for setup"}</span>
                            : num(r.entry_price, dec(r.entry_price))}</td>
                          <td className="whitespace-nowrap">{r.stop_loss == null ? "—" : <>{num(r.stop_loss, dec(r.stop_loss))} <span className="text-xs text-muted">({r.sl_pct}%)</span></>}</td>
                          <td className="whitespace-nowrap">{r.take_profit == null ? "—" : <>{num(r.take_profit, dec(r.take_profit))} <span className="text-xs text-muted">({r.tp_pct}%{r.risk_reward ? ` · 1:${r.risk_reward}` : ""})</span></>}</td>
                          <td className="whitespace-nowrap">{r.outcome ? <span title={r.outcome_at ? dateTime(r.outcome_at) : undefined} className={`rounded px-2 py-0.5 text-xs font-semibold ${OUTCOME[r.outcome][1]}`}>{OUTCOME[r.outcome][0]} {r.result_r != null && `${signed(r.result_r, 1)}R`}</span>
                            : r.stop_loss != null ? <span className="text-xs text-muted">Running</span> : r.method === "sd" && r.sd?.state === "none" ? <span className="text-xs text-muted">Not traded</span> : <span className="text-muted">—</span>}</td>
                          <td className={moveCls(r.ret_1d)}>{signed(r.ret_1d, 2, "%")}</td>
                          <td className={moveCls(r.ret_5d)}>{signed(r.ret_5d, 2, "%")}</td>
                          <td className={moveCls(r.ret_20d)}>{signed(r.ret_20d, 2, "%")}</td>
                          <td className="text-xs text-muted">{r.open ? "current" : "replaced"}{r.manual ? " · levels edited" : ""}{r.note ? ` · ${r.note}` : ""}</td>
                          <td><button onClick={(e) => { e.stopPropagation(); setShowing(showing === r.id ? null : r.id); }} aria-expanded={showing === r.id}
                            className={`whitespace-nowrap rounded border px-2 py-0.5 text-xs ${showing === r.id ? "border-verify text-verify" : "border-line hover:bg-panel-2"}`}>{showing === r.id ? "Hide setup" : "Setup"}</button></td>
                          <td>{r.method !== "sd" && <button onClick={(e) => { e.stopPropagation(); setEditing(editing === r.id ? null : r.id); }} className="rounded border border-line px-2 py-0.5 text-xs hover:bg-panel-2">Edit</button>}</td>
                        </tr>
                        {showing === r.id && <tr><td colSpan={15} style={{ padding: 0 }}><div className="sticky left-0 max-w-[1000px] p-3" style={{ width: "min(100%, calc(100vw - 4.5rem))" }}><CallSetup id={r.id} /></div></td></tr>}
                        {editing === r.id && <tr><td colSpan={15}><div className="sticky left-0 w-fit max-w-[85vw]"><PlanEditor r={r} onDone={() => { setEditing(null); reload(); }} /></div></td></tr>}
                      </Fragment>))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="mt-3 text-xs text-muted">{data.plan_note} Click a call to see its 4-hour candle chart with the zone, entry, stop and target. {data.fallback_note}</p>
            </Panel>
          </div>
        </>
      )}
      </>}
    </>
  );
}

function FragmentCells({ hit, n, avg }: { hit: unknown; n: unknown; avg: number | null }) {
  return (
    <>
      <td>{pct(hit)} <span className="text-xs text-muted">({typeof n === "number" ? n : 0})</span></td>
      <td className={moveCls(avg)}>{signed(avg, 2, "%")}</td>
    </>
  );
}
