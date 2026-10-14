export const num = (v: number | null | undefined, d = 1, suffix = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toFixed(d)}${suffix}`;

export const signed = (v: number | null | undefined, d = 1, suffix = "") =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}${suffix}`;

export const date = (v: string | null | undefined) => {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

export const dateTime = (v: string | null | undefined) => {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? v
    : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const pair = (a: string) => (a.length === 6 ? `${a.slice(0, 3)}/${a.slice(3)}` : a);

/** Tone class for a hawkish/dovish word or a signed number. */
export function toneClass(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted";
  if (typeof v === "number") return v > 0 ? "text-hawk" : v < 0 ? "text-dove" : "text-muted";
  const s = v.toLowerCase();
  if (s.includes("hawk") || s.includes("upside") || s.includes("restrictive")) return "text-hawk";
  if (s.includes("dov") || s.includes("downside") || s.includes("accommodative")) return "text-dove";
  if (s.includes("mixed")) return "text-amber";
  return "text-muted";
}

export function biasClass(b: string | null | undefined): string {
  if (!b) return "text-muted";
  if (b.includes("BULL") || b === "LONG") return "text-dove";
  if (b.includes("BEAR") || b === "SHORT") return "text-hawk";
  return "text-muted";
}
