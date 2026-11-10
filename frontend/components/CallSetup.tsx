"use client";

import { useMemo, useState } from "react";

import { ErrorBox, GradeBadge, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";
import { dateTime, num, pair, signed } from "@/lib/format";

const dec = (v: number | null | undefined) => (v == null ? 4 : v > 20 ? 3 : 5);
const t = (s: string) => new Date(s).getTime();
const shortDate = (ms: number) => new Date(ms).toLocaleDateString(undefined, { day: "numeric", month: "short" });

const GUTTER = "5.25rem"; // right-hand column for the level labels

const OUTCOME: Record<string, string> = { target: "Target hit", stop: "Stopped out", expired: "Expired" };

function SetupChart({ d }: { d: any }) {
  const c = d.call;
  const pts: [number, number][] = useMemo(() => d.prices.map(([ts, px]: [string, number]) => [t(ts), px]), [d.prices]);
  const bars: [number, number, number, number, number][] = useMemo(() => (d.bars || []).map(([ts, o, h, l, cl]: any[]) => [t(ts), o, h, l, cl]), [d.bars]);
  const barMs = (d.bar_hours || 24) * 3600e3;
  const [hover, setHover] = useState<number | null>(null);
  const [mode, setModeRaw] = useState<"candles" | "line">(() => {
    try { return (localStorage.getItem("callSetupChart") as any) === "line" ? "line" : "candles"; } catch { return "candles"; }
  });
  const setMode = (m: "candles" | "line") => { setModeRaw(m); setHover(null); try { localStorage.setItem("callSetupChart", m); } catch { /* ignore */ } };
  const candles = mode === "candles" && bars.length >= 2;
  if (pts.length < 2) return <p className="rounded border border-line p-4 text-sm text-muted">Not enough stored prices around this call to draw it yet.</p>;

  const x0 = Math.min(pts[0][0], t(c.opened_at), candles ? bars[0][0] : Infinity);
  const x1 = Math.max(pts[pts.length - 1][0], t(c.opened_at), candles ? bars[bars.length - 1][0] + barMs : -Infinity);
  const levels = [c.entry_price, c.stop_loss, c.take_profit].filter((v) => v != null) as number[];
  const all = (candles ? bars.flatMap((b) => [b[2], b[3]]) : pts.map((p) => p[1])).concat(levels);
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo || hi * 0.002) * 0.1; lo -= pad; hi += pad;
  const fx = (ms: number) => (ms - x0) / (x1 - x0 || 1);
  const fy = (v: number) => 1 - (v - lo) / (hi - lo);
  const path = pts.map(([ms, v], i) => `${i ? "L" : "M"}${(fx(ms) * 1000).toFixed(1)},${(fy(v) * 100).toFixed(2)}`).join("");

  const opened = t(c.opened_at);
  const closed = c.outcome_at ? t(c.outcome_at) : Math.min(t(d.window.trade_end), x1);
  const zx = fx(opened) * 1000, zw = Math.max(0, (fx(closed) - fx(opened)) * 1000);
  const band = (a: number, b: number) => ({ y: Math.min(fy(a), fy(b)) * 100, h: Math.abs(fy(a) - fy(b)) * 100 });
  const risk = c.stop_loss != null ? band(c.entry_price, c.stop_loss) : null;
  const reward = c.take_profit != null ? band(c.entry_price, c.take_profit) : null;
  const outPx = c.outcome === "target" ? c.take_profit : c.outcome === "stop" ? c.stop_loss : null;
  const hb = candles && hover != null ? bars[hover] : null;
  const h: [number, number] | null = hover == null ? null : hb ? [hb[0] + barMs / 2, hb[4]] : pts[hover];
  const bw = Math.max(0.6, (barMs / (x1 - x0 || 1)) * 1000 * 0.68);

  const labels: { v: number; text: string; cls: string }[] = [
    c.take_profit != null && { v: c.take_profit, text: `TP ${num(c.take_profit, dec(c.take_profit))}`, cls: "border-up text-up" },
    { v: c.entry_price, text: `In ${num(c.entry_price, dec(c.entry_price))}`, cls: "border-verify text-verify" },
    c.stop_loss != null && { v: c.stop_loss, text: `SL ${num(c.stop_loss, dec(c.stop_loss))}`, cls: "border-bear-soft text-bear-soft" },
  ].filter(Boolean) as any;
  // keep labels at least ~9% of the height apart
  const placed = labels.map((l) => ({ ...l, y: fy(l.v) * 100 })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < placed.length; i++) if (placed[i].y - placed[i - 1].y < 9) placed[i].y = placed[i - 1].y + 9;

  const ticks = [x0, opened, x1].filter((v, i, a) => i === 0 || Math.abs(fx(v) - fx(a[i - 1])) > 0.12);
  return (
    <div>
      <div className="relative h-64 select-none sm:h-72" style={{ paddingRight: GUTTER }}>
       <div className="relative h-full">
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const ms = x0 + ((e.clientX - r.left) / r.width) * (x1 - x0);
            const xs = candles ? bars.map((b) => b[0] + barMs / 2) : pts.map((p) => p[0]);
            let best = 0; for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - ms) < Math.abs(xs[best] - ms)) best = i;
            setHover(best);
          }}>
          {reward && <rect x={zx} width={zw} y={reward.y} height={reward.h} fill="var(--color-up)" opacity={0.14} />}
          {risk && <rect x={zx} width={zw} y={risk.y} height={risk.h} fill="var(--color-bear-soft)" opacity={0.14} />}
          {[[c.take_profit, "var(--color-up)"], [c.stop_loss, "var(--color-bear-soft)"], [c.entry_price, "var(--color-verify)"]].map(([v, col]) => v != null && (
            <line key={col as string} x1={0} x2={1000} y1={fy(v as number) * 100} y2={fy(v as number) * 100} stroke={col as string}
              strokeWidth={1.2} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" opacity={0.85} />))}
          <line x1={zx} x2={zx} y1={0} y2={100} stroke="var(--color-amber)" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
          {candles ? bars.map(([ms, o, hi2, lo2, cl], i) => {
            const cx = fx(ms + barMs / 2) * 1000, up = cl >= o, col = up ? "var(--color-dove)" : "var(--color-hawk)";
            const top = fy(Math.max(o, cl)) * 100, bot = fy(Math.min(o, cl)) * 100;
            return (<g key={i} opacity={hover === i ? 1 : 0.92}>
              <line x1={cx} x2={cx} y1={fy(hi2) * 100} y2={fy(lo2) * 100} stroke={col} strokeWidth={1} vectorEffect="non-scaling-stroke" />
              <rect x={cx - bw / 2} width={bw} y={top} height={Math.max(bot - top, 0.35)} fill={col} />
            </g>);
          }) : <path d={path} fill="none" stroke="var(--color-text)" strokeWidth={1.6} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
          {h && <line x1={fx(h[0]) * 1000} x2={fx(h[0]) * 1000} y1={0} y2={100} stroke="var(--color-muted)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />}
        </svg>
        {/* dots as HTML so they stay round */}
        <span className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-amber"
          style={{ left: `${fx(opened) * 100}%`, top: `${fy(c.entry_price) * 100}%` }} />
        {outPx != null && c.outcome_at && <span className={`pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink ${c.outcome === "target" ? "bg-up" : "bg-bear-soft"}`}
          style={{ left: `${fx(t(c.outcome_at)) * 100}%`, top: `${fy(outPx) * 100}%` }} />}
        <span className="pointer-events-none absolute top-1 -translate-x-1/2 whitespace-nowrap rounded border border-amber bg-ink px-1.5 text-[11px] text-amber" style={{ left: `${Math.min(92, Math.max(8, fx(opened) * 100))}%` }}>
          Call: {c.direction === "LONG" ? "Buy" : "Sell"}
        </span>

        {h && (
          <span className="pointer-events-none absolute bottom-1 rounded border border-line bg-ink/90 px-2 py-0.5 text-xs tabular-nums sm:whitespace-nowrap"
            style={fx(h[0]) > 0.6 ? { right: `${(1 - fx(h[0])) * 100 + 1}%` } : { left: `${fx(h[0]) * 100 + 1}%` }}>
            {hb ? <>{dateTime(new Date(hb[0]).toISOString())} · O {num(hb[1], dec(hb[1]))} H {num(hb[2], dec(hb[2]))} L {num(hb[3], dec(hb[3]))} C {num(hb[4], dec(hb[4]))}</>
              : <>{dateTime(new Date(h[0]).toISOString())} · {num(h[1], dec(h[1]))}</>}{" "}
            <span className={(c.direction === "LONG" ? h[1] - c.entry_price : c.entry_price - h[1]) >= 0 ? "text-dove" : "text-hawk"}>
              ({signed(((c.direction === "LONG" ? 1 : -1) * (h[1] - c.entry_price) / c.entry_price) * 100, 2, "%")})
            </span>
          </span>
        )}
       </div>
        {placed.map((l) => (
          <span key={l.text} className={`pointer-events-none absolute right-0 -translate-y-1/2 whitespace-nowrap rounded border bg-ink px-1 text-[11px] font-medium tabular-nums ${l.cls}`} style={{ top: `${Math.min(96, Math.max(4, l.y))}%` }}>{l.text}</span>
        ))}
      </div>
      <div className="relative mt-1 h-4 text-[11px] text-muted" style={{ marginRight: GUTTER }}>
        {ticks.map((ms) => <span key={ms} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${Math.min(95, Math.max(5, fx(ms) * 100))}%` }}>{shortDate(ms)}</span>)}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        {bars.length >= 2 && (
          <span role="group" aria-label="Chart type" className="inline-flex overflow-hidden rounded border border-line">
            {(["candles", "line"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
                className={`px-2 py-0.5 ${mode === m ? "bg-panel-2 text-text" : "hover:text-text"}`}>{m === "candles" ? `Candles (${d.bar_hours < 24 ? `${d.bar_hours}h` : "daily"})` : "Line"}</button>
            ))}
          </span>
        )}
        <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-up/40" />Reward zone</span>
        <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-bear-soft/40" />Risk zone</span>
        <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-amber align-middle" />Call given</span>
        {c.outcome && <span><span className={`mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle ${c.outcome === "target" ? "bg-up" : c.outcome === "stop" ? "bg-bear-soft" : "bg-muted"}`} />{OUTCOME[c.outcome]}{c.outcome_at ? ` · ${dateTime(c.outcome_at)}` : ""}{c.result_r != null ? ` · ${signed(c.result_r, 1)}R` : ""}</span>}
        {!c.outcome && c.stop_loss != null && <span>Still running</span>}
      </div>
    </div>
  );
}

const text = (x: any) => (typeof x === "string" ? x : x?.name ? `${x.name}${x.date ? ` · ${x.date}` : ""}` : x?.description || x?.text || JSON.stringify(x));

function List({ title, items, tone = "" }: { title: string; items: any[]; tone?: string }) {
  if (!items?.length) return null;
  return (
    <div>
      <h4 className={`mb-1 text-xs font-semibold uppercase tracking-wide ${tone || "text-muted"}`}>{title}</h4>
      <ul className="list-disc space-y-0.5 pl-4 text-sm">{items.map((x, i) => <li key={i}>{text(x)}</li>)}</ul>
    </div>
  );
}

function Snapshot({ s, call }: { s: any; call: any }) {
  if (!s) return <p className="text-sm text-muted">The analysis snapshot for this call was not stored, so only the price chart is shown.</p>;
  const [base, quote] = call.asset.length === 6 ? [call.asset.slice(0, 3), call.asset.slice(3)] : ["base", "quote"];
  const long = call.direction === "LONG";
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <GradeBadge grade={s.grade} />
          <span className="font-semibold">{s.direction === "LONG" ? "Buy" : s.direction === "SHORT" ? "Sell" : "No trade"} {pair(call.asset)}</span>
          <span className="text-muted">Confluence {signed(s.confluence, 0)} · analysis of {dateTime(s.as_of)}</span>
        </div>
        {s.primary_driver && <p className="mb-3 text-sm"><span className="text-muted">Main driver: </span>{s.primary_driver}</p>}
        {s.factors?.length > 0 && (
          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">What scored the call</h4>
            <ul className="space-y-1.5">
              {s.factors.map((f: any) => {
                const max = f.max || Math.max(...s.factors.map((g: any) => Math.abs(g.score)), 1);
                const w = Math.min(50, (Math.abs(f.score) / max) * 50);
                const supports = (f.score > 0) === long;
                return (
                  <li key={f.name} className="grid items-center gap-2 text-xs" style={{ gridTemplateColumns: "minmax(0,9rem) 1fr 3rem" }} title={`${f.score > 0 ? `Favours ${base}` : `Favours ${quote}`} · ${supports ? "supports" : "goes against"} the call`}>
                    <span className="truncate">{f.name}</span>
                    <span className="relative h-2.5 rounded bg-panel-2">
                      <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                      <span className={`absolute inset-y-0 rounded ${supports ? "bg-dove" : "bg-hawk"}`}
                        style={f.score >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
                    </span>
                    <span className={`text-right tabular-nums ${supports ? "text-dove" : "text-hawk"}`}>{signed(f.score, 1)}{f.max ? <span className="text-muted">/{f.max}</span> : ""}</span>
                  </li>
                );
              })}
            </ul>
            <p className="mt-1.5 text-[11px] text-muted">Bars right favour {base}, left favour {quote}. Green supports the {long ? "buy" : "sell"}, red goes against it.</p>
          </div>
        )}
        {s.grade_cap_reason && <p className="mt-3 text-xs text-amber">Grade capped: {s.grade_cap_reason}</p>}
      </div>
      <div className="space-y-3">
        <List title="Also supporting" items={s.secondary_drivers} />
        <List title="Confirms it" items={s.confirmation} tone="text-dove" />
        <List title="Invalidates it" items={s.invalidation} tone="text-hawk" />
        <List title="Catalysts ahead (at the time)" items={s.catalysts} />
        <List title="Risks" items={s.risks} />
        {s.alternative && <p className="text-sm"><span className="text-muted">Alternative: </span>{s.alternative}</p>}
      </div>
    </div>
  );
}

export default function CallSetup({ id }: { id: number }) {
  const { data, error, loading } = useApi<any>(`/api/track-record/${id}/setup`);
  return (
    <div className="rounded border border-line bg-panel-2/30 p-3">
      <ErrorBox error={error} />
      {loading && !data ? <Loading what="Loading setup" /> : data && (
        <>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">
              {data.call.direction === "LONG" ? "Buy" : "Sell"} {pair(data.call.asset)} · given {dateTime(data.call.opened_at)}
            </h3>
            <span className="text-xs text-muted">{data.call.trade_type === "day" ? "Day trade" : "Swing"}{data.call.risk_reward ? ` · 1:${data.call.risk_reward}` : ""}</span>
          </div>
          <SetupChart d={data} />
          <div className="mt-5 border-t border-line pt-4"><Snapshot s={data.setup} call={data.call} /></div>
          <p className="mt-4 text-[11px] text-muted">{data.note}</p>
        </>
      )}
    </div>
  );
}
