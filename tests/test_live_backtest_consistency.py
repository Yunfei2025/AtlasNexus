# -*- coding: utf-8 -*-
"""The Portfolio tab (live) and the backtest must size the book identically (docs 3.17): same signals, same
date -> same positions up to lot rounding. Uses real market data and saved signals; skips when absent.
Writes nothing to the shared input folder (the positions export is redirected to tmp_path)."""

import pandas as pd
import pytest

C = 10e9
P06 = ['IRDL.CN', 'IRSL.CN', 'IRCV.CN', 'FXDL.USDCNY', 'CMDL.AU', 'CMDL.AL']
P11 = P06 + ['CMDL.AG', 'CMDL.CU', 'CMDL.ZN', 'CMDL.RB', 'CMDL.JM']
CREDIT = P06 + ['CRDL.CDB', 'CRDL.LGB', 'CRDL.MTN', 'CRDL.NCD']
# production default pool (web.tabs.beta.data.SELECTED_FACTOR_POOL, 2026-11-03)
DEFAULT = ['IRDL.CN', 'IRSL.CN', 'IRCV.CN'] + [f'{k}.{u}' for u in ('CDB', 'LGB', 'MTN') for k in ('CRDL', 'CRSL', 'CRCV')] \
    + ['CRDL.NCD', 'CRSL.NCD']


def _live_and_backtest(factors, tmp_path, monkeypatch, snapshot_factors=None, extra_assets=()):
    try:
        from settings.paths import DIR_INPUT
        from multiasset.config import RiskModelConfig as R
        from multiasset.data import load_raw_market_data, get_asset_type
        from multiasset.factor_backtest import load_factor_backtest
        from multiasset.book import sizing as SZ
        from multiasset.book.capital import weights_to_notional
        from multiasset.book.overlay import substitute_shorts, overlay_routed_assets
        from web.tabs.beta.data import get_assets_from_factors, FACTOR_TO_ASSET_MAP, compute_factor_vol_map, compute_factor_cov
        from web.tabs.beta.callbacks.portfolio_run import _run_analysis as RA
        md = load_raw_market_data()
        fm = load_factor_backtest(DIR_INPUT)['FactorModel']
        # a pool factor with no saved signal holds no sleeve on either side (backtest and live)
        pos = {f: float(fm[f]['position'].dropna().iloc[-1]) for f in factors if f in fm}
        last_date = fm[factors[0]].index.max()
    except Exception as exc:                                    # data/artifacts unavailable
        pytest.skip(f'market data or saved signals unavailable: {exc}')

    monkeypatch.setattr(RA, '_BETA_BOOK_POSITIONS_PARQUET', str(tmp_path / 'positions.parquet'))
    # snapshot_factors: the factors this session predicted; the rest must come from the saved signals
    snap = [{'risk_factor': f, 'scalar': -p if f.startswith('IRSL.') else p} for f, p in pos.items()
            if snapshot_factors is None or f in snapshot_factors]

    # live path = the Portfolio tab helpers
    names = list(dict.fromkeys([a['name'] for a in get_assets_from_factors(factors)] + list(extra_assets)))
    rb, _ = RA.build_risk_budgets('factor_scaling', [], [])
    summary, _r, _v, fexp, _fr, port, _w = RA.run_optimization(C, names, rb)
    summary = RA.apply_factor_scaling(summary, snap, factors, C)
    live = RA.build_portfolio_table(summary, fexp, port, C, R.MAX_DV01_PER_CAPITAL, allocation_mode='factor_scaling')
    live_cap = pd.Series(live['final_capital'], dtype=float)

    # backtest path = the functions the orchestrator calls, in its order
    budget = SZ.pool_sleeve_budgets(factors, compute_factor_vol_map(factors), cov=compute_factor_cov(factors))
    days = pd.bdate_range(end=last_date, periods=4)
    sig = {f: pd.Series(p, index=pd.bdate_range(end=days[-1], periods=40)) for f, p in pos.items()}
    w, mdur, _sk = SZ.signed_sleeve_weights_daily({days[0]: budget}, sig, days, FACTOR_TO_ASSET_MAP, md,
                                                  long_only_assets=R.SHORT_END_LONG_ONLY_TENORS)
    ov = overlay_routed_assets(w.columns, md) if R.ROUTE_CN_SHORTS_TO_OVERLAY else []
    w = SZ.scale_sleeve_to_dv01_target(w, mdur, C, R.MAX_DV01_PER_CAPITAL, R.CAPITAL_UTILISATION_MAX,
                                       overlay_assets=ov, overlay_margin_rate=0.03)
    cls = {n: {'Commodities': 'comm', 'FX': 'fx', 'Credit': 'credit'}.get(get_asset_type(n), 'bond') for n in w.columns}
    row = weights_to_notional(w.iloc[-1], C, asset_class_of=cls, signed_classes=('fx', 'bond', 'comm', 'credit'),
                              overlay_assets=ov, overlay_margin_rate=0.03)
    bt = substitute_shorts(pd.DataFrame([row]), md).iloc[0]
    return live, live_cap, bt


def test_load_factor_signal_series_handles_incompatible_pickle(monkeypatch):
    import web.tabs.beta.callbacks.backtest_hist._signals as signals
    def boom(_input_dir=None):
        raise NotImplementedError("(dtype('<M8[ns]'), array(['2026-01-01'], dtype='datetime64[ns]'))")
    monkeypatch.setattr(signals, 'load_factor_backtest', boom)
    assert signals.load_factor_signal_series() == {}


def test_default_pool_is_the_documented_one():
    from web.tabs.beta.data import selected_factors
    assert selected_factors() == DEFAULT


@pytest.mark.parametrize('factors,snapshot_factors,extra_assets', [
    (P06, None, ()), (P11, None, ()),
    # credit pool, session snapshot holds only the CN rates factors (the 2026-11-03 live book), and
    # an asset in the pool that no factor sleeve trades (a UK bond) - it must hold nothing
    (CREDIT, ('IRDL.CN', 'IRSL.CN', 'IRCV.CN'), ('UK10Y',)),
    (DEFAULT, None, ()), (DEFAULT, ('IRDL.CN', 'IRSL.CN', 'IRCV.CN'), ()),
], ids=['P06', 'P11', 'CREDIT-partial-snapshot', 'DEFAULT', 'DEFAULT-partial-snapshot'])
def test_live_tab_sizes_the_book_like_the_backtest(factors, snapshot_factors, extra_assets, tmp_path, monkeypatch):
    live, live_cap, bt = _live_and_backtest(factors, tmp_path, monkeypatch, snapshot_factors, extra_assets)
    for a in extra_assets:
        assert live_cap.get(a, 0.0) == 0.0
    both = pd.DataFrame({'live': live_cap, 'bt': bt}).fillna(0.0)
    # lot rounding only (10m bonds / 1m others, plus the DV01 re-truncation): well under 0.3% of capital per asset
    assert (both['live'] - both['bt']).abs().max() <= 0.003 * C, both
    long_bt, short_bt = bt.clip(lower=0).sum() / C, bt.clip(upper=0).abs().sum() / C
    long_l, short_l = live['long_cny'] / C, live['short_cny'] / C
    assert abs(long_l - long_bt) < 0.005 and abs(short_l - short_bt) < 0.005
    # the design limits hold in the live book
    assert long_l <= 0.95 + 1e-9 and short_l <= 0.95 + 1e-9
    assert live['total_dv01'] <= 5.0 * 1.001                       # gross DV01 within the 5 MM/bp cap
    for a in ('CN1Y', 'CN2Y', 'CN5Y', 'CN20Y'):
        assert live_cap.get(a, 0.0) >= 0.0                         # floor 1/2/5Y and no 20Y short (held as 30Y)
    # the Duration column is shown with 2 decimals (sizing keeps full precision)
    dur = live['portfolio_table_df'].loc[lambda d: d['Asset Type'] != 'TOTAL', 'Duration'].astype(float)
    assert (dur == dur.round(2)).all() and (dur > 0).any()
    col = next(c for c in live['positions_table'].columns if c['id'] == 'Duration')
    assert col['format'].to_plotly_json()['specifier'] == '.2f'
