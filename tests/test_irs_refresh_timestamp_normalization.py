import pickle
from datetime import date

import pandas as pd

import curves.utils.loader as loader
from curves.generators.irs import IRSGenerator, _normalize_datetime_index
from curves.refreshers.irs import IRSRefresher
from web.tabs.alpha.data.io import _normalize_repo_frame


def test_irs_refresher_normalizes_date_index_for_timestamp_lookups():
    ts = pd.Timestamp('2026-10-10 00:00:00')
    series = pd.Series([1.25], index=[date(2026, 10, 10)])

    normalized = IRSRefresher._normalize_date_index(series)

    assert ts in normalized.index
    assert normalized.loc[ts] == 1.25


def test_irs_generator_normalizes_legacy_date_index_for_timestamp_lookups():
    ts = pd.Timestamp('2026-10-10 00:00:00')
    df = pd.DataFrame({'value': [1.0, 2.0]}, index=pd.Index([date(2026, 10, 10), date(2026, 10, 11)], dtype=object))

    normalized = _normalize_datetime_index(df)

    assert ts in normalized.index
    assert normalized.loc[ts, 'value'] == 1.0


def test_alpha_repo_frame_normalizes_mixed_date_index_for_dashboard_lookups():
    ts = pd.Timestamp('2026-10-10 00:00:00')
    df = pd.DataFrame({'value': [1.0, 2.0]}, index=pd.Index([date(2026, 10, 10), date(2026, 10, 11)], dtype=object))

    normalized = _normalize_repo_frame(df)

    assert ts in normalized.index
    assert normalized.loc[ts, 'value'] == 1.0


def test_loadCNBDTS_rebuilds_empty_irs_snapshot(monkeypatch, tmp_path):
    db_path = tmp_path / 'database-px.pkl'
    db_path.write_bytes(pickle.dumps({'IRS': pd.DataFrame()}))
    ref_path = tmp_path / 'TBond-cvref.pkl'
    ref_path.write_bytes(pickle.dumps({'Factors': pd.DataFrame()}))

    monkeypatch.setattr(loader, 'DIR_INPUT', tmp_path)

    def fake_retrieve():
        refreshed = {
            'IRS': pd.DataFrame(
                {'FR001.IR': [1.0]},
                index=pd.DatetimeIndex(['2026-10-10']),
            )
        }
        return refreshed

    monkeypatch.setattr('curves.utils.retrieve.retrieveCNBDTS', fake_retrieve)

    env = loader.loadCNBDTS()

    assert 'SwapTS' in env
    assert env['SwapTS'].shape == (1, 1)
    assert 'FR001.IR' in env['SwapTS'].columns


def test_irs_generator_uses_latest_available_market_date_when_target_missing():
    g = IRSGenerator(asof=date(2026, 10, 10))
    g.environment_ts = pd.DataFrame(
        {'FR001.IR': [1.0, 2.0]},
        index=pd.DatetimeIndex(['2026-10-08', '2026-10-09'])
    )

    assert g._resolve_market_date(pd.Timestamp('2026-10-10')) == pd.Timestamp('2026-10-09')
    assert g._resolve_market_date(pd.Timestamp('2026-10-08')) == pd.Timestamp('2026-10-08')
