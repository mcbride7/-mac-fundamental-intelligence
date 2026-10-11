"use client";

import Link from "next/link";
import { useState } from "react";

import Scenarios from "@/components/Scenarios";
import { Disclaimer, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { pair } from "@/lib/format";

const PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "USDZAR", "USDMXN", "EURGBP", "EURJPY"];

export default function ScenariosPage() {
  const [asset, setAsset] = useState("EURUSD");
  const { data, error, loading } = useApi<any>(`/api/scenarios/${asset}`);
  return (
    <>
      <PageTitle title="Scenarios" subtitle="Never one forecast: a base case, a bullish and a bearish alternative, and a risk scenario, each with what would confirm or invalidate it.">
        <label className="text-sm text-muted">Pair
          <select value={asset} onChange={(e) => setAsset(e.target.value)} className="ml-2 rounded border border-line bg-panel px-2 py-1 text-text">
            {PAIRS.map((p) => <option key={p} value={p}>{pair(p)}</option>)}
          </select></label>
      </PageTitle>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (
        <Panel title={pair(data.asset)} action={<Link href={`/analysis/${data.asset}`} className="text-sm text-verify">Full analysis</Link>}>
          <Scenarios scenarios={data.scenarios} />
          <p className="mt-4 text-xs text-muted">{data.probability_method}</p>
        </Panel>
      )}
      <Disclaimer />
    </>
  );
}
