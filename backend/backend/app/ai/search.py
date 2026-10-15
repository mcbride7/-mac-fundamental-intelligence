"""AI macro search (Section 43). Questions are routed to the platform's own
analytics; every answer is built from stored evidence and cites it, in the
professional response format (Section 59). An LLM, if configured, only
rephrases the evidence — it cannot add facts."""
from __future__ import annotations

import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.llm import DATA_GUARD, get_llm
from app.core.verification import badge
from app.engines import cb_engine, currency_engine, research_engine, scenario_engine, trading_engine
from app.engines import fundamentals as fnd
from app.engines.forecast_engine import accuracy_summary
from app.models import Alert, CentralBankStatement, PolicyScore
from app.services import data_access as da

CB_ALIASES = {
    "FED": ["fed", "fomc", "federal reserve"], "ECB": ["ecb", "european central bank"],
    "BOE": ["boe", "bank of england"], "BOJ": ["boj", "bank of japan"], "SNB": ["snb", "swiss national bank"],
    "BOC": ["boc", "bank of canada"], "RBA": ["rba", "reserve bank of australia"],
    "RBNZ": ["rbnz", "reserve bank of new zealand"], "SARB": ["sarb", "south african reserve bank", "reserve bank"],
    "PBOC": ["pboc", "people's bank of china"], "BANXICO": ["banxico", "bank of mexico", "banco de mexico"],
}
VARIABLES = {"inflation": "inflation", "core inflation": "core_inflation", "core pce": "core_inflation",
             "gdp": "gdp", "growth": "gdp", "unemployment": "unemployment", "jobs": "unemployment"}


def _find_cb(q: str) -> str | None:
    low = q.lower()
    for code, al in CB_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", low) for a in al):
            return code
    return None


def _find_pair(q: str) -> str | None:
    m = re.search(r"\b([A-Z]{3})\s*/?\s*([A-Z]{3})\b", q.upper())
    if m and m.group(1) in fnd.COUNTRY and m.group(2) in fnd.COUNTRY and m.group(1) != m.group(2):
        return m.group(1) + m.group(2)
    return None


def _find_ccy(q: str) -> str | None:
    for c in fnd.CURRENCIES:
        if re.search(rf"\b{c}\b", q.upper()):
            return c
    return None


def _find_var(q: str) -> str:
    low = q.lower()
    for k in sorted(VARIABLES, key=len, reverse=True):
        if k in low:
            return VARIABLES[k]
    return "inflation"


def _resp(conclusion: str, facts: list[dict], intent: str, **sections) -> dict:
    out = {"intent": intent, "conclusion": conclusion, "facts": facts}
    for k in ("market_expectation", "central_bank_projection", "actual", "forecast_accuracy", "what_changed",
              "why_it_matters", "policy_implication", "market_impact", "scenarios", "confirmation",
              "invalidation", "trade_bias", "risk"):
        if k in sections and sections[k] not in (None, [], {}):
            out[k] = sections[k]
    out["citations"] = [{"ref": i + 1, **f} for i, f in enumerate(facts)]
    return out


def _fact_from_source(s: dict) -> dict:
    return {"text": f"{s['label']}: {s['value']:g} ({s.get('period')})", "type": s["type"], "id": s["id"],
            "source": s.get("source"), "status": badge(s["status"], s.get("basis"))}


def answer(db: Session, question: str) -> dict:
    q = question.strip()
    low = q.lower()
    pair, ccy, cb = _find_pair(q), _find_ccy(q), _find_cb(q)
    if re.search(r"(what would make|what could make).*(bullish|bearish)", low) and pair:
        return _what_would_make(db, pair, "bullish" in low)
    if re.search(r"(underpric|overpric|market wrong|mispric|priced in)", low):
        return _market_wrong(db, cb)
    if re.search(r"(which|what).*(central bank).*(best|most accurate)", low) or \
            re.search(r"best .*forecast", low):
        return _rankings(db, _find_var(q))
    if cb and re.search(r"(underestimat|overestimat|accura|forecast)", low):
        return _accuracy(db, cb, _find_var(q))
    if cb and re.search(r"(dovish|hawkish|policy|stance)", low):
        return _policy(db, cb)
    if re.search(r"(strongest|weakest).*(currenc|fundamental)", low) or re.search(r"rank.*currenc", low):
        return _strongest(db, "weakest" in low)
    if re.search(r"(upcoming|next|which).*(event|release|data)", low):
        return _catalysts(db, pair or ccy)
    if re.search(r"(what happened|historical|history|in the past|how did .* react|when .* exceeded)", low):
        if re.search(r"(exceed|above|below|undershoot|overshoot).*(projection|forecast)", low) and cb:
            return _event_study(db, cb, _find_var(q), "below" if "below" in low else "above")
        if pair:
            return _analogues(db, pair)
    if pair:
        return _pair(db, pair)
    if ccy:
        return _currency(db, ccy)
    return _fulltext(db, q)


def _maybe_llm(resp: dict, question: str) -> dict:
    llm = get_llm()
    if not llm.available:
        return resp
    try:
        prompt = ("Rewrite the CONCLUSION below as 2-3 clear sentences for a professional macro trader, using ONLY "
                  "the facts provided. Keep hedged language (likely, evidence suggests). Never promise outcomes.\n"
                  f"Question: {question}\nConclusion: {resp['conclusion']}\nFacts: {resp['facts'][:12]}")
        resp["conclusion_ai"] = llm.complete(DATA_GUARD, prompt, 300).text.strip()
    except Exception:
        pass
    return resp


def search(db: Session, question: str) -> dict:
    return _maybe_llm(answer(db, question), question)


# ---------------------------------------------------------------------------
# intents
# ---------------------------------------------------------------------------

def _pair(db: Session, pair: str) -> dict:
    a = trading_engine.analyse(db, pair)
    sb, sq = fnd.build(db, pair[:3]), fnd.build(db, pair[3:])
    facts = [_fact_from_source(s) for s in sb.sources + sq.sources]
    return _resp(a["report"]["conclusion"], facts, "asset_analysis",
                 why_it_matters=a["report"]["why_it_matters"],
                 scenarios=a["report"]["scenarios"], confirmation=a["confirmation"], invalidation=a["invalidation"],
                 trade_bias=a["report"]["trade_bias"], risk=a["risks"],
                 market_expectation=a["report"]["market_expectation"],
                 central_bank_projection=a["report"]["central_bank_projection"])


def _currency(db: Session, ccy: str) -> dict:
    scores = currency_engine.latest_scores(db)
    s = scores.get(ccy)
    snap = fnd.build(db, ccy)
    facts = [_fact_from_source(x) for x in snap.sources]
    if s is None:
        return _resp(f"No fundamental score has been computed for {ccy} yet. Add data or run a full recompute.",
                     facts, "currency")
    comp = ", ".join(f"{k.replace('_', ' ')} {v:+.0f}" for k, v in sorted(s.components.items(), key=lambda kv:
                                                                          -abs(kv[1])))
    concl = (f"{ccy} has a {s.bias.lower()} fundamental bias (score {s.total:+.0f}). Main components: {comp}. "
             f"Evidence quality {s.evidence_quality:.0f}/100.")
    return _resp(concl, facts, "currency", why_it_matters=[comp],
                 policy_implication={"policy_score": snap.policy_score, "statement_tone": snap.statement_tone})


def _policy(db: Session, code: str) -> dict:
    cb = da.cb_by_code(db, code)
    scores = list(db.scalars(select(PolicyScore).where(PolicyScore.central_bank_id == cb.id)
                             .order_by(PolicyScore.as_of.desc()).limit(6)))
    cmp = cb_engine.comparison(db, cb)
    facts = []
    if scores:
        p = scores[0]
        facts.append({"text": f"{cb.short_name} policy score {p.score:.0f}/100 ({p.classification}), "
                              f"confidence {p.confidence:.0f}%", "type": "policy_score", "id": p.id,
                      "source": "platform analysis", "status": f"evidence quality {p.evidence_quality:.0f}/100"})
    what = []
    if cmp:
        s = cmp["summary"]
        facts.append({"text": f"Latest statement tone {s['tone_latest']:+.0f} vs {s['tone_previous']:+.0f} previously "
                              f"({s['direction']})", "type": "cb_statement", "id": cmp["latest"]["id"],
                      "source": cmp["latest"].get("url") or "statement", "status": cmp["latest"]["verification_status"]})
        what = [f"{c['importance']}: {c['what_changed']} ({c['direction']})" for c in cmp["changes"][:4]]
    if not scores:
        return _resp(f"No policy score yet for {cb.short_name}.", facts, "policy")
    trend = scores[0].score - scores[-1].score
    if trend <= -5:
        verdict = f"Yes — {cb.short_name} has become more dovish (score {scores[-1].score:.0f} → {scores[0].score:.0f})."
    elif trend >= 5:
        verdict = f"No — {cb.short_name} has become more hawkish (score {scores[-1].score:.0f} → {scores[0].score:.0f})."
    else:
        verdict = f"{cb.short_name}'s stance is broadly unchanged (score {scores[0].score:.0f}, {scores[0].classification})."
    return _resp(verdict, facts, "policy", what_changed=what, why_it_matters=scores[0].explanation)


def _accuracy(db: Session, code: str, variable: str) -> dict:
    acc = accuracy_summary(db, code, variable)
    b = acc["bias"].get(variable)
    cbv = acc["central_bank"].get(variable)
    mk = acc["market"].get(variable)
    facts = []
    if cbv:
        facts.append({"text": f"{code} {variable} accuracy {cbv['score']:.0f}/100 (MAE {cbv['mae']:.2f} pp, "
                              f"n={cbv['n']}, {acc['window']}, {acc['basis']})", "type": "forecast_accuracy",
                      "source": "platform analysis", "status": "computed from stored forecast errors"})
    if mk:
        facts.append({"text": f"Market consensus MAE {mk['mae']:.2f} pp (n={mk['n']})", "type": "forecast_accuracy",
                      "source": "platform analysis", "status": "computed"})
    if not cbv:
        return _resp(f"Not enough stored projections and outcomes to assess {code} {variable} forecasts yet.",
                     facts, "forecast_accuracy")
    concl = f"{code}'s {variable.replace('_', ' ')} forecasts score {cbv['score']:.0f}/100 (mean error " \
            f"{cbv['mean_error']:+.2f} pp)."
    if b:
        concl += f" Bias: {b['classification']}. {b['explanation']}"
    return _resp(concl, facts, "forecast_accuracy", forecast_accuracy=acc)


def _rankings(db: Session, variable: str) -> dict:
    r = research_engine.forecast_rankings(db, variable)
    rows = r["by_variable"].get(variable, [])
    facts = [{"text": f"{x['forecaster']}: {x['score']:.0f}/100 (MAE {x['mae']:.2f}, n={x['n']})",
              "type": "forecast_accuracy", "source": "platform analysis", "status": "computed"} for x in rows]
    if not rows:
        return _resp("Not enough forecast history stored to rank central banks yet.", facts, "rankings")
    return _resp(f"{rows[0]['forecaster']} has the most accurate {variable.replace('_', ' ')} projections "
                 f"({rows[0]['score']:.0f}/100) over the {r['window']} window.", facts, "rankings",
                 forecast_accuracy=r)


def _strongest(db: Session, weakest: bool) -> dict:
    scores = sorted(currency_engine.latest_scores(db).values(), key=lambda s: s.total, reverse=not weakest)
    facts = [{"text": f"{s.currency} {s.total:+.0f} ({s.bias})", "type": "currency_score", "id": s.id,
              "source": "platform analysis", "status": f"evidence quality {s.evidence_quality:.0f}/100"}
             for s in scores]
    if not scores:
        return _resp("No currency scores yet.", facts, "currency_ranking")
    top = scores[0]
    return _resp(f"{top.currency} currently has the {'weakest' if weakest else 'strongest'} fundamentals "
                 f"(score {top.total:+.0f}).", facts, "currency_ranking")


def _catalysts(db: Session, target: str | None) -> dict:
    ccys = [target[:3], target[3:]] if target and len(target) == 6 else ([target] if target else fnd.CURRENCIES)
    cats = scenario_engine.catalysts(db, ccys, days=21)
    facts = [{"text": f"{c['name']} — {c['date']} ({c['importance']})", "type": "economic_event",
              "source": "economic calendar", "status": "scheduled"} for c in cats[:10]]
    if not cats:
        return _resp("No scheduled events found in the calendar for the next three weeks. Import the calendar "
                     "(Finnhub, CSV or a screenshot).", facts, "catalysts")
    top = next((c for c in cats if c["importance"] == "high"), cats[0])
    return _resp(f"The highest-impact upcoming event is {top['name']} on {top['date']}.", facts, "catalysts")


def _what_would_make(db: Session, pair: str, bullish: bool) -> dict:
    scen = scenario_engine.latest_scenarios(db, pair) or [
        {"kind": s.kind, "title": s.title, "direction": s.direction, "probability": s.probability,
         "triggers": s.triggers} for s in scenario_engine.build_for_asset(db, pair)["scenarios"]]
    want = "up" if bullish else "down"
    match = [s for s in scen if s["direction"] == want and s["kind"] != "risk"]
    conds = [t["description"] for s in match for t in s["triggers"] if t["trigger_type"] == "confirmation"]
    facts = [{"text": f"{s['title']} — {s['probability']:.0f}%", "type": "scenario", "source": "scenario engine",
              "status": "model output"} for s in match]
    return _resp(f"{pair} would turn {'bullish' if bullish else 'bearish'} if: " + ("; ".join(conds[:4]) or
                                                                                    "the policy differential reverses")
                 + ".", facts, "conditions", confirmation=conds, scenarios=match)


def _market_wrong(db: Session, code: str | None) -> dict:
    alerts = research_engine.market_wrong_checks(db, {code} if code else None)
    facts = [{"text": a["title"] + ": " + a["body"], "type": "research_alert", "source": "platform analysis",
              "status": "research alert (not a trade)"} for a in alerts]
    if not alerts:
        return _resp("No significant disconnect detected between economic data/policy signals and market pricing"
                     + (f" for {code}" if code else "") + ".", facts, "market_wrong")
    return _resp(alerts[0]["title"] + ". " + alerts[0]["body"], facts, "market_wrong")


def _event_study(db: Session, code: str, variable: str, condition: str) -> dict:
    r = research_engine.event_study(db, code, variable, condition)
    h = r.get("horizons", {})
    facts = [{"text": f"{k}: mean {v['mean_pct']:+.2f}%, hit rate {v['hit_rate_up']:.0%} (n={v['n']})",
              "type": "event_study", "source": r["measured_with"], "status": "historical"} for k, v in h.items()]
    if not h:
        return _resp(r["question"] + " Not enough stored history to answer yet.", facts, "event_study")
    k, v = next(iter(h.items()))
    return _resp(r["question"] + f" Over {k}, {r['measured_with']} moved {v['mean_pct']:+.2f}% on average "
                                 f"across {v['n']} episodes. {r['disclaimer']}", facts, "event_study")


def _analogues(db: Session, pair: str) -> dict:
    r = research_engine.historical_analogues(db, pair)
    facts = [{"text": f"{m['when']:%Y-%m}: similarity {m['similarity']:.0f}%, subsequent {m.get('subsequent')}",
              "type": "analogue", "source": "platform history", "status": "historical"} for m in r["analogues"]]
    if not r["analogues"]:
        return _resp(r["note"], facts, "analogues")
    return _resp(f"The most similar past setup for {pair} was {r['analogues'][0]['when']:%B %Y} "
                 f"({r['analogues'][0]['similarity']:.0f}% similar). {r['disclaimer']}", facts, "analogues")


def _fulltext(db: Session, q: str) -> dict:
    facts = []
    if db.bind.dialect.name == "postgresql":
        rows = db.execute(text("SELECT id, title, ts_headline('english', text, plainto_tsquery('english', :q)) AS h "
                               "FROM central_bank_statements WHERE to_tsvector('english', text) @@ "
                               "plainto_tsquery('english', :q) ORDER BY published_at DESC LIMIT 5"), {"q": q}).all()
        facts = [{"text": f"{r.title}: …{r.h}…", "type": "cb_statement", "id": r.id, "source": "statement",
                  "status": "stored document"} for r in rows]
    else:
        words = [w for w in re.findall(r"[a-z]{4,}", q.lower())][:4]
        for st in db.scalars(select(CentralBankStatement).order_by(CentralBankStatement.published_at.desc())
                             .limit(50)):
            if words and all(w in st.text.lower() for w in words):
                facts.append({"text": st.title or "statement", "type": "cb_statement", "id": st.id,
                              "source": st.url, "status": st.verification_status})
    for a in db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(100)):
        if any(w in (a.title + a.body).lower() for w in re.findall(r"[a-z]{4,}", q.lower())[:4]):
            facts.append({"text": a.title, "type": "alert", "id": a.id, "source": "alerts", "status": a.severity})
            if len(facts) >= 10:
                break
    concl = ("Here is what the platform has on that." if facts else
             "I couldn't map that question to the platform's analytics. Try naming a currency, pair or central bank "
             "(e.g. 'Why is EUR/USD bearish?', 'Is the Fed becoming more dovish?').")
    return _resp(concl, facts, "search")

