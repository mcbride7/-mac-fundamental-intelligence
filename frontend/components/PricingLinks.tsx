"use client";

const CME = { label: "CME FedWatch", sub: "Fed odds from Fed Funds futures, updates through the day",
  url: "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html" };
const ASX = { label: "ASX RBA Rate Tracker", sub: "RBA odds from ASX cash rate futures, each trading day",
  url: "https://www.asx.com.au/markets/trade-our-derivatives-market/futures-market/rba-rate-tracker" };
const CBW_PAGE: Record<string, string> = {
  FED: "federal-reserve", ECB: "european-central-bank", BOE: "bank-of-england", BOJ: "bank-of-japan",
  SNB: "swiss-national-bank", BOC: "bank-of-canada", RBA: "reserve-bank-of-australia",
  RBNZ: "reserve-bank-of-new-zealand", PBOC: "peoples-bank-of-china",
};

/** Quick links to where the market's rate odds are published, best source for this bank first. */
export default function PricingLinks({ code, name }: { code: string; name?: string }) {
  const page = CBW_PAGE[code];
  const cbw = {
    label: `centralbank.watch${page ? `: ${name || code}` : ""}`,
    sub: page ? "Market-implied odds for this bank, about daily" : "Market-implied odds for most major banks (this bank isn't covered)",
    url: page ? `https://centralbank.watch/${page}/` : "https://centralbank.watch/central-banks/",
  };
  const links = code === "FED" ? [CME, cbw, ASX] : code === "RBA" ? [ASX, cbw, CME] : [cbw, CME, ASX];
  return (
    <div>
      <ul className="grid gap-2 sm:grid-cols-3">
        {links.map((l, i) => (
          <li key={l.url}>
            <a href={l.url} target="_blank" rel="noreferrer"
              className={`block h-full rounded border px-3 py-2 hover:bg-panel-2 ${i === 0 ? "border-verify" : "border-line"}`}>
              <span className="font-medium text-verify">{l.label} ↗</span>
              {i === 0 && <span className="ml-1.5 rounded bg-verify/20 px-1.5 py-px text-[0.65rem] text-verify">best for {code}</span>}
              <span className="mt-0.5 block text-xs text-muted">{l.sub}</span>
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">Open the page, then type the cut / hold / hike odds below, or screenshot them into Data input. Typed odds replace the yield-based estimate.</p>
    </div>
  );
}
