"use client";

import { useState } from "react";

import Review from "@/components/Review";
import { Button, ErrorBox, Loading, Panel } from "@/components/ui";
import { post, useApi } from "@/lib/api";

type Kind = "statement" | "projections";
type Sc = { page: string; label: string; auto: boolean; note: string };
type Row = { code: string; statement: Sc; projections: Sc; extra: { label: string; url: string }[] };

const KINDS: { key: Kind; title: string }[] = [
  { key: "statement", title: "Policy statement" },
  { key: "projections", title: "Projections" },
];

/**
 * Shortcuts to each central bank's official statement and projections.
 * "Open" shows the official page; "Fetch latest" finds the newest document, reads it and opens the
 * review screen so nothing is saved until you press Confirm. If the newest one can't be found, paste its link.
 */
export default function CbShortcuts({ code, names, onSaved }: {
  code?: string; names?: Record<string, string>; onSaved?: () => void;
}) {
  const { data, error, loading } = useApi<Row[]>("/api/central-banks/shortcuts");
  const [sub, setSub] = useState<any>(null);
  const rows = (data || []).filter((r) => !code || r.code === code);

  if (sub) {
    return (
      <Panel title={`Review: ${names?.[sub._code] || sub._code} ${sub._kind}`}
        action={<a href={sub.resolved_url} target="_blank" rel="noreferrer" className="text-sm text-verify hover:underline">Source ↗</a>}>
        <Review sub={sub} preview={null} onReset={() => { setSub(null); onSaved?.(); }} />
      </Panel>
    );
  }
  return (
    <Panel title={code ? "Official documents" : "Shortcuts: official statements and projections"}>
      <p className="mb-4 max-w-[75ch] text-sm text-muted">
        <b className="text-text">Open</b> shows the bank's own page. <b className="text-text">Fetch latest</b> reads the newest
        document and opens the review screen: nothing is saved until you check it and press Confirm.
      </p>
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : (
        <div className={code ? "grid gap-4 md:grid-cols-2" : "grid gap-4 md:grid-cols-2 xl:grid-cols-3"}>
          {code ? KINDS.map((k) => (
            <Card key={k.key} row={rows[0]} kind={k.key} title={k.title} onOpen={setSub} />
          )) : rows.map((r) => (
            <div key={r.code} className="rounded-md border border-line p-3">
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <span className="font-medium">{names?.[r.code] || r.code}</span>
                <span className="text-xs text-muted">{r.code}</span>
              </div>
              <div className="space-y-3">
                {KINDS.map((k) => <Line key={k.key} row={r} kind={k.key} title={k.title} onOpen={setSub} />)}
              </div>
            </div>
          ))}
        </div>
      )}
      {code && (rows[0]?.extra.length ?? 0) > 0 && (
        <p className="mt-4 text-sm text-muted">More from the bank:{" "}
          {rows[0].extra.map((e, i) => (
            <span key={e.url}>{i > 0 && " · "}<a href={e.url} target="_blank" rel="noreferrer" className="text-verify hover:underline">{e.label} ↗</a></span>
          ))}
        </p>
      )}
    </Panel>
  );
}

function useFetcher(code: string, kind: Kind, onOpen: (s: any) => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (url?: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await post(`/api/central-banks/${code}/fetch`, { kind, url: url || null });
      if (r.status === "failed") throw new Error(r.error || "Couldn't read that document");
      onOpen({ ...r, _code: code, _kind: kind === "statement" ? "statement" : "projections" });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, err, run };
}

function PasteLink({ busy, run }: { busy: boolean; run: (u: string) => void }) {
  const [url, setUrl] = useState("");
  return (
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (url.trim()) run(url.trim()); }}>
      <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="…or paste the document's link"
        aria-label="Document link" inputMode="url"
        className="min-w-0 flex-1 rounded border border-line bg-panel-2 px-2 py-1 text-sm" />
      <Button type="submit" kind="ghost" disabled={busy || !url.trim()}>Fetch</Button>
    </form>
  );
}

/** compact line used on the all-banks list */
function Line({ row, kind, title, onOpen }: { row: Row; kind: Kind; title: string; onOpen: (s: any) => void }) {
  const sc = row[kind];
  const { busy, err, run } = useFetcher(row.code, kind, onOpen);
  const [paste, setPaste] = useState(false);
  return (
    <div className="text-sm">
      <div className="text-xs uppercase tracking-wide text-muted">{title}</div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <a href={sc.page} target="_blank" rel="noreferrer" title={sc.label}
          className="rounded border border-line px-2.5 py-1 hover:bg-panel-2">Open ↗</a>
        {sc.auto && <Button kind="ghost" disabled={busy} onClick={() => run()}>{busy ? "Fetching…" : "Fetch latest"}</Button>}
        <button className="text-xs text-muted underline-offset-2 hover:underline" onClick={() => setPaste(!paste)}>
          {paste ? "hide link box" : "paste link"}</button>
      </div>
      {(paste || err) && <div className="mt-2"><PasteLink busy={busy} run={run} /></div>}
      {err && <p className="mt-1 text-xs text-hawk">{err}</p>}
    </div>
  );
}

/** larger card used on a single bank's page */
function Card({ row, kind, title, onOpen }: { row?: Row; kind: Kind; title: string; onOpen: (s: any) => void }) {
  const { busy, err, run } = useFetcher(row?.code || "", kind, onOpen);
  if (!row) return null;
  const sc = row[kind];
  return (
    <div className="rounded-md border border-line p-3">
      <div className="text-xs uppercase tracking-wide text-muted">{title}</div>
      <div className="mt-0.5 font-medium">{sc.label}</div>
      {sc.note && <p className="mt-1 text-xs text-muted">{sc.note}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <a href={sc.page} target="_blank" rel="noreferrer"
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-panel-2">Open official page ↗</a>
        {sc.auto && <Button disabled={busy} onClick={() => run()}>{busy ? "Fetching…" : "Fetch latest"}</Button>}
      </div>
      <div className="mt-3"><PasteLink busy={busy} run={run} /></div>
      {err && <p className="mt-2 text-xs text-hawk">{err}</p>}
    </div>
  );
}
