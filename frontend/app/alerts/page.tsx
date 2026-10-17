"use client";

import { useState } from "react";

import { Button, Empty, ErrorBox, Loading, PageTitle } from "@/components/ui";
import { post, useApi } from "@/lib/api";
import { dateTime } from "@/lib/format";

const KINDS = ["", "economic_surprise", "forecast_miss", "forecast_revision", "statement_change", "policy_shift", "cb_surprise",
  "rate_repricing", "divergence_change", "bias_change", "scenario_probability", "high_conviction_setup", "thesis_invalidation",
  "market_wrong", "data_conflict", "source_failure", "missing_data", "yield_move", "regime_change", "watchlist"];

const SEV: Record<string, string> = { CRITICAL: "border-l-hawk", HIGH: "border-l-hawk", MEDIUM: "border-l-amber", LOW: "border-l-line" };

function PhoneAlerts() {
  const { data, reload } = useApi<any>("/api/notifications");
  const [msg, setMsg] = useState<string | null>(null);
  const test = async () => {
    setMsg("Sending…");
    try { await post("/api/notifications/test"); setMsg("Sent. Check Telegram."); reload(); }
    catch (e: any) { setMsg(e?.message || String(e)); }
  };
  if (!data) return null;
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded border border-line bg-panel px-3 py-2 text-sm">
      <span>
        <span className={data.configured ? "text-dove" : "text-muted"}>{data.configured ? "● Phone alerts on (Telegram)" : "○ Phone alerts off"}</span>
        {data.configured
          ? <span className="text-muted"> · important alerts are sent within 2 minutes{data.last_status === "failed" ? ` · last send failed: ${data.last_error}` : ""}</span>
          : <span className="text-muted"> · add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway to get alerts on your phone</span>}
      </span>
      <span className="flex items-center gap-3">
        {msg && <span className="text-xs text-muted">{msg}</span>}
        {data.configured && <Button kind="ghost" onClick={test}>Send test message</Button>}
      </span>
    </div>
  );
}

export default function Alerts() {
  const [kind, setKind] = useState("");
  const [unread, setUnread] = useState(false);
  const { data, error, loading, reload } = useApi<any>(`/api/alerts?limit=200${kind ? `&kind=${kind}` : ""}${unread ? "&unread=true" : ""}`);
  return (
    <>
      <PageTitle title="Alerts" subtitle={data ? `${data.unread} unread` : undefined}>
        <div className="flex flex-wrap items-center gap-3">
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Alert type" className="rounded border border-line bg-panel px-2 py-1 text-sm">
            {KINDS.map((k) => <option key={k} value={k}>{k ? k.replaceAll("_", " ") : "All types"}</option>)}
          </select>
          <label className="text-sm"><input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} className="mr-1" />Unread only</label>
          <Button kind="ghost" onClick={async () => { await post("/api/alerts/read-all"); reload(); }}>Mark all read</Button>
        </div>
      </PageTitle>
      <PhoneAlerts />
      <ErrorBox error={error} />
      {loading && !data ? <Loading /> : !data?.alerts.length ? <Empty>No alerts.</Empty> : (
        <ul className="space-y-2">{data.alerts.map((a: any) => (
          <li key={a.id} className={`rounded-r border-l-4 ${SEV[a.severity] || "border-l-line"} bg-panel p-3 ${a.is_read ? "opacity-70" : ""}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">{a.title}</span>
              <span className="text-xs text-muted">{a.kind.replaceAll("_", " ")}, {a.severity.toLowerCase()}, {dateTime(a.created_at)}</span>
            </div>
            {a.body && <p className="mt-1 text-sm text-muted">{a.body}</p>}
            {!a.is_read && <button className="mt-1 text-xs text-verify" onClick={async () => { await post(`/api/alerts/${a.id}/read`); reload(); }}>Mark read</button>}
          </li>))}</ul>
      )}
    </>
  );
}
