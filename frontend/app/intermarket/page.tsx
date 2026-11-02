"use client";

import { useEffect, useState } from "react";

import { Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";

const STATUS_CLS: Record<string, string> = {
  Working: "bg-up/20 text-up", Weak: "bg-amber/20 text-amber", Flipped: "bg-bear-soft/20 text-bear-soft", "No data": "bg-panel-2 text-muted",
};
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
  useEffect(() => { try { const p = localStorage.getItem("im-pair"); if (p) setPair(p); } catch { /* ignore */ } }, []);
  const pick = (p: string) => { setPair(p); try { localStorage.setItem("im-pair", p); } catch { /* ignore */ } };
  const rels: any[] = data?.relationships || [];
  const pairs: string[] = Array.from(new Set(rels.map((r) => r.pair)));
  const hasData = rels.some((r) => r.status !== "No data");
  const mine = rels.filter((r) => r.pair === pair);
  const conf = data?.confirmation?.[pair];
  return (
    <>
      <PageTitle title="Intermarket" subtitle="How currencies move with yields, stocks, commodities and volatility: which links are working, which pairs are out of line with their drivers, and what the overall market pattern says." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !hasData ? (
        <Empty href="/data-health" cta="Open Data health">No price history yet. On Data health, press Run now on the Seasonality / Intermarket price histories, Risk sentiment and the government bond yields.</Empty>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Market regime · last 20 trading days" collapseId="im-regime">
              <p className={`text-2xl font-semibold ${REGIME_CLS[data.regime.label] || ""}`}>{data.regime.label}</p>
              <p className="mt-1 text-sm text-muted">{data.regime.explanation}</p>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
                {Object.entries<any>(data.regime.moves).map(([k, v]) => (
                  <div key={k} className="rounded border border-line bg-panel-2/40 px-2 py-1.5">
                    <dt className="text-xs text-muted">{k}</dt>
                    <dd className={`font-semibold tabular-nums ${v > 0 ? "text-up" : v < 0 ? "text-bear-soft" : ""}`}>{v == null ? "—" : `${v > 0 ? "+" : ""}${v}${k.includes("(") ? "" : "%"}`}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
            <Panel title="Leading signals" collapseId="im-leading">
              <ul className="space-y-2.5">
                {data.leading.map((l: any) => (
                  <li key={l.name} className="text-sm">
                    <div className="flex flex-wrap items-baseline justify-between gap-2"><span className="font-medium">{l.name}</span>
                      <span className="tabular-nums">{l.value} <span className="text-xs text-muted">{l.change}</span></span></div>
                    <div className="text-xs text-muted">{l.read}</div>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>

          <Panel title="Out of line with their drivers" collapseId="im-outofline"
            action={<span className="text-xs text-muted">Possible catch-up trades: the gap tends to close (price moves or the driver reverses)</span>}>
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
            ) : <p className="text-sm text-muted">Nothing is far out of line right now (all within 1.5 standard deviations of where its drivers put it).</p>}
          </Panel>

          <Panel title="Driver checks" collapseId="im-drivers">
            <div role="tablist" aria-label="Pair" className="mb-3 flex flex-wrap gap-1">
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
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_CLS[r.status]}`}>{r.status === "Working" ? "Link working" : r.status === "Flipped" ? "Link flipped" : r.status === "Weak" ? "Link weak" : "No data"}</span>
                  </div>
                  <p className="mb-2 text-xs text-muted">{r.why}</p>
                  {r.status !== "No data" && (<>
                    <div className="overflow-x-auto"><DualChart r={r} /></div>
                    <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                      {(["20", "60", "120"] as const).map((w) => (
                        <div key={w}><dt className="text-muted">Correlation {w}d</dt><dd className="font-semibold tabular-nums" style={{ color: r.corr[w] == null ? undefined : r.corr[w] * r.expected > 0 ? "var(--color-up)" : "var(--color-bear-soft)" }}>{r.corr[w] ?? "—"}</dd></div>
                      ))}
                      <div><dt className="text-muted">Out of line</dt><dd className="font-semibold tabular-nums">{r.z == null ? "—" : `${r.z > 0 ? "+" : ""}${r.z}σ`}</dd></div>
                    </dl>
                    <p className="mt-2 text-xs text-muted">
                      {r.fair != null && <>Price {r.price}, where the driver puts it: {r.fair}. </>}
                      {r.driver_name} moved {r.driver_move > 0 ? "+" : ""}{r.driver_move}{r.driver_unit} over 20 days
                      {r.impulse ? <> → <b className={r.impulse > 0 ? "text-up" : "text-bear-soft"}>{r.impulse > 0 ? `supports ${r.name} higher` : `points ${r.name} lower`}</b></> : " (no strong push)"}.
                    </p>
                  </>)}
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Correlation matrix" collapseId="im-matrix"
            action={<span className="flex items-center gap-2 text-xs text-muted">Daily moves over
              {[20, 60, 120].map((w) => (
                <button key={w} onClick={() => setWin(w)} aria-pressed={win === w}
                  className={`rounded border px-2 py-0.5 ${win === w ? "border-verify bg-panel-2 text-text" : "border-line"}`}>{w} days</button>
              ))}</span>}>
            <div className="overflow-x-auto">
              <table className="min-w-[52rem] border-separate border-spacing-0.5 text-xs tabular-nums">
                <thead><tr><th />{data.matrix.names.map((n: string) => <th key={n} className="h-24 w-12 whitespace-nowrap px-0.5 align-bottom font-medium text-muted"><span className="inline-block -rotate-45 origin-bottom-left translate-x-3">{n}</span></th>)}</tr></thead>
                <tbody>
                  {data.matrix.cells.map((row: (number | null)[], i: number) => (
                    <tr key={i}>
                      <th className="whitespace-nowrap pr-2 text-right font-medium text-muted">{data.matrix.names[i]}</th>
                      {row.map((c, j) => (
                        <td key={j} className="h-8 w-12 rounded text-center" style={i === j ? { background: "var(--color-panel-2)" } : corrStyle(c)}
                          title={`${data.matrix.names[i]} vs ${data.matrix.names[j]}: ${c ?? "no data"}`}>{i === j ? "" : c == null ? "" : c.toFixed(2)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted">Blue = move together, red = move opposite, pale = little link. Yields and the VIX use point changes; everything else % changes. USD/xxx pairs rise when the dollar rises.</p>
          </Panel>

          <p className="text-xs text-muted">
            Daily closes from FRED, Twelve Data (gold) and the official government bond yield feeds. A link is <b>working</b> when the 60-day correlation of daily moves points the usual way (0.2 or more),
            <b> flipped</b> when it runs the other way. &ldquo;Out of line&rdquo; uses a 120-day regression of the pair on its driver. The <b>Intermarket</b> column on Top setups adds up the drivers&rsquo; 20-day push
            plus a catch-up nudge for out-of-line pairs (−2 to +2). Relationships change over time; not financial advice.</p>
        </div>
      )}
    </>
  );
}
