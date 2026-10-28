"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import QuickEdit from "@/components/QuickEdit";
import RetailBoard from "@/components/RetailBoard";
import { Button, Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { post, put, useApi } from "@/lib/api";

const MEASURES = [
  { key: "spec", label: "Speculators net" },
  { key: "comm", label: "Commercials net" },
  { key: "all", label: "All groups" },
  { key: "ls", label: "Spec long vs short" },
  { key: "oi", label: "Open interest" },
] as const;
type Measure = (typeof MEASURES)[number]["key"];
const WEEKS = [13, 26, 52, 0] as const;
const C = { spec: "var(--color-line-a)", comm: "var(--color-line-b)", small: "var(--color-muted)", long: "var(--color-good)", short: "var(--color-bad)", oi: "#8e7cc3", price: "var(--color-text)" };

function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`;
  return String(Math.round(n));
}
const signed = (n: number | null | undefined) => (n === null || n === undefined ? "—" : `${n > 0 ? "+" : ""}${compact(n)}`);
function fmtPx(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—";
  const a = Math.abs(p);
  const dp = a >= 1000 ? 0 : a >= 10 ? 2 : a >= 0.1 ? 4 : 6;
  return p.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
const shortDate = (d: string) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit", timeZone: "UTC" });

function idxClass(v: number | null | undefined) {
  if (v === null || v === undefined) return "text-muted";
  if (v >= 90) return "bg-good/80 text-white";
  if (v <= 10) return "bg-bad/80 text-white";
  if (v >= 75) return "bg-good/30";
  if (v <= 25) return "bg-bad/30";
  return "";
}

type S = { name: string; color: string; kind: "bar" | "line"; values: (number | null)[] };

/** Weekly chart: bars or lines for positions (left axis) and the price line (right axis). */
function Chart({ dates, series, price, priceNote }: { dates: string[]; series: S[]; price: (number | null)[]; priceNote: string }) {
  const W = 820, H = 300, L = 56, R = 58, T = 12, B = 28;
  const iw = W - L - R, ih = H - T - B;
  const vals = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  if (!dates.length || !vals.length) return <p className="text-sm text-muted">No weeks to chart.</p>;
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (lo === hi) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.06; lo -= series.some((s) => s.kind === "bar") && lo === 0 ? 0 : pad; hi += pad;
  const y = (v: number) => T + ih - ((v - lo) / (hi - lo)) * ih;
  const n = dates.length, step = iw / n, x = (i: number) => L + step * i + step / 2;
  const bars = series.filter((s) => s.kind === "bar");
  const bw = Math.max(1.5, (step * 0.8) / Math.max(1, bars.length));
  const pv = price.filter((p): p is number => p !== null);
  const plo = pv.length ? Math.min(...pv) : 0, phi = pv.length ? Math.max(...pv) : 1;
  const py = (v: number) => T + ih - ((v - plo) / (phi - plo || 1)) * ih * 0.9 - ih * 0.05;
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  const every = Math.max(1, Math.ceil(n / 8));
  const linePath = (vs: (number | null)[], f: (v: number) => number) =>
    vs.map((v, i) => (v === null ? "" : `${i && vs[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${f(v).toFixed(1)}`)).join(" ");
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[38rem]" role="img" aria-label="Weekly positioning chart">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="currentColor" opacity="0.08" />
            <text x={L - 6} y={y(t) + 4} fontSize="11" textAnchor="end" fill="currentColor" opacity="0.6">{compact(t)}</text>
          </g>
        ))}
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.35" />
        {bars.map((s, bi) => s.values.map((v, i) => v === null ? null : (
          <rect key={`${s.name}${i}`} x={x(i) - (bw * bars.length) / 2 + bi * bw} width={bw - 0.5}
            y={Math.min(y(v), y(0))} height={Math.max(0.5, Math.abs(y(v) - y(0)))} fill={s.color} opacity="0.85">
            <title>{`${shortDate(dates[i])}: ${s.name} ${compact(v)}`}</title></rect>)))}
        {series.filter((s) => s.kind === "line").map((s) => (
          <path key={s.name} d={linePath(s.values, y)} fill="none" stroke={s.color} strokeWidth="2.2" />
        ))}
        {pv.length > 1 && (
          <>
            <path d={linePath(price, py)} fill="none" stroke={C.price} strokeWidth="1.6" strokeDasharray="5 3" opacity="0.85" />
            <text x={W - R + 6} y={py(phi) + 4} fontSize="11" fill="currentColor" opacity="0.7">{fmtPx(phi)}</text>
            <text x={W - R + 6} y={py(plo) + 4} fontSize="11" fill="currentColor" opacity="0.7">{fmtPx(plo)}</text>
          </>
        )}
        {dates.map((d, i) => (i % every === 0 && n - 1 - i >= every * 0.6) || i === n - 1 ? (
          <text key={d} x={x(i)} y={H - 8} fontSize="10.5" textAnchor="middle" fill="currentColor" opacity="0.6">{shortDate(d)}</text>
        ) : null)}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {series.map((s) => <span key={s.name} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />{s.name}</span>)}
        {pv.length > 1 && <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: C.price }} />Price ({priceNote}, right scale)</span>}
        <span>Contracts, as of each Tuesday</span>
      </figcaption>
    </figure>
  );
}

function Seg<T extends string | number>({ value, options, onChange, label }: {
  value: T; options: { key: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap overflow-hidden rounded border border-line text-sm">
      {options.map((o) => (
        <button key={String(o.key)} role="radio" aria-checked={value === o.key} onClick={() => onChange(o.key)}
          className={`px-3 py-1.5 ${value === o.key ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>{o.label}</button>
      ))}
    </div>
  );
}

function Stat({ label, value, sub, cls = "" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; cls?: string }) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-panel-2/50 px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-0.5 rounded px-1 text-lg font-semibold tabular-nums ${cls}`}>{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export default function CotPage() {
  const board = useApi<any>("/api/cot");
  const [code, setCode] = useState<string>("");
  const [measure, setMeasure] = useState<Measure>("spec");
  const [weeks, setWeeks] = useState<number>(52);
  const [kind, setKind] = useState<"bar" | "line">("bar");
  const markets: any[] = board.data?.markets || [];
  useEffect(() => {
    if (!code && markets.length) {
      let saved = "";
      try { saved = localStorage.getItem("cot-market") || ""; } catch { /* private mode */ }
      setCode(markets.some((m) => m.code === saved) ? saved : markets.find((m) => m.code === "088691")?.code || markets[0].code);
    }
  }, [markets, code]);
  const pick = (c: string) => { setCode(c); try { localStorage.setItem("cot-market", c); } catch { /* ignore */ } };
  const detail = useApi<any>(code ? `/api/cot/${code}` : null);
  const reloadAll = () => { detail.reload(); board.reload(); };

  const m = detail.data;
  const all: any[] = m?.series || [];
  const shown = weeks ? all.slice(-weeks) : all;
  const dates = shown.map((r) => r.d);
  const series: S[] = useMemo(() => {
    const v = (f: (r: any) => number | null) => shown.map(f);
    if (measure === "spec") return [{ name: "Speculators net", color: C.spec, kind, values: v((r) => r.spec_net) }];
    if (measure === "comm") return [{ name: "Commercials net", color: C.comm, kind, values: v((r) => r.comm_net) }];
    if (measure === "all") return [
      { name: "Speculators net", color: C.spec, kind: "line", values: v((r) => r.spec_net) },
      { name: "Commercials net", color: C.comm, kind: "line", values: v((r) => r.comm_net) },
      { name: "Small traders net", color: C.small, kind: "line", values: v((r) => r.small_net) }];
    if (measure === "ls") return [
      { name: "Spec long", color: C.long, kind, values: v((r) => r.ncl) },
      { name: "Spec short", color: C.short, kind, values: v((r) => -r.ncs) }];
    return [{ name: "Open interest", color: C.oi, kind, values: v((r) => r.oi) }];
  }, [shown, measure, kind]);

  return (
    <>
      <PageTitle title="COT positioning"
        subtitle="CFTC Commitments of Traders (Legacy, futures only) for 19 macro markets. Positions are as of Tuesday and published Friday 21:30 SA time; new weeks are added automatically." />
      <ErrorBox error={board.error} />
      {board.loading && !board.data ? <Loading /> : !markets.length ? <Empty>No COT data yet.</Empty> : (
        <div className="space-y-6">
          <Panel title="COT chart" collapseId="cot-chart">
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-muted">Market
                <select value={code} onChange={(e) => pick(e.target.value)}
                  className="rounded border border-line bg-panel-2 px-2 py-1.5 text-text">
                  {board.data.groups.map((g: string) => (
                    <optgroup key={g} label={g}>
                      {markets.filter((x) => x.group === g).map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
                    </optgroup>
                  ))}
                </select>
              </label>
              <Seg label="Measure" value={measure} onChange={setMeasure} options={MEASURES.map((x) => ({ key: x.key, label: x.label }))} />
              <Seg label="Weeks" value={weeks} onChange={setWeeks} options={WEEKS.map((w) => ({ key: w, label: w ? String(w) : "All" }))} />
              <Seg label="Chart" value={kind} onChange={setKind} options={[{ key: "bar", label: "Bar" }, { key: "line", label: "Line" }]} />
            </div>
            <ErrorBox error={detail.error} />
            {!m ? <Loading /> : (
              <>
                <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
                  <Stat label="Speculators net" value={signed(m.spec_net)} sub={m.spec_long_pct != null ? `${m.spec_long_pct}% of spec positions long` : undefined} />
                  <Stat label="Week change" value={signed(m.spec_change)} cls={m.spec_change > 0 ? "text-up" : m.spec_change < 0 ? "text-bear-soft" : ""} />
                  <Stat label="COT index (52w)" value={m.cot_index_52 ?? "—"} cls={idxClass(m.cot_index_52)}
                    sub={m.cot_index_156 != null ? `3-year: ${m.cot_index_156}` : "0 = most short, 100 = most long"} />
                  <Stat label="Commercials net" value={signed(m.comm_net)} sub={m.comm_index_52 != null ? `index ${m.comm_index_52}` : undefined} />
                  <Stat label="Open interest" value={compact(m.oi)} sub={m.oi_change != null ? `${signed(m.oi_change)} on the week` : undefined} />
                  <Stat label="Price" value={fmtPx(m.price)} sub={m.price_note} />
                </div>
                <h2 className="mb-2 mt-5 font-medium">{m.name}: weekly positioning <span className="text-sm text-muted">· latest {m.report_date ? shortDate(m.report_date) : "—"}</span></h2>
                <div className="overflow-x-auto"><Chart dates={dates} series={series} price={shown.map((r) => r.price)} priceNote={m.price_note} /></div>
                {m.signals?.length > 0 && (
                  <ul className="mt-4 space-y-2">
                    {m.signals.map((s: any) => (
                      <li key={s.kind} className={`rounded border-l-4 bg-panel-2/60 px-3 py-2 text-sm ${s.tone === "warn" ? "border-amber" : s.tone === "ok" ? "border-good" : "border-verify"}`}>{s.text}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </Panel>

          <Panel title="Market board" collapseId="cot-board" action={<span className="text-xs text-muted">Latest week · COT index over 52 weeks · tap a row to chart it</span>}>
            <table className="grid-table">
              <thead><tr><th>Market</th><th className="text-right">Spec net</th><th className="text-right">Δ week</th>
                <th className="text-right">Comm net</th><th className="text-center">COT index</th><th className="text-right">Long %</th><th>Flags</th><th>Week</th></tr></thead>
              <tbody>
                {board.data.groups.map((g: string) => [
                  <tr key={g}><td colSpan={8} className="pt-3 text-xs uppercase tracking-wide text-muted">{g}</td></tr>,
                  ...markets.filter((x) => x.group === g).map((x) => (
                    <tr key={x.code} onClick={() => { pick(x.code); window.scrollTo({ top: 0, behavior: "smooth" }); }}
                      className={`cursor-pointer hover:bg-panel-2/60 ${x.code === code ? "bg-panel-2/60" : ""}`}>
                      <td className="whitespace-nowrap">{x.name}</td>
                      <td className="text-right tabular-nums">{signed(x.spec_net)}</td>
                      <td className={`text-right tabular-nums ${x.spec_change > 0 ? "text-up" : x.spec_change < 0 ? "text-bear-soft" : ""}`}>{signed(x.spec_change)}</td>
                      <td className="text-right tabular-nums">{signed(x.comm_net)}</td>
                      <td className="text-center"><span className={`inline-block min-w-[2.6rem] rounded px-1.5 py-0.5 tabular-nums ${idxClass(x.cot_index_52)}`}>{x.cot_index_52 ?? "—"}</span></td>
                      <td className="text-right tabular-nums">{x.spec_long_pct ?? "—"}</td>
                      <td className="text-xs text-amber">{(x.signals || []).filter((s: any) => s.tone === "warn").map((s: any) =>
                        s.kind === "crowded_long" ? "Crowded long" : s.kind === "crowded_short" ? "Crowded short" : s.kind === "divergence_top" ? "Top warning" : "Bottom warning").join(", ")}</td>
                      <td className="whitespace-nowrap text-xs text-muted">{x.report_date ? shortDate(x.report_date) : "—"}</td>
                    </tr>
                  )),
                ])}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-muted">COT index: where the latest speculator net sits in its 52-week range (0 = most short, 100 = most long). Green 90+ and red 10 or below mark crowded trades.
              Currency futures are quoted against the US dollar, so a crowded euro short is a crowded long-dollar trade.</p>
          </Panel>

          {m && <Ledger m={m} onSaved={reloadAll} />}
          {m && <Tools code={code} name={m.name} onDone={reloadAll} />}
          <RetailBoard />
          <p className="text-xs text-muted">Source: U.S. Commodity Futures Trading Commission, Commitments of Traders (Legacy, futures only), via the CFTC Public Reporting Environment.
            &ldquo;Speculators&rdquo; are non-commercial traders; &ldquo;Commercials&rdquo; are hedgers. COT data shows how crowded a trade is; it does not time entries. Not financial advice.</p>
        </div>
      )}
    </>
  );
}

function Ledger({ m, onSaved }: { m: any; onSaved: () => void }) {
  const [all, setAll] = useState(false);
  const rows = [...(m.series || [])].reverse();
  const shown = all ? rows : rows.slice(0, 12);
  return (
    <Panel title={`Weekly ledger: ${m.name}`} collapseId="cot-ledger" action={<span className="text-xs text-muted">Newest first · tap a price to change it</span>}>
      <table className="grid-table">
        <thead><tr><th>Report date</th><th className="text-right">Price</th><th className="text-right">Open interest</th>
          <th className="text-right">Spec long</th><th className="text-right">Spec short</th><th className="text-right">Spec net</th><th className="text-right">Δ net</th>
          <th className="text-right">Comm long</th><th className="text-right">Comm short</th><th className="text-right">Comm net</th></tr></thead>
        <tbody>
          {shown.map((r: any) => (
            <tr key={r.d}>
              <td className="whitespace-nowrap">{shortDate(r.d)}{r.input_method === "manual" && <span className="ml-1 text-xs text-amber">typed</span>}</td>
              <td className="text-right">
                <QuickEdit label="Price" display={<span title={r.price_source ? `Source: ${r.price_source}` : undefined}>{fmtPx(r.price)}{r.price_source === "manual" && <span className="ml-1 text-xs text-amber">✎</span>}</span>}
                  initial={r.price == null ? "" : String(r.price)} allowEmpty
                  onSave={async (v) => { await put(`/api/cot/${m.code}/weeks/${r.d}/price`, { price: v === null ? null : Number(v.replace(",", ".")) }); onSaved(); }} />
              </td>
              <td className="text-right tabular-nums">{r.oi.toLocaleString()}</td>
              <td className="text-right tabular-nums">{r.ncl.toLocaleString()}</td>
              <td className="text-right tabular-nums">{r.ncs.toLocaleString()}</td>
              <td className="text-right font-medium tabular-nums">{r.spec_net.toLocaleString()}</td>
              <td className={`text-right tabular-nums ${r.spec_change > 0 ? "text-up" : r.spec_change < 0 ? "text-bear-soft" : ""}`}>{r.spec_change == null ? "—" : `${r.spec_change > 0 ? "+" : ""}${r.spec_change.toLocaleString()}`}</td>
              <td className="text-right tabular-nums">{r.cl.toLocaleString()}</td>
              <td className="text-right tabular-nums">{r.cs.toLocaleString()}</td>
              <td className="text-right tabular-nums">{r.comm_net.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 12 && <div className="mt-3"><Button kind="ghost" onClick={() => setAll(!all)}>{all ? "Show the latest 12 weeks" : `Show all ${rows.length} weeks`}</Button></div>}
    </Panel>
  );
}

function Tools({ code, name, onDone }: { code: string; name: string; onDone: () => void }) {
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [fmsg, setFmsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const paste = async () => {
    setMsg(null);
    try {
      const r = await post(`/api/cot/${code}/prices`, { text });
      setMsg(`Saved ${r.saved} price${r.saved === 1 ? "" : "s"}${r.skipped.length ? `; skipped ${r.skipped.length} line${r.skipped.length === 1 ? "" : "s"} with no matching week` : ""}.`);
      setText(""); onDone();
    } catch (e: any) { setMsg(e.message); }
  };
  const upload = async () => {
    const f = fileRef.current?.files?.[0];
    if (!f) { setFmsg("Choose a CFTC file first."); return; }
    setBusy(true); setFmsg("Reading the file…");
    try {
      const fd = new FormData(); fd.append("file", f);
      const r = await post("/api/cot/import", fd);
      setFmsg(`Read ${r.rows_read} rows: ${r.added} new weeks added, ${r.updated} corrected, ${r.prices_filled} prices filled.`);
      onDone();
    } catch (e: any) { setFmsg(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title={`Paste prices: ${name}`} collapseId="cot-paste">
        <p className="mb-2 text-sm text-muted">One week per line as <code>date, price</code>, e.g. <code>2026-10-13, 2475.30</code>. Each line goes to the report dated on, or up to 3 days before, that date. Typed prices are never overwritten.</p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} className="w-full rounded border border-line bg-ink p-2 text-sm" placeholder="2026-10-13, 2475.30" />
        <div className="mt-2 flex flex-wrap items-center gap-3"><Button disabled={!text.trim()} onClick={paste}>Save prices</Button>{msg && <span className="text-sm text-muted">{msg}</span>}</div>
      </Panel>
      <Panel title="Add weeks from a CFTC file" collapseId="cot-file">
        <p className="mb-2 text-sm text-muted">New weeks arrive automatically every Friday night. To fill a gap, download the CFTC&rsquo;s Legacy futures-only history file
          (<a className="text-verify hover:underline" href="https://www.cftc.gov/files/dea/history/deacot2026.zip" target="_blank" rel="noreferrer">2026</a>,{" "}
          <a className="text-verify hover:underline" href="https://www.cftc.gov/files/dea/history/deacot2025.zip" target="_blank" rel="noreferrer">2025</a>) and upload it here, zipped or not. Weeks already stored are matched by date.</p>
        <input ref={fileRef} type="file" accept=".zip,.txt,.csv,.json" className="block w-full text-sm" />
        <div className="mt-2 flex flex-wrap items-center gap-3"><Button disabled={busy} onClick={upload}>{busy ? "Merging…" : "Merge into tracker"}</Button>{fmsg && <span className="text-sm text-muted">{fmsg}</span>}</div>
      </Panel>
    </div>
  );
}
