"use client";

type Cell = { symbol: string; diff: number };
type Heatmap = { currencies: string[]; matrix: Record<string, Record<string, Cell>> };

function cellClass(d: number) {
  if (d >= 8) return "bg-dove/45";
  if (d >= 3) return "bg-dove/20";
  if (d <= -8) return "bg-hawk/45";
  if (d <= -3) return "bg-hawk/20";
  return "";
}

/** Row currency vs column currency: + means the row currency has stronger fundamentals. */
export default function CurrencyMatrix({ heatmap, compact = false }: { heatmap: Heatmap | null; compact?: boolean }) {
  if (!heatmap || heatmap.currencies.length === 0)
    return <p className="text-sm text-muted">No currency scores yet.</p>;
  const c = compact ? heatmap.currencies.slice(0, 10) : heatmap.currencies;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-center text-xs">
        <caption className="mb-2 text-left text-xs text-muted">Row vs column. “+” = row currency fundamentally stronger.</caption>
        <thead>
          <tr><th className="p-1" />{c.map((x) => <th key={x} className="p-1 font-medium text-muted">{x}</th>)}</tr>
        </thead>
        <tbody>
          {c.map((row) => (
            <tr key={row}>
              <th className="p-1 text-left font-medium text-muted">{row}</th>
              {c.map((col) => {
                const cell = heatmap.matrix[row]?.[col];
                return (
                  <td key={col} title={cell ? `${row} vs ${col}: ${cell.diff > 0 ? "+" : ""}${cell.diff}` : ""}
                    className={`border border-ink p-1.5 ${cell ? cellClass(cell.diff) : ""}`}>
                    {cell?.symbol ?? ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
