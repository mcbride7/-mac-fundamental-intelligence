"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorBox, Loading } from "@/components/ui";
import { useApi } from "@/lib/api";

const BLUE = "#3d4fd6", RED = "#e45d5d";
const BIASES = ["Very Bullish", "Bullish", "Neutral", "Bearish", "Very Bearish"];

function cell(v: number | null | undefined) {
  if (v === null || v === undefined) return { text: "", style: { color: "var(--color-muted)" } as React.CSSProperties };
  const strong = Math.abs(v) >= 2;
  const style: React.CSSProperties = v > 0 ? { background: strong ? BLUE : `${BLUE}bb`, color: "#fff" }
    : v < 0 ? { background: strong ? RED : `${RED}bb`, color: "#fff" } : {};
  return { text: `${v > 0 ? "+" : ""}${v}`, style };
}

function biasStyle(b: string): React.CSSProperties {
  if (b === "Very Bullish") return { background: BLUE, color: "#fff" };
  if (b === "Bullish") return { background: `${BLUE}99`, color: "#fff" };
  if (b === "Very Bearish") return { background: RED, color: "#fff" };
  if (b === "Bearish") return { background: `${RED}99`, color: "#fff" };
  return {};
}

const SIGN_FILTERS: [string, string][] = [["", "Any"], ["pos", "Bullish (above 0)"], ["neg", "Bearish (below 0)"], ["strong+", "Strong bullish (+2 or more)"], ["strong-", "Strong bearish (−2 or less)"]];
function passes(v: number, f: string) {
  return !f || (f === "pos" && v > 0) || (f === "neg" && v < 0) || (f === "strong+" && v >= 2) || (f === "strong-" && v <= -2);
}

export default function SetupsTable({ limit }: { limit?: number }) {
  const { data, error, loading } = useApi<any>("/api/setups/table");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [bias, setBias] = useState("");
  const [tech, setTech] = useState("");
  const [sent, setSent] = useState("");
  const [macro, setMacro] = useState("");
  const [showAll, setShowAll] = useState(false);
  const rows: any[] = useMemo(() => (data?.rows || []).filter((r: any) =>
    (!q || r.symbol.toLowerCase().includes(q.toLowerCase().replace("/", "")) || r.name.toLowerCase().includes(q.toLowerCase())) &&
    (!cat || r.category === cat) && (!bias || r.bias === bias) &&
    passes(r.technical, tech) && passes(r.sentiment_cot, sent) && passes(r.macro, macro)), [data, q, cat, bias, tech, sent, macro]);
  if (error) return <ErrorBox error={error} />;
  if (loading && !data) return <Loading what="Scoring setups" />;
  if (!data) return null;
  const groups: any[] = data.groups;
  const cols: any[] = groups.flatMap((g) => g.columns);
  const shown = limit && !showAll ? rows.slice(0, limit) : rows;
  const sel = (label: string, value: string, set: (v: string) => void, opts: [string, string][]) => (
    <label className="flex min-w-0 flex-col gap-1 text-xs text-muted">{label}
      <select value={value} onChange={(e) => set(e.target.value)} className="rounded border border-line bg-panel-2 px-2 py-1.5 text-sm text-text">
        {opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  );
  return (
    <div>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <label className="flex min-w-0 flex-col gap-1 text-xs text-muted">Symbol search
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. GBP, gold" className="rounded border border-line bg-panel-2 px-2 py-1.5 text-sm text-text" />
        </label>
        {sel("Category", cat, setCat, [["", "All categories"], ...data.categories.map((c: string) => [c, c] as [string, string])])}
        {sel("Bias", bias, setBias, [["", "Any bias"], ...BIASES.map((b) => [b, b] as [string, string])])}
        {sel("Technical score", tech, setTech, SIGN_FILTERS)}
        {sel("Sentiment + COT score", sent, setSent, SIGN_FILTERS)}
        {sel("Macro score", macro, setMacro, SIGN_FILTERS)}
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full min-w-[78rem] border-collapse text-xs tabular-nums">
          <thead>
            <tr>
              <th colSpan={4} className="bg-panel-2 px-2 py-1.5 text-center font-medium italic text-muted">Summary</th>
              {groups.map((g, i) => (
                <th key={g.key} colSpan={g.columns.length}
                  className={`px-2 py-1.5 text-center font-medium italic ${i === 0 ? "bg-[#e45d5d]/70 text-white" : "bg-[#3d4fd6]/80 text-white"}`}>{g.label}</th>
              ))}
            </tr>
            <tr className="border-b border-line text-[0.7rem] text-muted">
              <th className="px-1.5 py-1.5 font-medium">1 day change</th>
              <th className="px-1.5 py-1.5 text-left font-medium">Symbol</th>
              <th className="px-1.5 py-1.5 font-medium">Bias</th>
              <th className="px-1.5 py-1.5 font-medium">Score</th>
              {cols.map((c) => <th key={c.key} className="px-1 py-1.5 font-medium leading-tight">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.symbol} className="border-b border-line/60">
                <td className={`px-1.5 py-1.5 text-center ${r.day_change > 0 ? "text-[#9ccc65]" : r.day_change < 0 ? "text-[#ff7b7b]" : "text-muted"}`}>
                  {r.day_change == null ? "—" : `${r.day_change > 0 ? "+" : ""}${r.day_change_unit === "bp" ? r.day_change.toFixed(0) + " bp" : r.day_change.toFixed(2) + "%"}`}</td>
                <td className="whitespace-nowrap px-1.5 py-1.5 font-semibold">
                  <Link href={r.symbol.length === 6 && !r.symbol.startsWith("X") ? `/analysis/${r.symbol}` : "/seasonality"} className="underline decoration-dotted underline-offset-2 hover:text-verify">{r.name}</Link>
                </td>
                <td className="whitespace-nowrap px-1.5 py-1.5 text-center font-medium" style={biasStyle(r.bias)}>{r.bias}</td>
                <td className="px-1.5 py-1.5 text-center font-semibold">{r.score}</td>
                {cols.map((c) => { const x = cell(r.cells[c.key]); return <td key={c.key} className="border-l border-line/40 px-1 py-1.5 text-center" style={x.style}>{x.text}</td>; })}
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={4 + cols.length} className="px-3 py-4 text-center text-muted">No symbols match these filters.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>Each cell is −2 to +2 (blue = bullish, red = bearish, blank = no data). Score = the sum. Pairs compare base vs quote; gold, silver and the T-note read US data the other way round.
          Scores refresh every 10 minutes.</span>
        {limit && rows.length > limit && (
          <button className="rounded border border-line px-2 py-1 text-text hover:bg-panel-2" onClick={() => setShowAll(!showAll)}>
            {showAll ? `Show top ${limit}` : `Show all ${rows.length}`}</button>
        )}
      </div>
    </div>
  );
}
