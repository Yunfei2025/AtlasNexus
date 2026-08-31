# -*- coding: utf-8 -*-
"""Pin the Alpha backtest trade-direction convention.

For a yield-based spread the engines are fed ``-raw``; a ``position`` of
``+1`` on that series profits when the *raw* spread falls/narrows, which for
a curve spread (``CGB-10s30s = Y30 - Y10``) is economically long the 30y and
short the 10y -- the desk's LONG.  The MR branch used to label that same
position ``SELL``, contradicting the trend branch and reporting an
economically long trade as a short.
"""

import numpy as np
import pandas as pd

from web.tabs.alpha.backtest._direction import _direction_label
from web.tabs.alpha.backtest.engine_monthly import run_monthly_style_backtest


def test_direction_label_follows_position_sign():
    assert _direction_label(1) == 'LONG'
    assert _direction_label(-1) == 'SHORT'


def _run_on(raw: pd.Series):
    """Run the monthly engine on a yield-based (negated) series."""
    ts_bt = -raw
    months = sorted(set(ts_bt.index.to_period('M')))
    return run_monthly_style_backtest(
        ts_bt, {m: 'mr' for m in months},
        entry_z=1.0, exit_z=0.0, stop_z=99.0, min_hold=1,
        theta_z=1.5, mom_window=20, vol_window=60, trailing_mult=999.0,
        allow_short=True, duration_mult=1.0, spread_type='TenorSpread',
    )


def test_long_loses_when_raw_spread_rises():
    """A LONG must lose when the raw spread widens, and win when it narrows."""
    idx = pd.bdate_range('2020-01-01', periods=600)
    rng = np.random.default_rng(0)
    # mean-reverting core so the MR engine actually trades, plus a late ramp
    noise = pd.Series(rng.normal(0, 0.02, len(idx)), index=idx).cumsum()
    raw = pd.Series(0.30, index=idx) + noise - noise.rolling(120, min_periods=1).mean()

    res = _run_on(raw)
    tdf = res.get('trades_df')
    assert isinstance(tdf, pd.DataFrame) and not tdf.empty, 'expected trades'

    for _, t in tdf.iterrows():
        entry, exit_ = pd.Timestamp(t['entry_date']), pd.Timestamp(t['exit_date'])
        raw_move = float(raw.loc[:exit_].iloc[-1] - raw.loc[:entry].iloc[-1])
        price_pnl = float(t['spd_chg'])          # bp, price leg only
        if abs(raw_move) < 1e-9:
            continue
        if str(t['direction']).upper() == 'LONG':
            # long the spread => profits when raw FALLS
            assert (price_pnl > 0) == (raw_move < 0), (
                f"LONG at {entry.date()}: raw moved {raw_move:+.4f} "
                f"but price pnl was {price_pnl:+.2f}bp"
            )
        else:
            assert (price_pnl > 0) == (raw_move > 0), (
                f"SHORT at {entry.date()}: raw moved {raw_move:+.4f} "
                f"but price pnl was {price_pnl:+.2f}bp"
            )


def test_mr_and_trend_branches_agree_on_labels():
    """Both style branches must label the same position sign identically."""
    import inspect
    from web.tabs.alpha.backtest import engine_monthly
    src = inspect.getsource(engine_monthly)
    # the old inverted mapping must not come back
    assert "'SELL' if position == 1" not in src
    assert "'BUY' if position == 1" not in src
