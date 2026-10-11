"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, Empty, ErrorBox, GradeBadge, PageTitle, Panel } from "@/components/ui";
import { del, post, useApi } from "@/lib/api";
import { biasClass, pair, signed } from "@/lib/format";

export default function Watchlist() {
  const { data, error, reload } = useApi<any[]>("/api/watchlist");
  const [asset, setAsset] = useState("");
  const add = async () => { await post("/api/watchlist", { asset }); setAsset(""); reload(); };
  return (
    <>
      <PageTitle title="Watchlist" subtitle="You get an alert whenever the bias or grade of a watched pair changes." />
      <ErrorBox error={error} />
      <Panel>
        <div className="mb-4 flex gap-2">
          <input value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} placeholder="e.g. USD/ZAR" aria-label="Pair"
            className="rounded border border-line bg-ink px-3 py-1.5 text-sm" />
          <Button onClick={add} disabled={asset.replace("/", "").length !== 6}>Add pair</Button>
        </div>
        {!data?.length ? <Empty>Nothing on your watchlist yet.</Empty> : (
          <table className="grid-table">
            <thead><tr><th>Pair</th><th>Grade</th><th>Direction</th><th>Confluence</th><th>Data</th><th /></tr></thead>
            <tbody>{data.map((w) => (
              <tr key={w.id}><td><Link href={`/analysis/${w.asset}`} className="font-medium hover:underline">{pair(w.asset)}</Link></td>
                <td><GradeBadge grade={w.grade} /></td><td className={biasClass(w.direction)}>{w.direction || "—"}</td>
                <td>{signed(w.confluence, 0)}</td><td className="text-xs text-muted">{w.data_status || "Not analysed yet"}</td>
                <td><button className="text-xs text-hawk" onClick={async () => { await del(`/api/watchlist/${w.id}`); reload(); }}>Remove</button></td></tr>))}</tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
