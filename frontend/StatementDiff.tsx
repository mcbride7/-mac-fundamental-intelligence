"use client";

import { toneClass } from "@/lib/format";

const BORDER: Record<string, string> = { red: "border-l-hawk", green: "border-l-dove", yellow: "border-l-amber",
  grey: "border-l-line" };

function Diff({ parts, side }: { parts: { op: string; text: string }[]; side: "previous" | "latest" }) {
  return (
    <>
      {parts.map((p, i) => {
        if (p.op === "equal") return <span key={i}>{p.text} </span>;
        if (side === "previous" && p.op === "delete") return <del key={i} className="diff-delete">{p.text} </del>;
        if (side === "latest" && p.op === "insert") return <ins key={i} className="diff-insert no-underline">{p.text} </ins>;
        return null;
      })}
    </>
  );
}

export default function StatementDiff({ changes }: { changes: any[] }) {
  if (!changes?.length) return <p className="text-sm text-muted">No wording changes.</p>;
  return (
    <ol className="space-y-4">
      {changes.map((c, i) => (
        <li key={i} className={`border-l-4 ${BORDER[c.color] || "border-l-line"} rounded-r bg-panel-2/50 p-3`}>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <span className={`font-medium ${toneClass(c.direction)}`}>{c.direction}</span>
            <span className="rounded border border-line px-1.5 py-0.5">{c.importance} importance</span>
            <span className="text-muted">{c.categories.join(", ")}</span>
            <span className="text-muted">{c.type === "modified" ? "Reworded" : c.type === "added" ? "New sentence" : "Removed"}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <div className="mb-1 text-xs text-muted">Previous</div>
              <p className="note text-sm">{c.type === "modified" ? <Diff parts={c.diff} side="previous" /> : (c.previous || <span className="text-muted">—</span>)}</p>
            </div>
            <div>
              <div className="mb-1 text-xs text-muted">Latest</div>
              <p className="note text-sm">{c.type === "modified" ? <Diff parts={c.diff} side="latest" /> : (c.latest || <span className="text-muted">—</span>)}</p>
            </div>
          </div>
          <p className="mt-2 text-sm"><span className="text-muted">What changed: </span>{c.what_changed}</p>
          <p className="mt-1 text-sm text-muted">{c.interpretation}</p>
        </li>
      ))}
    </ol>
  );
}
