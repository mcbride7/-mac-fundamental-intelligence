"use client";

import Link from "next/link";

import { ErrorBox, Loading, PageTitle, PolicyDial } from "@/components/ui";
import { useApi } from "@/lib/api";
import { date, num, signed, toneClass } from "@/lib/format";

export default function CentralBanks() {
  const { data, error, loading } = useApi<any[]>("/api/central-banks");
  return (
    <>
      <PageTitle title="Central banks" subtitle="Policy scores run from 0 (extremely dovish) to 100 (extremely hawkish). The thin mark shows the previous reading." />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data?.map((b) => (
            <Link key={b.code} href={`/central-banks/${b.code}`}
              className="rounded-md border border-line bg-panel p-4 hover:border-verify/60">
              <div className="flex items-baseline justify-between">
                <span className="text-lg font-medium">{b.name}</span>
                <span className="text-sm text-muted">{b.currency}</span>
              </div>
              <div className={`mt-1 text-sm ${toneClass(b.policy_bias)}`}>{b.policy_bias || "No score yet"}
                {b.score != null && <span className="text-muted"> — {num(b.score, 0)}/100</span>}</div>
              <div className="mt-4"><PolicyDial score={b.score} previous={b.score != null && b.shift != null ? b.score - b.shift : null} /></div>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-muted">Shift</dt><dd className={toneClass(b.shift)}>{signed(b.shift, 0)}</dd></div>
                <div><dt className="text-muted">Next meeting</dt><dd>{date(b.next_meeting)}</dd></div>
                <div><dt className="text-muted">Forecast accuracy</dt><dd>{num(b.forecast_accuracy, 0)}</dd></div>
              </dl>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
