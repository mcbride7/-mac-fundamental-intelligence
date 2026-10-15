"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { Button, ErrorBox, PageTitle, Panel } from "@/components/ui";
import { patch, post, useApi } from "@/lib/api";

const FIELDS: Record<string, string[]> = {
  economic_release: ["indicator_code", "reference_period", "actual", "consensus", "previous", "unit", "release_date"],
  cb_projection: ["central_bank_code", "variable", "target_period", "value", "vintage_date"],
  cb_statement: ["central_bank_code", "published_date", "doc_type"],
  speech: ["central_bank_code", "published_date"],
  rate_expectation: ["central_bank_code", "prob_cut", "prob_hold", "prob_hike"],
  market_price: ["symbol", "price"],
  bond_yield: ["country", "tenor", "yield_pct"],
};
const NUMERIC = new Set(["actual", "consensus", "previous", "value", "prob_cut", "prob_hold", "prob_hike", "price", "yield_pct"]);

// What will happen to a row when it is saved, worked out from its warnings.
function rowState(p: any): "ready" | "upcoming" | "untracked" | "fix" | "override" {
  const errs = (p.warnings || []).filter((w: any) => w.severity === "error").map((w: any) => w.code);
  const has = (v: any) => v !== null && v !== undefined && v !== "";
  if (p.kind === "economic_release" && !has(p.fields.actual) && has(p.fields.indicator_code) && has(p.fields.reference_period)
      && (has(p.fields.consensus) || has(p.fields.previous))
      && errs.every((c: string) => c === "MISSING_ACTUAL" || c === "MISSING_FIELD")) return "upcoming";
  if (p.kind === "economic_release" && !has(p.fields.indicator_code)) return "untracked";
  if (errs.some((c: string) => ["MISSING_FIELD", "UNMAPPED_INDICATOR", "MISSING_ACTUAL", "MISSING_PERIOD"].includes(c))) return "fix";
  if (errs.length) return "override";
  return "ready";
}

const STATE_LABEL: Record<string, [string, string]> = {
  ready: ["Ready", "text-dove"],
  upcoming: ["Upcoming: saved to the calendar with forecast and previous", "text-verify"],
  untracked: ["Not an indicator the app tracks: choose one or it will be skipped", "text-muted"],
  fix: ["Needs a correction before it can be saved", "text-amber"],
  override: ["Looks unusual: fix it or give a reason", "text-amber"],
};

function confClass(c?: number) {
  if (c === undefined) return "border-line";
  if (c < 70) return "border-amber bg-amber/10";
  return "border-line";
}

export default function Review({ sub: initial, preview, onReset }: { sub: any; preview: string | null; onReset: () => void }) {
  const [sub, setSub] = useState(initial);
  const { data: catalogue } = useApi<any[]>("/api/indicators/catalogue");
  const pending = useRef<Set<Promise<unknown>>>(new Set());
  const [include, setInclude] = useState<Record<number, boolean>>(() =>
    Object.fromEntries(initial.points.map((p: any) => [p.id, rowState(p) !== "untracked"])));
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [confirm, setConfirm] = useState<{ on: boolean; basis: string; source_name: string; source_url: string }>({
    on: false, basis: "OFFICIAL_SOURCE", source_name: "", source_url: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const edit = async (pid: number, key: string, raw: string) => {
    const value = NUMERIC.has(key) ? (raw.trim() === "" ? null : Number(raw.replace(/[%\s]/g, "").replace(",", "."))) : raw;
    const req = patch(`/api/manual/points/${pid}`, { fields: { [key]: value } });
    pending.current.add(req);
    try {
      const p = await req;
      setSub((cur: any) => ({ ...cur, points: cur.points.map((x: any) => (x.id === pid ? p : x)) }));
      if (key === "indicator_code" && value) setInclude((cur) => ({ ...cur, [pid]: true }));
    } catch (e: any) { setError(e.message); }
    finally { pending.current.delete(req); }
  };

  const commit = async () => {
    setBusy(true);
    setError(null);
    // Save the box you were typing in before saving the rows (it saves when you leave it).
    (document.activeElement as HTMLElement | null)?.blur();
    await new Promise((r) => setTimeout(r, 50));
    await Promise.allSettled(Array.from(pending.current));
    try {
      const rows = sub.points.map((p: any) => ({ id: p.id, include: include[p.id], override_reason: reasons[p.id] || null }));
      const body: any = { rows };
      if (confirm.on) body.confirm = { basis: confirm.basis, source_name: confirm.source_name || null, source_url: confirm.source_url || null };
      setResult(await post(`/api/manual/${sub.id}/confirm`, body));
    } catch (e: any) {
      const probs = e.detail?.problems;
      setError(probs ? `Nothing could be saved yet. ${probs.map((p: any) => `Row ${p.row_index + 1} ${p.needs === "correction" ? "needs a correction" : "needs a reason"}`).join("; ")}. Fix those rows, or untick them and save the rest` : e.message);
    } finally { setBusy(false); }
  };

  const discard = async () => { await post(`/api/manual/${sub.id}/discard`); onReset(); };

  if (result) {
    return (
      <>
        <PageTitle title="Data saved and re-analysed" />
        <Panel>
          {result.recompute_jobs.map((j: any) => <p key={j.id} className="note">{j.summary?.message}</p>)}
          <ul className="mt-4 space-y-1 text-sm text-muted">
            {result.committed.map((c: any, i: number) => <li key={i}>{c.entity.replaceAll("_", " ")} #{c.id ?? ""} {c.notes?.join(" ")}</li>)}
          </ul>
          {result.skipped?.length > 0 && (
            <div className="mt-4 rounded border border-amber/50 bg-amber/10 px-3 py-2 text-sm">
              <p className="font-medium">Not saved ({result.skipped.length})</p>
              <ul className="mt-1 space-y-1 text-muted">
                {result.skipped.map((p: any) => (
                  <li key={p.id}>Row {p.row_index + 1}{p.label ? ` “${p.label}”` : ""}: {p.errors.map((w: any) => w.message).join("; ")}</li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-muted">Add these again with the Type tab if you need them.</p>
            </div>
          )}
          <div className="mt-5 flex gap-3">
            <Button onClick={onReset}>Add more data</Button>
            <Link href="/" className="rounded border border-line px-3 py-1.5 text-sm">Go to dashboard</Link>
            <Link href="/data-health" className="rounded border border-line px-3 py-1.5 text-sm">Data health</Link>
          </div>
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageTitle title="Review extracted data"
        subtitle={`Detected ${sub.content_type.replaceAll("_", " ")} (${Math.round(sub.content_type_confidence)}% sure), read via ${sub.extraction_method}${sub.ocr_confidence ? `, OCR confidence ${sub.ocr_confidence}%` : ""}. Fields under 70% confidence are highlighted.`} />
      {sub.status === "failed" && <div className="mb-4"><ErrorBox error={sub.error} /></div>}
      {sub.notes?.length > 0 && <p className="mb-4 text-sm text-muted">{sub.notes.join(" ")}</p>}
      <div className={`grid gap-6 ${preview || sub.raw_text ? "xl:grid-cols-[minmax(0,26rem)_1fr]" : ""}`}>
        {(preview || sub.raw_text) && (
          <Panel title="Original">
            {preview ? <img src={preview} alt="Uploaded original" className="w-full rounded" /> :
              <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap text-xs text-muted">{sub.raw_text}</pre>}
            {sub.files?.[0] && <p className="mt-2 break-all text-xs text-muted">SHA-256 {sub.files[0].sha256}</p>}
          </Panel>
        )}
        <div className="space-y-4">
          {sub.points.map((p: any, i: number) => {
            const keys = FIELDS[p.kind] || Object.keys(p.fields);
            return (
              <Panel key={p.id} title={<span>Row {i + 1}: {p.kind.replaceAll("_", " ")}{p.fields.indicator_text ? <span className="text-muted"> “{p.fields.indicator_text}”</span> : null}
                  <span className={`ml-2 text-xs font-normal ${STATE_LABEL[rowState(p)][1]}`}>{STATE_LABEL[rowState(p)][0]}</span></span>}
                action={<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={include[p.id]}
                  onChange={(e) => setInclude({ ...include, [p.id]: e.target.checked })} />Include</label>}>
                {p.kind === "cb_statement" || p.kind === "speech" ? (
                  <p className="note mb-3 max-h-40 overflow-auto text-sm text-muted">{String(p.fields.text).slice(0, 1200)}…</p>
                ) : null}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {keys.map((k) => (
                    <label key={k} className="text-xs text-muted">{k.replaceAll("_", " ")}
                      {k === "indicator_code" ? (
                        <select value={p.fields.indicator_code || ""} onChange={(e) => edit(p.id, k, e.target.value)}
                          className={`mt-1 w-full rounded border bg-ink px-2 py-1.5 text-sm text-text ${confClass(p.mapping_confidence)}`}>
                          <option value="">Choose…</option>
                          {p.fields.candidates?.length > 0 && (
                            <optgroup label="Best matches">
                              {p.fields.candidates.map(([c, s]: [string, number]) => <option key={`m-${c}`} value={c}>{c} ({Math.round(s)}%)</option>)}
                            </optgroup>
                          )}
                          <optgroup label="All indicators">
                            {(catalogue || []).map((ind: any) => <option key={ind.code} value={ind.code}>{ind.name}</option>)}
                          </optgroup>
                        </select>
                      ) : (
                        <input defaultValue={p.fields[k] ?? ""} onBlur={(e) => e.target.value !== String(p.fields[k] ?? "") && edit(p.id, k, e.target.value)}
                          className={`mt-1 w-full rounded border bg-ink px-2 py-1.5 text-sm text-text ${confClass(p.field_confidence?.[k])}`}
                          title={p.field_confidence?.[k] !== undefined ? `Extraction confidence ${p.field_confidence[k]}%` : undefined} />
                      )}
                    </label>
                  ))}
                </div>
                {p.warnings.length > 0 && (
                  <ul className="mt-3 space-y-1 text-sm">
                    {p.warnings.map((w: any, j: number) => (
                      <li key={j} className={w.severity === "error" ? "text-hawk" : w.severity === "info" ? "text-muted" : "text-amber"}>
                        {w.severity === "error" ? "✕" : "!"} {w.message}</li>
                    ))}
                  </ul>
                )}
                {p.has_errors && !p.missing_fields.length && (
                  <input placeholder="Reason for overriding the warning (recorded in the audit log)" value={reasons[p.id] || ""}
                    onChange={(e) => setReasons({ ...reasons, [p.id]: e.target.value })}
                    className="mt-3 w-full rounded border border-line bg-ink px-2 py-1.5 text-sm" />
                )}
              </Panel>
            );
          })}
          <Panel title="Confirm the values yourself (optional)">
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={confirm.on} onChange={(e) => setConfirm({ ...confirm, on: e.target.checked })} />
              <span>I have checked these values. Mark them as user-confirmed so they count at almost full weight until the official source can verify them.</span>
            </label>
            {confirm.on && (
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <label className="text-xs text-muted">Confirmed against
                  <select value={confirm.basis} onChange={(e) => setConfirm({ ...confirm, basis: e.target.value })}
                    className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5 text-sm text-text">
                    <option value="OFFICIAL_SOURCE">The official source</option>
                    <option value="SECONDARY_SOURCE">A secondary source</option>
                    <option value="NO_SOURCE">No source (I’m certain)</option>
                  </select></label>
                <label className="text-xs text-muted">Source name
                  <input value={confirm.source_name} onChange={(e) => setConfirm({ ...confirm, source_name: e.target.value })}
                    placeholder="e.g. BLS, Stats SA, my broker" className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5 text-sm text-text" /></label>
                <label className="text-xs text-muted">Source link
                  <input value={confirm.source_url} onChange={(e) => setConfirm({ ...confirm, source_url: e.target.value })}
                    className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5 text-sm text-text" /></label>
              </div>
            )}
            <p className="mt-3 text-xs text-muted">Unconfirmed values are still analysed, labelled “unverified”, with lower evidence quality. The platform keeps checking the official source either way.</p>
          </Panel>
          <ErrorBox error={error} />
          <div className="flex gap-3">
            <Button onClick={commit} disabled={busy || sub.points.length === 0}>{busy ? "Analysing…" : "Confirm and analyse"}</Button>
            <Button kind="danger" onClick={discard}>Discard</Button>
          </div>
        </div>
      </div>
    </>
  );
}
