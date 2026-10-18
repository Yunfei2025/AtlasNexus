# -*- coding: utf-8 -*-
"""Audit that the beta backtest and the saved signals follow the design plan (docs/plans/factor_model_improvement.md 3.14-3.17).

    python scripts/audit_design_conformance.py [P06|P11|P14 ...]      (default: P06)

Runs a full factor_scaling backtest per pool and checks, DAILY over the whole history:
  * long size <= 95% of capital and short size <= 95% (independent ceilings, never netted)
  * gross DV01 <= MAX_DV01_PER_CAPITAL (lagged annuity durations, the backtest's own convention)
  * no short in the floored tenors (RiskModelConfig.SHORT_END_LONG_ONLY_TENORS) and no short in a
    substituted tenor (CN20Y is held as CN30Y)
  * shorts only in CN10Y / CN30Y bonds and non-bond assets (FX / commodity / equity)
and on the saved factor-backtest.pkl: IRDL positions follow the symmetric trend floor on every date,
and the default factor pool contains no foreign rate factor.
The live-vs-backtest sizing check is the pytest tests/test_live_backtest_consistency.py.

Nothing is written to the shared input folder: the risk-parity cache save is disabled (a cache MISS recomputes,
which takes a few minutes per pool).
Exit code 0 = all checks passed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from multiasset.book.hedge_instruments import mod_duration
from multiasset.config import RiskModelConfig as R
from multiasset.data import get_asset_type, get_asset_yield_series, load_raw_market_data
from multiasset.factor_backtest import load_factor_backtest, load_factor_rates
from multiasset.factor_model import FactorModelConfig
from settings.paths import DIR_INPUT
from web.tabs.beta import data as beta_data
from web.tabs.beta.callbacks.backtest_hist import orchestrator as orch

C = 10e9
BASE = dict(ir=['IRDL.CN', 'IRSL.CN', 'IRCV.CN'], fx=['FXDL.USDCNY'])
CM6 = ['CMDL.AU', 'CMDL.AL']
CM11 = CM6 + ['CMDL.AG', 'CMDL.CU', 'CMDL.ZN', 'CMDL.RB', 'CMDL.JM']
POOLS = {'P06': (CM6, []), 'P11': (CM11, []), 'P14': (CM11, ['EQDL.IF', 'EQDL.IC', 'EQDL.IH'])}
failures = []


def check(ok, msg):
    print(('PASS  ' if ok else 'FAIL  ') + msg)
    if not ok:
        failures.append(msg)


def audit_backtest(pool, md):
    cm, eq = POOLS[pool]
    beta_data.SELECTED_FACTOR_POOL.update({'ir_factors': BASE['ir'], 'sp_factors': [], 'cr_factors': [],
                                           'fx_factors': BASE['fx'], 'cmd_factors': cm, 'eq_factors': eq, 'timestamp': None})
    seen = {}
    orig = orch.compute_book_pnl
    orch.compute_book_pnl = lambda alloc, *a, **k: (seen.update(alloc=alloc.copy()), orig(alloc, *a, **k))[1]
    orch.save_rp = lambda *a, **k: None                           # never write the shared RP cache
    orch.run_historical_allocation(10, 'billion', '2017-01-02', '2026-10-13', '1Y', 10, 'factor_scaling')
    A = seen['alloc']
    long_, short_ = A.clip(lower=0).sum(axis=1) / C, A.clip(upper=0).abs().sum(axis=1) / C
    cap = R.CAPITAL_UTILISATION_MAX
    check(long_.max() <= cap + 1e-6, f'{pool}: max long size {long_.max():.4f} <= {cap}')
    check(short_.max() <= cap * R.SHORT_SIZE_MAX_RATIO + 1e-6, f'{pool}: max short size {short_.max():.4f} <= {cap * R.SHORT_SIZE_MAX_RATIO}')
    dv01 = pd.Series(0.0, index=A.index)
    for a in A.columns:
        if get_asset_type(a) != 'Rates':
            continue
        s, n, _c, _b = get_asset_yield_series(a, md)
        y = pd.Series(s, dtype=float); y.index = pd.to_datetime(y.index)
        y = y.reindex(y.index.union(A.index)).ffill().reindex(A.index).shift(1)
        dv01 += (A[a].abs() * mod_duration(y, float(n)) / 1e10).fillna(0.0)
    lim = R.MAX_DV01_PER_CAPITAL * C / 1e10
    check(dv01.max() <= lim * 1.001, f'{pool}: max gross DV01 {dv01.max():.3f} <= {lim:.1f} MM/bp')
    for a in R.SHORT_END_LONG_ONLY_TENORS:
        if a in A:
            check((A[a] >= -1).all(), f'{pool}: no short in floored tenor {a}')
    for t_from in R.CN_SHORT_SUBSTITUTE:
        a = f'CN{int(t_from)}Y'
        if a in A:
            check((A[a] >= -1).all(), f'{pool}: no short in substituted tenor {a} (held as {int(R.CN_SHORT_SUBSTITUTE[t_from])}Y)')
    bond_shorts = {c for c in A.columns if get_asset_type(c) in ('Rates', 'Credit') and (A[c] < -1).any()}
    check(bond_shorts <= {'CN10Y', 'CN30Y'}, f'{pool}: bond shorts only in CN10Y/CN30Y (found {sorted(bond_shorts)})')


def audit_signals():
    cfg = FactorModelConfig()
    fm = load_factor_backtest(DIR_INPUT)['FactorModel']
    lv = load_factor_rates(DIR_INPUT)
    for code in [c for c in fm if c.startswith('IRDL.')]:
        p = fm[code]['position'].dropna(); L = lv[code]
        s60, s120 = L.diff(60).reindex(p.index), L.diff(cfg.long_floor_confirm_window).reindex(p.index)
        bull, bear = (s60 < 0) & (s120 < 0), (s60 > 0) & (s120 > 0)
        ok = bool((p[bull] >= cfg.long_floor - 1e-9).all() and (p[bear] <= -cfg.long_floor + 1e-9).all())
        check(ok, f'{code}: symmetric trend floor holds on every date ({int(bull.sum())} bull / {int(bear.sum())} bear days)')
        check(p.between(-1.0001, 1.0001).all(), f'{code}: position within [-1, 1]')
    dp = beta_data.SELECTED_FACTOR_POOL
    foreign = [f for k in ('ir_factors', 'sp_factors', 'cr_factors') for f in dp[k] if f.split('.')[-1] in ('US', 'DE', 'JP', 'UK')]
    check(not foreign, 'default pool excludes foreign rate factors' if not foreign else f'foreign factors in default pool: {foreign}')


if __name__ == '__main__':
    md = load_raw_market_data()
    audit_signals()
    for pool in (sys.argv[1:] or ['P06']):
        audit_backtest(pool, md)
    print('\nALL CHECKS PASSED' if not failures else f'\n{len(failures)} CHECK(S) FAILED')
    sys.exit(1 if failures else 0)
