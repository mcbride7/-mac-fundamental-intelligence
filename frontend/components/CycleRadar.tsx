"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorBox, Loading, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";

const STAGE_CLS: Record<string, string> = {
  hiking: "bg-hawk/20 text-hawk border-hawk/50", cutting: "bg-dove/20 text-dove border-dove/50",
  holding: "bg-panel-2 text-muted border-line",
};
const SUPPORT_CLS = (s: boolean | null) => (s === true ? "text-up" : s === false ? "text-bear-soft" : "text-amber");
const STRENGTH_CLS: Record<string, string> = {
  Strong: "bg-verify/25 text-verify", Moderate: "bg-amber/20 text-amber", Weak: "bg-panel-2 text-muted",
};

/** -1.5 (easing) .. +1.5 (tightening) strip with every bank placed on it. */
function StanceStrip({ banks }: { banks: any[] }) {
  const W = 760, H = 132, L = 20, R = 20, mid = 62;
  const x = (v: number) => L + ((Math.max(-1.6, Math.min(1.6, v)) + 1.6) / 3.2) * (W - L - R);
  const sorted = [...banks].sort((a, b) => a.stance - b.stance);
  // four label rows (two above, two below): each label goes to the row whose last label is furthest away
  const rows = [-18, 18, -36, 36], lastX = [-1e9, -1e9, -1e9, -1e9];
  const slot: Record<string, number> = {};
  sorted.forEach((b) => {
    const cx = x(b.stance);
    let best = 0;
    rows.forEach((_, r) => { if (cx - lastX[r] > cx - lastX[best] + (r > best ? 0.01 : 0)) best = r; });
    const free = rows.findIndex((_, r) => cx - lastX[r] >= 38);
    const r = free >= 0 ? free : best;
    slot[b.code] = rows[r]; lastX[r] = cx;
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[34rem]" role="img" aria-label="Where each central bank sits from easing to tightening">
      <defs><linearGradient id="cyc" x1="0" x2="1"><stop offset="0" stopColor="var(--color-dove)" /><stop offset="0.5" stopColor="var(--color-line)" /><stop offset="1" stopColor="var(--color-hawk)" /></linearGradient></defs>
      <rect x={L} y={mid - 3} width={W - L - R} height="6" rx="3" fill="url(#cyc)" opacity="0.8" />
      <text x={L} y={H - 4} fontSize="11" fill="currentColor" opacity="0.6">Cutting / easing</text>
      <text x={W / 2} y={H - 4} fontSize="11" textAnchor="middle" fill="currentColor" opacity="0.6">Holding</text>
      <text x={W - R} y={H - 4} fontSize="11" textAnchor="end" fill="currentColor" opacity="0.6">Hiking / tightening</text>
      {sorted.map((b) => {
        const off = slot[b.code], up = off < 0, cx = x(b.stance);
        return (
          <g key={b.code}>
            <line x1={cx} x2={cx} y1={mid} y2={mid + off} stroke="currentColor" opacity="0.35" />
            <circle cx={cx} cy={mid} r="5" fill={b.stance > 0.3 ? "var(--color-hawk)" : b.stance < -0.3 ? "var(--color-dove)" : "var(--color-muted)"} stroke="var(--color-ink)" strokeWidth="1.5">
              <title>{`${b.name}: ${b.cycle.label}, data ${b.data.label.toLowerCase()} (stance ${b.stance > 0 ? "+" : ""}${b.stance})`}</title>
            </circle>
            <text x={cx} y={up ? mid + off - 4 : mid + off + 12} fontSize="11.5" fontWeight="600" textAnchor="middle" fill="currentColor">{b.currency}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function CycleRadar() {
  const { data, error, loading } = useApi<any>("/api/central-banks/cycles");
  const [open, setOpen] = useState<string | null>(null);
  const [only, setOnly] = useState<"all" | "confirmed">("all");
  if (error) return <Panel title="Policy cycle divergence"><ErrorBox error={error} /></Panel>;
  if (loading && !data) return <Panel title="Policy cycle divergence"><Loading /></Panel>;
  if (!data) return null;
  const pairs: any[] = data.pairs.filter((p: any) => only === "all" || p.confirmed);
  return (
    <Panel title="Policy cycle divergence radar" collapseId="cb-cycles"
      action={<span className="text-xs text-muted">Who is hiking, cutting or holding, and whether the data backs it</span>}>
      <div className="overflow-x-auto"><StanceStrip banks={data.banks} /></div>

      <h3 className="mb-2 mt-4 font-medium">Diverging pairs</h3>
      <div className="mb-2 flex gap-1 text-sm">
        {([["all", "All"], ["confirmed", "Data confirms both sides"]] as const).map(([k, t]) => (
          <button key={k} onClick={() => setOnly(k)} aria-pressed={only === k}
            className={`rounded border px-3 py-1 ${only === k ? "border-verify bg-panel-2" : "border-line text-muted hover:text-text"}`}>{t}</button>
        ))}
      </div>
      {pairs.length ? (
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[52rem]">
            <thead><tr><th>Trade idea</th><th>Strength</th><th>Cycles</th><th>Hawkish side</th><th>Dovish side</th><th>Data backs it?</th></tr></thead>
            <tbody>
              {pairs.slice(0, 15).map((p) => (
                <tr key={p.pair}>
                  <td className="whitespace-nowrap font-semibold">{p.trade}</td>
                  <td><span className={`rounded px-1.5 py-0.5 text-xs ${STRENGTH_CLS[p.strength]}`}>{p.strength}</span></td>
                  <td className="whitespace-nowrap text-sm">{p.kind}</td>
                  <td className="text-sm"><b>{p.hawk.currency}</b> · {p.hawk.cycle}<span className="block text-xs text-muted">{p.hawk.support}</span></td>
                  <td className="text-sm"><b>{p.dove.currency}</b> · {p.dove.cycle}<span className="block text-xs text-muted">{p.dove.support}</span></td>
                  <td className={`text-sm ${p.confirmed ? "text-up" : p.against ? "text-bear-soft" : "text-amber"}`}>
                    {p.confirmed ? "✓ Both sides" : p.against ? "✗ Data disagrees on one side" : "Partly"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="text-sm text-muted">No clear cycle divergence right now{only === "confirmed" ? " that the data backs on both sides" : ""}. It shows once banks are in different cycles (rate history or decisions needed).</p>}

      <h3 className="mb-2 mt-5 font-medium">Each bank&rsquo;s cycle <span className="text-sm font-normal text-muted">· tap a bank for the data behind it</span></h3>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {[...data.banks].sort((a, b) => b.stance - a.stance).map((b: any) => (
          <div key={b.code} className="rounded border border-line bg-panel-2/40 p-3 text-sm">
            <button onClick={() => setOpen(open === b.code ? null : b.code)} aria-expanded={open === b.code} className="w-full text-left">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{b.name} <span className="font-normal text-muted">{b.currency}{b.rate != null && ` · ${b.rate}%`}</span></span>
                <span className={`rounded border px-1.5 py-0.5 text-xs ${STAGE_CLS[b.cycle.stage]}`}>{b.cycle.label}</span>
              </div>
              <div className="mt-1 text-xs text-muted">
                {b.cycle.hikes_12m || b.cycle.cuts_12m
                  ? `Last 12 months: ${b.cycle.hikes_12m ? `${b.cycle.hikes_12m} hike${b.cycle.hikes_12m > 1 ? "s" : ""}` : ""}${b.cycle.hikes_12m && b.cycle.cuts_12m ? ", " : ""}${b.cycle.cuts_12m ? `${b.cycle.cuts_12m} cut${b.cycle.cuts_12m > 1 ? "s" : ""}` : ""} (${b.cycle.change_12m_bps > 0 ? "+" : ""}${b.cycle.change_12m_bps} bp)`
                  : "No rate change in the last 12 months"}
                {b.cycle.market && ` · market: ${b.cycle.market}`}
              </div>
              <div className="mt-1.5 flex items-center justify-between text-xs">
                <span>Data: <b className={b.data.label === "Hawkish" ? "text-hawk" : b.data.label === "Dovish" ? "text-dove" : ""}>{b.data.label}</b>
                  {b.data.score != null && <span className="text-muted"> ({b.data.score > 0 ? "+" : ""}{b.data.score})</span>}</span>
                <span className={`font-medium ${SUPPORT_CLS(b.support.supported)}`}>{b.support.verdict}</span>
              </div>
            </button>
            {open === b.code && (
              <div className="mt-2 border-t border-line pt-2 text-xs">
                <p className="mb-1 text-muted">{b.support.note}</p>
                {b.data.signals.length ? (
                  <ul className="space-y-0.5">
                    {b.data.signals.map((s: any) => (
                      <li key={s.name} className="flex justify-between gap-2"><span>{s.name}: <span className="text-muted">{s.note}</span></span>
                        <span className={s.score > 0.1 ? "text-hawk" : s.score < -0.1 ? "text-dove" : "text-muted"}>{s.score > 0 ? "+" : ""}{s.score}</span></li>
                    ))}
                  </ul>
                ) : <p className="text-muted">No data stored yet: add releases on the Macro page or the economic calendar.</p>}
                <Link href={`/central-banks/${b.code}`} className="mt-1 inline-block text-verify hover:underline">Open {b.name} →</Link>
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Cycle comes from the rate path: <b>Hiking</b> or <b>Cutting</b> if the last move was within 9 months (paused after 4 months without a move), otherwise <b>Holding</b>.
        Data runs from −1 (dovish) to +1 (hawkish): inflation and core inflation vs target, the inflation trend, jobs, growth and PMIs, and data surprises.
        A cycle is <b>supported</b> when the data points the same way (hawkish for hikes, dovish for cuts, balanced for a hold). The strongest trades pair a supported hiker
        (or a hawkish hold) against a supported cutter (or a dovish hold). Not financial advice.</p>
    </Panel>
  );
}
