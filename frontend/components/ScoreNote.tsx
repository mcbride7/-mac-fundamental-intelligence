"use client";

import { useState } from "react";

import { useCollapsed } from "@/components/ui";

const NOTE_BG = "#fff1a8", NOTE_INK = "#3b3410";

function Chip({ v }: { v: number }) {
  const bg = v >= 2 ? "#3d4fd6" : v === 1 ? "#3d4fd6bb" : v === -1 ? "#e45d5dbb" : v <= -2 ? "#e45d5d" : "#ffffff";
  return (
    <span className="inline-block w-7 rounded text-center text-[0.7rem] font-semibold tabular-nums"
      style={{ background: bg, color: v === 0 ? NOTE_INK : "#fff", border: v === 0 ? "1px solid #d8cb7a" : undefined }}>
      {v > 0 ? `+${v}` : v}
    </span>
  );
}

/** Yellow sticky note explaining what the Top setups numbers mean. Can be folded away (remembered). */
export default function ScoreNote() {
  const [folded, toggle] = useCollapsed("setups-note");
  const [more, setMore] = useState(false);
  if (folded) {
    return (
      <button onClick={toggle} title="Show what the numbers mean"
        className="rounded px-3 py-1.5 text-xs font-semibold shadow-md" style={{ background: NOTE_BG, color: NOTE_INK }}>
        📌 What do the numbers mean?
      </button>
    );
  }
  return (
    <aside aria-label="What the numbers mean" className="relative w-full rounded-sm p-3 pt-4 text-xs leading-snug shadow-lg sm:w-[22rem] sm:rotate-1"
      style={{ background: NOTE_BG, color: NOTE_INK }}>
      <span aria-hidden className="absolute -top-2 left-1/2 -translate-x-1/2 text-base">📌</span>
      <button onClick={toggle} title="Fold the note away" aria-label="Fold the note away"
        className="absolute right-1.5 top-1 rounded px-1.5 text-sm font-bold opacity-60 hover:opacity-100">×</button>
      <p className="mb-1.5 font-semibold">What the numbers mean</p>
      <ul className="grid grid-cols-2 gap-x-2 gap-y-1">
        <li><Chip v={2} /> strongly bullish</li>
        <li><Chip v={-2} /> strongly bearish</li>
        <li><Chip v={1} /> bullish</li>
        <li><Chip v={-1} /> bearish</li>
        <li><Chip v={0} /> neutral, no edge</li>
        <li>blank = no data yet</li>
      </ul>
      <p className="mt-2"><b>Pairs</b>: base minus quote, so EUR/USD +2 = the euro side is much stronger.</p>
      <p className="mt-1"><b>Score</b> = all cells added up. <b>Bias</b>: 7+ Very Bullish · 4 to 6 Bullish · −3 to 3 Neutral · −4 to −6 Bearish · −7 or less Very Bearish.</p>
      <button onClick={() => setMore(!more)} className="mt-2 font-semibold underline decoration-dotted underline-offset-2">
        {more ? "Hide the column guide" : "What each column means ▸"}</button>
      {more && (
        // on wider screens the guide hangs below the note over the table, so the page doesn't jump
        <ul className="mt-1.5 space-y-1 sm:absolute sm:left-0 sm:right-0 sm:top-full sm:z-20 sm:mt-0 sm:rounded-b-sm sm:p-3 sm:pt-1 sm:shadow-lg"
          style={{ background: NOTE_BG }}>
          <li><b>Trend</b>: price vs its 20 and 50-day averages.</li>
          <li><b>Seasonality</b>: how it usually moves this month and the next 2 weeks.</li>
          <li><b>COT</b>: big speculators adding longs (+) or shorts (−); crowded extremes count against.</li>
          <li><b>Retail sentiment</b>: read the opposite way; most retail traders long = bearish.</li>
          <li><b>News tone</b>: hawkish minus dovish headlines, last 3 days.</li>
          <li><b>CB diverg.</b>: gap between the two central banks&rsquo; policy scores.</li>
          <li><b>CB tone / Rate expect. / Interest rates</b>: hawkish statements, hikes priced in, and the last decision (hike + / cut −).</li>
          <li><b>Data columns</b> (GDP, PMIs, CPI, jobs…): latest release beat (+) or missed (−) the forecast in the hawkish direction. Higher unemployment or claims count as −.</li>
          <li><b>Gold, silver, T-note</b> read US data the other way round: soft US data = bullish.</li>
          <li><b>Summary filters</b>: Technical = Trend · Sentiment + COT = COT + Retail + News · Macro = all the macro columns.</li>
        </ul>
      )}
    </aside>
  );
}
