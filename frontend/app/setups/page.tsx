"use client";

import TopSetups from "@/components/TopSetups";
import { PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";

export default function SetupsPage() {
  const { data } = useApi<any>("/api/setups?limit=1");
  const w = data?.weights || {};
  return (
    <>
      <PageTitle title="Top setups"
        subtitle="Every pair and gold scored on five pillars: central bank and rate expectations, economic data and inflation, COT positioning, seasonality and retail sentiment. Best-aligned setups first." />
      <div className="space-y-6">
        <TopSetups editable />
        <Panel title="How the score works">
          <ul className="space-y-1.5 text-sm">
            <li><b>Central bank &amp; rate expectations ({w.central_bank ?? 30}%)</b>: hawkish statements and markets pricing hikes are bullish for a currency.</li>
            <li><b>Economic data &amp; inflation ({w.economic ?? 25}%)</b>: inflation above the central bank&rsquo;s target and data beating forecasts support hikes, which is bullish.</li>
            <li><b>COT positioning ({w.cot ?? 15}%)</b>: speculators building longs is bullish, but a crowded extreme (COT index above 90 or below 10) counts against the crowd.</li>
            <li><b>Seasonality ({w.seasonality ?? 15}%)</b>: how the pair has usually moved this month and over the next two weeks.</li>
            <li><b>Retail sentiment ({w.retail ?? 15}%)</b>: read contrarian; when most retail traders are long, it leans short. Comes from Myfxbook if an account is set, or tap &ldquo;Retail long %&rdquo; on a card to type it in (it counts for 3 days).</li>
          </ul>
          <p className="mt-3 text-sm text-muted">For a pair, each currency is scored and the quote is subtracted from the base. Grades need both size and agreement:
            A+ (score 60+, 80% of pillars agree, most data present), A (45+), B (30+), C (20+); otherwise &ldquo;No setup&rdquo;.
            For gold, a dovish Fed and soft US data count as bullish. The risk-on / risk-off mood is shown as context for yen, franc, Aussie, kiwi, rand, peso and gold trades.</p>
          <p className="mt-2 text-xs text-muted">Decision support only, not financial advice. Seasonality and positioning are tendencies; confirm with price before acting.</p>
        </Panel>
      </div>
    </>
  );
}
