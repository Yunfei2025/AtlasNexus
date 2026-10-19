# -*- coding: utf-8 -*-
"""factor_scaling backtest design (user, 2026-10-18): at each month start run risk parity over ALL instruments of the
selected pool, then scale daily with the factor model. No correlation screen, no Stage-1 solve, no shared-cache I/O.
Uses real market data and saved signals; skips when absent."""

import pytest

POOL = ['IRDL.CN', 'IRSL.CN', 'IRCV.CN', 'FXDL.USDCNY', 'CMDL.AU', 'CMDL.AL', 'CMDL.AG', 'CMDL.CU', 'CMDL.ZN', 'CMDL.RB', 'CMDL.JM']


def _run(monkeypatch, screen):
    try:
        from multiasset.config import RiskModelConfig
        from multiasset.book import sizing as SZ
        from web.tabs.beta import data as beta_data
        from web.tabs.beta.callbacks.backtest_hist import orchestrator as orch
    except Exception as exc:
        pytest.skip(f'imports unavailable: {exc}')
    monkeypatch.setattr(RiskModelConfig, 'FACTOR_SCALING_CORR_SCREEN', screen)
    sizes = []
    real = SZ.pool_sleeve_budgets
    monkeypatch.setattr(SZ, 'pool_sleeve_budgets', lambda factors, *a, **k: (sizes.append(len(list(factors))), real(factors, *a, **k))[1])
    monkeypatch.setitem(beta_data.SELECTED_FACTOR_POOL, 'ir_factors', ['IRDL.CN', 'IRSL.CN', 'IRCV.CN'])
    for key, val in (('sp_factors', []), ('cr_factors', []), ('fx_factors', ['FXDL.USDCNY']),
                     ('cmd_factors', ['CMDL.AU', 'CMDL.AL', 'CMDL.AG', 'CMDL.CU', 'CMDL.ZN', 'CMDL.RB', 'CMDL.JM']), ('eq_factors', [])):
        monkeypatch.setitem(beta_data.SELECTED_FACTOR_POOL, key, val)
    return orch, sizes


def test_default_runs_pool_risk_parity_every_month_without_touching_the_rp_cache(monkeypatch):
    orch, sizes = _run(monkeypatch, screen=False)

    def boom(*a, **k):
        raise AssertionError('the no-screen mode must not read or write the shared RP cache')
    monkeypatch.setattr(orch, 'load_rp', boom)
    monkeypatch.setattr(orch, 'save_rp', boom)
    try:
        r = orch.run_historical_allocation(10, 'billion', '2023-01-02', '2024-12-31', '1Y', 10, 'factor_scaling')
    except Exception as exc:
        if 'No FactorModel signals' in str(exc) or 'not found' in str(exc).lower():
            pytest.skip(f'saved signals/data unavailable: {exc}')
        raise
    assert sizes and set(sizes) == {len(POOL)}               # every month budgets ALL 11 pool factors
    assert len(sizes) >= 20                                  # one budget per month start
    m = r['metrics']
    assert m['avg_capital_usage'] <= 0.95 + 1e-9 and m['avg_short_pct'] <= 95.0


def test_legacy_screen_is_still_available_behind_the_flag(monkeypatch):
    orch, sizes = _run(monkeypatch, screen=True)
    # with the screen the Stage-1 solve runs (in-memory cache so the shared one is never written)
    mem = {}
    from multiasset.backtest_cache import rp_hash
    monkeypatch.setattr(orch, 'load_rp', lambda d, p: mem.get(rp_hash(p)))
    monkeypatch.setattr(orch, 'save_rp', lambda d, p, w, a, s, c=None, x=None: (mem.__setitem__(rp_hash(p), dict(
        weights_by_date=w, asset_pools_by_date=a, screened_factors_by_date=s, last_corr_matrix=c, stage2_ctx_by_date=x or {})), rp_hash(p))[1])
    try:
        orch.run_historical_allocation(10, 'billion', '2024-07-01', '2024-12-31', '1Y', 5, 'factor_scaling')
    except Exception as exc:
        pytest.skip(f'saved signals/data unavailable: {exc}')
    assert sizes and min(sizes) < len(POOL)                  # top_pairs=5 keeps only a subset of the 11 factors
