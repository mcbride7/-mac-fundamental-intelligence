"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

export type NavItem = { href: string; label: string };
type Saved = { order: string[]; hidden: string[] };
const KEY = "mfi-nav";

/** Saved order, with pages added to the site later slotted in where they sit by default. */
export function arrange(nav: NavItem[], saved: Saved | null): NavItem[] {
  if (!saved?.order?.length) return nav;
  const byHref = new Map(nav.map((n) => [n.href, n]));
  const out = saved.order.filter((h) => byHref.has(h));
  nav.forEach((n, i) => {
    if (out.includes(n.href)) return;
    const prev = nav.slice(0, i).reverse().find((p) => out.includes(p.href));
    out.splice(prev ? out.indexOf(prev.href) + 1 : 0, 0, n.href);
  });
  return out.map((h) => byHref.get(h)!);
}

function load(): Saved | null {
  try { const s = localStorage.getItem(KEY); return s ? JSON.parse(s) : null; } catch { return null; }
}
function store(s: Saved | null) {
  try { if (s) localStorage.setItem(KEY, JSON.stringify(s)); else localStorage.removeItem(KEY); } catch { /* ignore */ }
}

/** Side menu you can rearrange (drag, or the arrows), hide items from, and lock. */
export default function NavMenu({ nav, active, onNavigate }: { nav: NavItem[]; active: (href: string) => boolean; onNavigate: () => void }) {
  const [saved, setSaved] = useState<Saved | null>(null);
  const [editing, setEditing] = useState(false);
  const [drag, setDrag] = useState<string | null>(null);
  useEffect(() => { setSaved(load()); }, []);

  const items = arrange(nav, saved);
  const hidden = new Set(saved?.hidden || []);
  const update = (order: string[], hid: string[]) => { const s = { order, hidden: hid }; setSaved(s); store(s); };
  const move = (href: string, to: number) => {
    const order = items.map((n) => n.href).filter((h) => h !== href);
    order.splice(Math.max(0, Math.min(order.length, to)), 0, href);
    update(order, [...hidden]);
  };
  const toggleHide = (href: string) =>
    update(items.map((n) => n.href), hidden.has(href) ? [...hidden].filter((h) => h !== href) : [...hidden, href]);
  const reset = () => { setSaved(null); store(null); };

  if (!editing) {
    return (
      <>
        <nav aria-label="Main" className="flex flex-col px-2 pb-3">
          {items.filter((n) => !hidden.has(n.href) || active(n.href)).map((n) => (
            <Link key={n.href} href={n.href} onClick={onNavigate}
              className={`rounded px-3 py-1.5 text-sm ${active(n.href) ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="px-4 pb-3">
          <button onClick={() => setEditing(true)} title="Menu order is locked. Tap to rearrange or hide items."
            className="text-xs text-muted hover:text-text">🔒 Menu locked · <span className="underline decoration-dotted">arrange</span></button>
          {hidden.size > 0 && <span className="ml-1 text-xs text-muted">({hidden.size} hidden)</span>}
        </div>
      </>
    );
  }

  return (
    <div className="px-2 pb-3">
      <p className="mb-2 rounded bg-panel-2 px-2 py-1.5 text-xs text-muted">Drag items (or use ▲ ▼) into the order you like. 👁 hides an item. Press <b>Lock</b> when done.</p>
      <ol aria-label="Arrange the menu" className="flex flex-col gap-0.5">
        {items.map((n, i) => (
          <li key={n.href} draggable
            onDragStart={(e) => { setDrag(n.href); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
            onDrop={(e) => { e.preventDefault(); if (drag && drag !== n.href) move(drag, i); setDrag(null); }}
            onDragEnd={() => setDrag(null)}
            className={`flex items-center gap-1 rounded border px-1.5 py-1 text-sm ${drag === n.href ? "border-verify opacity-50" : "border-line"} ${hidden.has(n.href) ? "text-muted line-through" : ""}`}>
            <span aria-hidden className="cursor-grab select-none px-0.5 text-muted">⠿</span>
            <span className="min-w-0 flex-1 truncate">{n.label}</span>
            <button onClick={() => move(n.href, i - 1)} disabled={i === 0} aria-label={`Move ${n.label} up`}
              className="rounded px-1 text-xs text-muted hover:bg-panel-2 hover:text-text disabled:opacity-30">▲</button>
            <button onClick={() => move(n.href, i + 1)} disabled={i === items.length - 1} aria-label={`Move ${n.label} down`}
              className="rounded px-1 text-xs text-muted hover:bg-panel-2 hover:text-text disabled:opacity-30">▼</button>
            <button onClick={() => toggleHide(n.href)} aria-label={hidden.has(n.href) ? `Show ${n.label}` : `Hide ${n.label}`}
              title={hidden.has(n.href) ? "Hidden: tap to show" : "Tap to hide"}
              className={`rounded px-1 text-xs hover:bg-panel-2 ${hidden.has(n.href) ? "opacity-40" : ""}`}>👁</button>
          </li>
        ))}
      </ol>
      <div className="mt-2 flex gap-2">
        <button onClick={() => setEditing(false)} className="flex-1 rounded bg-verify px-2 py-1.5 text-sm font-medium text-ink hover:bg-verify/90">🔒 Lock</button>
        <button onClick={reset} className="rounded border border-line px-2 py-1.5 text-sm text-muted hover:text-text">Reset</button>
      </div>
    </div>
  );
}
