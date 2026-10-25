"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/**
 * Click a value to edit it in place (same behaviour as the economic calendar):
 * Enter saves, Esc cancels. If the value looks unusual, the server asks for a reason first.
 *
 * kind: "number" | "date" | "decision" (HIKE / CUT / HOLD).
 * period: when given, a period box is shown too (e.g. 2026-09 or 2026Q3) so you choose which month the number is for.
 */
export default function QuickEdit({ display, initial, kind = "number", period, label, onSave, allowEmpty }: {
  display: ReactNode; initial: string; kind?: "number" | "date" | "decision"; label: string;
  period?: { value: string; quarterly?: boolean };
  onSave: (value: string | null, period: string | undefined, reason: string | null) => Promise<unknown>;
  allowEmpty?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(initial);
  const [per, setPer] = useState(period?.value || "");
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement & HTMLSelectElement>(null);
  useEffect(() => { if (editing) { first.current?.focus(); if (kind === "number") first.current?.select?.(); } }, [editing, kind]);

  const open = () => {
    setText(initial); setPer(period?.value || ""); setErr(null); setNeedReason(null); setReason(""); setEditing(true);
  };
  const cancel = () => { setEditing(false); setErr(null); setNeedReason(null); };
  const save = async () => {
    const v = text.trim();
    if (!v && !allowEmpty) { setErr("Type a value"); return; }
    if (v === initial && (!period || per === period.value) && !needReason) { cancel(); return; }
    setBusy(true); setErr(null);
    try {
      await onSave(v || null, period ? per.trim() : undefined, reason.trim() || null);
      setEditing(false); setNeedReason(null);
    } catch (e: any) {
      const probs = e?.detail?.problems;
      if (probs?.length && probs.every((p: any) => p.needs === "override_reason")) {
        setNeedReason(probs.flatMap((p: any) => p.errors.map((w: any) => w.message)).join("; "));
      } else if (probs?.length) {
        setErr(probs.flatMap((p: any) => p.errors.map((w: any) => w.message)).join("; "));
      } else setErr(e?.message || String(e));
    } finally { setBusy(false); }
  };
  const keys = (e: React.KeyboardEvent) => { if (e.key === "Enter") save(); if (e.key === "Escape") cancel(); };

  if (!editing) {
    return (
      <button type="button" onClick={open} title={`Click to edit ${label.toLowerCase()}`}
        className="-mx-1 rounded px-1 text-left underline decoration-muted decoration-dotted decoration-2 underline-offset-4 hover:bg-panel-2 hover:outline hover:outline-1 hover:outline-line">
        {display}
      </button>
    );
  }
  const box = "rounded border border-verify bg-ink px-2 py-1 text-sm font-normal text-text";
  return (
    <div className="min-w-[8rem] text-sm font-normal">
      <div className="flex flex-wrap items-center gap-2">
        {kind === "decision" ? (
          <select ref={first} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={keys} disabled={busy}
            aria-label={`New ${label.toLowerCase()}`} className={box}>
            {allowEmpty && <option value="">Not set</option>}
            <option value="HOLD">HOLD</option><option value="HIKE">HIKE</option><option value="CUT">CUT</option>
          </select>
        ) : (
          <input ref={first} type={kind === "date" ? "date" : "text"} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={keys} disabled={busy} inputMode={kind === "number" ? "decimal" : undefined}
            aria-label={`New ${label.toLowerCase()}`} className={`${box} ${kind === "number" ? "w-24" : ""}`} />
        )}
        {period && (
          <label className="flex items-center gap-1 text-xs text-muted">for
            <input value={per} onChange={(e) => setPer(e.target.value)} onKeyDown={keys} disabled={busy}
              placeholder={period.quarterly ? "2026Q3" : "2026-09"} aria-label="Period"
              className="w-20 rounded border border-line bg-ink px-1.5 py-1 text-xs text-text" />
          </label>
        )}
      </div>
      {needReason && (
        <div className="mt-1 text-xs text-amber">
          {needReason}. Give a reason to keep it:
          <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. checked on the official site"
            onKeyDown={(e) => { if (e.key === "Enter" && reason.trim()) save(); if (e.key === "Escape") cancel(); }}
            className="mt-1 block w-52 rounded border border-line bg-ink px-2 py-1 text-xs text-text" />
        </div>
      )}
      {err && <p className="mt-1 max-w-[16rem] text-xs text-hawk">{err}</p>}
      <div className="mt-1 flex gap-3 text-xs">
        <button type="button" onClick={save} disabled={busy || (!!needReason && !reason.trim())}
          className="text-verify disabled:opacity-50">{busy ? "Saving…" : "Save"}</button>
        <button type="button" onClick={cancel} disabled={busy} className="text-muted">Cancel</button>
      </div>
    </div>
  );
}
