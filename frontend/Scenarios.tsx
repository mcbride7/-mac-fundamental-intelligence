"use client";

const KIND: Record<string, string> = { base: "Base case", bullish: "Bullish alternative", bearish: "Bearish alternative",
  risk: "Risk scenario" };

export default function Scenarios({ scenarios }: { scenarios: any[] }) {
  if (!scenarios?.length) return <p className="text-sm text-muted">No scenarios yet.</p>;
  return (
    <div className="space-y-4">
      <div className="flex h-3 overflow-hidden rounded" role="img" aria-label="Scenario probabilities">
        {scenarios.map((s) => (
          <span key={s.kind} title={`${KIND[s.kind]} ${s.probability}%`} style={{ width: `${s.probability}%` }}
            className={s.kind === "risk" ? "bg-amber/70" : s.direction === "up" ? "bg-dove/70" : "bg-hawk/70"} />
        ))}
      </div>
      {scenarios.map((s) => {
        const trig = (t: string) => (s.triggers || []).filter((x: any) => x.trigger_type === t);
        return (
          <article key={s.kind} className="rounded border border-line bg-panel-2/40 p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="font-medium">{KIND[s.kind] || s.kind}: {s.title}</h3>
              <span className="whitespace-nowrap text-lg">{s.probability}%
                <span className={`ml-2 text-sm ${s.direction === "up" ? "text-dove" : "text-hawk"}`}>{s.direction === "up" ? "▲" : "▼"}</span></span>
            </div>
            <p className="note mt-1 text-sm text-muted">{s.narrative}</p>
            <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
              {(["activation", "confirmation", "invalidation"] as const).map((t) => (
                <div key={t}>
                  <div className="text-xs text-muted">{t === "activation" ? "What needs to happen" : t === "confirmation" ? "Confirms it" : "Invalidates it"}</div>
                  <ul className="mt-1 space-y-1">
                    {trig(t).length ? trig(t).map((x: any, i: number) => (
                      <li key={i}>{x.description}{x.status && x.status !== "pending" &&
                        <span className={`ml-1 text-xs ${x.status === "met" ? (t === "invalidation" ? "text-hawk" : "text-dove") : "text-muted"}`}>({x.status.replace("_", " ")})</span>}</li>
                    )) : <li className="text-muted">—</li>}
                  </ul>
                </div>
              ))}
            </div>
          </article>
        );
      })}
    </div>
  );
}
