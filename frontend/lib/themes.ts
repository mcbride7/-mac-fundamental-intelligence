/** Colour themes ("moods"). Each sets every colour token in globals.css; the choice is kept per browser. */

export type Vars = Record<string, string>;
export type Theme = { id: string; name: string; mood: string; scheme: "dark" | "light"; vars: Vars };

export const KEYS = ["ink", "panel", "panel-2", "line", "text", "muted", "verify", "amber", "hawk", "dove", "bull", "bear",
  "bull-soft", "bear-soft", "up", "good", "bad", "line-a", "line-b"] as const;

const v = (a: string[]): Vars => Object.fromEntries(KEYS.map((k, i) => [k, a[i]]));

export const THEMES: Theme[] = [
  { id: "navy", name: "Calm navy", mood: "The default. Steady and balanced for everyday analysis.", scheme: "dark",
    vars: v(["#0f1c2e", "#15263d", "#1b3049", "#2a4060", "#e7ebf0", "#93a1b5", "#6fa8e6", "#e2b14a", "#e0605e", "#3db58a",
      "#3d4fd6", "#e45d5d", "#9aa6ff", "#ff8a8a", "#9ccc65", "#43a047", "#e53935", "#5b8def", "#e2a03f"]) },
  { id: "focus", name: "Focus slate", mood: "Neutral grey with blue / orange signals. Least alarming, colour-blind friendly. Good for decisions.", scheme: "dark",
    vars: v(["#16191d", "#1d2127", "#252a31", "#353c46", "#e6e8eb", "#9aa3ad", "#7fb2e5", "#e3b25a", "#e08a4f", "#4fa3d9",
      "#3b7dd8", "#e07b39", "#8fb8ef", "#f2a774", "#7fc8a9", "#3a9d7c", "#d9822b", "#5b9be8", "#e9b44c"]) },
  { id: "night", name: "Deep night", mood: "Near-black, softer contrast and dimmer colours. Easy on the eyes late at night.", scheme: "dark",
    vars: v(["#0a0b0d", "#111317", "#171a1f", "#262a31", "#cfd3d8", "#7f8791", "#6c93c4", "#c9a14c", "#c86b67", "#4f9c80",
      "#4058b8", "#b85a5a", "#8e9bd9", "#d98c8c", "#8fb36a", "#3f8a46", "#b84a46", "#5778b8", "#c08a3a"]) },
  { id: "forest", name: "Forest calm", mood: "Deep green with teal and coral. Relaxed and grounded when the market is stressful.", scheme: "dark",
    vars: v(["#0f1f1b", "#142a25", "#1a342e", "#2a4a42", "#e4ece8", "#93aaa2", "#6cc4b0", "#e0b45e", "#e07a6a", "#4fbf9a",
      "#2f9e8f", "#e0806a", "#8fe0d0", "#f4ac9c", "#a6d48a", "#3fa07a", "#d8664f", "#5fb8c9", "#e6b450"]) },
  { id: "classic", name: "Classic trader", mood: "Navy with green for bullish and red for bearish, like most trading platforms.", scheme: "dark",
    vars: v(["#0f1c2e", "#15263d", "#1b3049", "#2a4060", "#e7ebf0", "#93a1b5", "#6fa8e6", "#e2b14a", "#e0605e", "#3db58a",
      "#2e9e5b", "#d64545", "#7fd6a0", "#ff8a8a", "#9ccc65", "#43a047", "#e53935", "#5b8def", "#e2a03f"]) },
  { id: "paper", name: "Paper light", mood: "Bright and clear for daytime, like reading a report.", scheme: "light",
    vars: v(["#f4f6f8", "#ffffff", "#eef1f5", "#d5dbe3", "#1b2430", "#5d6b7c", "#2563b8", "#a86a00", "#c0392b", "#1e8a64",
      "#2f45c4", "#d0453f", "#2f45c4", "#b8322b", "#2e7d32", "#2e8b3e", "#c62828", "#2f6fd1", "#c27a10"]) },
  { id: "sand", name: "Warm sand", mood: "Soft warm light background. Gentle, like paper in the sun.", scheme: "light",
    vars: v(["#f5efe4", "#fbf7f0", "#efe6d6", "#ddd0bb", "#2d261c", "#6e6352", "#3d6fa8", "#a36a10", "#b5503a", "#3f8a6a",
      "#3c5aa8", "#c0563e", "#34508f", "#a8452f", "#4f7d2a", "#4a8a3c", "#b8442f", "#3d6fa8", "#b07a1e"]) },
];

export const STORAGE = "mfi-theme";

export type Saved = { id: string; scheme: "dark" | "light"; vars: Vars; custom?: Partial<Record<CustomKey, string>> };
export type CustomKey = "ink" | "panel" | "text" | "verify" | "bull" | "bear";
export const CUSTOM_FIELDS: [CustomKey, string][] = [["ink", "Background"], ["panel", "Panels"], ["text", "Text"],
  ["verify", "Links and highlights"], ["bull", "Bullish"], ["bear", "Bearish"]];

function hex(c: string): [number, number, number] {
  const h = c.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}
export function mix(a: string, b: string, t: number): string {  // t = share of b
  const x = hex(a), y = hex(b);
  return "#" + x.map((c, i) => Math.round(c * (1 - t) + y[i] * t).toString(16).padStart(2, "0")).join("");
}
export function isLight(c: string): boolean {
  const [r, g, b] = hex(c);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
}

/** A custom theme: a preset as the base, the chosen colours on top, and the in-between shades worked out. */
export function customVars(base: Theme, c: Partial<Record<CustomKey, string>>): { vars: Vars; scheme: "dark" | "light" } {
  const out = { ...base.vars, ...Object.fromEntries(Object.entries(c).filter(([, x]) => !!x)) } as Vars;
  if (c.panel || c.text || c.ink) {
    out["panel-2"] = mix(out.panel, out.text, 0.06);
    out.line = mix(out.panel, out.text, 0.18);
    out.muted = mix(out.text, out.ink, 0.38);
  }
  if (c.bull) out["bull-soft"] = mix(out.bull, out.text, 0.45);
  if (c.bear) out["bear-soft"] = mix(out.bear, out.text, 0.4);
  return { vars: out, scheme: isLight(out.ink) ? "light" : "dark" };
}

export function apply(vars: Vars, scheme: "dark" | "light") {
  const r = document.documentElement;
  for (const [k, val] of Object.entries(vars)) r.style.setProperty(`--color-${k}`, val);
  r.style.setProperty("color-scheme", scheme);
  r.dataset.theme = scheme;
}

export function load(): Saved | null {
  try { const s = localStorage.getItem(STORAGE); return s ? JSON.parse(s) : null; } catch { return null; }
}
export function save(s: Saved | null) {
  try { if (s) localStorage.setItem(STORAGE, JSON.stringify(s)); else localStorage.removeItem(STORAGE); } catch { /* ignore */ }
}

/** Runs in <head> before the page paints, so a saved theme shows without a flash of the default colours. */
export const EARLY_SCRIPT = `try{var s=JSON.parse(localStorage.getItem("${STORAGE}")||"null");if(s&&s.vars){var r=document.documentElement;for(var k in s.vars){r.style.setProperty("--color-"+k,s.vars[k])}r.style.setProperty("color-scheme",s.scheme||"dark");r.dataset.theme=s.scheme||"dark"}}catch(e){}`;
