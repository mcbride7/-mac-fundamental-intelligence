"use client";

import StickyNote, { NOTE_INK } from "@/components/StickyNote";

function Chip({ v }: { v: number }) {
  const bg = v >= 2 ? "#3d4fd6" : v === 1 ? "#3d4fd6bb" : v === -1 ? "#e45d5dbb" : v <= -2 ? "#e45d5d" : "#ffffff";
  return (
    <span className="inline-block w-7 rounded text-center text-[0.7rem] font-semibold tabular-nums"
      style={{ background: bg, color: v === 0 ? NOTE_INK : "#fff", border: v === 0 ? "1px solid #d8cb7a" : undefined }}>
      {v > 0 ? `+${v}` : v}
    </span>
  );
}

/** Sticky note explaining what the Top setups numbers mean. */
export default function ScoreNote() {
  return (
    <StickyNote id="setups-note" title="What the numbers mean" folded="What do the numbers mean?"
      moreLabel="What each column means ▸" lessLabel="Hide the column guide"
      more={
        <ul className="space-y-1">
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
      }>
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
    </StickyNote>
  );
}
