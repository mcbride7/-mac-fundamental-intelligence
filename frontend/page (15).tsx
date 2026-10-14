"use client";

import Link from "next/link";
import { useState } from "react";

import { Empty, ErrorBox, Loading, PageTitle, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/api";
import { num, signed, toneClass } from "@/lib/format";

const IMPORTANCE: Record<string, { mark: string; label: string; cls: string }> = {
  high: { mark: "●", label: "High", cls: "text-hawk" },
  medium: { mark: "●", label: "Medium", cls: "text-amber" },
  low: { mark: "●", label: "Low", cls: "text-dove" },
};

export default function Calendar() {
  const [f, setF] = useState({ currency: "", importance: "", category: "", status: "", days: "14" });
  const today = new Date();
  const end = new Date(today.getTime() + +f.days * 86400000).toISOString().slice(0, 10);
  const start = new Date(today.getTime() - 7 * 86400000).toISOString().slice(0, 10);
  const qs = new URLSearchParams({ start, end, ...Object.fromEntries(Object.entries(f).filter(([k, v]) => v && k !== "days")) });
  const { data, error, loading } = useApi<any[]>(`/api/economic-calendar?${qs}`);
  const sel = (k: keyof typeof f, opts: [string, string][]) => (
    <label className="text-sm text-muted">{k === "days" ? "Range" : k.replace(/^\w/, (c) => c.toUpperCase())}
      <select value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}
        className="ml-2 rounded border border-line bg-panel px-2 py-1 text-text">
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
  return (
    <>
      <PageTitle title="Economic calendar" subtitle="Market forecast, central-bank projection and actual side by side. Releases that are overdue can be filled in by hand." />
      <div className="mb-4 flex flex-wrap gap-4">
        {sel("currency", [["", "All"], ...["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY"].map((c) => [c, c] as [string, string])])}
        {sel("importance", [["", "All"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]])}
        {sel("category", [["", "All"], ["inflation", "Inflation"], ["employment", "Employment"], ["growth", "Growth"], ["business", "Business"], ["consumers", "Consumers"], ["monetary_policy", "Monetary policy"]])}
        {sel("status", [["", "All"], ["missing", "Missing"], ["unverified", "Unverified"], ["user_confirmed", "User-confirmed"], ["verified", "Verified"], ["scheduled", "Scheduled"]])}
        {sel("days", [["7", "Next 7 days"], ["14", "Next 14 days"], ["30", "Next 30 days"]])}
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !data?.length ? (
        <Empty href="/data-input" cta="Import a calendar">No events in this range. Import a calendar via Finnhub, a CSV, or a screenshot of any calendar.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-panel">
          <table className="grid-table">
            <thead><tr><th>Date</th><th>Time (UTC)</th><th>Ccy</th><th>Event</th><th></th><th>Previous</th><th>Forecast</th>
              <th>CB projection</th><th>Actual</th><th>Surprise</th><th>Data</th></tr></thead>
            <tbody>
              {data.map((e) => {
                const imp = IMPORTANCE[e.importance] || IMPORTANCE.low;
                const u = e.unit === "%" ? "%" : e.unit === "k" ? "k" : "";
                return (
                  <tr key={e.event_id}>
                    <td className="whitespace-nowrap">{e.date}</td><td>{e.time}</td><td>{e.currency}</td>
                    <td>{e.release_id ? <Link href={`/calendar/${e.event_id}`} className="hover:underline">{e.event}</Link> : e.event}
                      <span className="block text-xs text-muted">{e.reference_period}</span></td>
                    <td className={imp.cls} title={`${imp.label} importance`}><span aria-hidden>{imp.mark}</span><span className="sr-only">{imp.label}</span></td>
                    <td>{num(e.previous, 2, u)}</td><td>{num(e.market_forecast, 2, u)}</td><td>{num(e.central_bank_projection, 1, u)}</td>
                    <td className="font-medium">{num(e.actual, 2, u)}</td>
                    <td className={toneClass(e.surprise_class)} title={e.surprise_class}>{signed(e.surprise, 2)}</td>
                    <td>{e.needs_manual_input ? (
                      <Link href={`/data-input?indicator=${e.indicator}&period=${e.reference_period}`}
                        className="whitespace-nowrap rounded border border-hawk/70 px-2 py-0.5 text-xs text-hawk hover:bg-hawk/10">Provide data</Link>
                    ) : <StatusBadge status={e.data_status} title={e.badge} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
