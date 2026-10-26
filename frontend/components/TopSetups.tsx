"use client";

import Link from "next/link";

import QuickEdit from "@/components/QuickEdit";
import { Empty, ErrorBox, Loading } from "@/components/ui";
import { put, useApi } from "@/lib/api";

const GREEN = "#43a047", RED = "#e53935";

function GradeChip({ grade }: { grade: string }) {
  const cls = grade === "A+" ? "bg-[#43a047] text-white" : grade === "A" ? "bg-[#43a047]/70 text-white"
    : grade === "B" ? "bg-amber/80 text-ink" : grade === "C" ? "border border-amber/70 text-amber" : "border border-line text-muted";
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>{grade}</span>;
}

/** -2..+2 as a small centred bar. */
function PillarBar({ v }: { v: number | null }) {
  if (v === null || v === undefined) return <span className="text-xs text-muted">no data</span>;
  const w = Math.min(50, (Math.abs(v) / 2) * 50);
  return (
    <span className="relative block h-2 w-full rounded bg-panel-2" aria-hidden>
      <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
      <span className="absolute inset-y-0 rounded" style={{ background: v >= 0 ? GREEN : RED, ...(v >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }) }} />
    </span>
  );
}

export function SetupCard({ s, onRetail }: { s: any; onRetail?: () => void }) {
  const long = s.direction === "LONG", short = s.direction === "SHORT";
  const dirCol = long ? "text-[#9ccc65]" : short ? "text-[#ff7b7b]" : "text-muted";
  return (
    <article className="flex min-w-0 flex-col rounded-md border border-line bg-panel p-4">
      <header className="flex items-start justify-between gap-2">
        <div>
          <Link href={s.asset === "XAUUSD" ? "/seasonality" : `/analysis/${s.asset}`} className="text-lg font-semibold hover:underline">{s.label}</Link>
          <div className={`text-sm font-medium ${dirCol}`}>{long ? "▲ Long bias" : short ? "▼ Short bias" : "No clear setup"}
            <span className="ml-2 text-xs text-muted">score {s.score > 0 ? "+" : ""}{s.score}</span></div>
        </div>
        <GradeChip grade={s.grade} />
      </header>
      <ul className="mt-3 space-y-1.5">
        {s.pillars.map((p: any) => (
          <li key={p.key} className="grid grid-cols-[7.5rem_1fr] items-center gap-2 text-xs" title={p.note || undefined}>
            <span className="truncate text-muted">{p.label.replace(" & rate expectations", "").replace(" & inflation", "")}</span>
            <PillarBar v={p.score} />
          </li>
        ))}
      </ul>
      {s.reasons?.length > 0 && (
        <div className="mt-3 text-sm"><span className="font-semibold">Why: </span>{s.reasons.join("; ")}.</div>
      )}
      {s.against?.length > 0 && (
        <div className="mt-1 text-sm text-muted"><span className="font-semibold text-amber">Watch: </span>{s.against.join("; ")}.</div>
      )}
      {s.risk_context && <div className="mt-2 text-xs text-muted">Risk mood: {s.risk_context}.</div>}
      {onRetail && (
        <div className="mt-auto flex items-center gap-2 pt-3 text-xs text-muted">Retail long %:
          <QuickEdit label={`Retail long % for ${s.label}`} display={s.retail_long_pct == null ? "add" : `${s.retail_long_pct.toFixed(0)}%`}
            initial={s.retail_long_pct == null ? "" : String(Math.round(s.retail_long_pct))}
            onSave={async (v) => { await put(`/api/setups/retail/${s.asset}`, { long_pct: Number(v) }); onRetail(); }} />
          {s.retail_source && <span>({s.retail_source})</span>}
        </div>
      )}
    </article>
  );
}

export default function TopSetups({ limit, editable = false }: { limit?: number; editable?: boolean }) {
  const { data, error, loading, reload } = useApi<any>("/api/setups");
  if (error) return <ErrorBox error={error} />;
  if (loading && !data) return <Loading what="Scoring setups" />;
  const all: any[] = data?.setups || [];
  const list = limit ? all.filter((s) => ["A+", "A", "B", "C"].includes(s.grade)).slice(0, limit) : all;
  if (!list.length) return <Empty href="/setups" cta="See every asset">{limit ? "No asset has enough agreement between the pillars for a setup right now." : "Not enough data yet to score setups."}</Empty>;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {list.map((s) => <SetupCard key={s.asset} s={s} onRetail={editable ? reload : undefined} />)}
    </div>
  );
}
