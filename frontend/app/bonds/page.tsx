"use client";

import { useState } from "react";

import { Button, Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { num, signed } from "@/lib/format";

export default function Bonds() {
  const { data, error, loading, reload } = useApi<any[]>("/api/bonds");
  const div = useApi<any[]>("/api/policy-divergence");
  const [f, setF] = useState({ country: "DE", tenor: "2Y", yield_pct: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const add = async () => { const r = await post("/api/yields", [{ ...f, yield_pct: +f.yield_pct }]); setMsg(r.recompute?.message); reload(); div.reload(); };
  return (
    <>
      <PageTitle title="Bonds and policy divergence" subtitle="Government yields, curve shape, and the gap between central banks' policy scores." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <Panel title="Yields">
              {!data?.length ? <Empty>No yields yet. US yields arrive from FRED; enter others by hand.</Empty> : (
                <table className="grid-table">
                  <thead><tr><th>Country</th><th>2Y</th><th>5Y</th><th>10Y</th><th>30Y</th><th>2s10s</th><th>Curve</th></tr></thead>
                  <tbody>{data.map((r) => (
                    <tr key={r.country}><td className="font-medium">{r.country}</td>
                      {["2Y", "5Y", "10Y", "30Y"].map((t) => <td key={t}>{r[t] ? <>{num(r[t].yield, 2, "%")} <span className="text-xs text-muted">{signed(r[t].change_1w_bps, 0, " bp")}</span></> : "—"}</td>)}
                      <td>{signed(r.slope_2s10s_bps, 0, " bp")}</td><td>{r.shape ? r.shape.toLowerCase() : "—"}</td></tr>))}</tbody>
                </table>
              )}
            </Panel>
            <Panel title="Enter a yield">
              <div className="grid grid-cols-3 gap-2">
                <input aria-label="Country" value={f.country} onChange={(e) => setF({ ...f, country: e.target.value.toUpperCase() })} className="rounded border border-line bg-ink px-2 py-1.5 text-sm" />
                <select aria-label="Tenor" value={f.tenor} onChange={(e) => setF({ ...f, tenor: e.target.value })} className="rounded border border-line bg-ink px-2 py-1.5 text-sm">
                  {["2Y", "5Y", "10Y", "30Y"].map((t) => <option key={t}>{t}</option>)}</select>
                <input aria-label="Yield %" placeholder="%" inputMode="decimal" value={f.yield_pct} onChange={(e) => setF({ ...f, yield_pct: e.target.value })} className="rounded border border-line bg-ink px-2 py-1.5 text-sm" />
              </div>
              <div className="mt-3"><Button onClick={add} disabled={!f.yield_pct}>Save yield</Button></div>
              {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
            </Panel>
          </div>
          <Panel title="Policy divergence">
            {!div.data?.length ? <Empty>Divergence appears once two central banks have policy scores.</Empty> : (
              <table className="grid-table">
                <thead><tr><th>Banks</th><th>Score gap</th><th>Rate gap</th><th>2Y yield gap</th><th>Implication</th></tr></thead>
                <tbody>{div.data.map((d) => (
                  <tr key={d.pair}><td className="font-medium">{d.pair}</td><td>{signed(d.divergence, 0)}</td>
                    <td>{signed(d.details.differences.policy_rate, 2, " pp")}</td><td>{signed(d.details.differences.yield_2y, 2, " pp")}</td>
                    <td className="text-muted">{d.implication}</td></tr>))}</tbody>
              </table>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
