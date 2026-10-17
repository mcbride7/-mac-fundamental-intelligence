"use client";

import { useCallback, useEffect, useState } from "react";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
// Login session kept in this browser (set by the login page). The old NEXT_PUBLIC_API_TOKEN still
// works as a fallback so an existing deployment keeps running, but remove it from Railway: anything
// NEXT_PUBLIC_ is readable by anyone who opens the website.
const SESSION_KEY = "mfi_session";
const LEGACY_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

export function getSession(): string {
  if (typeof window === "undefined") return "";
  try { return window.localStorage.getItem(SESSION_KEY) || ""; } catch { return ""; }
}
export function setSession(token: string | null) {
  try {
    if (token) window.localStorage.setItem(SESSION_KEY, token);
    else window.localStorage.removeItem(SESSION_KEY);
  } catch { /* private mode: session lasts this tab only */ }
}
export function logout() {
  setSession(null);
  window.location.href = "/login";
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

function headers(extra?: HeadersInit): HeadersInit {
  const h: Record<string, string> = {};
  const token = getSession() || LEGACY_TOKEN;
  if (token) h["Authorization"] = `Bearer ${token}`;
  return { ...h, ...(extra as Record<string, string>) };
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: headers(isForm ? init?.headers : { "Content-Type": "application/json", ...(init?.headers || {}) }),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/")
      && window.location.pathname !== "/login") {
    setSession(null);
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
  }
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

/** Download a file from the API (with the login session) and save it in the browser. */
export async function download(path: string, fallbackName: string) {
  const res = await fetch(`${API_URL}${path}`, { headers: headers() });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export const post = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) });
export const put = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) });
export const patch = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });

export function useApi<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    load();
  }, [load]);
  return { data, error, loading, reload: load, setData };
}
