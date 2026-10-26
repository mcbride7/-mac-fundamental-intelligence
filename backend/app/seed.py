"""Reference data: central banks, source registry, indicator catalogue.
Idempotent — safe to run on every start. Add new banks/indicators here without
changing any other code (Section 3: extensible without redesign)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CentralBank, Indicator, Source, SourceHealth, User, UserTrustSettings

CENTRAL_BANKS = [
    # code, name, short, country, currency, website, inflation target, published projection variables
    ("FED", "Federal Reserve", "Fed", "US", "USD", "https://www.federalreserve.gov", 2.0,
     ["gdp", "inflation", "core_inflation", "unemployment", "policy_rate"]),
    ("ECB", "European Central Bank", "ECB", "EA", "EUR", "https://www.ecb.europa.eu", 2.0,
     ["gdp", "inflation", "core_inflation", "unemployment"]),
    ("BOE", "Bank of England", "BoE", "GB", "GBP", "https://www.bankofengland.co.uk", 2.0,
     ["gdp", "inflation", "unemployment"]),
    ("BOJ", "Bank of Japan", "BoJ", "JP", "JPY", "https://www.boj.or.jp/en", 2.0,
     ["gdp", "inflation", "core_inflation"]),
    ("SNB", "Swiss National Bank", "SNB", "CH", "CHF", "https://www.snb.ch/en", 1.0, ["inflation"]),
    ("BOC", "Bank of Canada", "BoC", "CA", "CAD", "https://www.bankofcanada.ca", 2.0, ["gdp", "inflation"]),
    ("RBA", "Reserve Bank of Australia", "RBA", "AU", "AUD", "https://www.rba.gov.au", 2.5,
     ["gdp", "inflation", "core_inflation", "unemployment"]),
    ("RBNZ", "Reserve Bank of New Zealand", "RBNZ", "NZ", "NZD", "https://www.rbnz.govt.nz", 2.0,
     ["gdp", "inflation", "unemployment", "policy_rate"]),
    ("SARB", "South African Reserve Bank", "SARB", "ZA", "ZAR", "https://www.resbank.co.za", 3.0,
     ["gdp", "inflation", "core_inflation", "policy_rate"]),
    ("PBOC", "People's Bank of China", "PBoC", "CN", "CNY", "http://www.pbc.gov.cn/en", 3.0, []),
    ("BANXICO", "Banco de México", "Banxico", "MX", "MXN", "https://www.banxico.org.mx", 3.0,
     ["gdp", "inflation", "core_inflation"]),
]

SOURCES = [
    # key, name, tier, kind, url, country, cb, freshness_minutes, config
    ("fred", "FRED (St. Louis Fed)", "1", "api", "https://api.stlouisfed.org/fred", "US", None, 1440, {}),
    ("fed_rss", "Federal Reserve press releases (monetary)", "1", "rss",
     "https://www.federalreserve.gov/feeds/press_monetary.xml", "US", "FED", 1440, {}),
    ("ecb_rss", "ECB press releases", "1", "rss", "https://www.ecb.europa.eu/rss/press.html", "EA", "ECB", 1440, {}),
    ("boe_rss", "Bank of England news", "1", "rss", "https://www.bankofengland.co.uk/rss/news", "GB", "BOE", 1440, {}),
    ("bls", "US Bureau of Labor Statistics", "1", "official", "https://www.bls.gov", "US", None, 1440, {}),
    ("bea", "US Bureau of Economic Analysis", "1", "official", "https://www.bea.gov", "US", None, 1440, {}),
    ("eurostat", "Eurostat", "1", "official", "https://ec.europa.eu/eurostat", "EA", None, 1440, {}),
    ("ons", "UK Office for National Statistics", "1", "official", "https://www.ons.gov.uk", "GB", None, 1440, {}),
    ("statssa", "Statistics South Africa", "1", "official", "https://www.statssa.gov.za", "ZA", None, 1440, {}),
    ("statcan", "Statistics Canada", "1", "official", "https://www150.statcan.gc.ca", "CA", None, 1440, {}),
    ("abs", "Australian Bureau of Statistics", "1", "official", "https://www.abs.gov.au", "AU", None, 1440, {}),
    ("finnhub", "Finnhub economic calendar", "2", "api", "https://finnhub.io", None, None, 360, {}),
    ("forexfactory", "Forex Factory calendar (forecasts)", "2", "api", "https://www.forexfactory.com/calendar",
     None, None, 720, {}),
    ("risk", "Risk sentiment market series (FRED daily: VIX, credit spreads, S&P 500, FX)", "1", "api",
     "https://fred.stlouisfed.org", "US", None, 1440, {}),
    ("cftc", "CFTC Commitments of Traders (weekly positioning)", "1", "api",
     "https://publicreporting.cftc.gov", "US", None, 10080, {}),
    ("seasonality", "Seasonality price histories (FRED daily since 2000, gold and silver from Twelve Data)", "1", "api",
     "https://fred.stlouisfed.org", None, None, 10080, {}),
    ("myfxbook", "Myfxbook retail sentiment (Community Outlook)", "2", "api", "https://www.myfxbook.com",
     None, None, 360, {}),
    ("twelvedata", "Twelve Data market prices", "2", "api", "https://twelvedata.com", None, None, 15, {}),
    ("calendar_csv", "Calendar CSV import", "2", "csv", None, None, None, 10080, {}),
    ("manual", "User-supplied manual data", "M", "manual", None, None, None, 0, {}),
]

# code, name, country, ccy, category, unit, freq, importance, transform, higher_is,
# aliases, fred_series, official_source, cb, projection_variable
INDICATORS = [
    ('US_CB_CONF', 'US CB Consumer Confidence', 'US', 'USD', 'consumers', 'index', 'monthly', 'medium', 'level', 'hawkish', ['cb consumer confidence', 'consumer confidence'], None, None, 'FED', None),
    ('US_UMICH', 'US UoM Consumer Sentiment', 'US', 'USD', 'consumers', 'index', 'monthly', 'medium', 'level', 'hawkish', ['uom consumer sentiment', 'michigan sentiment'], None, None, 'FED', None),
    ('EA_RETAIL_SALES_MOM', 'Euro Area Retail Sales (m/m)', 'EA', 'EUR', 'consumers', '%', 'monthly', 'medium', 'mom', 'hawkish', ['retail sales'], None, None, 'ECB', None),
    ('EA_MANUF_PMI', 'Euro Area Manufacturing PMI', 'EA', 'EUR', 'business', 'index', 'monthly', 'medium', 'level', 'hawkish', ['manufacturing pmi', 'flash manufacturing pmi'], None, None, 'ECB', None),
    ('EA_SERVICES_PMI', 'Euro Area Services PMI', 'EA', 'EUR', 'business', 'index', 'monthly', 'medium', 'level', 'hawkish', ['services pmi', 'flash services pmi'], None, None, 'ECB', None),
    ('EA_CONSUMER_CONF', 'Euro Area Consumer Confidence', 'EA', 'EUR', 'consumers', 'index', 'monthly', 'low', 'level', 'hawkish', ['consumer confidence'], None, None, 'ECB', None),
    ('EA_PPI_MOM', 'Euro Area PPI (m/m)', 'EA', 'EUR', 'inflation', '%', 'monthly', 'low', 'mom', 'hawkish', ['ppi'], None, None, 'ECB', None),
    ('GB_RETAIL_SALES_MOM', 'UK Retail Sales (m/m)', 'GB', 'GBP', 'consumers', '%', 'monthly', 'high', 'mom', 'hawkish', ['retail sales'], None, None, 'BOE', None),
    ('GB_MANUF_PMI', 'UK Manufacturing PMI', 'GB', 'GBP', 'business', 'index', 'monthly', 'medium', 'level', 'hawkish', ['manufacturing pmi', 'flash manufacturing pmi'], None, None, 'BOE', None),
    ('GB_SERVICES_PMI', 'UK Services PMI', 'GB', 'GBP', 'business', 'index', 'monthly', 'high', 'level', 'hawkish', ['services pmi', 'flash services pmi'], None, None, 'BOE', None),
    ('GB_CLAIMANT', 'UK Claimant Count Change', 'GB', 'GBP', 'employment', 'k', 'monthly', 'medium', 'level', 'dovish', ['claimant count change'], None, None, 'BOE', None),
    ('GB_PPI_YOY', 'UK PPI Input (y/y)', 'GB', 'GBP', 'inflation', '%', 'monthly', 'low', 'yoy', 'hawkish', ['ppi input'], None, None, 'BOE', None),
    ('GB_CONSUMER_CONF', 'UK GfK Consumer Confidence', 'GB', 'GBP', 'consumers', 'index', 'monthly', 'low', 'level', 'hawkish', ['gfk consumer confidence'], None, None, 'BOE', None),
    ('JP_GDP_QOQ', 'Japan GDP (q/q)', 'JP', 'JPY', 'growth', '%', 'quarterly', 'high', 'qoq', 'hawkish', ['gdp'], None, None, 'BOJ', None),
    ('JP_RETAIL_SALES_YOY', 'Japan Retail Sales (y/y)', 'JP', 'JPY', 'consumers', '%', 'monthly', 'low', 'yoy', 'hawkish', ['retail sales'], None, None, 'BOJ', None),
    ('JP_MANUF_PMI', 'Japan Manufacturing PMI', 'JP', 'JPY', 'business', 'index', 'monthly', 'low', 'level', 'hawkish', ['manufacturing pmi'], None, None, 'BOJ', None),
    ('JP_SERVICES_PMI', 'Japan Services PMI', 'JP', 'JPY', 'business', 'index', 'monthly', 'low', 'level', 'hawkish', ['services pmi'], None, None, 'BOJ', None),
    ('JP_UNEMPLOYMENT', 'Japan Unemployment Rate', 'JP', 'JPY', 'employment', '%', 'monthly', 'low', 'level', 'dovish', ['unemployment rate'], None, None, 'BOJ', None),
    ('JP_PPI_YOY', 'Japan PPI (y/y)', 'JP', 'JPY', 'inflation', '%', 'monthly', 'low', 'yoy', 'hawkish', ['ppi'], None, None, 'BOJ', None),
    ('CH_GDP_QOQ', 'Switzerland GDP (q/q)', 'CH', 'CHF', 'growth', '%', 'quarterly', 'medium', 'qoq', 'hawkish', ['gdp'], None, None, 'SNB', None),
    ('CH_RETAIL_SALES_YOY', 'Switzerland Retail Sales (y/y)', 'CH', 'CHF', 'consumers', '%', 'monthly', 'low', 'yoy', 'hawkish', ['retail sales'], None, None, 'SNB', None),
    ('CH_MANUF_PMI', 'Switzerland Manufacturing PMI', 'CH', 'CHF', 'business', 'index', 'monthly', 'low', 'level', 'hawkish', ['manufacturing pmi'], None, None, 'SNB', None),
    ('CH_UNEMPLOYMENT', 'Switzerland Unemployment Rate', 'CH', 'CHF', 'employment', '%', 'monthly', 'low', 'level', 'dovish', ['unemployment rate'], None, None, 'SNB', None),
    ('CH_PPI_MOM', 'Switzerland PPI (m/m)', 'CH', 'CHF', 'inflation', '%', 'monthly', 'low', 'mom', 'hawkish', ['ppi'], None, None, 'SNB', None),
    ('CA_GDP_MOM', 'Canada GDP (m/m)', 'CA', 'CAD', 'growth', '%', 'monthly', 'medium', 'mom', 'hawkish', ['gdp'], None, None, 'BOC', None),
    ('CA_RETAIL_SALES_MOM', 'Canada Retail Sales (m/m)', 'CA', 'CAD', 'consumers', '%', 'monthly', 'medium', 'mom', 'hawkish', ['retail sales'], None, None, 'BOC', None),
    ('CA_IVEY_PMI', 'Canada Ivey PMI', 'CA', 'CAD', 'business', 'index', 'monthly', 'low', 'level', 'hawkish', ['ivey pmi'], None, None, 'BOC', None),
    ('CA_PPI_MOM', 'Canada Producer Prices (m/m)', 'CA', 'CAD', 'inflation', '%', 'monthly', 'low', 'mom', 'hawkish', ['ippi'], None, None, 'BOC', None),
    ('AU_GDP_QOQ', 'Australia GDP (q/q)', 'AU', 'AUD', 'growth', '%', 'quarterly', 'high', 'qoq', 'hawkish', ['gdp'], None, None, 'RBA', None),
    ('AU_RETAIL_SALES_MOM', 'Australia Retail Sales (m/m)', 'AU', 'AUD', 'consumers', '%', 'monthly', 'medium', 'mom', 'hawkish', ['retail sales'], None, None, 'RBA', None),
    ('AU_EMPLOYMENT_CHANGE', 'Australia Employment Change', 'AU', 'AUD', 'employment', 'k', 'monthly', 'high', 'level', 'hawkish', ['employment change'], None, None, 'RBA', None),
    ('AU_MANUF_PMI', 'Australia Manufacturing PMI', 'AU', 'AUD', 'business', 'index', 'monthly', 'low', 'level', 'hawkish', ['manufacturing pmi'], None, None, 'RBA', None),
    ('AU_SERVICES_PMI', 'Australia Services PMI', 'AU', 'AUD', 'business', 'index', 'monthly', 'low', 'level', 'hawkish', ['services pmi'], None, None, 'RBA', None),
    ('AU_PPI_QOQ', 'Australia PPI (q/q)', 'AU', 'AUD', 'inflation', '%', 'quarterly', 'low', 'qoq', 'hawkish', ['ppi'], None, None, 'RBA', None),
    ('NZ_GDP_QOQ', 'New Zealand GDP (q/q)', 'NZ', 'NZD', 'growth', '%', 'quarterly', 'high', 'qoq', 'hawkish', ['gdp'], None, None, 'RBNZ', None),
    ('NZ_UNEMPLOYMENT', 'New Zealand Unemployment Rate', 'NZ', 'NZD', 'employment', '%', 'quarterly', 'high', 'level', 'dovish', ['unemployment rate'], None, None, 'RBNZ', None),
    ('NZ_EMPLOYMENT_CHANGE', 'New Zealand Employment Change (q/q)', 'NZ', 'NZD', 'employment', '%', 'quarterly', 'medium', 'qoq', 'hawkish', ['employment change'], None, None, 'RBNZ', None),
    ('NZ_RETAIL_SALES_QOQ', 'New Zealand Retail Sales (q/q)', 'NZ', 'NZD', 'consumers', '%', 'quarterly', 'low', 'qoq', 'hawkish', ['retail sales'], None, None, 'RBNZ', None),

    ("US_CPI_YOY", "US CPI (y/y)", "US", "USD", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["cpi", "cpi y/y", "us cpi", "consumer price index", "headline cpi", "inflation"], "CPIAUCSL", "bls", "FED", None),
    ("US_CPI_MOM", "US CPI (m/m)", "US", "USD", "inflation", "%", "monthly", "high", "mom", "hawkish",
     ["cpi m/m", "cpi mom"], "CPIAUCSL", "bls", "FED", None),
    ("US_CORE_CPI_YOY", "US Core CPI (y/y)", "US", "USD", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["core cpi", "core cpi y/y", "cpi ex food and energy"], "CPILFESL", "bls", "FED", None),
    ("US_PCE_YOY", "US PCE Price Index (y/y)", "US", "USD", "inflation", "%", "monthly", "medium", "yoy", "hawkish",
     ["pce", "pce price index", "pce y/y"], "PCEPI", "bea", "FED", "inflation"),
    ("US_CORE_PCE_YOY", "US Core PCE (y/y)", "US", "USD", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["core pce", "core pce y/y", "core pce price index"], "PCEPILFE", "bea", "FED", "core_inflation"),
    ("US_PPI_YOY", "US PPI (y/y)", "US", "USD", "inflation", "%", "monthly", "medium", "yoy", "hawkish",
     ["ppi", "producer prices", "ppi y/y"], "PPIFIS", "bls", "FED", None),
    ("US_NFP", "US Nonfarm Payrolls", "US", "USD", "employment", "k", "monthly", "high", "diff", "hawkish",
     ["nfp", "nonfarm payrolls", "non-farm payrolls", "payrolls", "non farm payrolls"], "PAYEMS", "bls", "FED", None),
    ("US_UNEMPLOYMENT", "US Unemployment Rate", "US", "USD", "employment", "%", "monthly", "high", "level", "dovish",
     ["unemployment", "unemployment rate", "jobless rate"], "UNRATE", "bls", "FED", "unemployment"),
    ("US_AHE_YOY", "US Average Hourly Earnings (y/y)", "US", "USD", "employment", "%", "monthly", "medium", "yoy",
     "hawkish", ["average hourly earnings", "ahe", "wages"], "CES0500000003", "bls", "FED", None),
    ("US_GDP_QOQ", "US GDP (q/q annualised)", "US", "USD", "growth", "%", "quarterly", "high", "qoq_saar", "hawkish",
     ["gdp", "gdp q/q", "gdp annualized", "gdp growth rate"], "GDPC1", "bea", "FED", "gdp"),
    ("US_RETAIL_SALES_MOM", "US Retail Sales (m/m)", "US", "USD", "consumers", "%", "monthly", "high", "mom",
     "hawkish", ["retail sales", "retail sales m/m"], "RSAFS", "bea", "FED", None),
    ("US_ISM_MANUF", "US ISM Manufacturing PMI", "US", "USD", "business", "index", "monthly", "high", "level",
     "hawkish", ["ism manufacturing", "ism manufacturing pmi", "manufacturing pmi"], None, None, "FED", None),
    ("US_ISM_SERVICES", "US ISM Services PMI", "US", "USD", "business", "index", "monthly", "high", "level",
     "hawkish", ["ism services", "ism services pmi", "services pmi", "ism non-manufacturing"], None, None, "FED", None),
    ("US_JOBLESS_CLAIMS", "US Initial Jobless Claims", "US", "USD", "employment", "k", "weekly", "high", "level",
     "dovish", ["initial jobless claims", "jobless claims", "unemployment claims", "initial claims"], None, None,
     "FED", None),
    ("US_JOLTS", "US JOLTS Job Openings", "US", "USD", "employment", "m", "monthly", "medium", "level", "hawkish",
     ["jolts", "jolts job openings", "job openings"], None, None, "FED", None),
    ("US_ADP", "US ADP Employment Change", "US", "USD", "employment", "k", "monthly", "medium", "level", "hawkish",
     ["adp", "adp employment", "adp non-farm employment change", "adp employment change"], None, None, "FED", None),
    ("US_FED_RATE", "Fed Funds Rate (upper bound)", "US", "USD", "monetary_policy", "%", "meeting", "high", "level",
     "hawkish", ["fed interest rate decision", "fed funds rate", "fomc rate decision"], "DFEDTARU", "fred", "FED",
     "policy_rate"),
    ("EA_HICP_YOY", "Euro Area HICP (y/y)", "EA", "EUR", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["hicp", "cpi", "euro area cpi", "eurozone cpi", "cpi flash", "hicp y/y"], "CP0000EZ19M086NEST", "eurostat",
     "ECB", "inflation"),
    ("EA_CORE_HICP_YOY", "Euro Area Core HICP (y/y)", "EA", "EUR", "inflation", "%", "monthly", "high", "yoy",
     "hawkish", ["core hicp", "core cpi", "eurozone core cpi"], None, "eurostat", "ECB", "core_inflation"),
    ("EA_UNEMPLOYMENT", "Euro Area Unemployment Rate", "EA", "EUR", "employment", "%", "monthly", "medium", "level",
     "dovish", ["unemployment", "unemployment rate"], None, "eurostat", "ECB", "unemployment"),
    ("EA_GDP_QOQ", "Euro Area GDP (q/q)", "EA", "EUR", "growth", "%", "quarterly", "high", "qoq", "hawkish",
     ["gdp", "gdp q/q", "gdp growth rate"], None, "eurostat", "ECB", "gdp"),
    ("EA_PMI_COMPOSITE", "Euro Area Composite PMI", "EA", "EUR", "business", "index", "monthly", "medium", "level",
     "hawkish", ["composite pmi", "hcob composite pmi"], None, None, "ECB", None),
    ("EA_ECB_RATE", "ECB Deposit Facility Rate", "EA", "EUR", "monetary_policy", "%", "meeting", "high", "level",
     "hawkish", ["ecb interest rate decision", "deposit facility rate"], None, "ecb_rss", "ECB", "policy_rate"),
    ("GB_CPI_YOY", "UK CPI (y/y)", "GB", "GBP", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["cpi", "uk cpi", "cpi y/y"], None, "ons", "BOE", "inflation"),
    ("GB_CORE_CPI_YOY", "UK Core CPI (y/y)", "GB", "GBP", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["core cpi"], None, "ons", "BOE", None),
    ("GB_UNEMPLOYMENT", "UK Unemployment Rate", "GB", "GBP", "employment", "%", "monthly", "medium", "level", "dovish",
     ["unemployment", "unemployment rate", "ilo unemployment rate"], None, "ons", "BOE", "unemployment"),
    ("GB_GDP_QOQ", "UK GDP (q/q)", "GB", "GBP", "growth", "%", "quarterly", "high", "qoq", "hawkish",
     ["gdp", "gdp q/q"], None, "ons", "BOE", "gdp"),
    ("GB_BOE_RATE", "BoE Bank Rate", "GB", "GBP", "monetary_policy", "%", "meeting", "high", "level", "hawkish",
     ["boe interest rate decision", "bank rate"], None, "boe_rss", "BOE", "policy_rate"),
    ("JP_CPI_YOY", "Japan National CPI (y/y)", "JP", "JPY", "inflation", "%", "monthly", "medium", "yoy", "hawkish",
     ["cpi", "national cpi"], None, None, "BOJ", "inflation"),
    ("JP_CORE_CPI_YOY", "Japan Core CPI (y/y)", "JP", "JPY", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["core cpi", "national core cpi", "tokyo core cpi"], None, None, "BOJ", "core_inflation"),
    ("JP_BOJ_RATE", "BoJ Policy Rate", "JP", "JPY", "monetary_policy", "%", "meeting", "high", "level", "hawkish",
     ["boj interest rate decision"], None, None, "BOJ", "policy_rate"),
    ("CH_CPI_YOY", "Switzerland CPI (y/y)", "CH", "CHF", "inflation", "%", "monthly", "medium", "yoy", "hawkish",
     ["cpi", "swiss cpi"], None, None, "SNB", "inflation"),
    ("CA_CPI_YOY", "Canada CPI (y/y)", "CA", "CAD", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["cpi", "canada cpi"], None, None, "BOC", "inflation"),
    ("CA_UNEMPLOYMENT", "Canada Unemployment Rate", "CA", "CAD", "employment", "%", "monthly", "high", "level",
     "dovish", ["unemployment", "unemployment rate"], None, None, "BOC", None),
    ("CA_EMPLOYMENT_CHANGE", "Canada Employment Change", "CA", "CAD", "employment", "k", "monthly", "high", "diff",
     "hawkish", ["employment change"], None, None, "BOC", None),
    ("AU_CPI_YOY", "Australia CPI (y/y)", "AU", "AUD", "inflation", "%", "quarterly", "high", "yoy", "hawkish",
     ["cpi", "australia cpi", "monthly cpi indicator"], None, None, "RBA", "inflation"),
    ("AU_UNEMPLOYMENT", "Australia Unemployment Rate", "AU", "AUD", "employment", "%", "monthly", "high", "level",
     "dovish", ["unemployment", "unemployment rate"], None, None, "RBA", "unemployment"),
    ("NZ_CPI_YOY", "New Zealand CPI (y/y)", "NZ", "NZD", "inflation", "%", "quarterly", "high", "yoy", "hawkish",
     ["cpi", "nz cpi"], None, None, "RBNZ", "inflation"),
    ("ZA_CPI_YOY", "South Africa CPI (y/y)", "ZA", "ZAR", "inflation", "%", "monthly", "high", "yoy", "hawkish",
     ["cpi", "sa cpi", "south africa cpi"], None, "statssa", "SARB", "inflation"),
    ("ZA_CORE_CPI_YOY", "South Africa Core CPI (y/y)", "ZA", "ZAR", "inflation", "%", "monthly", "medium", "yoy",
     "hawkish", ["core cpi"], None, "statssa", "SARB", "core_inflation"),
    ("ZA_GDP_QOQ", "South Africa GDP (q/q)", "ZA", "ZAR", "growth", "%", "quarterly", "high", "qoq", "hawkish",
     ["gdp", "gdp q/q"], None, "statssa", "SARB", "gdp"),
    ("ZA_SARB_RATE", "SARB Repo Rate", "ZA", "ZAR", "monetary_policy", "%", "meeting", "high", "level", "hawkish",
     ["sarb interest rate decision", "repo rate"], None, None, "SARB", "policy_rate"),
    ("CN_CPI_YOY", "China CPI (y/y)", "CN", "CNY", "inflation", "%", "monthly", "medium", "yoy", "hawkish",
     ["cpi", "china cpi"], None, None, "PBOC", None),
    ("MX_CPI_YOY", "Mexico CPI (y/y)", "MX", "MXN", "inflation", "%", "monthly", "medium", "yoy", "hawkish",
     ["cpi", "mexico inflation"], None, None, "BANXICO", "inflation"),
]


def seed(db: Session) -> None:
    for code, name, short, country, ccy, web, target, publishes in CENTRAL_BANKS:
        cb = db.scalar(select(CentralBank).where(CentralBank.code == code))
        if cb is None:
            db.add(CentralBank(code=code, name=name, short_name=short, country=country, currency=ccy,
                               website=web, inflation_target=target, publishes=publishes))
    for key, name, tier, kind, url, country, cb, fresh, cfg in SOURCES:
        src = db.scalar(select(Source).where(Source.key == key))
        if src is None:
            src = Source(key=key, name=name, tier=tier, kind=kind, url=url, country=country,
                         central_bank_code=cb, freshness_minutes=fresh, config=cfg)
            db.add(src)
            db.flush()
            db.add(SourceHealth(source_id=src.id))
    for row in INDICATORS:
        (code, name, country, ccy, cat, unit, freq, imp, tr, hi, aliases, fred, off, cb, pv) = row
        ind = db.scalar(select(Indicator).where(Indicator.code == code))
        if ind is None:
            db.add(Indicator(code=code, name=name, country=country, currency=ccy, category=cat, unit=unit,
                             frequency=freq, importance=imp, transform=tr, higher_is=hi, aliases=aliases,
                             fred_series=fred, official_source_key=off, central_bank_code=cb,
                             projection_variable=pv))
    from app.services.cot import import_bundled

    db.flush()
    import_bundled(db)  # first start only: the stored COT history (Jan 2025 onwards)
    if db.scalar(select(User).where(User.id == 1)) is None:
        db.add(User(id=1, email="owner@localhost", name="Owner"))
        db.flush()
        db.add(UserTrustSettings(user_id=1))
    db.commit()
