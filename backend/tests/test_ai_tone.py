import pytest

from app.ai.llm import LLMProvider, LLMResponse, set_llm

HAWK = ("The Committee judges that inflation remains elevated. Further tightening may be appropriate. "
        "The Committee will remain vigilant.")
DOVE = ("Inflation has eased substantially. The Committee will be patient. Risks to employment have "
        "increased and the Committee is prepared to adjust the stance as appropriate.")


class FakeLLM(LLMProvider):
    name, model = "fake", "fake-1"
    calls = 0

    @property
    def available(self):
        return True

    def complete(self, system, prompt, max_tokens=1500):
        FakeLLM.calls += 1
        tone = 70 if "Further tightening may" in prompt else -60
        return LLMResponse(f'Sure: {{"tone": {tone}, "reasons": ["forward guidance", "risk balance"]}}', "fake", "fake-1")


@pytest.fixture()
def fake_llm():
    from app.engines import cb_engine

    cb_engine._ai_tone_cache.clear()
    FakeLLM.calls = 0
    set_llm(FakeLLM())
    yield
    set_llm(None)
    cb_engine._ai_tone_cache.clear()


def test_word_list_only_without_ai():
    from app.analytics import statement as sx
    from app.engines import cb_engine

    set_llm(LLMProvider())
    t = cb_engine.blended_tone(HAWK)
    assert t["method"] == "word list" and t["score"] == sx.statement_tone(HAWK) and t["ai"] is None
    set_llm(None)


def test_blend_and_cache(fake_llm):
    from app.analytics import statement as sx
    from app.engines import cb_engine

    t = cb_engine.blended_tone(HAWK)
    assert t["method"] == "AI + word list" and t["ai"] == 70
    assert t["score"] == round(0.6 * 70 + 0.4 * sx.statement_tone(HAWK), 1)
    cb_engine.blended_tone(HAWK)
    assert FakeLLM.calls == 1  # same text is not sent twice


def test_bad_ai_reply_falls_back(fake_llm, monkeypatch):
    from app.engines import cb_engine

    monkeypatch.setattr(FakeLLM, "complete", lambda self, *a, **k: LLMResponse("I can't rate this", "fake", "f"))
    assert cb_engine.blended_tone(DOVE)["method"] == "word list"


def test_comparison_uses_blended_tone(db, fake_llm):
    from datetime import datetime, timezone

    from app.engines import cb_engine
    from app.models import CentralBankStatement
    from app.services import data_access as da

    cb = da.cb_by_code(db, "FED")
    old = CentralBankStatement(central_bank_id=cb.id, doc_type="statement", title="old", text=HAWK,
                               published_at=datetime(2026, 7, 29, tzinfo=timezone.utc))
    new = CentralBankStatement(central_bank_id=cb.id, doc_type="statement", title="new", text=DOVE,
                               published_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
    db.add_all([old, new])
    db.flush()
    cb_engine.compare_statements(db, old)
    v = cb_engine.compare_statements(db, new)
    s = v.summary
    assert s["tone_method"] == "AI + word list" and s["tone_ai_latest"] == -60
    assert s["tone_shift"] == round(new.tone_score - old.tone_score, 1) and s["direction"] == "Dovish"
    assert s["tone_ai_reasons"] == ["forward guidance", "risk balance"]
