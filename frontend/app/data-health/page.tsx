"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, Empty, ErrorBox, Loading, PageTitle, Panel, StatusBadge } from "@/components/ui";
import { post, put, useApi } from "@/lib/api";
import { dateTime } from "@/lib/format";

const SRC_CLS: Record<string, string> = { OK: "text-dove", DELAYED: "text-amber", STALE: "text-amber", FAILED: "text-hawk",
  UNKNOWN: "text-muted" };

function ConfirmForm({ releaseId, onDone }: { releaseId: number; onDone: (msg: string) => void }) {
  const [basis, setBasis] = useState("OFFICIAL_SOURCE");
  const [name, setName] = useState("");
  const [link, setLink] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    try {
      const r = await post(`/api/data/${releaseId}/confirm`, { basis, source_name: name || null, source_url: link || null });
      onDone(`${r.badge}. ${r.recompute?.message || ""}`);
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <div className="mt-2 grid gap-2 rounded border border-line bg-ink p-3 sm:grid-cols-[12rem_1fr_1fr_auto]">
      <select value={basis} onChange={(e) => setBasis(e.target.value)} className="rounded border border-line bg-panel px-2 py-1 text-sm"
        aria-label="Confirmed against">
        <option value="OFFICIAL_SOURCE">Official source</option>
        <option value="SECONDARY_SOURCE">Secondary source</option>
        <option value="NO_SOURCE">No source</option>
      </select>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Source name" aria-label="Source name"
        className="rounded border border-line bg-panel px-2 py-1 text-sm" />
      <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Link (optional)" aria-label="Source link"
        className="rounded border border-line bg-panel px-2 py-1 text-sm" />
      <Button onClick={go}>Confirm</Button>
      {err && <p className="text-sm text-hawk sm:col-span-4">{err}</p>}
    </div>
  );
}

export default function DataHealth() {
  const { data: h, error, loading, reload } = useApi<any>("/api/data-health");
  const recs = useApi<any[]>("/api/reconciliation");
  const trust = useApi<any>("/api/settings/trust");
  const [open, setOpen] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (key: string) => { const r = await post(`/api/sources/${key}/run`); setMsg(`${key}: ${r.status}${r.error ? ` — ${r.error}` : ""}`); reload(); };
  const verify = async () => { const r = await post("/api/data-health/verify-now"); setMsg(`Verification run: ${JSON.stringify(r)}`); reload(); recs.reload(); };
  const resolve = async (id: number, resolution: string) => { const r = await post(`/api/reconciliation/${id}/resolve`, { resolution }); setMsg(r.recompute?.message); recs.reload(); reload(); };
  const saveTrust = async (patch: any) => { trust.setData(await put("/api/settings/trust", patch)); };
  if (loading && !h) return <Loading />;
  return (
    <>
      <PageTitle title="Data health" subtitle="Every feed, every missing release, and every value that still needs verification. Data failure never stops the analysis: fill gaps here and the platform re-analyses immediately.">
        <div className="flex gap-2"><Button kind="ghost" onClick={verify}>Check official sources now</Button>
          <Link href="/data-input" className="rounded bg-verify px-3 py-1.5 text-sm font-medium text-ink">Add data</Link></div>
      </PageTitle>
      <ErrorBox error={error} />
      {msg && <p className="mb-4 rounded border border-line bg-panel px-3 py-2 text-sm">{msg}</p>}
      {h && (
        <div className="space-y-6">
          <Panel title="Releases that are overdue">
            {h.missing_scheduled.length === 0 ? <p className="text-sm text-muted">No overdue releases.</p> : (
              <ul className="space-y-3">{h.missing_scheduled.map((m: any) => (
                <li key={m.event_id} className="flex flex-wrap items-center justify-between gap-3 text-sm">
                  <span>{m.message}</span>
                  <span className="flex gap-2">
                    {["Upload screenshot", "Upload PDF", "Type value"].map((l) => (
                      <Link key={l} href={`/data-input?indicator=${m.indicator_code}&period=${m.reference_period}`}
                        className="rounded border border-line px-2 py-1 text-xs hover:bg-panel-2">{l}</Link>))}
                  </span>
                </li>))}</ul>
            )}
          </Panel>

          <Panel title={`Conflicts with official data (${h.conflicts})`}>
            {!recs.data?.length ? <p className="text-sm text-muted">No open conflicts.</p> : (
              <table className="grid-table">
                <thead><tr><th>Indicator</th><th>Period</th><th>Your value</th><th>Official value</th><th>Source</th><th /></tr></thead>
                <tbody>{recs.data.map((r) => (
                  <tr key={r.id}><td>{r.name}</td><td>{r.period}</td><td>{r.manual_value}</td><td>{r.official_value}</td><td>{r.official_source}</td>
                    <td className="flex gap-2"><Button onClick={() => resolve(r.id, "use_official")}>Use official</Button>
                      <Button kind="ghost" onClick={() => resolve(r.id, "keep_manual")}>Keep mine</Button></td></tr>))}</tbody>
              </table>
            )}
          </Panel>

          <Panel title={`Awaiting verification (${h.pending_verification.length})`}>
            {h.pending_verification.length === 0 ? <p className="text-sm text-muted">Every manual value has been verified.</p> : (
              <ul className="divide-y divide-line/60">{h.pending_verification.map((p: any) => (
                <li key={p.release_id} className="py-2.5 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span>{p.name} <span className="text-muted">{p.period}</span>: <span className="font-medium">{p.actual}</span>
                      <span className="ml-2 text-xs text-muted">via {p.input_method}{p.last_attempt ? `, last check ${dateTime(p.last_attempt.attempted_at)}: ${p.last_attempt.outcome.replace("_", " ")}` : ", not yet checked"}</span></span>
                    <span className="flex items-center gap-2"><StatusBadge status={p.status} title={p.badge} />
                      {p.can_confirm && <Button kind="ghost" onClick={() => setOpen(open === p.release_id ? null : p.release_id)}>Confirm data is correct</Button>}</span>
                  </div>
                  {p.last_attempt?.outcome === "unreachable" && <p className="mt-1 text-xs text-amber">Could not verify against the official source (unreachable). You can confirm it yourself.</p>}
                  {open === p.release_id && <ConfirmForm releaseId={p.release_id} onDone={(m) => { setMsg(m); setOpen(null); reload(); }} />}
                </li>))}</ul>
            )}
          </Panel>

          <Panel title="Sources">
            <div className="overflow-x-auto">
              <table className="grid-table">
                <thead><tr><th>Source</th><th>Tier</th><th>Status</th><th>Last success</th><th>Expected next</th><th>Retries</th><th>Last error</th><th /></tr></thead>
                <tbody>{h.sources.map((s: any) => (
                  <tr key={s.key}>
                    <td>{s.name}</td><td>{s.tier}</td><td className={SRC_CLS[s.status] || ""}>{s.status}</td>
                    <td>{dateTime(s.last_success_at)}</td><td>{dateTime(s.expected_next_at)}</td><td>{s.retries}</td>
                    <td className="max-w-xs truncate text-muted" title={s.last_error || ""}>{s.last_error || ""}</td>
                    <td className="whitespace-nowrap">
                      {["fred", "fed_rss", "ecb_rss", "boe_rss", "twelvedata", "finnhub"].includes(s.key) && <button onClick={() => run(s.key)} className="mr-3 text-xs text-verify">Run now</button>}
                      {s.needs_manual_input && <Link href="/data-input" className="text-xs text-hawk">Provide data manually</Link>}
                    </td>
                  </tr>))}</tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Trust settings">
            {trust.data ? (
              <div className="space-y-3 text-sm">
                <label className="flex items-center gap-2"><input type="checkbox" checked={trust.data.auto_confirm_typed}
                  onChange={(e) => saveTrust({ auto_confirm_typed: e.target.checked })} />Auto-confirm data I type myself</label>
                <label className="flex flex-wrap items-center gap-2"><input type="checkbox" checked={trust.data.auto_confirm_official_screenshots}
                  onChange={(e) => saveTrust({ auto_confirm_official_screenshots: e.target.checked })} />
                  Auto-confirm screenshots of official sources when extraction confidence is at least
                  <input type="number" min={50} max={100} defaultValue={trust.data.auto_confirm_threshold}
                    onBlur={(e) => saveTrust({ auto_confirm_threshold: +e.target.value })} className="w-16 rounded border border-line bg-ink px-1.5 py-0.5" />%</label>
                <label className="block">Sources I always trust (comma-separated)
                  <input defaultValue={(trust.data.trusted_sources || []).join(", ")}
                    onBlur={(e) => saveTrust({ trusted_sources: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                    className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
                <p className="text-xs text-muted">Auto-confirmations are logged and shown with the same “user-confirmed” label as manual ones.</p>
              </div>
            ) : <Empty>Loading settings…</Empty>}
          </Panel>
        </div>
      )}
    </>
  );
}
