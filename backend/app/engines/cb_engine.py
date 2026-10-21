"""Central-bank intelligence engine (Phase 2): statement comparison, tone,
policy score, policy shift, central-bank surprise and policy divergence."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import hashlib

from app.ai.llm import DATA_GUARD, extract_json, get_llm, wrap_document
from app.analytics import policy as px
from app.analytics import statement as sx
from app.core.verification import DataPointStatus, evidence_quality
from app.db import utcnow
from app.engines import fundamentals as fnd
from app.models import (
    CentralBank,
    CentralBankMeeting,
    CentralBankStatement,
    CentralBankStatementVersion,
    PolicyDivergence,
    PolicyScore,
)
from app.services import data_access as da
from app.services.audit import alert
from app.services.recompute import Context, node

DIVERGENCE_PAIRS = [("FED", "ECB"), ("FED", "BOE"), ("FED", "BOJ"), ("ECB", "BOE"), ("FED", "SNB"),
                    ("FED", "BOC"), ("FED", "RBA"), ("FED", "RBNZ"), ("FED", "SARB"), ("FED", "BANXICO"),
                    ("ECB", "BOJ"), ("BOE", "BOJ")]


def previous_statement(db: Session, st: CentralBankStatement) -> CentralBankStatement | None:
    q = (select(CentralBankStatement)
         .where(CentralBankStatement.central_bank_id == st.central_bank_id,
                CentralBankStatement.doc_type == st.doc_type, CentralBankStatement.id != st.id))
    if st.published_at is not None:
        q = q.where(CentralBankStatement.published_at <= st.published_at)
    return db.scalar(q.order_by(CentralBankStatement.published_at.desc(), CentralBankStatement.id.desc()))


AI_TONE_PROMPT = (
    "Rate the monetary-policy tone of this central-bank statement on a scale from -100 (very dovish: easing, "
    "rate cuts, worry about growth or jobs) to +100 (very hawkish: tightening, rate hikes, worry about "
    "inflation). 0 means balanced. Judge forward guidance and the balance of risks, including softer signals "
    "such as 'patient', 'data-dependent', 'further adjustment', 'for some time' or 'vigilant'. Reply with JSON "
    'only: {"tone": <number>, "reasons": ["<short reason>", "<short reason>", "<short reason>"]}\n'
)
AI_WEIGHT = 0.6  # the AI reads nuance better; the word list keeps it anchored and explainable
_ai_tone_cache: dict[str, tuple[float, list[str], str]] = {}


def ai_tone(text: str) -> tuple[float, list[str], str] | None:
    """AI tone score, or None when no AI is set up or it fails (the word list is then used alone)."""
    llm = get_llm()
    if not llm.available or not text.strip():
        return None
    key = hashlib.sha256(text.encode()).hexdigest()
    if key in _ai_tone_cache:
        return _ai_tone_cache[key]
    try:
        resp = llm.complete(DATA_GUARD, AI_TONE_PROMPT + wrap_document(text[:12000]), 300)
        data = extract_json(resp.text)
        score = max(-100.0, min(100.0, float(data["tone"])))
        reasons = [str(r)[:200] for r in (data.get("reasons") or [])][:3]
    except Exception:
        return None
    _ai_tone_cache[key] = (round(score, 1), reasons, resp.model)
    return _ai_tone_cache[key]


def blended_tone(text: str) -> dict:
    lex = sx.statement_tone(text)
    ai = ai_tone(text)
    if ai is None:
        return {"score": lex, "lexicon": lex, "ai": None, "reasons": [], "method": "word list", "model": None}
    score = round(AI_WEIGHT * ai[0] + (1 - AI_WEIGHT) * lex, 1)
    return {"score": score, "lexicon": lex, "ai": ai[0], "reasons": ai[1], "method": "AI + word list",
            "model": ai[2]}


def compare_statements(db: Session, st: CentralBankStatement) -> CentralBankStatementVersion | None:
    t_new = blended_tone(st.text)
    st.tone_score = t_new["score"]
    prev = previous_statement(db, st)
    if prev is None:
        return None
    if prev.tone_score is None:
        prev.tone_score = blended_tone(prev.text)["score"]
    cmp = sx.compare(prev.text, st.text)
    summary = dict(cmp.summary)
    shift = round(st.tone_score - prev.tone_score, 1)
    summary.update({
        "tone_previous": prev.tone_score, "tone_latest": st.tone_score, "tone_shift": shift,
        "direction": sx.overall_direction(shift, summary["hawkish_changes"], summary["dovish_changes"]),
        "tone_method": t_new["method"], "tone_lexicon_latest": t_new["lexicon"], "tone_ai_latest": t_new["ai"],
        "tone_ai_reasons": t_new["reasons"], "tone_ai_model": t_new["model"],
    })
    llm = get_llm()
    if llm.available and cmp.changes:
        try:
            top = [{"previous": c["previous"], "latest": c["latest"], "direction": c["direction"]}
                   for c in cmp.changes[:6]]
            resp = llm.complete(
                DATA_GUARD,
                "You are a central-bank analyst. In 3 sentences, explain the policy significance of these statement "
                "changes. Use only the text given; do not speculate beyond it.\n" + wrap_document(str(top)), 400)
            summary["ai_interpretation"] = resp.text.strip()
            summary["ai_model"] = resp.model
        except Exception:
            pass
    db.execute(delete(CentralBankStatementVersion).where(CentralBankStatementVersion.latest_statement_id == st.id))
    v = CentralBankStatementVersion(central_bank_id=st.central_bank_id, previous_statement_id=prev.id,
                                    latest_statement_id=st.id, changes=cmp.changes, summary=summary)
    db.add(v)
    return v


@node("statement_comparison", triggers=("statement", "full"), label="Statement comparison")
def statement_comparison_node(db: Session, ctx: Context) -> None:
    ids = ctx.metrics.get("statement_ids") or []
    if ctx.trigger_entity == "statement" and ctx.trigger_id:
        ids = [ctx.trigger_id]
    sts = [db.get(CentralBankStatement, i) for i in ids] if ids else []
    if not sts:
        codes = ctx.central_banks or {c.code for c in db.scalars(select(CentralBank))}
        for code in codes:
            cb = da.cb_by_code(db, code)
            if cb:
                st = db.scalar(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id)
                               .order_by(CentralBankStatement.published_at.desc()))
                if st:
                    sts.append(st)
    for st in sts:
        if st is None:
            continue
        cb = db.get(CentralBank, st.central_bank_id)
        ctx.central_banks.add(cb.code)
        ctx.currencies.add(cb.currency)
        v = compare_statements(db, st)
        if v is None:
            ctx.change(f"{cb.short_name}: first statement stored (tone {st.tone_score:+.0f}).")
            continue
        s = v.summary
        ctx.change(f"{cb.short_name} statement: {s['changed']} changes, direction {s['direction']} "
                   f"(tone {s['tone_previous']:+.0f} → {s['tone_latest']:+.0f}).")
        if ctx.trigger_entity == "statement" and (s.get("critical") or s.get("high")):
            top = v.changes[0]
            alert(db, "statement_change", f"{cb.short_name} statement: {s['direction'].lower()} language shift",
                  f"{s['critical']} critical and {s['high']} high-importance changes. Top change: "
                  f"{top['what_changed']} ({top['direction']}).", "HIGH" if s.get("critical") else "MEDIUM",
                  entity="cb_statement", entity_id=st.id, currency=cb.currency, central_bank_code=cb.code)


@node("cb_surprise", depends_on=("statement_comparison",), triggers=("meeting",), label="Central bank surprise")
def cb_surprise_node(db: Session, ctx: Context) -> None:
    for code in list(ctx.central_banks):
        cb = da.cb_by_code(db, code)
        if cb is None:
            continue
        m = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                       CentralBankMeeting.decision.is_not(None))
                      .order_by(CentralBankMeeting.meeting_date.desc()))
        if m is None:
            continue
        st = db.scalar(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id)
                       .order_by(CentralBankStatement.published_at.desc()))
        s, label = px.cb_surprise_score(m.expected_change_bps, m.change_bps, m.expected_tone,
                                        st.tone_score if st else None)
        if s is not None and s != m.surprise_score:
            m.surprise_score = s
            ctx.change(f"{cb.short_name} meeting surprise score {s:+.0f} ({label}).")
            if abs(s) >= 15:
                alert(db, "cb_surprise", f"{cb.short_name}: {label}",
                      f"Expected {m.expected_decision or '?'} / tone {m.expected_tone}, actual {m.decision} "
                      f"/ tone {st.tone_score if st else 'n/a'}. Surprise score {s:+.0f}.",
                      "HIGH" if abs(s) >= 40 else "MEDIUM", entity="cb_meeting", entity_id=m.id,
                      currency=cb.currency, central_bank_code=cb.code)


def compute_policy_score(db: Session, cb: CentralBank) -> PolicyScore:
    snap = fnd.build(db, cb.currency)
    dev = snap.deviations
    infl_dev = dev.get("core_inflation", dev.get("inflation"))
    inputs = px.PolicyInputs(
        inflation=snap.inflation, inflation_target=cb.inflation_target, inflation_vs_projection=infl_dev,
        unemployment_change_6m=snap.unemployment_change_6m, unemployment_vs_projection=dev.get("unemployment"),
        growth_vs_projection=dev.get("gdp"), pmi=snap.pmi, last_decision=snap.last_decision,
        last_change_bps=snap.last_change_bps, statement_tone=snap.statement_tone,
        implied_12m_change_bps=snap.implied_change_bps, prob_cut=snap.prob_cut, prob_hike=snap.prob_hike,
        yield_2y_change_1m_bps=snap.y2_change_1m_bps, surprise_index=snap.surprise_index,
        policy_rate=snap.policy_rate, evidence_quality=snap.evidence_quality)
    res = px.score(inputs)
    prev = fnd.latest_policy_score(db, cb.id)
    d, label = px.shift(prev.score if prev else None, res.score)
    why = list(res.explanation)
    if prev:
        why += px.explain_shift(prev.components or {}, res.components)
    if snap.implied_is_proxy and "rate_expectations" in res.components:
        why.append("Rate expectations use the 2Y-yield proxy (no futures data supplied)")
    ps = PolicyScore(central_bank_id=cb.id, as_of=utcnow(), score=res.score, classification=res.classification,
                     direction=res.direction, confidence=res.confidence, components=res.components,
                     evidence_quality=snap.evidence_quality, previous_score=prev.score if prev else None, shift=d,
                     shift_classification=label, explanation=why)
    db.add(ps)
    return ps


@node("policy_score", depends_on=("surprise", "forecast_error", "statement_comparison", "cb_surprise",
                                  "rate_repricing", "forecast_revisions", "yield_curves"),
      triggers=("full",), label="Policy score")
def policy_score_node(db: Session, ctx: Context) -> None:
    codes = ctx.central_banks or {c.code for c in db.scalars(select(CentralBank))}
    for code in sorted(codes):
        cb = da.cb_by_code(db, code)
        if cb is None:
            continue
        prev = fnd.latest_policy_score(db, cb.id)
        ps = compute_policy_score(db, cb)
        if not ps.components:
            # no inputs at all: don't publish a fake "neutral 50"
            db.expunge(ps)
            continue
        db.flush()
        ctx.metrics[f"POLICY:{cb.code}"] = ps.score
        if prev is None or abs(ps.score - prev.score) >= 0.5:
            ctx.change(f"{cb.short_name} policy score {prev.score:.0f} → {ps.score:.0f}." if prev else
                       f"{cb.short_name} policy score {ps.score:.0f} ({ps.classification}).")
        if prev is not None and ps.shift is not None and abs(ps.shift) >= 5:
            alert(db, "policy_shift", f"{cb.short_name}: {ps.shift_classification}",
                  f"Policy score {prev.score:.0f} → {ps.score:.0f} ({ps.classification}). "
                  + "; ".join(ps.explanation[-3:]), "HIGH" if abs(ps.shift) >= 15 else "MEDIUM",
                  entity="central_bank", entity_id=cb.id, currency=cb.currency, central_bank_code=cb.code)
        ctx.currencies.add(cb.currency)


@node("policy_divergence", depends_on=("policy_score",), triggers=("full",), label="Policy divergence")
def policy_divergence_node(db: Session, ctx: Context) -> None:
    snaps: dict[str, fnd.Snapshot] = {}
    for a, b in DIVERGENCE_PAIRS:
        if ctx.central_banks and a not in ctx.central_banks and b not in ctx.central_banks:
            continue
        cba, cbb = da.cb_by_code(db, a), da.cb_by_code(db, b)
        if not cba or not cbb:
            continue
        for cb in (cba, cbb):
            if cb.currency not in snaps:
                snaps[cb.currency] = fnd.build(db, cb.currency)
        sa, sb = snaps[cba.currency], snaps[cbb.currency]
        if sa.policy_score is None or sb.policy_score is None:
            continue

        def d(s: fnd.Snapshot, cb: CentralBank) -> dict:
            return {"code": cb.code, "currency": cb.currency, "score": s.policy_score, "rate": s.policy_rate,
                    "expected_change_bps": s.implied_change_bps, "y2": s.y2, "y10": s.y10,
                    "inflation": s.inflation, "growth": s.gdp_latest,
                    "unemployment": None, "direction": None}

        res = px.divergence(d(sa, cba), d(sb, cbb))
        prev = db.scalar(select(PolicyDivergence).where(PolicyDivergence.base_bank_id == cba.id,
                                                        PolicyDivergence.quote_bank_id == cbb.id)
                         .order_by(PolicyDivergence.as_of.desc()))
        div = round(sa.policy_score - sb.policy_score, 1)
        db.add(PolicyDivergence(base_bank_id=cba.id, quote_bank_id=cbb.id, score_divergence=div,
                                details=res, currency_implication=res["implication"]))
        if prev is not None and abs(div - prev.score_divergence) >= 10:
            alert(db, "divergence_change", f"{a}/{b} policy divergence {prev.score_divergence:+.0f} → {div:+.0f}",
                  res["implication"], "MEDIUM", entity="policy_divergence", currency=cba.currency)
            ctx.change(f"{a}/{b} divergence {prev.score_divergence:+.0f} → {div:+.0f}.")


# ---------------------------------------------------------------------------
# read models
# ---------------------------------------------------------------------------

def dashboard(db: Session, cb: CentralBank) -> dict:
    from app.engines.forecast_engine import accuracy_summary
    from app.engines.market_engine import latest_reaction_for_cb

    snap = fnd.build(db, cb.currency)
    ps = fnd.latest_policy_score(db, cb.id)
    sts = list(db.scalars(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id,
                                                             CentralBankStatement.doc_type == "statement")
                          .order_by(CentralBankStatement.published_at.desc()).limit(2)))
    nxt = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                     CentralBankMeeting.meeting_date >= utcnow().date())
                    .order_by(CentralBankMeeting.meeting_date))
    version = db.scalar(select(CentralBankStatementVersion).where(
        CentralBankStatementVersion.latest_statement_id == sts[0].id)) if sts else None
    acc = accuracy_summary(db, cb.code)
    from app.engines.forecast_engine import where_are_we

    wa = where_are_we(db, cb.code)
    rx = fnd.latest_rate_expectation(db, cb.code)
    return {
        "code": cb.code, "name": cb.name, "short_name": cb.short_name, "currency": cb.currency,
        "country": cb.country, "inflation_target": cb.inflation_target,
        "current_rate": snap.policy_rate, "previous_rate": _previous_rate(cb, snap),
        "rate_from_indicator": cb.code in fnd.POLICY_RATE,
        "edit_codes": {"rate": fnd.POLICY_RATE.get(cb.code), "inflation": fnd.HEADLINE_INFL.get(fnd.COUNTRY.get(cb.currency, cb.country)),
                       "gdp": fnd.GDP.get(fnd.COUNTRY.get(cb.currency, cb.country))}, "last_decision": snap.last_decision,
        "last_change_bps": snap.last_change_bps,
        "next_meeting": nxt.meeting_date if nxt else None, "expected_decision": nxt.expected_decision if nxt else None,
        "policy": ({"score": ps.score, "classification": ps.classification, "direction": ps.direction,
                    "confidence": ps.confidence, "previous_score": ps.previous_score, "shift": ps.shift,
                    "shift_classification": ps.shift_classification, "components": ps.components,
                    "explanation": ps.explanation, "evidence_quality": ps.evidence_quality,
                    "as_of": ps.as_of} if ps else None),
        "momentum": _momentum(db, cb),
        "inflation": snap.inflation, "growth": snap.gdp_latest, "unemployment_change_6m": snap.unemployment_change_6m,
        "market_rate_expectations": ({"prob_cut": rx.prob_cut, "prob_hold": rx.prob_hold, "prob_hike": rx.prob_hike,
                                      "implied_12m_change_bps": rx.implied_12m_change_bps, "as_of": rx.ts,
                                      "source": rx.source} if rx else
                                     ({"implied_12m_change_bps": snap.implied_change_bps, "proxy": True}
                                      if snap.implied_change_bps is not None else None)),
        "latest_statement": _st(sts[0]) if sts else None,
        "previous_statement": _st(sts[1]) if len(sts) > 1 else None,
        "statement_changes": version.summary if version else None,
        "market_reaction": latest_reaction_for_cb(db, cb),
        "where_are_we": wa, "forecast_accuracy": acc,
        "fundamental_implication": wa["policy_implication"]["overall"] if wa["table"] else None,
        "data_status": {"evidence_quality": snap.evidence_quality,
                        "manual_inputs": [s for s in snap.sources if s["input_method"] != "automated"],
                        "sources": snap.sources},
    }


def _previous_rate(cb: CentralBank, snap) -> float | None:
    """Rate before the last move. Banks with a rate indicator: worked out from its history."""
    if cb.code in fnd.POLICY_RATE and snap.policy_rate is not None and snap.last_decision:
        return round(snap.policy_rate - (snap.last_change_bps or 0) / 100, 4)
    return cb.previous_rate


def _momentum(db: Session, cb: CentralBank) -> str | None:
    scores = list(db.scalars(select(PolicyScore.score).where(PolicyScore.central_bank_id == cb.id)
                             .order_by(PolicyScore.as_of.desc()).limit(6)))
    if len(scores) < 2:
        return None
    d = scores[0] - scores[-1]
    return "HAWKISH" if d >= 3 else "DOVISH" if d <= -3 else "STABLE"


def _st(st: CentralBankStatement) -> dict:
    return {"id": st.id, "title": st.title, "published_at": st.published_at, "tone_score": st.tone_score,
            "tone_label": px.tone_label(st.tone_score or 0), "url": st.url, "input_method": st.input_method,
            "verification_status": st.verification_status, "excerpt": st.text[:600]}


def heatmap(db: Session) -> list[dict]:
    from app.engines.forecast_engine import accuracy_summary

    out = []
    for cb in db.scalars(select(CentralBank).order_by(CentralBank.id)):
        ps = fnd.latest_policy_score(db, cb.id)
        nxt = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                         CentralBankMeeting.meeting_date >= utcnow().date())
                        .order_by(CentralBankMeeting.meeting_date))
        acc = accuracy_summary(db, cb.code)
        out.append({"code": cb.code, "name": cb.short_name, "currency": cb.currency,
                    "policy_bias": ps.classification if ps else None, "score": ps.score if ps else None,
                    "shift": ps.shift if ps else None, "next_meeting": nxt.meeting_date if nxt else None,
                    "expected_action": nxt.expected_decision if nxt else None,
                    "forecast_accuracy": acc.get("overall")})
    return out


def comparison(db: Session, cb: CentralBank, statement_id: int | None = None) -> dict | None:
    q = select(CentralBankStatementVersion).where(CentralBankStatementVersion.central_bank_id == cb.id)
    if statement_id:
        q = q.where(CentralBankStatementVersion.latest_statement_id == statement_id)
    v = db.scalar(q.order_by(CentralBankStatementVersion.id.desc()))
    if v is None:
        return None
    prev, latest = db.get(CentralBankStatement, v.previous_statement_id), db.get(CentralBankStatement,
                                                                                 v.latest_statement_id)
    pts = [DataPointStatus(s.verification_status, None, None, True) for s in (prev, latest)]
    return {"previous": _st(prev) | {"text": prev.text}, "latest": _st(latest) | {"text": latest.text},
            "changes": v.changes, "summary": v.summary, "evidence_quality": evidence_quality(pts)}
