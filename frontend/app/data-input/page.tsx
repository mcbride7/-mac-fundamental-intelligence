"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";

import Review from "@/components/Review";
import { Button, ErrorBox, PageTitle, Panel } from "@/components/ui";
import { post, useApi } from "@/lib/api";

const MODES = [
  { key: "screenshot", label: "Screenshot", hint: "PNG, JPG, WEBP or HEIC of a release, calendar, table or statement" },
  { key: "camera", label: "Camera", hint: "Take a photo of a screen or a printed release" },
  { key: "pdf", label: "PDF", hint: "Official release, statement or projection table. Scanned PDFs are read with OCR" },
  { key: "type", label: "Type", hint: "For example: US CPI September 3.4% y/y, consensus 3.1%, previous 3.2%" },
  { key: "table", label: "Paste table", hint: "CSV or a table copied from any calendar or spreadsheet" },
  { key: "url", label: "URL", hint: "A page or PDF link for the system to fetch and read" },
] as const;

const EXAMPLES: Record<string, string> = {
  type: "US CPI September 3.4% y/y, core 3.1%, consensus 3.1%, previous 3.2%",
  table: "Indicator,Period,Actual,Previous,Forecast,Unit,Date\nUS CPI y/y,2026-09,3.4,3.2,3.1,%,2026-10-14\nUS Core CPI y/y,2026-09,3.1,3.0,3.0,%,2026-10-14",
};

function Input() {
  const params = useSearchParams();
  const [mode, setMode] = useState<(typeof MODES)[number]["key"]>("screenshot");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [hint, setHint] = useState({ indicator_code: params?.get("indicator") || "", reference_period: params?.get("period") || "",
    central_bank_code: "", release_date: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sub, setSub] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: cat } = useApi<any[]>("/api/indicators/catalogue");

  const cleanHint = Object.fromEntries(Object.entries(hint).filter(([, v]) => v));
  const pick = (f: File | null) => {
    setFile(f);
    setPreview(f && f.type.startsWith("image/") ? URL.createObjectURL(f) : null);
  };
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      let r;
      if (mode === "type" || mode === "table") {
        r = await post("/api/manual/text", { text, hint: cleanHint, input_method: mode === "table" ? "csv" : "typed" });
      } else if (mode === "url") {
        r = await post("/api/manual/url", { url, hint: cleanHint });
      } else {
        if (!file) throw new Error("Choose a file first");
        const fd = new FormData();
        fd.append("file", file);
        fd.append("hint", JSON.stringify(cleanHint));
        fd.append("input_method", mode === "camera" ? "photo" : mode === "pdf" ? "pdf" : "screenshot");
        r = await post("/api/manual/upload", fd);
      }
      setSub(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (sub) return <Review sub={sub} preview={preview} onReset={() => { setSub(null); pick(null); setText(""); }} />;

  const m = MODES.find((x) => x.key === mode)!;
  const isFile = ["screenshot", "camera", "pdf"].includes(mode);
  return (
    <>
      <PageTitle title="Add data" subtitle="Use this whenever a feed fails, a release is late, or you simply have newer numbers. You review every extracted value before it is used, and it is labelled with its source." />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Panel>
          <div role="tablist" className="mb-4 flex flex-wrap gap-1">
            {MODES.map((x) => (
              <button key={x.key} role="tab" aria-selected={mode === x.key} onClick={() => setMode(x.key)}
                className={`rounded px-3 py-1.5 text-sm ${mode === x.key ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>{x.label}</button>
            ))}
          </div>
          <p className="mb-3 text-sm text-muted">{m.hint}</p>
          {isFile && (
            <div onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files?.[0] || null); }}
              className="flex min-h-48 flex-col items-center justify-center gap-3 rounded border border-dashed border-line p-6 text-center">
              {preview ? <img src={preview} alt="Selected upload" className="max-h-72 rounded" /> :
                file ? <p className="text-sm">{file.name}</p> : <p className="text-sm text-muted">Drop a file here, or</p>}
              <input ref={fileRef} type="file" className="hidden" onChange={(e) => pick(e.target.files?.[0] || null)}
                accept={mode === "pdf" ? "application/pdf" : "image/*"} capture={mode === "camera" ? "environment" : undefined} />
              <Button kind="ghost" onClick={() => fileRef.current?.click()}>{mode === "camera" ? "Open camera" : file ? "Choose another file" : "Choose a file"}</Button>
            </div>
          )}
          {(mode === "type" || mode === "table") && (
            <>
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={mode === "table" ? 8 : 4}
                className="w-full rounded border border-line bg-ink p-3 font-mono text-sm" placeholder={EXAMPLES[mode]} />
              <button className="mt-1 text-xs text-verify" onClick={() => setText(EXAMPLES[mode])}>Use the example</button>
            </>
          )}
          {mode === "url" && (
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.bls.gov/news.release/cpi.nr0.htm"
              className="w-full rounded border border-line bg-ink px-3 py-2 text-sm" />
          )}
          <div className="mt-4 flex items-center gap-3">
            <Button onClick={submit} disabled={busy}>{busy ? "Reading…" : "Extract data"}</Button>
            <span className="text-xs text-muted">Nothing is saved until you confirm on the next screen.</span>
          </div>
          <div className="mt-3"><ErrorBox error={error} /></div>
        </Panel>
        <Panel title="Optional hints">
          <p className="mb-3 text-xs text-muted">Hints help when the screenshot doesn’t show the indicator or period.</p>
          <label className="block text-sm">Indicator
            <select value={hint.indicator_code} onChange={(e) => setHint({ ...hint, indicator_code: e.target.value })}
              className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5">
              <option value="">Detect automatically</option>
              {cat?.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select></label>
          <label className="mt-3 block text-sm">Reference period
            <input value={hint.reference_period} placeholder="2026-09 or 2026Q3" onChange={(e) => setHint({ ...hint, reference_period: e.target.value })}
              className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
          <label className="mt-3 block text-sm">Release date
            <input type="date" value={hint.release_date} onChange={(e) => setHint({ ...hint, release_date: e.target.value })}
              className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5" /></label>
          <label className="mt-3 block text-sm">Central bank (statements, projections)
            <select value={hint.central_bank_code} onChange={(e) => setHint({ ...hint, central_bank_code: e.target.value })}
              className="mt-1 w-full rounded border border-line bg-ink px-2 py-1.5">
              <option value="">Detect automatically</option>
              {["FED", "ECB", "BOE", "BOJ", "SNB", "BOC", "RBA", "RBNZ", "SARB", "PBOC", "BANXICO"].map((c) => <option key={c}>{c}</option>)}
            </select></label>
          <p className="mt-4 text-xs text-muted">Recent submissions: <Link href="/data-health" className="text-verify">Data health</Link></p>
        </Panel>
      </div>
    </>
  );
}

export default function DataInputPage() {
  return <Suspense><Input /></Suspense>;
}
