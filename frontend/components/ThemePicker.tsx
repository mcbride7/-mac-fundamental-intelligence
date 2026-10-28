"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { CUSTOM_FIELDS, THEMES, apply, customVars, load, save, type CustomKey, type Saved } from "@/lib/themes";

function Swatches({ vars }: { vars: Record<string, string> }) {
  return (
    <div className="flex h-12 overflow-hidden rounded border" style={{ background: vars.ink, borderColor: vars.line }}>
      <div className="m-1.5 flex flex-1 flex-col justify-between rounded p-1.5" style={{ background: vars.panel }}>
        <div className="h-1.5 w-3/4 rounded" style={{ background: vars.text }} />
        <div className="h-1.5 w-1/2 rounded" style={{ background: vars.muted }} />
      </div>
      <div className="my-1.5 mr-1.5 flex w-14 flex-col gap-1">
        <div className="flex-1 rounded" style={{ background: vars.bull }} />
        <div className="flex-1 rounded" style={{ background: vars.bear }} />
      </div>
    </div>
  );
}

/** "Colours" button in the top bar: pick a mood preset, or set your own background, panel, text and signal colours. */
export default function ThemePicker() {
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState<Saved | null>(null);
  const [custom, setCustom] = useState<Partial<Record<CustomKey, string>>>({});
  useEffect(() => {  // the <head> script already painted it; this re-applies it in case that script didn't run
    const s = load(); setCur(s); setCustom(s?.custom || {});
    if (s?.vars) apply(s.vars, s.scheme);
  }, []);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);

  const currentId = cur?.id || "navy";
  const choose = (id: string) => {
    const t = THEMES.find((x) => x.id === id)!;
    const s: Saved = { id, scheme: t.scheme, vars: t.vars };
    apply(t.vars, t.scheme); save(id === "navy" ? null : s); setCur(s); setCustom({});
  };
  const setOne = (k: CustomKey, val: string) => {
    const next = { ...custom, [k]: val };
    const b = THEMES.find((t) => t.id === ((cur as any)?.base || (currentId !== "custom" ? currentId : "navy"))) || THEMES[0];
    const { vars, scheme } = customVars(b, next);
    const s = { id: "custom", scheme, vars, custom: next, base: b.id } as Saved & { base: string };
    apply(vars, scheme); save(s); setCur(s); setCustom(next);
  };
  const reset = () => choose("navy");
  const vars = cur?.vars || THEMES[0].vars;

  return (
    <>
      <button onClick={() => setOpen(true)} title="Change the website colours"
        className="whitespace-nowrap rounded border border-line px-2 py-1.5 text-sm text-muted hover:bg-panel-2 hover:text-text sm:px-3">🎨<span className="hidden sm:inline"> Colours</span></button>
      {open && typeof document !== "undefined" && createPortal(
        // rendered on <body>: the sticky, blurred top bar would otherwise trap a fixed panel inside it
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={() => setOpen(false)}>
          <aside role="dialog" aria-label="Website colours" onClick={(e) => e.stopPropagation()}
            className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-panel p-4 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Colours for your mood</h2>
              <button onClick={() => setOpen(false)} className="rounded border border-line px-2 py-1 text-sm hover:bg-panel-2">Close</button>
            </div>
            <p className="mb-3 text-sm text-muted">Tap a theme to switch straight away. Your choice is remembered on this device.</p>
            <ul className="space-y-2">
              {THEMES.map((t) => (
                <li key={t.id}>
                  <button onClick={() => choose(t.id)} aria-pressed={currentId === t.id}
                    className={`grid w-full grid-cols-[6.5rem_1fr] items-center gap-3 rounded border p-2 text-left hover:bg-panel-2 ${currentId === t.id ? "border-verify ring-1 ring-verify" : "border-line"}`}>
                    <Swatches vars={t.vars} />
                    <span><span className="font-medium">{t.name}</span>{currentId === t.id && <span className="ml-1.5 text-xs text-verify">✓ in use</span>}
                      <span className="block text-xs text-muted">{t.mood}</span></span>
                  </button>
                </li>
              ))}
            </ul>

            <h3 className="mb-1 mt-5 font-medium">Make your own</h3>
            <p className="mb-2 text-xs text-muted">Starts from the theme above that you last picked; change any colour and the in-between shades are worked out for you.</p>
            <div className="grid grid-cols-2 gap-2">
              {CUSTOM_FIELDS.map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 rounded border border-line px-2 py-1.5 text-sm">
                  <input type="color" value={custom[k] || vars[k]} onChange={(e) => setOne(k, e.target.value)}
                    className="h-7 w-9 cursor-pointer rounded border border-line bg-transparent" aria-label={label} />
                  {label}
                </label>
              ))}
            </div>
            {currentId === "custom" && <p className="mt-2 text-xs text-verify">✓ Using your own colours</p>}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button onClick={reset} className="rounded border border-line px-3 py-1.5 text-sm hover:bg-panel-2">Reset to default</button>
              <span className="text-xs text-muted">Tip: for calm focus, try Focus slate or Forest calm; for late nights, Deep night.</span>
            </div>
            <div className="mt-4 rounded border border-line p-3 text-sm">
              <p className="mb-2 text-xs text-muted">Preview</p>
              <div className="flex flex-wrap gap-2">
                <span className="rounded bg-bull px-2 py-0.5 text-white">Very Bullish +2</span>
                <span className="rounded bg-bull/60 px-2 py-0.5 text-white">Bullish +1</span>
                <span className="rounded bg-panel-2 px-2 py-0.5 text-muted">Neutral 0</span>
                <span className="rounded bg-bear/60 px-2 py-0.5 text-white">Bearish −1</span>
                <span className="rounded bg-bear px-2 py-0.5 text-white">Very Bearish −2</span>
              </div>
              <p className="mt-2"><span className="text-up">+0.45%</span> · <span className="text-bear-soft">−0.32%</span> · <span className="text-verify">a link</span> · <span className="text-amber">a warning</span></p>
            </div>
          </aside>
        </div>, document.body,
      )}
    </>
  );
}
