"use client";

import { useState } from "react";

import { Button, Empty, ErrorBox, Loading, PageTitle, Panel, StatusBadge } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { dateTime, num, signed } from "@/lib/format";

export default function Markets() {
  const { data, error, loading, reload } = useApi<any[]>("/api/markets");
  const [sym, setSym] = useState("EURUSD");
  const [px, setPx] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const add = async () => { const r = await post("/api/markets/prices", [{ symbol: sym, price: +px }]); setMsg(r.recompute?.message); setPx(""); reload(); };
  return (
    <>
      <PageTitle title="Markets" subtitle="Latest prices and changes. Prices typed by hand are labelled unverified." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : (
        <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
          <Panel>
            {data?.every((d) => d.price === null) ? <Empty>No prices yet. Set TWELVEDATA_API_KEY or enter prices by hand.</Empty> : (
              <table className="grid-table">
                <thead><tr><th>Symbol</th><th>Class</th><th>Price</th><th>1 day</th><th>1 week</th><th>1 month</th><th>As of</th><th /></tr></thead>
                <tbody>{data?.filter((d) => d.price !== null).map((d) => (
                  <tr key={d.symbol}><td className="font-medium">{d.symbol}</td><td className="text-muted">{d.asset_class}</td>
                    <td>{num(d.price, d.price > 100 ? 2 : 4)}</td>
                    {["change_1d_pct", "change_1w_pct", "change_1m_pct"].map((k) => <td key={k} className={d[k] > 0 ? "text-dove" : d[k] < 0 ? "text-hawk" : ""}>{signed(d[k], 2, "%")}</td>)}
                    <td className="text-xs text-muted">{dateTime(d.ts)}</td>
                    <td>{d.input_method !== "automated" && <StatusBadge status={d.verification_status} />}</td></tr>))}</tbody>
              </table>
            )}
          </Panel>
          <Panel title="Enter a price">
            <label className="block text-sm">Symbol<input value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())}
              className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
            <label className="mt-3 block text-sm">Price<input inputMode="decimal" value={px} onChange={(e) => setPx(e.target.value)}
              className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
            <div className="mt-3"><Button onClick={add} disabled={!px}>Save price</Button></div>
            {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
          </Panel>
        </div>
      )}
    </>
  );
}
