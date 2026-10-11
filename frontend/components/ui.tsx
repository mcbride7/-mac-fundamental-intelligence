"use client";

import Link from "next/link";
import type { ReactNode } from "react";

export function Panel({ title, action, children, className = "" }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-md border border-line bg-panel ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[0.95rem] font-medium">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageTitle({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-[70ch] text-sm text-muted">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

const STATUS: Record<string, { label: string; cls: string }> = {
  VERIFIED: { label: "Verified", cls: "border-verify/50 text-verify" },
  USER_CONFIRMED: { label: "User-confirmed", cls: "border-amber/60 text-amber" },
  UNVERIFIED: { label: "Unverified", cls: "border-muted/60 text-muted" },
  CONFLICT: { label: "Conflict", cls: "border-hawk/70 text-hawk" },
  SUPERSEDED: { label: "Superseded", cls: "border-line text-muted" },
  MISSING: { label: "Missing — add data", cls: "border-hawk/70 text-hawk" },
  SCHEDULED: { label: "Scheduled", cls: "border-line text-muted" },
};

/** Verification badge. Shape + text, never colour alone. */
export function StatusBadge({ status, title }: { status?: string | null; title?: string | null }) {
  if (!status) return null;
  const s = STATUS[status] || { label: status, cls: "border-line text-muted" };
  const icon = status === "VERIFIED" ? "✓" : status === "CONFLICT" ? "!" : status === "USER_CONFIRMED" ? "◐" : "○";
  return (
    <span title={title || s.label}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-xs ${s.cls}`}>
      <span aria-hidden>{icon}</span>{s.label}
    </span>
  );
}

export function GradeBadge({ grade }: { grade?: string | null }) {
  if (!grade) return <span className="text-muted">—</span>;
  const cls = grade === "NO TRADE" ? "border-line text-muted" : grade.startsWith("A") ? "border-dove text-dove"
    : "border-amber/70 text-amber";
  return <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${cls}`}>{grade}</span>;
}

/** The signature element: a dovish→hawkish spectrum with a marker for the policy score. */
export function PolicyDial({ score, previous, compact = false }: { score?: number | null; previous?: number | null;
  compact?: boolean }) {
  if (score === null || score === undefined) return <span className="text-sm text-muted">No score yet</span>;
  return (
    <div className={compact ? "w-40" : "w-full"} role="img"
      aria-label={`Policy score ${score.toFixed(0)} of 100, where 0 is extremely dovish and 100 extremely hawkish`}>
      <div className="relative h-2.5 rounded-full"
        style={{ background: "linear-gradient(90deg, var(--color-dove), #4d6a86 50%, var(--color-hawk))" }}>
        {previous !== null && previous !== undefined && (
          <span className="absolute -top-1 h-4.5 w-0.5 bg-text/40" style={{ left: `calc(${previous}% - 1px)` }}
            title={`Previous ${previous.toFixed(0)}`} />
        )}
        <span className="absolute -top-1.5 h-5.5 w-1.5 rounded-sm bg-text shadow-[0_0_0_2px_var(--color-ink)]"
          style={{ left: `calc(${score}% - 3px)` }} />
      </div>
      {!compact && (
        <div className="mt-1 flex justify-between text-[0.7rem] text-muted"><span>Dovish</span><span>Neutral</span>
          <span>Hawkish</span></div>
      )}
    </div>
  );
}

export function Stat({ label, value, sub, tone = "" }: { label: string; value: ReactNode; sub?: ReactNode;
  tone?: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-medium ${tone}`}>{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="text-sm text-muted">{what}…</p>;
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded border border-hawk/60 bg-hawk/10 px-3 py-2 text-sm">
      {error}. Check that the API is running at the configured address.
    </div>
  );
}

export function Empty({ children, href, cta }: { children: ReactNode; href?: string; cta?: string }) {
  return (
    <div className="rounded border border-dashed border-line px-4 py-6 text-sm text-muted">
      {children}
      {href && cta && (
        <div className="mt-3">
          <Link href={href} className="rounded bg-verify/15 px-3 py-1.5 text-verify hover:bg-verify/25">{cta}</Link>
        </div>
      )}
    </div>
  );
}

export function Button({ children, onClick, kind = "primary", disabled, type = "button" }: {
  children: ReactNode; onClick?: () => void; kind?: "primary" | "ghost" | "danger"; disabled?: boolean;
  type?: "button" | "submit";
}) {
  const cls = kind === "primary" ? "bg-verify text-ink hover:bg-verify/90" : kind === "danger"
    ? "border border-hawk/60 text-hawk hover:bg-hawk/10" : "border border-line text-text hover:bg-panel-2";
  return (
    <button type={type} disabled={disabled} onClick={onClick}
      className={`rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${cls}`}>{children}</button>
  );
}

export function Disclaimer() {
  return (
    <p className="mt-8 text-xs text-muted">
      Decision-support research only. Not investment advice. No outcome is guaranteed and nothing is executed
      automatically.
    </p>
  );
}
