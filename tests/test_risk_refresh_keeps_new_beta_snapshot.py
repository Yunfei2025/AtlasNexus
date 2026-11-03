import pandas as pd

from web.tabs.risk.books import interactions


def _paths(tmp_path, monkeypatch):
    canon, disp = tmp_path / 'canon.parquet', tmp_path / 'disp.parquet'
    monkeypatch.setattr(interactions, '_SUMMARY_BETA_PARQUET', str(canon))
    monkeypatch.setattr(interactions, '_SUMMARY_BETA_DISPLAY_PARQUET', str(disp))
    return canon, disp


def test_cache_invalidated_after_add_to_portfolio(tmp_path, monkeypatch):
    canon, disp = _paths(tmp_path, monkeypatch)
    pd.DataFrame({'Instrument': ['260021.IB']}).to_parquet(canon, index=False)
    assert interactions._beta_display_cache_invalidated()


def test_cache_not_invalidated_when_cache_exists(tmp_path, monkeypatch):
    canon, disp = _paths(tmp_path, monkeypatch)
    pd.DataFrame({'Instrument': ['260021.IB']}).to_parquet(canon, index=False)
    pd.DataFrame({'Instrument': ['2600006.IB']}).to_parquet(disp, index=False)
    assert not interactions._beta_display_cache_invalidated()


def test_cache_not_invalidated_without_canonical_snapshot(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    assert not interactions._beta_display_cache_invalidated()
