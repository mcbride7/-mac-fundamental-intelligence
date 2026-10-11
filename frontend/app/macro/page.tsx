"use client";

import { Empty, ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { dateTime, num } from "@/lib/format";

export default function Macro() {
  const { data, error, loading } = useApi<any>("/api/macro/regime");
  const eco = useApi<any[]>("/api/economic-data");
  const c = data?.current;
  return (
    <>
      <PageTitle title="Macro regime" subtitle="Inflation trend, growth, risk appetite and central-bank liquidity, combined into one regime reading." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !c ? <Empty>No regime computed yet.</Empty> : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Current regime">
            <p className="font-serif text-2xl">{c.primary}</p>
            <p className="text-sm text-muted">{c.secondary || "No clear risk signal"}, confidence {num(c.confidence, 0)}%</p>
            <ul className="note mt-3 list-disc pl-5 text-sm">{c.explanation.map((e: string) => <li key={e}>{e}</li>)}</ul>
            <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">{Object.entries(c.signals).map(([k, v]: any) => (
              <div key={k}><dt className="text-xs capitalize text-muted">{k}</dt><dd>{v}</dd></div>))}</dl>
          </Panel>
          <Panel title="Regime history">
            <ul className="space-y-1 text-sm">{data.history.map((h: any) => (
              <li key={h.id} className="flex justify-between"><span>{h.primary}{h.secondary ? `, ${h.secondary.toLowerCase()}` : ""}</span>
                <span className="text-muted">{dateTime(h.as_of)}</span></li>))}</ul>
          </Panel>
        </div>
      )}
      <Panel title="Latest economic data" className="mt-6">
        <div className="overflow-x-auto">
          <table className="grid-table">
            <thead><tr><th>Indicator</th><th>Country</th><th>Category</th><th>Latest</th><th>Period</th><th>Data</th></tr></thead>
            <tbody>{eco.data?.filter((e) => e.latest !== null).map((e) => (
              <tr key={e.code}><td>{e.name}</td><td>{e.country}</td><td className="text-muted">{e.category}</td>
                <td>{num(e.latest, 2)}{e.unit === "%" ? "%" : e.unit === "k" ? "k" : ""}</td><td>{e.period}</td><td className="text-xs text-muted">{e.badge}</td></tr>))}</tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
