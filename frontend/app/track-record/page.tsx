"use client";

import { Empty, ErrorBox, GradeBadge, Loading, PageTitle, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { dateTime, num, pair, signed } from "@/lib/format";

type Row = { grade: string; signals: number; [k: string]: number | string | null };

const pct = (v: unknown) => (typeof v === "number" ? `${v.toFixed(0)}%` : "—");
const moveCls = (v: number | null) => (v === null || v === undefined ? "text-muted" : v > 0 ? "text-dove" : v < 0 ? "text-hawk" : "");

export default function TrackRecord() {
  const { data, error, loading } = useApi<any>("/api/track-record");
  return (
    <>
      <PageTitle title="Track record"
        subtitle="Every graded call the app makes, and what the price did 1, 5 and 20 days later. Moves are in the call's direction, before costs." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : data && (
        <>
          {!data.enough_data && (
            <p className="mb-4 rounded border border-amber/50 bg-amber/10 px-3 py-2 text-sm">
              Only {data.evaluated_5d} call{data.evaluated_5d === 1 ? "" : "s"} have a 5-day result so far. Treat the grades as
              research, not signals, until there are at least 30.
            </p>
          )}
          <Panel title="By grade">
            <div className="overflow-x-auto">
              <table className="grid-table">
                <thead>
                  <tr><th>Grade</th><th>Calls</th>
                    <th>Right after 1 day</th><th>Avg move 1d</th>
                    <th>Right after 5 days</th><th>Avg move 5d</th>
                    <th>Right after 20 days</th><th>Avg move 20d</th></tr>
                </thead>
                <tbody>
                  {data.by_grade.map((g: Row) => (
                    <tr key={g.grade}>
                      <td><GradeBadge grade={g.grade} /></td><td>{g.signals}</td>
                      {[1, 5, 20].map((d) => (
                        <FragmentCells key={d} hit={g[`hit_rate_${d}d`]} n={g[`n_${d}d`]} avg={g[`avg_move_${d}d`] as number | null} />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted">{data.note}</p>
          </Panel>
          <div className="mt-6">
            <Panel title="Calls">
              {!data.recent.length ? (
                <Empty>No graded calls yet. They are recorded automatically each time the analysis gives a pair an A+, A, B or C.</Empty>
              ) : (
                <div className="overflow-x-auto">
                  <table className="grid-table">
                    <thead><tr><th>Given</th><th>Pair</th><th>Call</th><th>Grade</th><th>Entry</th><th>1 day</th><th>5 days</th><th>20 days</th><th></th></tr></thead>
                    <tbody>
                      {data.recent.map((r: any) => (
                        <tr key={r.id}>
                          <td className="whitespace-nowrap">{dateTime(r.opened_at)}</td><td>{pair(r.asset)}</td>
                          <td>{r.direction === "LONG" ? "Buy" : "Sell"}</td><td><GradeBadge grade={r.grade} /></td>
                          <td>{num(r.entry_price, 4)}</td>
                          <td className={moveCls(r.ret_1d)}>{signed(r.ret_1d, 2, "%")}</td>
                          <td className={moveCls(r.ret_5d)}>{signed(r.ret_5d, 2, "%")}</td>
                          <td className={moveCls(r.ret_20d)}>{signed(r.ret_20d, 2, "%")}</td>
                          <td className="text-xs text-muted">{r.open ? "current" : "replaced"}{r.note ? ` · ${r.note}` : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

function FragmentCells({ hit, n, avg }: { hit: unknown; n: unknown; avg: number | null }) {
  return (
    <>
      <td>{pct(hit)} <span className="text-xs text-muted">({typeof n === "number" ? n : 0})</span></td>
      <td className={moveCls(avg)}>{signed(avg, 2, "%")}</td>
    </>
  );
}
