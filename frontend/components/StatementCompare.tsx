"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import StatementDiff from "@/components/StatementDiff";
import { Button, Empty, ErrorBox, Loading, Panel, StatusBadge } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { date, signed, toneClass } from "@/lib/format";

const MARK: Record<string, string> = {
  red: "bg-hawk/15 border-b-2 border-hawk/70", green: "bg-dove/15 border-b-2 border-dove/70",
  yellow: "bg-amber/15 border-b-2 border-amber/70", grey: "bg-panel-2 border-b border-line",
};

type Hl = { text: string; color: string };

/** Split a statement into paragraphs and highlight the sentences that changed. */
function Body({ text, marks = [] }: { text: string; marks?: Hl[] }) {
  const paras = (text || "").replace(/\r\n/g, "\n").split(/\n\s*\n|\n(?=[A-Z])/).map((p) => p.trim()).filter(Boolean);
  const useMarks = marks.filter((m) => m.text && m.text.length > 12);
  return (
    <div className="space-y-3 text-[0.95rem] leading-7">
      {paras.map((p, i) => <p key={i}>{highlight(p, useMarks)}</p>)}
    </div>
  );
}

function highlight(p: string, marks: Hl[]): ReactNode {
  const hits: { start: number; end: number; color: string }[] = [];
  for (const m of marks) {
    const at = p.indexOf(m.text.trim());
    if (at >= 0 && !hits.some((h) => at < h.end && at + m.text.trim().length > h.start)) {
      hits.push({ start: at, end: at + m.text.trim().length, color: m.color });
    }
  }
  if (!hits.length) return p;
  hits.sort((a, b) => a.start - b.start);
  const out: ReactNode[] = [];
  let pos = 0;
  hits.forEach((h, i) => {
    if (h.start > pos) out.push(p.slice(pos, h.start));
    out.push(<mark key={i} className={`rounded-sm px-0.5 text-text ${MARK[h.color] || MARK.grey}`}>{p.slice(h.start, h.end)}</mark>);
    pos = h.end;
  });
  out.push(p.slice(pos));
  return out;
}

/** Full-screen reader for one statement. */
export function StatementReader({ code, id, onClose }: { code: string; id: number; onClose: () => void }) {
  const { data, error } = useApi<any>(`/api/central-banks/${code}/statements/${id}`);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", esc); document.body.style.overflow = ""; };
  }, [onClose]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(data?.text || ""); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  return (
    <div role="dialog" aria-modal="true" aria-label="Full statement" onClick={onClose}
      className="fixed inset-0 z-50 flex items-stretch justify-center bg-ink/80 p-0 backdrop-blur-sm sm:p-6">
      <div onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-3xl flex-col overflow-hidden border border-line bg-panel sm:rounded-md">
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 className="font-medium">{data?.title || "Statement"}</h2>
            {data && (
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                <span>{date(data.published_at)}</span>
                <StatusBadge status={data.verification_status} />
                <span className={toneClass(data.tone_label)}>Tone {signed(data.tone_score, 0)} ({data.tone_label})</span>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {data?.url && <a href={data.url} target="_blank" rel="noreferrer"
              className="rounded border border-line px-3 py-1.5 text-sm hover:bg-panel-2">Original ↗</a>}
            <Button kind="ghost" onClick={copy} disabled={!data}>{copied ? "Copied" : "Copy text"}</Button>
            <Button onClick={onClose}>Close</Button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-8">
          <ErrorBox error={error} />
          {!data && !error ? <Loading /> : data && <Body text={data.text} />}
        </div>
      </div>
    </div>
  );
}

function Side({ title, s, marks, onRead, hiddenOnPhone }: {
  title: string; s: any; marks: Hl[]; onRead: () => void; hiddenOnPhone: boolean;
}) {
  return (
    <div className={`min-w-0 rounded-md border border-line ${hiddenOnPhone ? "hidden md:block" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line bg-panel-2/40 px-3 py-2">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-muted">{title}</div>
          <div className="font-medium">{s.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{date(s.published_at)}</span>
            <StatusBadge status={s.verification_status} />
            <span className={toneClass(s.tone_label)}>Tone {signed(s.tone_score, 0)}</span>
          </div>
        </div>
        <Button kind="ghost" onClick={onRead}>Read full</Button>
      </div>
      <div className="max-h-[32rem] overflow-y-auto p-3"><Body text={s.text} marks={marks} /></div>
    </div>
  );
}

export default function StatementCompare({ code, onAdded }: { code: string; onAdded: () => void }) {
  const [pick, setPick] = useState<number | null>(null);
  const { data, error, loading, reload } = useApi<any>(
    `/api/central-banks/${code}/statement-comparison${pick ? `?statement_id=${pick}` : ""}`);
  const { data: pairs, reload: reloadPairs } = useApi<any[]>(`/api/central-banks/${code}/statement-pairs`);
  const { data: all, reload: reloadAll } = useApi<any[]>(`/api/central-banks/${code}/statements`);
  const [view, setView] = useState<"side" | "changes">("side");
  const [phoneSide, setPhoneSide] = useState<"previous" | "latest">("latest");
  const [reading, setReading] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const add = async () => {
    try {
      const r = await post(`/api/central-banks/${code}/statements`, { text });
      setMsg(r.recompute?.message || "Saved");
      setText("");
      setPick(null);
      reload(); reloadPairs(); reloadAll();
      onAdded();
    } catch (e: any) { setMsg(e.message); }
  };

  const changes: any[] = data?.changes || [];
  const prevMarks: Hl[] = changes.filter((c) => c.previous).map((c) => ({ text: c.previous, color: c.color }));
  const latestMarks: Hl[] = changes.filter((c) => c.latest).map((c) => ({ text: c.latest, color: c.color }));

  return (
    <div className="space-y-6">
      {loading && !data ? <Loading /> : data ? (
        <Panel title="Previous vs latest statement"
          action={(pairs?.length || 0) > 1 ? (
            <label className="flex items-center gap-2 text-sm text-muted">Compare
              <select value={pick ?? ""} onChange={(e) => setPick(e.target.value ? Number(e.target.value) : null)}
                className="max-w-[16rem] rounded border border-line bg-panel-2 px-2 py-1 text-text">
                <option value="">Newest pair</option>
                {pairs!.map((p) => (
                  <option key={p.latest_id} value={p.latest_id}>{date(p.latest_date)} vs {date(p.previous_date)}</option>
                ))}
              </select>
            </label>
          ) : undefined}>
          <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            <span>Direction: <span className={toneClass(data.summary.direction)}>{data.summary.direction}</span></span>
            <span>Tone {signed(data.summary.tone_previous, 0)} → {signed(data.summary.tone_latest, 0)}</span>
            <span>{data.summary.changed} changed, {data.summary.unchanged} unchanged sentences</span>
          </div>
          {data.summary.tone_method && (
            <p className="mb-3 text-xs text-muted">
              Tone scored by {data.summary.tone_method}
              {data.summary.tone_ai_latest !== null && data.summary.tone_ai_latest !== undefined &&
                ` (AI ${signed(data.summary.tone_ai_latest, 0)}, word list ${signed(data.summary.tone_lexicon_latest, 0)})`}
              {data.summary.tone_ai_reasons?.length > 0 && `: ${data.summary.tone_ai_reasons.join("; ")}`}
            </p>
          )}
          {data.summary.ai_interpretation && <p className="note mb-4">{data.summary.ai_interpretation}</p>}

          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div role="tablist" className="flex rounded border border-line text-sm">
              {([["side", "Side by side"], ["changes", "Changes only"]] as const).map(([k, l]) => (
                <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
                  className={`px-3 py-1.5 ${view === k ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>{l}</button>
              ))}
            </div>
            {view === "side" && (
              <div className="flex rounded border border-line text-sm md:hidden">
                {(["previous", "latest"] as const).map((k) => (
                  <button key={k} onClick={() => setPhoneSide(k)}
                    className={`px-3 py-1.5 capitalize ${phoneSide === k ? "bg-panel-2 text-text" : "text-muted"}`}>{k}</button>
                ))}
              </div>
            )}
          </div>

          {view === "side" ? (
            <>
              <p className="mb-3 text-xs text-muted">Changed sentences are highlighted: red = hawkish, green = dovish,
                amber = important neutral or mixed, grey = minor. Press <b>Read full</b> to open a statement on its own.</p>
              <div className="grid gap-4 md:grid-cols-2">
                <Side title="Previous" s={data.previous} marks={prevMarks} onRead={() => setReading(data.previous.id)}
                  hiddenOnPhone={phoneSide !== "previous"} />
                <Side title="Latest" s={data.latest} marks={latestMarks} onRead={() => setReading(data.latest.id)}
                  hiddenOnPhone={phoneSide !== "latest"} />
              </div>
            </>
          ) : (
            <>
              <p className="mb-3 text-xs text-muted">Left border: red = hawkish, green = dovish, amber = important neutral or mixed, grey = minor. Inserted words are highlighted, removed words struck through.</p>
              <StatementDiff changes={changes} />
            </>
          )}
        </Panel>
      ) : (
        <Empty>{error ? `Couldn't load the comparison (${error}).` : all?.length === 1
          ? "Only one statement is stored so far. The comparison appears once the next one arrives, or paste an earlier statement below."
          : "A comparison appears once two statements are stored. Use Fetch latest below, or paste a statement."}</Empty>
      )}

      {(all?.length || 0) > 0 && (
        <Panel title={`All stored statements (${all!.length})`}>
          <ul className="divide-y divide-line text-sm">
            {all!.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <span className="font-medium">{s.title}</span>
                  <span className="ml-2 text-muted">{date(s.published_at)}</span>
                  {s.tone_score != null && <span className="ml-2 text-xs text-muted">tone {signed(s.tone_score, 0)}</span>}
                </div>
                <div className="flex gap-2">
                  {pairs?.some((p) => p.latest_id === s.id) && (
                    <Button kind="ghost" onClick={() => { setPick(s.id); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                      Compare with previous</Button>
                  )}
                  <Button kind="ghost" onClick={() => setReading(s.id)}>Read</Button>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title="Add a statement by pasting its text">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6}
          className="w-full rounded border border-line bg-ink p-3 text-sm" placeholder="Paste the full statement…" />
        <div className="mt-2 flex items-center gap-3">
          <Button disabled={text.trim().length < 50} onClick={add}>Save and compare</Button>
          {msg && <span className="text-sm text-muted">{msg}</span>}
        </div>
      </Panel>
      {reading != null && <StatementReader code={code} id={reading} onClose={() => setReading(null)} />}
    </div>
  );
}

