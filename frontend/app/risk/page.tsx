"use client";

import RiskSentiment from "@/components/RiskSentiment";
import { PageTitle } from "@/components/ui";

export default function RiskPage() {
  return (
    <>
      <PageTitle title="Risk sentiment"
        subtitle="Is the market in a risk-on or risk-off mood today? Worked out from VIX, credit spreads, stocks, bonds, gold and currencies, updated every 6 hours." />
      <RiskSentiment />
    </>
  );
}
