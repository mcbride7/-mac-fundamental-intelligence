"""Top setups: gathers the five pillars for every asset and ranks them (see analytics/setups.py).

Inputs already in the platform:
  central bank   policy score from statements, market rate expectations (fundamentals snapshot)
  economic       inflation vs target (snapshot) and the economic heatmap's hawkish/dovish surprises
  cot            CFTC speculator COT index (COT positioning page)
  seasonality    month and next-two-weeks statistics (Seasonality page; crosses built from their USD legs)
  retail         latest retail long % (Myfxbook or typed in)
"""
from __future__ import annotations

import time as _time
from datetime import date

from sqlalchemy.orm import Session

from app.analytics import cot as ca
from app.analytics import seasonality as sx
from app.analytics import setups as st
from app.engines import fundamentals as fnd
from app.services import cot, heatmap, retail
from app.services import seasonality as ss

PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "USDZAR", "USDMXN",
         "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "XAUUSD"]
NAMES = {"XAUUSD": "Gold"}
COT_CODE = {"EUR": "099741", "JPY": "097741", "GBP": "096742", "AUD": "232741", "CAD": "090741", "CHF": "092741",
            "ZAR": "122741", "USD": "098662", "GOLD": "088691"}
# crosses built from their USD legs for seasonality: (leg1, op, leg2)
SYNTH = {"EURJPY": ("EURUSD", "*", "USDJPY"), "GBPJPY": ("GBPUSD", "*", "USDJPY"),
         "AUDJPY": ("AUDUSD", "*", "USDJPY"), "EURGBP": ("EURUSD", "/", "GBPUSD")}
CB_NAME = {"USD": "Fed", "EUR": "ECB", "GBP": "BoE", "JPY": "BoJ", "CHF": "SNB", "CAD": "BoC", "AUD": "RBA",
           "NZD": "RBNZ", "ZAR": "SARB", "MXN": "Banxico", "CNY": "PBoC"}
_CACHE: dict = {}
TTL = 600  # seconds


def label(asset: str) -> str:
    return NAMES.get(asset, f"{asset[:3]}/{asset[3:]}")


def _pair_value(b: float | None, q: float | None) -> float | None:
    return None if b is None or q is None else round(st.clip(b - q), 2)


def _season_obs(db: Session, asset: str) -> list:
    if asset in SYNTH:
        a, op, b = SYNTH[asset]
        oa, ob = dict(ss._obs(db, a)), dict(ss._obs(db, b))
        days = sorted(set(oa) & set(ob))
        return [(d, oa[d] * ob[d] if op == "*" else oa[d] / ob[d]) for d in days if ob[d]]
    return ss._obs(db, asset)


def _season(db: Session, asset: str, today: date, years: int = 10) -> tuple[float | None, str]:
    obs = _season_obs(db, asset)
    if len(obs) < 500:
        return None, ""
    month = sx.month_stats(sx.monthly_moves(obs, "pct", today), years, today)[today.month - 1]
    weeks = sx.week_stats(sx.weekly_moves(obs, "pct", today), years, today)
    w = sx.week_of(today)
    nxt = [weeks[w - 1], weeks[w % 52]]
    score = st.seasonality_score(month, nxt)
    if score is None:
        return None, ""
    lean = "bullish" if score >= 0.25 else "bearish" if score <= -0.25 else "neutral"
    bits = []
    if month.get("n"):
        bits.append(f"{sx.MONTHS[today.month - 1]} up in {month['win_rate']}% of the last {month['n']} years "
                    f"(avg {month['avg']:+.2f}%)")
    wk = [x for x in nxt if x.get("n")]
    if wk:
        bits.append("next two weeks up in " + " and ".join(f"{x['win_rate']}%" for x in wk) + " of years")
    note = f"Seasonality leans {lean}: " + "; ".join(bits)
    return score, note


def _cot_ccy(db: Session, code: str) -> tuple[float | None, dict]:
    rows = cot.rows_of(db, code)
    if len(rows) < 12:
        return None, {}
    spec = ca.net(rows, "spec")
    idx, idx4 = ca.cot_index(spec, 52), ca.cot_index(spec[:-4], 52)
    return st.cot_score(idx, idx4, spec[-1] - spec[-2]), {"index": idx, "index_4w_ago": idx4,
                                                         "change": spec[-1] - spec[-2]}


def compute(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    key = today.isoformat()
    hit = _CACHE.get(key)
    if hit and _time.time() - hit[0] < TTL:
        return hit[1]
    snaps = fnd.build_all(db)
    ccys = set()
    for p in PAIRS:
        ccys |= {p[:3], p[3:]}
    ccys.discard("XAU")
    cb, econ, cotv, cotinfo, econ_info = {}, {}, {}, {}, {}
    for c in ccys:
        s = snaps.get(c)
        if s is not None:
            cb[c] = st.central_bank_score(s.policy_score, s.implied_change_bps, s.prob_hike, s.prob_cut)
            rows = [r for r in heatmap.rows_for(db, c) if r.get("actual") is not None]
            ds = sum(1 if r["currency_impact"] == "Bullish" else -1 if r["currency_impact"] == "Bearish" else 0
                     for r in rows)
            econ[c] = st.economic_score(s.inflation, s.inflation_target, ds if rows else None, len(rows))
            econ_info[c] = {"data_score": ds, "rows": len(rows), "inflation": s.inflation, "target": s.inflation_target}
        if c in COT_CODE:
            cotv[c], cotinfo[c] = _cot_ccy(db, COT_CODE[c])
    gold_cot, gold_info = _cot_ccy(db, COT_CODE["GOLD"])
    risk = None
    try:
        from app.services.risk_sentiment import reading
        r = reading(db, "daily", 10)
        risk = {"label": r["label"], "score": r["score"]} if r["score"] is not None else None
    except Exception:  # risk data not collected yet
        risk = None

    out = []
    for p in PAIRS:
        b, q = p[:3], p[3:]
        notes: dict[str, str] = {}
        if p == "XAUUSD":
            pc = None if cb.get("USD") is None else round(-cb["USD"], 2)
            pe = None if econ.get("USD") is None else round(-econ["USD"], 2)
            pcot = gold_cot
            if pc is not None:
                notes["central_bank"] = ("A dovish Fed supports gold" if pc > 0 else "A hawkish Fed weighs on gold")
            if pe is not None:
                notes["economic"] = ("Soft US data / cooling inflation supports gold" if pe > 0
                                     else "Firm US data / hot inflation weighs on gold")
            if gold_info:
                notes["cot"] = f"Gold speculators at COT index {gold_info['index']:.0f}"
        else:
            pc, pe = _pair_value(cb.get(b), cb.get(q)), _pair_value(econ.get(b), econ.get(q))
            if pc is not None:
                stronger, weaker = (b, q) if pc > 0 else (q, b)
                notes["central_bank"] = (f"{CB_NAME.get(stronger, stronger)} more hawkish than "
                                         f"{CB_NAME.get(weaker, weaker)} (statements and rate pricing)")
            if pe is not None:
                hot, cool = (b, q) if pe > 0 else (q, b)
                ih, ic = econ_info.get(hot, {}), econ_info.get(cool, {})
                bit = ""
                if ih.get("inflation") is not None and ih.get("target") is not None:
                    bit = f"; {hot} inflation {ih['inflation']:.1f}% vs {ih['target']:.1f}% target"
                notes["economic"] = f"{hot} data running hotter than {cool}{bit}"
            cb_ = cotv.get(b), cotv.get(q)
            if cb_[0] is not None and cb_[1] is not None:
                pcot = round(st.clip(cb_[0] - cb_[1]), 2)
            elif cb_[0] is not None:
                pcot = round(cb_[0] * 0.7, 2)
            elif cb_[1] is not None:
                pcot = round(-cb_[1] * 0.7, 2)
            else:
                pcot = None
            bits = [f"{c} index {cotinfo[c]['index']:.0f}" for c in (b, q) if cotinfo.get(c, {}).get("index") is not None]
            if bits:
                notes["cot"] = "Speculators: " + ", ".join(bits)
        ps, snote = _season(db, p, today)
        if snote:
            notes["seasonality"] = snote
        rr = retail.latest(db, p)
        pr = st.retail_score(rr.long_pct if rr else None)
        if rr:
            notes["retail"] = f"{rr.long_pct:.0f}% of retail traders long ({rr.source}): contrarian"
        pillars = {"central_bank": pc, "economic": pe, "cot": pcot, "seasonality": ps, "retail": pr}
        s = st.combine(p, pillars, notes)
        context = None
        if risk and risk["label"] in ("Risk-On", "Risk-Off"):
            on = risk["label"] == "Risk-On"
            if q in ("JPY", "CHF") or p == "XAUUSD":
                fits = (s.direction == "LONG") == on if p != "XAUUSD" else (s.direction == "LONG") != on
                context = f"{risk['label']} mood {'supports' if fits else 'works against'} this trade"
            elif b in ("AUD", "NZD") or q in ("ZAR", "MXN"):
                fits = (s.direction == "LONG") == on if b in ("AUD", "NZD") else (s.direction == "SHORT") == on
                context = f"{risk['label']} mood {'supports' if fits else 'works against'} this trade"
        out.append({
            "asset": p, "label": label(p), "grade": s.grade, "direction": s.direction, "score": s.score,
            "coverage": s.coverage, "agreement": s.agreement, "reasons": s.reasons, "against": s.against,
            "risk_context": context if s.direction != "NONE" else None,
            "pillars": [{"key": k, "label": st.LABELS[k], "score": v, "weight": st.WEIGHTS[k], "note": notes.get(k, "")}
                        for k, v in pillars.items()],
            "retail_long_pct": rr.long_pct if rr else None, "retail_source": rr.source if rr else None,
        })
    rank = {"A+": 0, "A": 1, "B": 2, "C": 3, "No setup": 4, "Not enough data": 5}
    out.sort(key=lambda x: (rank.get(x["grade"], 9), -abs(x["score"])))
    res = {"as_of": today.isoformat(), "risk": risk, "setups": out, "weights": st.WEIGHTS, "labels": st.LABELS}
    _CACHE.clear()
    _CACHE[key] = (_time.time(), res)
    return res


def clear_cache() -> None:
    _CACHE.clear()
