"use client";

import { useEffect, useState } from "react";

import { Button, Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { del, post, useApi } from "@/lib/api";

const toneCls = (t: number | null | undefined) => (t == null ? "text-muted" : t >= 8 ? "text-hawk" : t <= -8 ? "text-dove" : "text-muted");
const sgn = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);

/** -100..+100 bar: dovish (left) to hawkish (right). */
function ToneBar({ label, value }: { label: string; value: number | null | undefined }) {
  const p = value == null ? 50 : (Math.max(-100, Math.min(100, value)) + 100) / 2;
  return (
    <div className="min-w-0">
      <div className="flex justify-between text-xs text-muted"><span>{label}</span><span className={`font-semibold ${toneCls(value)}`}>{sgn(value)}</span></div>
      <div className="relative mt-1 h-2 rounded" style={{ background: "linear-gradient(90deg, var(--color-dove), var(--color-line) 50%, var(--color-hawk))" }}>
        {value != null && <span className="absolute top-1/2 h-3.5 w-1.5 -translate-y-1/2 rounded bg-text" style={{ left: `calc(${p}% - 3px)` }} />}
      </div>
    </div>
  );
}

function Detail({ code, id, onDeleted }: { code: string; id: number; onDeleted: () => void }) {
  const { data: d, error, loading } = useApi<any>(`/api/central-banks/${code}/press-conferences/${id}`);
  const [qa, setQa] = useState<"all" | "hawk" | "dove">("all");
  const [showText, setShowText] = useState(false);
  if (error) return <ErrorBox error={error} />;
  if (loading && !d) return <Loading />;
  if (!d) return null;
  const a = d.analysis;
  let pairs: any[] = a.qa || [];
  if (qa === "hawk") pairs = [...pairs].sort((x, y) => y.tone - x.tone).filter((p) => p.tone > 0);
  if (qa === "dove") pairs = [...pairs].sort((x, y) => x.tone - y.tone).filter((p) => p.tone < 0);
  const remove = async () => { await del(`/api/central-banks/${code}/press-conferences/${id}`); onDeleted(); };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-lg font-medium">{d.title}</h3>
          <p className="text-xs text-muted">{d.held_on} · {d.questions} questions · {d.input_method === "automated" ? "fetched automatically" : d.input_method === "url" ? "from a link" : "pasted"}
            {d.url && <> · <a href={d.url} target="_blank" rel="noreferrer" className="text-verify hover:underline">source ↗</a></>}
            {a.tone_method && ` · tone: ${a.tone_method}`}</p>
        </div>
        <span className={`rounded px-2 py-1 text-sm font-semibold ${d.tone >= 8 ? "bg-hawk/20 text-hawk" : d.tone <= -8 ? "bg-dove/20 text-dove" : "bg-panel-2 text-muted"}`}>{a.label} ({sgn(d.tone)})</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <ToneBar label="Overall" value={d.tone} />
        <ToneBar label="Opening remarks" value={a.opening_tone} />
        <ToneBar label="Q&A answers" value={a.qa_tone} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded border border-line bg-panel-2/40 p-3 text-sm">
          <p className="text-xs text-muted">vs the decision statement</p>
          {d.vs_statement == null ? <p className="text-muted">No statement stored for this meeting to compare with.</p> : (
            <p><b className={toneCls(d.vs_statement)}>{Math.abs(d.vs_statement) < 5 ? "In line with the statement" : d.vs_statement > 0 ? "More hawkish than the statement" : "More dovish than the statement"}</b>
              <span className="text-muted"> ({sgn(d.vs_statement)}: press conference {sgn(d.tone)} vs statement {sgn(a.statement?.tone)})</span></p>
          )}
          {a.qa_tone != null && a.opening_tone != null && Math.abs(a.qa_tone - a.opening_tone) >= 10 && (
            <p className="mt-1 text-xs">The Q&amp;A was <b className={toneCls(a.qa_tone - a.opening_tone)}>{a.qa_tone > a.opening_tone ? "more hawkish" : "more dovish"}</b> than the prepared remarks: the governor went off script.</p>
          )}
        </div>
        <div className="rounded border border-line bg-panel-2/40 p-3 text-sm">
          <p className="text-xs text-muted">vs the previous press conference</p>
          {!a.previous ? <p className="text-muted">First one stored for this bank.</p> : (<>
            <p><b className={toneCls(a.previous.shift)}>{Math.abs(a.previous.shift) < 5 ? "Similar tone" : a.previous.shift > 0 ? "Turned more hawkish" : "Turned more dovish"}</b>
              <span className="text-muted"> ({sgn(a.previous.tone)} → {sgn(d.tone)}, {a.previous.held_on})</span></p>
            {a.previous.added.length > 0 && <p className="mt-1 text-xs">New: {a.previous.added.map((p: string) => `“${p}”`).join(", ")}</p>}
            {a.previous.dropped.length > 0 && <p className="mt-1 text-xs text-muted">Dropped: {a.previous.dropped.map((p: string) => `“${p}”`).join(", ")}</p>}
          </>)}
        </div>
      </div>

      {a.ai_reasons?.length > 0 && (
        <div className="text-sm"><p className="text-xs text-muted">AI summary of the tone</p>
          <ul className="list-disc pl-5">{a.ai_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></div>
      )}

      <div>
        <h4 className="mb-1.5 font-medium">Key phrases</h4>
        {a.phrases.length ? (
          <div className="flex flex-wrap gap-1.5">
            {a.phrases.map((p: any) => (
              <span key={p.phrase} title={`…${p.context}…`}
                className={`cursor-help rounded border px-2 py-0.5 text-xs ${p.lean > 0 ? "border-hawk/50 bg-hawk/10 text-hawk" : p.lean < 0 ? "border-dove/50 bg-dove/10 text-dove" : "border-line text-muted"}`}>
                {p.phrase}{p.count > 1 && ` ×${p.count}`}</span>
            ))}
          </div>
        ) : <p className="text-sm text-muted">No forward-guidance phrases found.</p>}
        <p className="mt-1 text-xs text-muted">Red = hawkish, teal = dovish, grey = guidance to note. Hover a phrase to see it in context.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="mb-1.5 font-medium">What they talked about</h4>
          <ul className="space-y-1.5 text-sm">
            {a.topics.map((t: any) => (
              <li key={t.topic}>
                <div className="flex justify-between text-xs"><span>{t.topic}</span>
                  <span className={toneCls(t.lean)}>{t.lean >= 8 ? "hawkish" : t.lean <= -8 ? "dovish" : "neutral"} · {t.share}% of remarks</span></div>
                <div className="mt-0.5 h-1.5 rounded bg-panel-2"><div className="h-1.5 rounded bg-verify" style={{ width: `${Math.min(100, t.share * 2)}%` }} /></div>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-3 text-sm">
          {[["Most hawkish lines", a.hawkish_quotes, "border-hawk"], ["Most dovish lines", a.dovish_quotes, "border-dove"]].map(([t, qs, c]: any) => (
            <div key={t}><h4 className="mb-1 font-medium">{t}</h4>
              {qs.length ? qs.map((q: string, i: number) => <blockquote key={i} className={`mb-1.5 border-l-4 ${c} pl-2 text-muted`}>&ldquo;{q}&rdquo;</blockquote>)
                : <p className="text-xs text-muted">None found.</p>}
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-medium">Question by question</h4>
          <span className="flex gap-1 text-xs">
            {([["all", "In order"], ["hawk", "Most hawkish"], ["dove", "Most dovish"]] as const).map(([k, t]) => (
              <button key={k} onClick={() => setQa(k)} aria-pressed={qa === k}
                className={`rounded border px-2 py-0.5 ${qa === k ? "border-verify bg-panel-2" : "border-line text-muted"}`}>{t}</button>
            ))}
          </span>
        </div>
        {pairs.length ? (
          <ol className="space-y-2">
            {pairs.map((p: any, i: number) => (
              <li key={i} className="rounded border border-line p-2.5 text-sm">
                <details>
                  <summary className="cursor-pointer list-none">
                    <span className="flex items-start justify-between gap-2">
                      <span><span className="text-xs text-muted">{p.who}:</span> {p.question.length > 180 ? p.question.slice(0, 180) + "…" : p.question}</span>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${p.tone >= 8 ? "bg-hawk/20 text-hawk" : p.tone <= -8 ? "bg-dove/20 text-dove" : "bg-panel-2 text-muted"}`}>{sgn(p.tone)}</span>
                    </span>
                    {p.topics.length > 0 && <span className="mt-1 block text-xs text-muted">{p.topics.join(" · ")} · tap to read the answer</span>}
                  </summary>
                  <p className="mt-2 whitespace-pre-line border-t border-line pt-2 text-muted">{p.answer}</p>
                </details>
              </li>
            ))}
          </ol>
        ) : <p className="text-sm text-muted">{a.has_qa ? "No answers in this direction." : "No Q&A found: the transcript has no speaker labels (e.g. 'CHAIR POWELL.' or 'Question:'), so it was read as one block."}</p>}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-xs">
        <button onClick={() => setShowText(!showText)} className="text-verify hover:underline">{showText ? "Hide transcript" : "Read the full transcript"}</button>
        <button onClick={remove} className="text-muted hover:text-hawk">Delete this press conference</button>
      </div>
      {showText && <pre className="max-h-[32rem] overflow-y-auto whitespace-pre-wrap rounded bg-panel-2/50 p-3 text-xs leading-relaxed">{d.text}</pre>}
    </div>
  );
}

export default function PressConferences({ code, name, onChanged }: { code: string; name: string; onChanged?: () => void }) {
  const { data, error, loading, reload } = useApi<any>(`/api/central-banks/${code}/press-conferences`);
  const [sel, setSel] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [day, setDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (data?.items?.length && sel === null) setSel(data.items[0].id); }, [data, sel]);
  useEffect(() => { if (data?.last_decision_date && !day) setDay(String(data.last_decision_date).slice(0, 10)); }, [data, day]);
  const done = (r: any) => { setSel(r.id); setText(""); setUrl(""); setMsg("Analysed."); reload(); onChanged?.(); };
  const run = async (f: () => Promise<any>) => {
    setBusy(true); setMsg(null);
    try { done(await f()); } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Panel title="Press conference analysis">
        <ErrorBox error={error} />
        {loading && !data ? <Loading /> : !data?.items?.length ? (
          <Empty>No press conference stored for the {name} yet. {data?.auto ? "Fetch the latest one, or paste" : "Paste"} a transcript on the right.</Empty>
        ) : (
          <>
            {data.items.length > 1 && (
              <label className="mb-4 flex items-center gap-2 text-sm text-muted">Press conference
                <select value={sel ?? ""} onChange={(e) => setSel(Number(e.target.value))} className="rounded border border-line bg-panel-2 px-2 py-1.5 text-text">
                  {data.items.map((p: any) => <option key={p.id} value={p.id}>{p.held_on}: {p.label} ({p.tone > 0 ? "+" : ""}{Math.round(p.tone)})</option>)}
                </select>
              </label>
            )}
            {sel !== null && <Detail key={sel} code={code} id={sel} onDeleted={() => { setSel(null); reload(); }} />}
          </>
        )}
      </Panel>
      <Panel title="Add a press conference">
        {data?.auto && (
          <div className="mb-4">
            <Button onClick={() => run(() => post(`/api/central-banks/${code}/press-conferences/fetch`, { held_on: day || null }))} disabled={busy}>
              {busy ? "Working…" : data.full_transcript ? `Fetch the ${name} transcript` : `Look for the latest ${name} press conference`}</Button>
            <p className="mt-1 text-xs text-muted">{data.full_transcript
              ? "The full transcript is usually published a few hours after the decision."
              : `Picks up press conference transcripts, opening statements and introductory remarks from the ${name}'s press feed. If the Q&A was video only, paste a transcript (e.g. from YouTube).`}
              {" "}The app also checks automatically every 2 hours.</p>
          </div>
        )}
        <label className="block text-sm">Meeting date
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
        <label className="mt-3 block text-sm">Link to the transcript (web page or PDF)
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
        <p className="my-2 text-center text-xs text-muted">or</p>
        <label className="block text-sm">Paste the transcript
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} placeholder={"CHAIR POWELL. Good afternoon…\nREPORTER NAME. Question…\n\nor\n\nLagarde: …\nQuestion: …"}
            className="mt-1 w-full rounded border border-line bg-ink p-2 text-xs" /></label>
        <div className="mt-2"><Button disabled={busy || (!text.trim() && !url.trim())}
          onClick={() => run(() => post(`/api/central-banks/${code}/press-conferences`, { text: text.trim() || null, url: url.trim() || null, held_on: day || null }))}>
          {busy ? "Analysing…" : "Analyse"}</Button></div>
        {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
        <p className="mt-3 text-xs text-muted">Speaker labels (like &ldquo;CHAIR POWELL.&rdquo; or &ldquo;Question:&rdquo;) let the app split the Q&amp;A from the opening remarks.
          The result also feeds the hawkish / dovish read of the last decision on the Overview.</p>
      </Panel>
    </div>
  );
}
