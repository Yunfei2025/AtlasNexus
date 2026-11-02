import pandas as pd

from web.tabs.risk import helpers


def _setup(tmp_path, monkeypatch):
    snap, pos = tmp_path / 'snap.parquet', tmp_path / 'pos.parquet'
    pd.DataFrame({'spread_type': ['TenorSpread'] * 2, 'ID': ['CGB-2s5s', 'LGBCGB-30y'],
                  'notional_mm': [100, 200]}).to_parquet(snap, index=False)
    monkeypatch.setattr(helpers, '_SUMMARY_ALPHA_PARQUET', str(snap))
    monkeypatch.setattr(helpers, '_ALPHA_POSITIONS_PARQUET', str(pos))
    # the table rendered before LGBCGB-30y was added only knows CGB-2s5s
    return snap, [{'Spread Type': 'TenorSpread', 'ID': 'CGB-2s5s', 'Volume (mm)': 50}]


def test_refresh_persist_keeps_trades_added_after_render(tmp_path, monkeypatch):
    snap, rows = _setup(tmp_path, monkeypatch)
    helpers._persist_alpha_summary_rows(rows, prune=False)
    assert set(pd.read_parquet(snap)['ID']) == {'CGB-2s5s', 'LGBCGB-30y'}


def test_default_persist_still_prunes_deleted_trades(tmp_path, monkeypatch):
    snap, rows = _setup(tmp_path, monkeypatch)
    helpers._persist_alpha_summary_rows(rows)
    assert set(pd.read_parquet(snap)['ID']) == {'CGB-2s5s'}
