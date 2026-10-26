# COT Positioning Tracker

Weekly CFTC Commitments of Traders positioning for 19 macro futures markets, with price, charts and a stored weekly history.

- **Live tracker:** https://claude.ai/artifact/NJxvfy9teZphCYKtvwdjzu (private; open it signed in to claude.ai)
- **Report used:** CFTC Legacy, futures only. Positions are as of Tuesday and published Friday 3:30 pm US Eastern (21:30 SA time).
- **History stored:** 7 Jan 2025 to 13 Oct 2026, 93 weeks per market (exported 26 Oct 2026).

## What's in this folder

| Path | What it is |
|---|---|
| `app/cot-tracker.html` | Source of the tracker page. It runs inside claude.ai, which supplies the data store and the FMP / Alpha Vantage connections. Opened as a plain file it shows the layout but no data. |
| `data/markets/<code>.json` | One file per market: every stored week, plus price where one has been saved. |
| `data/cot_weekly_all_markets.csv` | Every market and week in one table. Opens in Excel or Google Sheets. |
| `data/latest_snapshot.csv` | Latest week per market: spec net, weekly change, commercial net, open interest, 52-week COT index. |
| `scripts/build_from_cftc_files.py` | Rebuilds `data/markets` from the CFTC's yearly history zips. Keeps any prices already saved. |
| `scripts/export_to_csv.py` | Regenerates the two CSVs from `data/markets`. |
| `automation/weekly-update-task.md` | The scheduled task that adds each new COT week, its schedule and how to fix it. |
| `docs/trading-notes.md` | How the data is read for trading, and its limits. |

## Field names in the market files

`d` report date (Tuesday) · `oi` open interest · `ncl`/`ncs` non-commercial (speculator) long/short · `cl`/`cs` commercial long/short · `nrl`/`nrs` non-reportable (small trader) long/short · `px` price · `pxs` price source (`FMP`, `Alpha Vantage`, or `manual` for typed in). Net = long minus short. All positions are in contracts.

## Markets, CFTC codes and price sources

| Market | CFTC code | Price source (in order) | Price shown as |
|---|---|---|---|
| Gold | 088691 | FMP → Alpha Vantage (spot) | USD per oz |
| Silver | 084691 | FMP → Alpha Vantage (spot) | USD per oz |
| Copper | 085692 | Hand entry | |
| WTI crude oil | 067651 | Alpha Vantage | USD per barrel, WTI spot |
| Natural gas (Henry Hub) | 023651 | Alpha Vantage | USD per MMBtu, spot |
| Euro | 099741 | FMP → Alpha Vantage | USD per EUR |
| Japanese yen | 097741 | FMP → Alpha Vantage | USD per JPY (USD/JPY inverted) |
| British pound | 096742 | FMP → Alpha Vantage | USD per GBP |
| Australian dollar | 232741 | FMP → Alpha Vantage | USD per AUD |
| Canadian dollar | 090741 | FMP → Alpha Vantage | USD per CAD (USD/CAD inverted) |
| Swiss franc | 092741 | FMP → Alpha Vantage | USD per CHF (USD/CHF inverted) |
| South African rand | 122741 | Alpha Vantage | USD per ZAR (USD/ZAR inverted) |
| US dollar index | 098662 | Hand entry | |
| S&P 500 E-mini | 13874A | FMP | Index points |
| Nasdaq-100 E-mini | 209742 | Alpha Vantage (QQQ ETF stand-in) | USD per QQQ share |
| 10-year T-note | 043602 | Alpha Vantage | 10-year yield in %; moves opposite to T-note prices |
| Bitcoin (CME) | 133741 | FMP → Alpha Vantage | USD |
| Corn | 002602 | Hand entry | |
| Soybeans | 005602 | Hand entry | |

Currencies are shown so that a rising line means that currency is strengthening, the same direction as a speculator long in its futures.

## How the tracker stays up to date

1. **New COT weeks:** a weekly scheduled task fetches the newest week from the CFTC and saves it (see `automation/`).
2. **Prices:** each time the tracker is opened by someone who can edit it, it fills missing weekly prices from FMP, then Alpha Vantage. Each market is checked at most every 12 hours. The first run needs a tap on **Update prices now** under "Prices and data sources" to approve both connectors.
3. **By hand:** any week can be edited or added in the weekly ledger, and prices can be pasted as `date, price` lines. Hand-entered values are never overwritten by a fetch.

## Plan limits found during setup (20 Oct 2026)

- FMP (current plan): no COT reports; no copper, WTI, natural gas, dollar index, Nasdaq, 10-year, corn, soybeans or rand prices. Premium would add these.
- Alpha Vantage (free plan): 25 requests per day; copper and corn are monthly only; no soybeans or dollar index.

## Rebuilding from CFTC files

```
cd scripts
python build_from_cftc_files.py deacot2025.zip deacot2026.zip --out ../data/markets
python export_to_csv.py --in ../data/markets --out ../data
```

Files: https://www.cftc.gov/files/dea/history/deacot2025.zip and https://www.cftc.gov/files/dea/history/deacot2026.zip (the 2026 file is refreshed every Friday).
