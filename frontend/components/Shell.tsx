"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { api, logout } from "@/lib/api";

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Home" },
  { href: "/markets", label: "Markets" },
  { href: "/central-banks", label: "Central banks" },
  { href: "/calendar", label: "Economic calendar" },
  { href: "/macro", label: "Macro" },
  { href: "/currencies", label: "Currencies" },
  { href: "/bonds", label: "Bonds" },
  { href: "/scenarios", label: "Scenarios" },
  { href: "/analysis", label: "Fundamental analysis" },
  { href: "/research", label: "AI research" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/alerts", label: "Alerts" },
  { href: "/data-input", label: "Data input" },
  { href: "/data-health", label: "Data health" },
];

type Health = { overall: string; unverified: number; user_confirmed_awaiting: number; conflicts: number;
  missing_scheduled: unknown[]; sources: { needs_manual_input: boolean }[] };

function DataStatus() {
  const [h, setH] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () => api<Health>("/api/data-health").then((d) => alive && (setH(d), setDown(false)))
      .catch(() => alive && setDown(true));
    load();
    const t = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (down) return <Link href="/data-health" className="text-sm text-hawk">API unreachable</Link>;
  if (!h) return <span className="text-sm text-muted">Checking data…</span>;
  const failing = h.sources.filter((s) => s.needs_manual_input).length;
  const issues = [
    failing && `${failing} feed${failing > 1 ? "s" : ""} down`,
    h.missing_scheduled.length && `${h.missing_scheduled.length} missing release${h.missing_scheduled.length > 1 ? "s" : ""}`,
    h.conflicts && `${h.conflicts} conflict${h.conflicts > 1 ? "s" : ""}`,
    h.unverified && `${h.unverified} unverified`,
  ].filter(Boolean);
  const dot = h.overall === "OK" ? "bg-dove" : h.overall === "DEGRADED" ? "bg-hawk" : "bg-amber";
  return (
    <Link href="/data-health" className="flex items-center gap-2 text-sm text-muted hover:text-text">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span>{issues.length ? issues.join(", ") : "All data current"}</span>
    </Link>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const [open, setOpen] = useState(false);
  if (path === "/login") return <main className="mx-auto max-w-md px-4 py-16">{children}</main>;
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className={`${open ? "block" : "hidden"} border-r border-line bg-ink lg:block`}>
        <div className="px-5 pb-4 pt-5">
          <Link href="/" className="block leading-tight">
            <span className="font-serif text-lg">Mac Fundamental</span>
            <span className="block text-sm text-muted">Intelligence</span>
          </Link>
        </div>
        <nav aria-label="Main" className="flex flex-col px-2 pb-6">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)}
              className={`rounded px-3 py-1.5 text-sm ${active(n.href) ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>
              {n.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-ink/95 px-4 py-2.5 backdrop-blur lg:px-8">
          <button className="rounded border border-line px-2 py-1 text-sm lg:hidden" onClick={() => setOpen(!open)}
            aria-expanded={open}>Menu</button>
          <DataStatus />
          <div className="flex items-center gap-2">
            <Link href="/data-input" className="whitespace-nowrap rounded bg-verify px-3 py-1.5 text-sm font-medium text-ink hover:bg-verify/90">
              + Add data
            </Link>
            <button type="button" onClick={logout} className="rounded border border-line px-2 py-1.5 text-sm text-muted hover:text-text">
              Log out
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
