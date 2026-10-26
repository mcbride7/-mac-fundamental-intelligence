"use client";

import { Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { num } from "@/lib/format";

function shortDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
}

function RiskChart({ hist, on, off }: { hist: { date: string; score: number }[]; on: number; off: number }) {
  if (hist.length < 2) return <p className="text-xs text-muted">The chart fills in as daily readings build up.</p>;
  const W = 600, H = 120, y = (v: number) => H - (v / 100) * H, x = (i: number) => (i / (hist.length - 1)) * W;
  const path = hist.map((h, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(h.score).toFixed(1)}`).join(" ");
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-32 w-full" preserveAspectRatio="none" role="img"
        aria-label={`Risk sentiment over the last ${hist.length} days, latest ${num(hist[hist.length - 1].score, 0)}`}>
        <rect x="0" y="0" width={W} height={y(on)} fill="#43a047" opacity="0.14" />
        <rect x="0" y={y(off)} width={W} height={H - y(off)} fill="#e53935" opacity="0.14" />
        <line x1="0" x2={W} y1={y(50)} y2={y(50)} stroke="currentColor" opacity="0.2" strokeDasharray="4 4" />
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-muted"><span>{shortDate(hist[0].date)}</span>
        <span>green band = risk-on (≥{on}), red band = risk-off (≤{off})</span><span>{shortDate(hist[hist.length - 1].date)}</span></figcaption>
    </figure>
  );
}

const GREEN = "#43a047", RED = "#e53935", MIXED = "#9aa5b5";

/** Round dial like a car gauge: Risk Off (red, left), Mixed (top), Risk On (green, right). */
function RiskDial({ score, on, off }: { score: number; on: number; off: number }) {
  // the dial sweeps 240 degrees, from bottom-left (0) over the top to bottom-right (100), like a car gauge
  const ang = (v: number) => ((210 - (v / 100) * 240) * Math.PI) / 180;
  const pt = (v: number, r: number) => [100 + r * Math.cos(ang(v)), 100 - r * Math.sin(ang(v))];
  const arc = (a: number, b: number, r: number) => {
    const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r);
    return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${(b - a) * 2.4 > 180 ? 1 : 0} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  };
  const v = Math.max(0, Math.min(100, score));
  const [nx, ny] = pt(v, 66);
  const tail = pt(v, -14);
  const major = [0, 25, 50, 75, 100];
  const minor = Array.from({ length: 21 }, (_, i) => i * 5).filter((t) => !major.includes(t));
  return (
    <svg viewBox="0 0 200 200" className="w-60 max-w-full drop-shadow-lg" role="img" aria-label={`Risk dial at ${Math.round(v)} out of 100`}>
      <defs>
        <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" /><stop offset="0.45" stopColor="#c7ccd3" /><stop offset="1" stopColor="#8d949e" />
        </linearGradient>
        <radialGradient id="face" cx="0.45" cy="0.4" r="0.7">
          <stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#dfe3e8" />
        </radialGradient>
        <radialGradient id="hub" cx="0.35" cy="0.35" r="0.7">
          <stop offset="0" stopColor="#6fb1ff" /><stop offset="1" stopColor="#1f6fd6" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="100" r="96" fill="url(#rim)" />
      <circle cx="100" cy="100" r="86" fill="url(#face)" stroke="#aeb5be" strokeWidth="1" />
      <path d={arc(0, off, 70)} fill="none" stroke={RED} strokeWidth="15" />
      <path d={arc(on, 100, 70)} fill="none" stroke={GREEN} strokeWidth="15" />
      <path d={arc(0, off, 77.5)} fill="none" stroke="#8a1f1c" strokeWidth="1" opacity="0.5" />
      <path d={arc(on, 100, 77.5)} fill="none" stroke="#2c6e2f" strokeWidth="1" opacity="0.5" />
      {minor.map((t) => { const [x1, y1] = pt(t, 82), [x2, y2] = pt(t, 78.5); return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#7b8490" strokeWidth="1" />; })}
      {major.map((t) => { const [x1, y1] = pt(t, 83), [x2, y2] = pt(t, 75); return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#3c4450" strokeWidth={t === 50 ? 3 : 2} />; })}
      <text x="100" y="47" fontSize="10" fill="#4f5966" textAnchor="middle">Mixed</text>
      <text x={pt(22, 50)[0]} y={pt(22, 50)[1] + 3} fontSize="10" fill="#4f5966" textAnchor="middle">R.Off</text>
      <text x={pt(78, 50)[0]} y={pt(78, 50)[1] + 3} fontSize="10" fill="#4f5966" textAnchor="middle">R.On</text>
      <text x={pt(2, 58)[0] + 6} y={pt(2, 58)[1] - 2} fontSize="8.5" fill="#6b7480" textAnchor="middle">R.Off−</text>
      <text x={pt(98, 58)[0] - 6} y={pt(98, 58)[1] - 2} fontSize="8.5" fill="#6b7480" textAnchor="middle">R.On+</text>
      <line x1={tail[0]} y1={tail[1]} x2={nx} y2={ny} stroke="#ef5a24" strokeWidth="3" strokeLinecap="round" />
      <circle cx="100" cy="100" r="12" fill="url(#hub)" stroke="#155bb5" strokeWidth="1" />
      <text x="100" y="168" fontSize="22" fontWeight="600" fill="#3a4350" textAnchor="middle">{Math.round(v)}</text>
    </svg>
  );
}

function Tile({ t }: { t: any }) {
  const chg = t.change_bps ?? t.change_1d_pct;
  const dp = t.unit === "%" ? 2 : t.symbol === "VIX" ? 2 : t.price >= 1000 ? 0 : t.price >= 100 ? 2 : 4;
  return (
    <div className="min-w-0 rounded-lg border border-line bg-panel-2/60 px-3 py-3" title={t.source ? `Source: ${t.source}` : undefined}>
      <div className="truncate text-base font-bold tracking-tight sm:text-lg">{t.label}</div>
      <div className="mt-1 grid grid-cols-2 gap-2 text-[0.7rem] text-muted"><span>{t.unit === "%" ? "Yield" : "Price"}</span><span>1-day</span></div>
      <div className="grid grid-cols-2 gap-2 text-base tabular-nums sm:text-lg">
        <span>{t.price.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}{t.unit || ""}</span>
        <span className={chg == null ? "text-muted" : chg < 0 ? "text-[#ff7b7b]" : "text-[#9ccc65]"}>
          {chg == null ? "—" : t.change_bps != null ? `${chg > 0 ? "+" : ""}${chg.toFixed(0)} bp` : `${chg > 0 ? "+" : ""}${chg.toFixed(2)}%`}</span>
      </div>
    </div>
  );
}

const DISPLAY: Record<string, string> = { BONDS: "US BONDS" };

function moveText(name: string, m: any): string | null {
  if (!m) return null;
  if (m.change_bps != null) return `10Y ${m.change_bps > 0 ? "+" : ""}${m.change_bps.toFixed(0)} bp`;
  if (m.change_pct == null) return null;
  return `${m.change_pct > 0 ? "+" : ""}${m.change_pct.toFixed(2)}%`;
}

function EvalBox({ title, items, colour, moves }: { title: string; items: string[]; colour: string; moves: Record<string, any> }) {
  return (
    <div className="flex min-w-0 flex-col">
      <div className="mb-1 text-center text-sm font-semibold">{title}</div>
      <div className="flex min-h-[10rem] flex-1 flex-col items-center justify-center rounded px-2 py-4 text-center text-base font-semibold leading-snug text-white sm:text-lg"
        style={{ background: colour }}>
        {items.length ? items.map((i, n) => {
          const mv = moveText(i, moves[i]);
          return (
            <span key={i} className="block" title={moves[i]?.against ? `vs ${moves[i].against}` : undefined}>
              <span className="whitespace-nowrap">{DISPLAY[i] || i}</span>{mv && " "}{mv && <span className="whitespace-nowrap text-sm font-medium opacity-90">({mv})</span>}{n < items.length - 1 ? "," : ""}
            </span>
          );
        }) : <span className="text-sm font-normal opacity-80">None today</span>}
      </div>
    </div>
  );
}

export default function RiskSentiment() {
  const { data, error, loading } = useApi<any>("/api/macro/risk");
  const c = data?.current;
  const ev = data?.evaluation;
  const biasColour = c?.label === "Risk-On" ? "text-[#9ccc65]" : c?.label === "Risk-Off" ? "text-[#ff7b7b]" : "text-muted";
  return (
    <Panel title="Daily Risk ON / Risk OFF">
      <ErrorBox error={error} />
      {data?.tiles?.length > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">{data.tiles.map((t: any) => <Tile key={t.symbol} t={t} />)}</div>
      )}
      {loading && !data ? <Loading /> : !c || c.score === null ? (
        <Empty href="/data-health" cta="Open Data health">No risk reading yet. It is worked out from daily FRED data (VIX, credit spreads, S&amp;P 500, FX).
          On Data health, press Run now on &ldquo;Risk sentiment market series&rdquo;, or wait for the next automatic run.</Empty>
      ) : (
        <>
          <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
            <div className="flex flex-col items-center">
              <h3 className="mb-2 self-start text-2xl font-medium sm:text-3xl">Daily Bias: <span className={biasColour}>{ev?.bias}</span></h3>
              <RiskDial score={c.score} on={data.thresholds.risk_on} off={data.thresholds.risk_off} />
              <p className="mt-1 text-center text-xs text-muted">Score out of 100. Market data up to {shortDate(c.data_date)};
                {" "}{Math.round(c.coverage * 100)}% of signals available.</p>
            </div>
            <div className="min-w-0">
              <h3 className="mb-3 text-center text-2xl font-medium sm:text-3xl lg:mt-1">Daily Evaluation</h3>
              <div className="grid grid-cols-2 gap-1">
                <EvalBox title="Bullish/D" items={ev?.bullish || []} colour={GREEN} moves={ev?.moves || {}} />
                <EvalBox title="Bearish/D" items={ev?.bearish || []} colour={RED} moves={ev?.moves || {}} />
              </div>
              {ev?.basis && <p className="mt-2 text-xs text-muted">{ev.basis} Brackets show the 1-day change: currencies against the US dollar (USD against
                the others), US bonds as the 10-year yield (yield up = bond prices down).</p>}
            </div>
          </div>
          {c.why && (
            <div className={`mt-5 rounded border-l-4 bg-panel-2/60 px-4 py-3 text-sm ${c.label === "Risk-On" ? "border-[#43a047]" : c.label === "Risk-Off" ? "border-[#e53935]" : "border-[#9aa5b5]"}`}>
              <span className="font-semibold">Why: </span>{c.why}
              {c.implication && <span className="mt-1 block text-muted">{c.implication}</span>}
            </div>
          )}
          {(c.notes || []).map((n: string) => (
            <p key={n} className="mt-3 rounded border border-amber/50 bg-amber/10 px-3 py-2 text-sm text-amber">{n}</p>
          ))}
          <details className="mt-5 rounded border border-line p-3">
            <summary className="cursor-pointer text-sm font-medium">The 8 signals behind the score, and its history</summary>
            <ul className="mt-4 space-y-3">
              {c.components.map((k: any) => (
                <li key={k.key} className="text-sm" title={k.reading}>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span>{k.label}</span><span className="text-xs text-muted">{k.reading}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-3">
                    <span className="relative h-2.5 flex-1 rounded bg-panel-2" aria-hidden>
                      <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                      <span className="absolute inset-y-0 rounded" style={{ background: k.score >= 0 ? GREEN : RED,
                        ...(k.score >= 0 ? { left: "50%", width: `${k.score / 2}%` } : { right: "50%", width: `${-k.score / 2}%` }) }} />
                    </span>
                    <span className={`w-10 text-right tabular-nums ${k.score >= 0 ? "text-[#9ccc65]" : "text-[#ff7b7b]"}`}>{k.score > 0 ? "+" : ""}{num(k.score, 0)}</span>
                  </div>
                </li>
              ))}
            </ul>
            {c.missing?.length > 0 && <p className="mt-3 text-xs text-muted">Not enough data yet: {c.missing.join(", ")}.</p>}
            <div className="mt-4"><RiskChart hist={data.history} on={data.thresholds.risk_on} off={data.thresholds.risk_off} /></div>
          </details>
        </>
      )}
    </Panel>
  );
}

