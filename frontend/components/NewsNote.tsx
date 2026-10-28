"use client";

import StickyNote from "@/components/StickyNote";

const Tag = ({ cls, children }: { cls: string; children: React.ReactNode }) => (
  <span className={`inline-block rounded px-1.5 py-px text-[0.7rem] font-semibold text-white ${cls}`}>{children}</span>
);

/** Sticky note explaining the News tab's numbers and tags. */
export default function NewsNote() {
  return (
    <StickyNote id="news-note" title="What the numbers mean" folded="What do the numbers mean?"
      moreLabel="What the tags mean ▸" lessLabel="Hide the tag guide" hang={false}
      more={
        <ul className="space-y-1">
          <li><Tag cls="bg-bull">Hawkish</Tag> rate hikes, tightening, hot inflation, strong data: supports the currency.</li>
          <li><Tag cls="bg-bear">Dovish</Tag> rate cuts, easing, cooling inflation, weak data: weighs on it.</li>
          <li><Tag cls="bg-good">Risk-on</Tag> rallies, record highs, deals: helps AUD, NZD, stocks; hurts JPY, CHF, gold.</li>
          <li><Tag cls="bg-amber">Risk-off</Tag> sell-offs, safe havens, war, fears: the reverse.</li>
          <li><Tag cls="bg-amber">High impact</Tag> rate decisions, CPI, NFP, GDP, press conferences.</li>
          <li><b>Currency tags</b>: who the headline is about. The tone only counts for currencies named by country or central bank, not a bare pair code (&ldquo;GBP/USD rallies on UK wages&rdquo; is hawkish for GBP only).</li>
          <li><b>Blue source name</b> = an official central bank press release.</li>
          <li>Tags come from keywords, so they&rsquo;re a quick guide; open the article when it matters.</li>
        </ul>
      }>
      <ul className="space-y-1">
        <li><b>+2 / −1 on a tile</b> = hawkish minus dovish headlines for that currency over the last 3 days.</li>
        <li><b>2↑ 1↓</b> = 2 hawkish and 1 dovish headline.</li>
        <li><b>Lean</b>: +2 or more <b>Hawkish</b> (bullish for the currency) · −2 or less <b>Dovish</b> (bearish) · in between <b>Balanced</b> · no headlines <b>Quiet</b>.</li>
        <li><b>Risk mood</b>: Risk-on or Risk-off when one side leads by 3+ headlines, otherwise Mixed.</li>
        <li><b>On Top setups</b> a Hawkish currency scores +1 and a Dovish one −1 in the News tone column; a pair is base minus quote (e.g. hawkish GBP + dovish EUR = EUR/GBP −2).</li>
      </ul>
    </StickyNote>
  );
}
