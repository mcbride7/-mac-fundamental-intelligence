"use client";

import { useEffect, useState } from "react";

import { Button, Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { post, useApi } from "@/lib/api";

const STATUS_CLS: Record<string, string> = {
  Working: "bg-up/20 text-up", "Moving together": "bg-verify/20 text-verify", "Moving opposite": "bg-verify/20 text-verify", Weak: "bg-amber/20 text-amber", Flipped: "bg-bear-soft/20 text-bear-soft", "No data": "bg-panel-2 text-muted",
};
const DIR_CLS: Record<string, string> = { Bullish: "text-up", Bearish: "text-bear-soft", Neutral: "text-muted" };
const SEV_CLS: Record<string, string> = { Strong: "bg-bear-soft/20 text-bear-soft", Moderate: "bg-amber/20 text-amber", Mild: "bg-panel-2 text-muted" };
const sgn = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${v > 0 ? "+" : ""}${d ? v.toFixed(d) : v}`);

/** -100..+100 bar with the zero in the middle. */
function Meter({ v, label }: { v: number; label?: string }) {
  const w = Math.min(50, Math.abs(v) / 2);
  return (
    <div className="relative h-2.5 w-full rounded bg-panel-2" role="img" aria-label={label || `${v}`}>
      <div className="absolute top-0 h-full rounded" style={{ left: v >= 0 ? "50%" : `${50 - w}%`, width: `${w}%`, background: v >= 0 ? "var(--color-bull)" : "var(--color-bear)" }} />
      <div className="absolute left-1/2 top-[-2px] h-[calc(100%+4px)] w-px bg-text/50" />
    </div>
  );
}

function Opportunity({ b }: { b: any }) {
  const [open, setOpen] = useState(false);
  const List = ({ title, items, cls }: { title: string; items: string[]; cls?: string }) => (
    <div><h4 className={`mb-1 text-xs font-semibold uppercase tracking-wide ${cls || "text-muted"}`}>{title}</h4>
      {items.length ? <ul className="list-disc space-y-0.5 pl-4 text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="text-sm text-muted">None</p>}</div>
  );
  return (
    <li className="py-2">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 text-left sm:grid-cols-[10rem_6rem_1fr_3rem]">
        <span className="font-medium">{b.name}<span className="ml-1 text-xs text-muted">{b.category}</span></span>
        <span className={`text-right font-semibold sm:text-left ${DIR_CLS[b.direction]}`}>{b.direction}</span>
        <span className="col-span-2 sm:col-span-1"><Meter v={b.score} label={`${b.direction} ${b.strength} out of 100`} /></span>
        <span className="hidden text-right tabular-nums sm:block">{b.strength}</span>
      </button>
      {open && (
        <div className="mt-3 grid gap-4 rounded border border-line bg-panel-2/30 p-3 md:grid-cols-2">
          <div className="md:col-span-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
            {Object.entries<any>(b.components).map(([k, v]) => (
              <div key={k} className="rounded border border-line px-2 py-1"><div className="text-muted">{k}</div>
                <div className={`font-semibold tabular-nums ${v > 0 ? "text-up" : v < 0 ? "text-bear-soft" : ""}`}>{v == null ? "no data" : sgn(v)}</div></div>
            ))}
          </div>
          <List title="Supporting" items={b.supporting} cls="text-up" />
          <List title="Conflicting" items={b.conflicting} cls="text-bear-soft" />
          <List title="Fundamental explanation" items={b.fundamentals} />
          <List title="Catalysts ahead" items={b.catalysts} />
          <div className="md:col-span-2"><List title="Invalidation" items={b.invalidation} cls="text-amber" /></div>
        </div>
      )}
    </li>
  );
}

const REGIME_CLS: Record<string, string> = {
  "Risk-on": "text-up", Reflation: "text-up", "Disinflation (goldilocks)": "text-verify",
  "Risk-off": "text-bear-soft", Stagflation: "text-amber", "Deflation scare": "text-bear-soft", Mixed: "text-muted",
};

function corrStyle(c: number | null): React.CSSProperties {
  if (c === null || c === undefined) return {};
  const a = Math.min(0.85, Math.abs(c));
  return { background: `color-mix(in srgb, ${c > 0 ? "var(--color-bull)" : "var(--color-bear)"} ${Math.round(a * 100)}%, transparent)`,
    color: a > 0.45 ? "#fff" : undefined };
}

/** Pair (left axis) against its driver (right axis), last ~180 trading days. */
function DualChart({ r }: { r: any }) {
  const pts: any[] = r.chart || [];
  if (pts.length < 2) return null;
  const W = 640, H = 200, L = 52, R = 52, T = 10, B = 24, iw = W - L - R, ih = H - T - B;
  const ps = pts.map((p) => p.p), xs = pts.map((p) => p.x);
  const sc = (vals: number[]) => { let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad; return [lo, hi]; };
  const [plo, phi] = sc(ps); const [xlo, xhi] = sc(xs);
  const x = (i: number) => L + (i / (pts.length - 1)) * iw;
  const yp = (v: number) => T + ih - ((v - plo) / (phi - plo)) * ih;
  const yx = (v: number) => T + ih - ((v - xlo) / (xhi - xlo)) * ih;
  // invert the driver axis when the link is negative, so "in line" means the lines move together on the chart
  const yd = r.expected < 0 ? (v: number) => T + ((v - xlo) / (xhi - xlo)) * ih : yx;
  const path = (vals: number[], f: (v: number) => number) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${f(v).toFixed(1)}`).join(" ");
  const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(Math.abs(v) < 2 ? 3 : 2));
  const ticks = [0, Math.floor(pts.length / 2), pts.length - 1];
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[30rem]" role="img" aria-label={`${r.name} against ${r.driver_name}`}>
        {[plo, (plo + phi) / 2, phi].map((v, i) => <text key={i} x={L - 6} y={yp(v) + 4} fontSize="10" textAnchor="end" fill="var(--color-line-a)">{fmt(v)}</text>)}
        {[xlo, (xlo + xhi) / 2, xhi].map((v, i) => <text key={i} x={W - R + 6} y={yd(v) + 4} fontSize="10" fill="var(--color-line-b)">{fmt(v)}</text>)}
        {ticks.map((i) => <text key={i} x={x(i)} y={H - 6} fontSize="10" textAnchor={i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"} fill="currentColor" opacity="0.6">{pts[i].d.slice(2)}</text>)}
        <path d={path(xs, yd)} fill="none" stroke="var(--color-line-b)" strokeWidth="1.8" opacity="0.9" />
        <path d={path(ps, yp)} fill="none" stroke="var(--color-line-a)" strokeWidth="2.2" />
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "var(--color-line-a)" }} />{r.name} (left)</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2" style={{ borderColor: "var(--color-line-b)" }} />{r.driver_name} (right{r.expected < 0 ? ", upside down" : ""})</span>
      </figcaption>
    </figure>
  );
}

export default function Intermarket() {
  const [win, setWin] = useState(60);
  const { data, error, loading } = useApi<any>(`/api/intermarket?window=${win}`);
  const [pair, setPair] = useState("EURUSD");
  const [cat, setCat] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [ai, setAi] = useState<{ text: string; ai: boolean } | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  useEffect(() => { try { const p = localStorage.getItem("im-pair"); if (p) setPair(p); } catch { /* ignore */ } }, []);
  const pick = (p: string) => { setPair(p); try { localStorage.setItem("im-pair", p); } catch { /* ignore */ } };
  const askAi = async () => { setAiBusy(true); try { setAi(await post("/api/intermarket/ai-note", {})); } finally { setAiBusy(false); } };
  const rels: any[] = data?.relationships || [];
  const pairs: string[] = Array.from(new Set(rels.map((r) => r.pair)));
  const hasData = rels.some((r) => r.status !== "No data");
  const mine = rels.filter((r) => r.pair === pair);
  const conf = data?.confirmation?.[pair];
  const risk = data?.risk;
  const biasAll: any[] = (data?.bias || []).filter((b: any) => !cat || b.category === cat);
  const cats: string[] = Array.from(new Set((data?.bias || []).map((b: any) => b.category)));
  const biasShown = showAll ? biasAll : biasAll.slice(0, 12);
  const bonds = data?.bonds;
  return (
    <>
      <PageTitle title="Intermarket" subtitle="Which market is driving which, why, and what it means for direction: risk mood, bond yields and rates, currency and commodity links, divergences, positioning and a combined bias for each asset." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !hasData ? (
        <Empty href="/data-health" cta="Open Data health">No price history yet. On Data health, press Run now on Intermarket extras, the Seasonality price histories, Risk sentiment and the government bond yields.</Empty>
      ) : (
        <div className="space-y-6">
          {/* 1. Global market regime */}
          <Panel title="Global market regime · last 20 trading days" collapseId="im-regime">
            <div className="grid gap-6 lg:grid-cols-[1fr_1fr_1fr]">
              <div>
                <p className={`text-3xl font-semibold ${REGIME_CLS[risk?.label] || ""}`}>{risk?.label}</p>
                {risk?.score != null && <>
                  <div className="mt-2"><Meter v={risk.score} label={`Risk score ${risk.score}`} /></div>
                  <p className="mt-1 flex justify-between text-xs text-muted"><span>Risk-off</span><span className="tabular-nums">score {sgn(risk.score)}</span><span>Risk-on</span></p>
                  <p className="mt-1 text-xs text-muted">{risk.agreement}</p>
                </>}
                <p className="mt-3 text-sm">Pattern: <b className={REGIME_CLS[data.regime.label] || ""}>{data.regime.label}</b></p>
                <p className="mt-1 text-xs text-muted">{data.regime.explanation}</p>
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">What each market says</h3>
                <ul className="space-y-1.5 text-sm">
                  {(risk?.components || []).map((c: any) => (
                    <li key={c.name} className="flex items-center justify-between gap-2">
                      <span>{c.name} <span className="text-xs text-muted tabular-nums">{sgn(c.z, 1)}σ</span></span>
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${c.reads === "risk-on" ? "bg-up/20 text-up" : c.reads === "risk-off" ? "bg-bear-soft/20 text-bear-soft" : "bg-panel-2 text-muted"}`}>{c.reads}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Leading signals</h3>
                <ul className="space-y-2">
                  {data.leading.map((l: any) => (
                    <li key={l.name} className="text-sm">
                      <div className="flex flex-wrap items-baseline justify-between gap-2"><span className="font-medium">{l.name}</span>
                        <span className="tabular-nums">{l.value} <span className="text-xs text-muted">{l.change}</span></span></div>
                      <div className="text-xs text-muted">{l.read}</div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="mt-4 rounded border-l-4 border-verify bg-panel-2/60 px-3 py-2 text-sm">
              <p className="whitespace-pre-line">{ai?.text || data.note}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button onClick={askAi} disabled={aiBusy}>{aiBusy ? "Writing…" : ai?.ai ? "Rewrite AI desk note" : "Write AI desk note"}</Button>
                {ai && !ai.ai && <span className="text-xs text-muted">No AI key set, so this is the plain summary.</span>}
                {ai?.ai && <span className="text-xs text-muted">Written by AI from the numbers on this page only. Not financial advice.</span>}
              </div>
            </div>
          </Panel>

          {/* 2. AI-generated trading opportunities */}
          <Panel title="Trading opportunities · directional bias" collapseId="im-bias"
            action={<select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category" className="rounded border border-line bg-panel-2 px-2 py-1 text-sm">
              <option value="">All assets</option>{cats.map((c) => <option key={c} value={c}>{c}</option>)}</select>}>
            {biasAll.length ? (<>
              <div className="hidden grid-cols-[10rem_6rem_1fr_3rem] gap-x-3 border-b border-line pb-1 text-xs text-muted sm:grid">
                <span>Asset</span><span>Bias</span><span className="flex justify-between"><span>Bearish</span><span>Bullish</span></span><span className="text-right">Strength</span></div>
              <ul className="divide-y divide-line">{biasShown.map((b) => <Opportunity key={b.symbol} b={b} />)}</ul>
              {biasAll.length > 12 && <button className="mt-2 rounded border border-line px-2 py-1 text-xs hover:bg-panel-2" onClick={() => setShowAll(!showAll)}>{showAll ? "Show top 12" : `Show all ${biasAll.length}`}</button>}
              <p className="mt-2 text-xs text-muted">Click an asset for its supporting and conflicting signals, the fundamentals behind it, upcoming catalysts and what would invalidate it.
                Score = intermarket 25% + economic data 25% + rate expectations &amp; central bank divergence 20% + positioning (COT, retail) 15% + price trend 15%, from −100 to +100. 20+ = bullish, −20 or lower = bearish; strength is the size. Not financial advice.</p>
            </>) : <p className="text-sm text-muted">No scores yet: the Top setups table needs data first.</p>}
          </Panel>

          {/* 3. Intermarket divergences */}
          <Panel title="Intermarket divergences" collapseId="im-div">
            {data.divergences.length ? (
              <ul className="space-y-3">
                {data.divergences.map((d: any, i: number) => (
                  <li key={i} className="rounded border border-line p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{d.title}</h3>
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${SEV_CLS[d.severity]}`}>{d.severity}</span></div>
                    <p className="mt-1 text-sm text-muted">{d.detail}</p>
                    <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted">Possible explanations</p>
                    <ul className="mt-1 list-disc pl-4 text-sm">{d.explanations.map((e: string, j: number) => <li key={j}>{e}</li>)}</ul>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-muted">No major divergences: markets that usually move together are doing so over the last 20 days.</p>}
            <h3 className="mb-1 mt-5 text-sm font-semibold">Out of line with their drivers <span className="font-normal text-xs text-muted">· possible catch-up trades</span></h3>
            {data.out_of_line.length ? (
              <ul className="divide-y divide-line">
                {data.out_of_line.map((o: any, i: number) => (
                  <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                    <button onClick={() => pick(o.pair)} className="text-left hover:text-verify"><b>{o.name}</b> vs {o.driver_name}
                      <span className="block text-xs text-muted">{o.note}</span></button>
                    <span className="flex items-center gap-3 tabular-nums">
                      <span className="text-xs text-muted">price {o.price} · fits {o.fair}</span>
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${o.z < 0 ? "bg-up/20 text-up" : "bg-bear-soft/20 text-bear-soft"}`}>{o.z < 0 ? "Cheap" : "Rich"} {o.z > 0 ? "+" : ""}{o.z}σ</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-muted">Nothing is far out of line (all within 1.5 standard deviations of where its drivers put it).</p>}
          </Panel>

          {/* 4. Currency & commodity relationships */}
          <Panel title="Currency & commodity relationships" collapseId="im-drivers">
            <div role="tablist" aria-label="Asset" className="mb-3 flex flex-wrap gap-1">
              {pairs.map((p) => {
                const c = data.confirmation?.[p]?.score;
                return (
                  <button key={p} role="tab" aria-selected={pair === p} onClick={() => pick(p)}
                    className={`rounded border px-3 py-1.5 text-sm ${pair === p ? "border-verify bg-panel-2" : "border-line text-muted hover:text-text"}`}>
                    {rels.find((r) => r.pair === p)?.name}
                    {c != null && <span className={`ml-1.5 text-xs ${c > 0 ? "text-up" : c < 0 ? "text-bear-soft" : "text-muted"}`}>{c > 0 ? "+" : ""}{c}</span>}
                  </button>
                );
              })}
            </div>
            {conf && (
              <p className="mb-3 rounded border-l-4 border-verify bg-panel-2/60 px-3 py-2 text-sm">
                <b>Intermarket read for {mine[0]?.name}: {conf.score > 0 ? `supports a rise (+${conf.score})` : conf.score < 0 ? `points lower (${conf.score})` : "neutral (0)"}</b>
                {conf.reasons.length > 0 && <span className="text-muted"> · {conf.reasons.join("; ")}</span>}
              </p>
            )}
            <div className="grid gap-5 xl:grid-cols-2">
              {mine.map((r) => (
                <div key={r.driver} className="rounded border border-line p-3">
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-medium">{r.name} vs {r.driver_name}</h3>
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_CLS[r.status] || STATUS_CLS["No data"]}`}>{r.status === "Working" ? "Link working" : r.status === "Flipped" ? "Link flipped" : r.status === "Weak" ? "Link weak" : r.status}</span>
                  </div>
                  <p className="mb-2 text-xs text-muted">{r.why}</p>
                  {r.status !== "No data" && (<>
                    <div className="overflow-x-auto"><DualChart r={r} /></div>
                    <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                      {(["20", "60", "120"] as const).map((w) => (
                        <div key={w}><dt className="text-muted">Correlation {w}d</dt><dd className="font-semibold tabular-nums" style={{ color: r.corr[w] == null || !r.expected ? undefined : r.corr[w] * r.expected > 0 ? "var(--color-up)" : "var(--color-bear-soft)" }}>{r.corr[w] ?? "—"}</dd></div>
                      ))}
                      <div><dt className="text-muted">Out of line</dt><dd className="font-semibold tabular-nums">{r.z == null ? "—" : `${r.z > 0 ? "+" : ""}${r.z}σ`}</dd></div>
                    </dl>
                    {r.read ? <p className="mt-2 text-xs text-muted">{r.read}</p> : (
                      <p className="mt-2 text-xs text-muted">
                        {r.fair != null && <>Price {r.price}, where the driver puts it: {r.fair}. </>}
                        {r.driver_move != null && <>{r.driver_name} moved {r.driver_move > 0 ? "+" : ""}{r.driver_move}{r.driver_unit} over 20 days</>}
                        {r.impulse ? <> → <b className={r.impulse > 0 ? "text-up" : "text-bear-soft"}>{r.impulse > 0 ? `supports ${r.name} higher` : `points ${r.name} lower`}</b></> : " (no strong push)"}.
                      </p>
                    )}
                  </>)}
                </div>
              ))}
            </div>
          </Panel>

          {/* 5. Bond yields & interest rates */}
          {bonds && (
            <Panel title="Bond yield & interest rate analysis" collapseId="im-bonds">
              <div className="grid gap-6 lg:grid-cols-3">
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">US Treasury yields</h3>
                  <table className="grid-table text-sm"><thead><tr><th>Tenor</th><th>Yield</th><th>1 month</th></tr></thead>
                    <tbody>{bonds.us.map((y: any) => <tr key={y.tenor}><td>{y.tenor}</td><td className="tabular-nums">{y.yield == null ? "—" : `${y.yield}%`}</td>
                      <td className={`tabular-nums ${y.change_1m_bp > 0 ? "text-hawk" : y.change_1m_bp < 0 ? "text-dove" : ""}`}>{y.change_1m_bp == null ? "—" : `${sgn(y.change_1m_bp)} bp`}</td></tr>)}
                      {bonds.real_10y && <tr><td>10Y real</td><td className="tabular-nums">{bonds.real_10y.yield}%</td><td className="tabular-nums">{sgn(bonds.real_10y.change_1m_bp)} bp</td></tr>}</tbody></table>
                  <ul className="mt-3 space-y-1 text-sm">{bonds.curves.map((c: any) => (
                    <li key={c.name}><b>{c.name}</b> curve: <span className="tabular-nums">{sgn(c.bp)} bp</span> <span className="text-muted">({c.shape}; {sgn(c.change_1m_bp)} bp in a month, {c.change_1m_bp > 0 ? "steepening" : c.change_1m_bp < 0 ? "flattening" : "unchanged"})</span></li>))}</ul>
                </div>
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Yield gaps vs the US</h3>
                  <table className="grid-table text-sm"><thead><tr><th>Currency</th><th>Yield</th><th>Gap</th><th>1 month</th></tr></thead>
                    <tbody>{bonds.gaps.map((g: any) => <tr key={g.currency} title={g.read || undefined}><td>{g.currency} <span className="text-xs text-muted">{g.tenor}</span></td>
                      <td className="tabular-nums">{g.yield == null ? "—" : `${g.yield}%`}</td><td className="tabular-nums">{g.gap_vs_us_bp == null ? "—" : `${sgn(g.gap_vs_us_bp)} bp`}</td>
                      <td className={`tabular-nums ${g.change_1m_bp > 5 ? "text-up" : g.change_1m_bp < -5 ? "text-bear-soft" : ""}`}>{g.change_1m_bp == null ? "—" : `${sgn(g.change_1m_bp)} bp`}</td></tr>)}</tbody></table>
                  <p className="mt-2 text-xs text-muted">Green = the gap is moving in that currency&rsquo;s favour against the dollar.</p>
                </div>
                <div>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Policy rates &amp; market pricing (12 months)</h3>
                  <table className="grid-table text-sm"><thead><tr><th>Bank</th><th>Rate</th><th>Priced</th></tr></thead>
                    <tbody>{bonds.rates.map((r: any) => <tr key={r.currency}><td>{r.bank}</td><td className="tabular-nums">{r.rate == null ? "—" : `${r.rate}%`}</td>
                      <td className={`tabular-nums ${r.priced_12m_bp >= 15 ? "text-hawk" : r.priced_12m_bp <= -15 ? "text-dove" : ""}`}>{r.priced_12m_bp == null ? "—" : `${sgn(Math.round(r.priced_12m_bp))} bp`}{r.proxy && <span className="text-xs text-muted"> (proxy)</span>}</td></tr>)}</tbody></table>
                </div>
              </div>
            </Panel>
          )}

          {/* 6. Institutional positioning */}
          <Panel title="Institutional positioning · CFTC COT" collapseId="im-pos">
            {data.positioning?.length ? (
              <div className="overflow-x-auto"><table className="grid-table min-w-[36rem] text-sm">
                <thead><tr><th>Market</th><th>Speculators net</th><th>Week change</th><th>COT index (1 year)</th><th>Read</th></tr></thead>
                <tbody>{data.positioning.map((p: any) => (
                  <tr key={p.name}><td>{p.name} <span className="text-xs text-muted">{p.group}</span></td>
                    <td className="tabular-nums">{p.spec_net?.toLocaleString() ?? "—"}</td>
                    <td className={`tabular-nums ${p.change > 0 ? "text-up" : p.change < 0 ? "text-bear-soft" : ""}`}>{p.change == null ? "—" : `${p.change > 0 ? "+" : ""}${p.change.toLocaleString()}`}</td>
                    <td className="tabular-nums">{p.cot_index ?? "—"}</td>
                    <td className={p.read?.startsWith("Crowded") ? "font-semibold text-amber" : "text-muted"}>{p.read ?? "—"}</td></tr>))}</tbody>
              </table></div>
            ) : <p className="text-sm text-muted">No COT reports stored yet (run the COT job on Data health).</p>}
            <p className="mt-2 text-xs text-muted">COT index: where speculators&rsquo; net position sits in its 1-year range (0 = most short, 100 = most long). Crowded positions (above 90 / below 10) can reverse sharply when the news turns. Reports are as of Tuesday, published Friday.</p>
          </Panel>

          {/* 7. Cross-asset correlation matrix */}
          <Panel title="Cross-asset correlation matrix" collapseId="im-matrix"
            action={<span className="flex items-center gap-2 text-xs text-muted">Daily moves over
              {[20, 60, 120].map((w) => (
                <button key={w} onClick={() => setWin(w)} aria-pressed={win === w}
                  className={`rounded border px-2 py-0.5 ${win === w ? "border-verify bg-panel-2 text-text" : "border-line"}`}>{w} days</button>
              ))}</span>}>
            <div className="overflow-x-auto">
              <table className="min-w-[60rem] border-separate border-spacing-0.5 text-xs tabular-nums">
                <thead><tr><th />{data.matrix.names.map((n: string) => <th key={n} className="h-28 w-11 whitespace-nowrap px-0.5 align-bottom font-medium text-muted"><span className="inline-block -rotate-45 origin-bottom-left translate-x-3">{n}</span></th>)}</tr></thead>
                <tbody>
                  {data.matrix.cells.map((row: (number | null)[], i: number) => (
                    <tr key={i}>
                      <th className="whitespace-nowrap pr-2 text-right font-medium text-muted">{data.matrix.names[i]}</th>
                      {row.map((c, j) => (
                        <td key={j} className="h-8 w-11 rounded text-center" style={i === j ? { background: "var(--color-panel-2)" } : corrStyle(c)}
                          title={`${data.matrix.names[i]} vs ${data.matrix.names[j]}: ${c ?? "no data"}`}>{i === j ? "" : c == null ? "" : c.toFixed(2)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted">Blue = move together, red = move opposite, pale = little link. Yields and the VIX use point changes; everything else % changes. USD/xxx pairs rise when the dollar rises. Correlation alone doesn&rsquo;t say who leads, so the bias above also weighs fundamentals, rate pricing, positioning and price action.</p>
          </Panel>

          <p className="text-xs text-muted">
            Daily closes from FRED, Twelve Data and the official government bond yield feeds; COT from the CFTC. A link is <b>working</b> when the 60-day correlation of daily moves points the usual way (0.2 or more),
            <b> flipped</b> when it runs the other way. &ldquo;Out of line&rdquo; uses a 120-day regression of the asset on its driver. Moves are measured in &ldquo;σ&rdquo;: the 20-day move divided by a normal 20-day move over the last year.
            Relationships change over time; not financial advice.</p>
        </div>
      )}
    </>
  );
}
