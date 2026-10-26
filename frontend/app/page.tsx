"use client";

import Link from "next/link";

import CurrencyMatrix from "@/components/CurrencyMatrix";
import SetupsTable from "@/components/SetupsTable";
import TopSetups from "@/components/TopSetups";
import { Disclaimer, Empty, ErrorBox, GradeBadge, Loading, Panel, PolicyDial, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/api";
import { biasClass, date, dateTime, num, pair, signed, toneClass } from "@/lib/format";

export default function Home() {
  const { data: d, error, loading } = useApi<any>("/api/dashboard");
  if (loading && !d) return <Loading what="Loading the macro picture" />;
  if (error) return <ErrorBox error={error} />;
  if (!d) return null;
  const r = d.regime;
  return (
    <div className="space-y-6">
      <section aria-labelledby="top-setups" className="min-w-0 rounded-md border border-line bg-panel p-4">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h1 id="top-setups" className="text-2xl font-semibold">Top setups</h1>
          <Link href="/setups" className="text-sm text-verify">Five-pillar cards and how the scores work</Link>
        </div>
        <p className="mb-3 text-sm text-muted">Trend, seasonality, COT and crowd sentiment, plus central bank tone, rate expectations and every economic release: each scored −2 to +2 and added up. Strongest first.</p>
        <SetupsTable limit={20} />
      </section>

      <Panel title="Setup cards (five-pillar view)" collapseId="home-setup-cards" startCollapsed>
        <TopSetups limit={6} />
      </Panel>

      <Panel title="Macro picture" collapseId="home-macro-picture">
        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div>
          <p className="text-sm text-muted">Global macro regime{r ? `, ${dateTime(r.as_of)}` : ""}</p>
          <p className="mt-1 font-serif text-3xl leading-tight sm:text-4xl">
            {r ? r.primary.toLowerCase().replace(/^\w/, (c: string) => c.toUpperCase()) : "Not enough data yet"}
          </p>
          {r && (
            <p className="mt-1 text-sm text-muted">
              {r.secondary ? `${r.secondary.toLowerCase()}, ` : ""}confidence {num(r.confidence, 0)}%
            </p>
          )}
          <p className="note mt-4 text-[1.02rem]">{d.ai_summary}</p>
        </div>
        <Panel title="Data health" collapseId="home-data-health" action={<Link href="/data-health" className="text-sm text-verify">Open</Link>}>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-muted">Status</dt><dd className="font-medium">{d.data_health.overall}</dd></div>
            <div><dt className="text-muted">Missing releases</dt><dd>{d.data_health.missing_scheduled}</dd></div>
            <div><dt className="text-muted">Unverified values</dt><dd>{d.data_health.unverified}</dd></div>
            <div><dt className="text-muted">Confirmed by you, awaiting source</dt><dd>{d.data_health.user_confirmed_awaiting}</dd></div>
            <div><dt className="text-muted">Conflicts</dt><dd className={d.data_health.conflicts ? "text-hawk" : ""}>{d.data_health.conflicts}</dd></div>
            <div><dt className="text-muted">Feeds down</dt><dd>{d.data_health.failing_sources.join(", ") || "None"}</dd></div>
          </dl>
          {(d.data_health.missing_scheduled > 0 || d.data_health.failing_sources.length > 0) && (
            <Link href="/data-input" className="mt-4 inline-block rounded bg-verify px-3 py-1.5 text-sm font-medium text-ink">
              Provide the missing data
            </Link>
          )}
        </Panel>
        </div>
      </Panel>



      <Panel title="Central banks" collapseId="home-central-banks" action={<Link href="/central-banks" className="text-sm text-verify">All banks</Link>}>
        <div className="overflow-x-auto">
          <table className="grid-table">
            <thead><tr><th>Bank</th><th>Policy bias</th><th className="w-48">Hawkish / dovish</th><th>Shift</th>
              <th>Next meeting</th><th>Expected</th><th>Forecast accuracy</th></tr></thead>
            <tbody>
              {d.central_bank_heatmap.map((b: any) => (
                <tr key={b.code}>
                  <td><Link href={`/central-banks/${b.code}`} className="font-medium hover:underline">{b.name}</Link>
                    <span className="ml-2 text-xs text-muted">{b.currency}</span></td>
                  <td className={toneClass(b.policy_bias)}>{b.policy_bias || "—"}</td>
                  <td><PolicyDial score={b.score} compact /></td>
                  <td className={toneClass(b.shift)}>{signed(b.shift, 0)}</td>
                  <td>{date(b.next_meeting)}</td>
                  <td>{b.expected_action || "—"}</td>
                  <td>{num(b.forecast_accuracy, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Fundamental setups (rates and macro only)" collapseId="home-fundamental-setups-rates-and-macro-only" action={<Link href="/analysis" className="text-sm text-verify">All assets</Link>}>
          {d.top_setups.length === 0 ? <Empty>No setups computed yet.</Empty> : (
            <table className="grid-table">
              <thead><tr><th>Asset</th><th>Grade</th><th>Direction</th><th>Confluence</th><th>Driver / reason</th></tr></thead>
              <tbody>
                {d.top_setups.map((s: any) => (
                  <tr key={s.asset}>
                    <td><Link href={`/analysis/${s.asset}`} className="font-medium hover:underline">{pair(s.asset)}</Link></td>
                    <td><GradeBadge grade={s.grade} /></td>
                    <td className={biasClass(s.direction)}>{s.direction === "NONE" ? "—" : s.direction}</td>
                    <td className={biasClass(s.confluence > 0 ? "LONG" : s.confluence < 0 ? "SHORT" : "")}>{signed(s.confluence, 0)}</td>
                    <td className="text-muted">{s.grade === "NO TRADE" ? s.no_trade_reasons?.[0] : s.primary_driver}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title="Currency strength" collapseId="home-currency-strength" action={<Link href="/currencies" className="text-sm text-verify">Scores</Link>}>
          <CurrencyMatrix heatmap={d.currency_strength} compact />
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Panel title="Biggest economic surprises" collapseId="home-biggest-economic-surprises">
          {d.biggest_surprises.length === 0 ? <Empty href="/data-input" cta="Add a release">No releases with a forecast yet.</Empty> : (
            <ul className="space-y-2 text-sm">
              {d.biggest_surprises.map((s: any) => (
                <li key={s.release_id} className="flex items-start justify-between gap-3">
                  <div>
                    <div>{s.indicator} <span className="text-muted">{s.period}</span></div>
                    <div className="text-xs text-muted">{num(s.actual, 2)} vs {num(s.consensus, 2)} expected</div>
                  </div>
                  <div className="text-right">
                    <div className={toneClass(s.direction)}>{signed(s.z, 1)}σ</div>
                    <StatusBadge status={s.status} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Central-bank forecast misses" collapseId="home-central-bank-forecast-misses">
          {d.forecast_errors.length === 0 ? <Empty>No projections compared yet.</Empty> : (
            <ul className="space-y-2 text-sm">
              {d.forecast_errors.map((e: any, i: number) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>{e.indicator} <span className="text-muted">{e.period}</span><span className="block text-xs text-muted">{e.classification}</span></span>
                  <span className="text-right">{num(e.cb_projection, 1)} → {num(e.actual, 1)}
                    <span className={`block text-xs ${toneClass(e.error)}`}>{signed(e.error, 2)} pp</span></span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Latest alerts" collapseId="home-latest-alerts" action={<Link href="/alerts" className="text-sm text-verify">All</Link>}>
          {d.alerts.length === 0 ? <Empty>No alerts.</Empty> : (
            <ul className="space-y-2.5 text-sm">
              {d.alerts.map((a: any) => (
                <li key={a.id}>
                  <span className={a.severity === "HIGH" || a.severity === "CRITICAL" ? "text-hawk" : "text-amber"}>●</span>{" "}
                  {a.title}<span className="block text-xs text-muted">{dateTime(a.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Rates and market pricing" collapseId="home-rates-and-market-pricing">
          <table className="grid-table">
            <thead><tr><th>Bank</th><th>Rate</th><th>Cut</th><th>Hold</th><th>Hike</th><th>Implied 12m</th></tr></thead>
            <tbody>
              {d.rates.map((r: any) => (
                <tr key={r.central_bank}>
                  <td>{r.central_bank}</td><td>{num(r.policy_rate, 2, "%")}</td>
                  <td>{num(r.prob_cut, 0, "%")}</td><td>{num(r.prob_hold, 0, "%")}</td><td>{num(r.prob_hike, 0, "%")}</td>
                  <td className={toneClass(r.implied_12m_change_bps)}>{signed(r.implied_12m_change_bps, 0, " bp")}
                    {r.implied_is_proxy && <span className="ml-1 text-xs text-muted" title="2Y yield minus policy rate">proxy</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Is the market wrong?" collapseId="home-is-the-market-wrong" action={<Link href="/research" className="text-sm text-verify">Research</Link>}>
          {d.market_wrong.length === 0 ? (
            <p className="text-sm text-muted">No significant disconnect between data, policy signals and market pricing.</p>
          ) : (
            <ul className="space-y-3 text-sm">
              {d.market_wrong.map((m: any) => (
                <li key={m.central_bank}><span className="font-medium">{m.title}</span>
                  <p className="text-muted">{m.body}</p></li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <Disclaimer />
    </div>
  );
}
