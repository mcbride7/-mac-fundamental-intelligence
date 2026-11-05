def test_page_caches_refresh_after_an_analysis_update(db):
    """A finished update (e.g. a new policy statement) must show on every tab at once, not after the 10-minute cache."""
    from app.services import recompute
    from app.services import setups_table as tb

    tb.clear_cache()
    a = tb.compute(db)
    assert tb.compute(db) is a  # cached
    s0 = recompute.data_stamp(db)
    recompute.trigger(db, "full")
    assert recompute.data_stamp(db) != s0
    assert tb.compute(db) is not a  # rebuilt with the new analysis
