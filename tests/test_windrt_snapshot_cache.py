"""retrieveWindRT must reuse a recent snapshot instead of re-querying Wind."""
import pandas as pd
import curves.utils.retrieve as rt


def _reset(monkeypatch, frame):
    calls = []

    def fake_wsq(symbols, fields, **kw):
        calls.append(list(symbols))
        return frame.copy()

    monkeypatch.setattr(rt, "_wsq_until_nonempty", fake_wsq)
    monkeypatch.setattr(rt, "_save_windrt_cache", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_rename_rt_columns", lambda d: d)
    monkeypatch.setattr(rt.pickle, "load", lambda f: pd.DataFrame(index=["A", "B"]))
    monkeypatch.setattr("builtins.open", lambda *a, **k: __import__("io").BytesIO(b""))
    rt._WINDRT_MEM.clear()
    return calls


def test_second_call_within_ttl_reuses_snapshot(monkeypatch):
    calls = _reset(monkeypatch, pd.DataFrame({"x": [1.0, 2.0]}, index=["A", "B"]))
    a = rt.retrieveWindRT("TBond")
    a.iloc[0, 0] = 99.0  # caller mutation must not poison the cache
    b = rt.retrieveWindRT("TBond")
    assert len(calls) == 1
    assert b.iloc[0, 0] == 1.0


def test_expired_snapshot_refetches_and_empty_not_cached(monkeypatch):
    calls = _reset(monkeypatch, pd.DataFrame({"x": [1.0, 2.0]}, index=["A", "B"]))
    rt.retrieveWindRT("TBond")
    rt._WINDRT_MEM["TBond"] = (rt._WINDRT_MEM["TBond"][0] - rt.WINDRT_TTL_SECONDS - 1, rt._WINDRT_MEM["TBond"][1])
    rt.retrieveWindRT("TBond")
    assert len(calls) == 2

    calls = _reset(monkeypatch, pd.DataFrame())
    rt.retrieveWindRT("CBond")
    rt.retrieveWindRT("CBond")
    assert len(calls) == 2
