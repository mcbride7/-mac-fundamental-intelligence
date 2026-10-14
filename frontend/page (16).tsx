"use client";

import CurrencyMatrix from "@/components/CurrencyMatrix";
import { ErrorBox, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { biasClass, num, signed } from "@/lib/format";

const COMPONENTS = ["growth", "inflation", "employment", "central_bank", "interest_rates", "bond_yields", "economic_surprises", "risk_sentiment"];

export default function Currencies() {
  const { data, error, loading } = useApi<any>("/api/currencies");
  return (
    <>
      <PageTitle title="Currencies" subtitle="Fundamental strength per currency. Each component scores from −3 to +3; blanks mean the input is not available yet." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (
        <div className="space-y-6">
          <Panel title="Fundamental scores">
            <div className="overflow-x-auto">
              <table className="grid-table">
                <thead><tr><th>Currency</th>{COMPONENTS.map((c) => <th key={c} className="capitalize">{c.replaceAll("_", " ")}</th>)}<th>Total</th><th>Bias</th><th>Evidence</th></tr></thead>
                <tbody>{data.scores.map((s: any) => (
                  <tr key={s.currency}>
                    <td className="font-medium">{s.currency}</td>
                    {COMPONENTS.map((c) => <td key={c} className={s.components[c] > 0 ? "text-dove" : s.components[c] < 0 ? "text-hawk" : "text-muted"}>
                      {s.components[c] === undefined ? "" : signed(s.components[c], 0)}</td>)}
                    <td className="font-medium">{signed(s.total, 0)}</td>
                    <td className={biasClass(s.bias)}>{s.bias}</td>
                    <td className="text-muted">{num(s.evidence_quality, 0)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          </Panel>
          <Panel title="Relative strength"><CurrencyMatrix heatmap={data.heatmap} /></Panel>
        </div>
      )}
    </>
  );
}
