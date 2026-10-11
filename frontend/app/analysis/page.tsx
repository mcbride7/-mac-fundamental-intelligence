"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Disclaimer, Empty, ErrorBox, GradeBadge, Loading, PageTitle } from "@/components/ui";
import { useApi } from "@/lib/api";
import { biasClass, dateTime, pair, signed } from "@/lib/format";

export default function Analysis() {
  const { data, error, loading } = useApi<any[]>("/api/trade-setups");
  const [q, setQ] = useState("");
  const router = useRouter();
  return (
    <>
      <PageTitle title="Fundamental analysis" subtitle="Every tracked pair, graded by how many independent factors agree. NO TRADE is the default when evidence is weak, conflicting, or important data is pending.">
        <form onSubmit={(e) => { e.preventDefault(); if (q.replace("/", "").length === 6) router.push(`/analysis/${q.replace("/", "").toUpperCase()}`); }}
          className="flex gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Any pair, e.g. GBP/JPY" aria-label="Pair"
            className="rounded border border-line bg-panel px-3 py-1.5 text-sm" />
          <button className="rounded bg-verify px-3 py-1.5 text-sm font-medium text-ink">Analyse</button>
        </form>
      </PageTitle>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !data?.length ? <Empty>No setups yet. Add data and run a full recompute from Data health.</Empty> : (
        <div className="overflow-x-auto rounded-md border border-line bg-panel">
          <table className="grid-table">
            <thead><tr><th>Pair</th><th>Grade</th><th>Direction</th><th>Confluence</th><th>Primary driver or reason</th><th>Data</th><th>Updated</th></tr></thead>
            <tbody>{data.map((s) => (
              <tr key={s.asset}>
                <td><Link href={`/analysis/${s.asset}`} className="font-medium hover:underline">{pair(s.asset)}</Link></td>
                <td><GradeBadge grade={s.grade} /></td>
                <td className={biasClass(s.direction)}>{s.direction === "NONE" ? "—" : s.direction}</td>
                <td className={biasClass(s.confluence > 0 ? "LONG" : s.confluence < 0 ? "SHORT" : "")}>{signed(s.confluence, 0)}</td>
                <td className="text-muted">{s.grade === "NO TRADE" ? s.no_trade_reasons?.[0] : s.primary_driver}</td>
                <td className="text-xs text-muted">{s.data_status}</td>
                <td className="text-xs text-muted">{dateTime(s.as_of)}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <Disclaimer />
    </>
  );
}
