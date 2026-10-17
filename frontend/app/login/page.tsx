"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { post, setSession } from "@/lib/api";

function LoginForm() {
  const params = useSearchParams();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ token: string }>("/api/auth/login", { password });
      setSession(r.token);
      const next = params?.get("next");
      window.location.href = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
    } catch (err: any) {
      setError(err?.status === 429 ? err.message : err?.status === 401 ? "Wrong password. Try again." :
        `Can't reach the server (${err?.message || err}).`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-md border border-line bg-panel p-6">
      <h1 className="font-serif text-2xl">Mac Fundamental Intelligence</h1>
      <p className="mt-1 text-sm text-muted">Log in to continue.</p>
      <label htmlFor="password" className="mt-6 block text-sm">Password</label>
      <input id="password" type="password" autoComplete="current-password" autoFocus value={password}
        onChange={(e) => setPassword(e.target.value)}
        className="mt-1 w-full rounded border border-line bg-ink px-3 py-2 text-text" />
      {error && <p role="alert" className="mt-3 text-sm text-hawk">{error}</p>}
      <button type="submit" disabled={busy || !password}
        className="mt-5 w-full rounded bg-verify px-3 py-2 text-sm font-medium text-ink disabled:opacity-60">
        {busy ? "Checking…" : "Log in"}
      </button>
      <p className="mt-4 text-xs text-muted">Stays logged in on this device for 30 days.</p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
