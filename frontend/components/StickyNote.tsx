"use client";

import { useState } from "react";
import type { ReactNode } from "react";

import { useCollapsed } from "@/components/ui";

export const NOTE_BG = "#fff1a8", NOTE_INK = "#3b3410";

/** Yellow sticky note (pin, fold-away × remembered per browser, optional "more" section that hangs below). */
export default function StickyNote({ id, title, folded: foldedLabel, children, more, moreLabel = "More ▸",
  lessLabel = "Hide", hang = true }: {
  id: string; title: string; folded: string; children: ReactNode; more?: ReactNode; moreLabel?: string; lessLabel?: string;
  /** false inside panels that clip overflow: the extra part then opens inside the note */
  hang?: boolean;
}) {
  const [folded, toggle] = useCollapsed(id);
  const [open, setOpen] = useState(false);
  if (folded) {
    return (
      <button onClick={toggle} title={`Show: ${title}`}
        className="rounded px-3 py-1.5 text-xs font-semibold shadow-md" style={{ background: NOTE_BG, color: NOTE_INK }}>
        📌 {foldedLabel}
      </button>
    );
  }
  return (
    <aside aria-label={title} className="relative w-full rounded-sm p-3 pt-4 text-xs leading-snug shadow-lg sm:w-[22rem] sm:rotate-1"
      style={{ background: NOTE_BG, color: NOTE_INK }}>
      <span aria-hidden className="absolute -top-2 left-1/2 -translate-x-1/2 text-base">📌</span>
      <button onClick={toggle} title="Fold the note away" aria-label="Fold the note away"
        className="absolute right-1.5 top-1 rounded px-1.5 text-sm font-bold opacity-60 hover:opacity-100">×</button>
      <p className="mb-1.5 font-semibold">{title}</p>
      {children}
      {more && (
        <>
          <button onClick={() => setOpen(!open)} className="mt-2 font-semibold underline decoration-dotted underline-offset-2">
            {open ? lessLabel : moreLabel}</button>
          {open && (
            // on wider screens the extra part hangs below the note over the content, so the page doesn't jump
            <div className={hang ? "mt-1.5 sm:absolute sm:left-0 sm:right-0 sm:top-full sm:z-20 sm:mt-0 sm:rounded-b-sm sm:p-3 sm:pt-1 sm:shadow-lg" : "mt-1.5"}
              style={{ background: NOTE_BG }}>{more}</div>
          )}
        </>
      )}
    </aside>
  );
}
