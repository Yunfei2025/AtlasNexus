# -*- coding: utf-8 -*-
"""Holdout check of the beta-book design decisions (docs/plans/factor_model_improvement.md, P5 / section 3.21).

    python scripts/holdout_validation.py [--holdout-start 2025-04-01] [--since YYYY-MM-DD] [--pools P06 P11 P14 P06+IRDL4]

For every design decision it runs the full 2017-2026 factor_scaling backtest with the production rule and with the alternative,
splits the daily excess-return stream (return over the cash benchmark, previous-NAV base) at ``--holdout-start`` and reports the
Sharpe in the development period and in the holdout, so you can see whether the winner chosen on development data also wins on
the holdout. IMPORTANT: the default holdout (2025-04-01 onward) was visible when the decisions were taken, so it is a SOFT holdout;
use ``--since <date>`` with a date after the freeze of the production configuration for the clean forward test.

Nothing is written to the shared input folder (the risk-parity cache is replaced by an in-memory dict).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dataclasses

import numpy as np
import pandas as pd

import multiasset.book.funding as F
from multiasset.backtest_cache import rp_hash
from multiasset.config import RiskModelConfig as R
from multiasset.factor_backtest import load_factor_backtest, load_factor_rates
from multiasset.factor_model import FactorModelConfig, apply_trend_floor, build_position_series, factor_sizing_override
from settings.paths import DIR_INPUT
from web.tabs.beta import data as beta_data
from web.tabs.beta.callbacks.backtest_hist import orchestrator as orch

BASE = dict(ir=['IRDL.CN', 'IRSL.CN', 'IRCV.CN'], fx=['FXDL.USDCNY'])
CM6 = ['CMDL.AU', 'CMDL.AL']
CM11 = CM6 + ['CMDL.AG', 'CMDL.CU', 'CMDL.ZN', 'CMDL.RB', 'CMDL.JM']
F4 = ['IRDL.US', 'IRDL.DE', 'IRDL.JP', 'IRDL.UK']
POOLS = {'P06': (BASE['ir'], CM6), 'P11': (BASE['ir'], CM11), 'P14': (BASE['ir'], CM11, ['EQDL.IF', 'EQDL.IC', 'EQDL.IH']),
         'P06+IRDL4': (BASE['ir'] + F4, CM6)}
ALL_BOND = {1.0: ['bond'], 2.0: ['bond'], 5.0: ['bond'], 10.0: ['bond'], 20.0: ['bond'], 30.0: ['bond']}
FUT_ROUTE = {**ALL_BOND, 10.0: ['T', 'bond'], 30.0: ['TL', 'bond']}

# (label, config overrides, old long-only IRDL signals?) - each is ONE design decision against the production rule
DECISIONS = [
    ('production', {}, False),
    ('IRDL long-only (old rule)', {}, True),
    ('no short-end floor', dict(SHORT_END_LONG_ONLY_TENORS=()), False),
    ('floor 1Y/2Y only', dict(SHORT_END_LONG_ONLY_TENORS=('CN1Y', 'CN2Y')), False),
    ('legacy sleeve budgets', dict(SLEEVE_BUDGET_RULE='sqrt_vol_equal'), False),
    ('shorts counted in capital (old)', dict(SHORT_CAPITAL_RATE=1.0), False),
    ('futures for 10Y/30Y shorts', dict(CN_SHORT_ROUTING=FUT_ROUTE), False),
    ('monthly correlation screen', dict(FACTOR_SCALING_CORR_SCREEN=True), False),
]


def long_only_irdl_signals():
    """The previous IRDL rule (long-only + bull-only floor), rebuilt from the saved predictions."""
    fm = load_factor_backtest(DIR_INPUT)['FactorModel']
    levels = load_factor_rates(DIR_INPUT)
    out = {}
    for code, df in fm.items():
        if 'position' not in df.columns:
            continue
        pos = df['position'].dropna()
        if code.startswith('IRDL.'):
            cfg = dataclasses.replace(FactorModelConfig(), trend_floor_symmetric=False, **factor_sizing_override(code))
            p = build_position_series(df['predicted_return'], df['returns'], cfg, long_only=True,
                                      effective_horizon=df['effective_horizon'])['position']
            pos, _ = apply_trend_floor(p, levels[code], cfg)
        pos.index = pd.to_datetime(pos.index)
        out[code] = pos.sort_index()
    return out


def stream_stats(exc, nav, start, end):
    s = exc[start:end]
    v = nav[start:end]
    sharpe = s.mean() / s.std() * np.sqrt(252) if len(s) > 20 and s.std() > 0 else float('nan')
    return dict(sharpe=float(sharpe), excess=float(s.mean() * 252), dd=float((v / v.cummax() - 1).min()) if len(v) else float('nan'))


def run_all(pools, holdout_start, since):
    mem, hurdle = {}, {}
    orch.load_rp = lambda d, p: mem.get(rp_hash(p))
    orch.save_rp = lambda d, p, w, a, s, c=None, x=None: (mem.__setitem__(rp_hash(p), dict(
        weights_by_date=w, asset_pools_by_date=a, screened_factors_by_date=s, last_corr_matrix=c, stage2_ctx_by_date=x or {})), rp_hash(p))[1]
    orig_h = F.benchmark_hurdle_daily
    F.benchmark_hurdle_daily = lambda *a, **k: (hurdle.__setitem__('h', orig_h(*a, **k)), hurdle['h'])[1]
    orig_load = orch.load_factor_signal_series
    lo_sig = long_only_irdl_signals()
    defaults = {k: getattr(R, k) for k in ('SHORT_END_LONG_ONLY_TENORS', 'SLEEVE_BUDGET_RULE', 'SHORT_CAPITAL_RATE', 'CN_SHORT_ROUTING',
                                           'FACTOR_SCALING_CORR_SCREEN')}
    hs = pd.Timestamp(holdout_start)
    results = {}
    for pool in pools:
        spec = POOLS[pool]
        ir, cm = spec[0], spec[1]
        eq = spec[2] if len(spec) > 2 else []
        beta_data.SELECTED_FACTOR_POOL.update({'ir_factors': ir, 'sp_factors': [], 'cr_factors': [], 'fx_factors': BASE['fx'],
                                               'cmd_factors': cm, 'eq_factors': eq, 'timestamp': None})
        for label, ov, old in DECISIONS:
            if label == 'monthly correlation screen' and pool not in ('P11',):
                continue                                              # Stage-1 solves are slow; one pool is enough for this decision
            for k, v in defaults.items():
                setattr(R, k, ov.get(k, v))
            orch.load_factor_signal_series = (lambda input_dir=None: {k: s.copy() for k, s in lo_sig.items()}) if old else orig_load
            r = orch.run_historical_allocation(10, 'billion', '2017-01-02', '2026-10-13', '1Y', 10, 'factor_scaling')
            nav = r['nav_series']
            nav.index = pd.DatetimeIndex(r['df_pnl']['Date'])
            v_cny = nav / 1000.0 * 10e9
            exc = (v_cny.pct_change() - hurdle['h'].reindex(nav.index).fillna(0.0) / v_cny.shift(1)).dropna()
            end = exc.index.max()
            results[(pool, label)] = dict(
                dev=stream_stats(exc, v_cny, exc.index.min(), hs - pd.Timedelta(days=1)),
                hold=stream_stats(exc, v_cny, hs, end),
                since=stream_stats(exc, v_cny, pd.Timestamp(since), end) if since else None)
            print(f'  done {pool:10s} {label}', flush=True)
    for k, v in defaults.items():
        setattr(R, k, v)
    return results


def report(results, holdout_start, since):
    print(f'\nSharpe (vs cash)   DEV = 2017-01-02 .. {pd.Timestamp(holdout_start) - pd.Timedelta(days=1):%Y-%m-%d}   HOLD = {holdout_start} .. end')
    agree = total = 0
    for pool in sorted({p for p, _ in results}):
        prod = results[(pool, 'production')]
        print(f"\n{pool}: production  DEV {prod['dev']['sharpe']:.2f}  HOLD {prod['hold']['sharpe']:.2f}  "
              f"(HOLD excess {prod['hold']['excess']*100:.2f}%/yr, maxDD {prod['hold']['dd']*100:.1f}%)"
              + (f"  SINCE {prod['since']['sharpe']:.2f}" if prod['since'] else ''))
        print(f"  {'alternative':36s} {'DEV d':>7s} {'HOLD d':>7s}   production still better in HOLD?")
        for (p, label), r in sorted(results.items()):
            if p != pool or label == 'production':
                continue
            d_dev = prod['dev']['sharpe'] - r['dev']['sharpe']
            d_hold = prod['hold']['sharpe'] - r['hold']['sharpe']
            same = (d_dev > 0) == (d_hold > 0)
            agree += same
            total += 1
            print(f"  {label:36s} {d_dev:+7.2f} {d_hold:+7.2f}   {'yes (consistent)' if d_hold > 0 and d_dev > 0 else 'no - production loses in HOLD' if d_hold <= 0 and d_dev > 0 else 'production lost in DEV, wins in HOLD' if d_hold > 0 else 'production loses in both'}")
    print(f'\nproduction-vs-alternative sign agrees between DEV and HOLD in {agree} of {total} comparisons')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--holdout-start', default='2025-04-01')
    ap.add_argument('--since', default=None, help='clean forward-test start date (after the production config was frozen)')
    ap.add_argument('--pools', nargs='+', default=['P06', 'P11', 'P14', 'P06+IRDL4'])
    a = ap.parse_args()
    res = run_all(a.pools, a.holdout_start, a.since)
    report(res, a.holdout_start, a.since)
