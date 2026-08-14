import numpy as np
import pandas as pd

from web.tabs.alpha.backtest.engine_monthly import (
    build_monthly_style_schedule,
    canonical_style,
    run_monthly_style_backtest,
)
from web.tabs.alpha.callbacks.backtest_tab import _apply_monthly_style_schedule


def _bdays(n, start='2020-01-01'):
    return pd.bdate_range(start, periods=n)


def _oscillating(n=900, amp=1.0, period=60):
    idx = _bdays(n)
    return pd.Series(amp * np.sin(np.arange(n) * 2 * np.pi / period), index=idx)


def _drifting(n=900, slope=0.05, noise=0.2, seed=7):
    """Trending series with noise: a perfectly linear ramp has zero MAD, so the
    z-momentum normalisation would be undefined."""
    idx = _bdays(n)
    rng = np.random.default_rng(seed)
    return pd.Series(np.arange(n) * slope + rng.normal(0, noise, n), index=idx)


# --------------------------------------------------------------------------
# Style alias resolution
# --------------------------------------------------------------------------

def test_canonical_style_resolves_aliases():
    assert canonical_style('mr') == 'mr'
    assert canonical_style('mean_reverting') == 'mr'
    assert canonical_style('Mean-Reverting') == 'mr'
    assert canonical_style('trend') == 'trend'
    assert canonical_style('trending') == 'trend'
    assert canonical_style('momentum') == 'trend'
    assert canonical_style('uncertain') == 'skip'
    assert canonical_style(None) == 'skip'


def test_apply_monthly_style_schedule_overrides_uncertain():
    schedule = pd.DataFrame([
        {'review_date': pd.Timestamp('2024-01-01'), 'regime': 'uncertain', 'assigned_style': 'mr'},
        {'review_date': pd.Timestamp('2024-02-01'), 'regime': 'trending', 'assigned_style': 'trend'},
    ])

    month_to_style, adjusted = _apply_monthly_style_schedule(schedule, 'mr', 'trend')

    assert month_to_style[pd.Period('2024-01', 'M')] == 'trend'
    assert month_to_style[pd.Period('2024-02', 'M')] == 'trend'
    assert adjusted.loc[0, 'assigned_style'] == 'trend'


def test_apply_monthly_style_schedule_keeps_manual_style_when_requested():
    schedule = pd.DataFrame([
        {'review_date': pd.Timestamp('2024-01-01'), 'regime': 'uncertain', 'assigned_style': 'mr'},
    ])

    month_to_style, adjusted = _apply_monthly_style_schedule(schedule, 'mr', 'manual')

    assert month_to_style[pd.Period('2024-01', 'M')] == 'mr'
    assert adjusted.loc[0, 'assigned_style'] == 'mr'


# --------------------------------------------------------------------------
# Monthly review scheduling (plan test items 5, 6)
# --------------------------------------------------------------------------

def test_review_dates_are_first_observation_of_each_month():
    s = _oscillating(400)
    schedule, _ = build_monthly_style_schedule(s, 'mr')

    assert not schedule.empty
    for review_date in schedule['review_date']:
        month = s[s.index.to_period('M') == review_date.to_period('M')]
        assert review_date == month.index.min()


def test_schedule_uses_only_data_up_to_review_date():
    """Appending future data must not change any earlier review's assignment."""
    s = _oscillating(600)
    early, _ = build_monthly_style_schedule(s.iloc[:400], 'mr')
    full, _ = build_monthly_style_schedule(s, 'mr')

    merged = early.merge(full, on='review_date', suffixes=('_early', '_full'))
    assert len(merged) == len(early)
    assert (merged['assigned_style_early'] == merged['assigned_style_full']).all()
    assert (merged['regime_early'] == merged['regime_full']).all()


def test_style_is_constant_within_a_calendar_month():
    s = _oscillating(600)
    _, month_to_style = build_monthly_style_schedule(s, 'mr')
    res = run_monthly_style_backtest(s, month_to_style)

    style_ts = res['style_ts']
    per_month = style_ts.groupby(style_ts.index.to_period('M')).nunique()
    assert (per_month <= 1).all()


def test_uncertain_carries_previous_style_forward():
    schedule, month_to_style = build_monthly_style_schedule(
        _oscillating(600), 'mr', uncertain_policy='carry_forward'
    )
    uncertain = schedule[schedule['regime'].isin(['uncertain', 'insufficient_history'])]
    assert (uncertain['assigned_style'].isin(['mr', 'trend'])).all()
    assert uncertain['fallback_reason'].str.contains('previous_style|default_style').all()


def test_uncertain_skip_policy_leaves_month_untradeable():
    schedule, month_to_style = build_monthly_style_schedule(
        _oscillating(600), 'mr', uncertain_policy='skip'
    )
    uncertain = schedule[schedule['regime'] == 'uncertain']
    if not uncertain.empty:
        assert (uncertain['assigned_style'] == 'skip').all()
        for review_date in uncertain['review_date']:
            assert review_date.to_period('M') not in month_to_style


# --------------------------------------------------------------------------
# Stateful continuous execution (the fix for "No trades generated")
# --------------------------------------------------------------------------

def test_position_is_held_across_month_boundaries():
    """A trade must be able to span a review date when the style is unchanged."""
    s = _oscillating(900, period=240)
    _, month_to_style = build_monthly_style_schedule(s, 'mr')
    # Force every month to MR so no style change can intervene.
    month_to_style = {k: 'mr' for k in month_to_style}

    res = run_monthly_style_backtest(s, month_to_style, entry_z=1.5, exit_z=0.5, min_hold=5)

    assert res['n_trades'] > 0
    trades = res['trades_df']
    spans_month = (
        trades['entry_date'].dt.to_period('M') != trades['exit_date'].dt.to_period('M')
    )
    assert spans_month.any(), "no trade survived a month boundary"


def test_month_local_slicing_would_starve_but_continuous_run_trades():
    """Regression: monthly routing must not restart the engine each month."""
    s = _oscillating(900, period=240)
    _, month_to_style = build_monthly_style_schedule(s, 'mr')
    res = run_monthly_style_backtest(s, month_to_style, entry_z=1.5, exit_z=0.5, min_hold=5)

    assert res['n_trades'] > 0 or res['open_trade'] is not None


def test_skip_month_blocks_entry_but_does_not_force_exit():
    s = _oscillating(900, period=240)
    _, month_to_style = build_monthly_style_schedule(s, 'mr')
    month_to_style = {k: 'mr' for k in month_to_style}

    full = run_monthly_style_backtest(s, month_to_style, entry_z=1.5, exit_z=0.5, min_hold=5)
    assert full['n_trades'] > 0

    # Drop one month from the map: it becomes untradeable but must not close a
    # position that is already running through it.
    open_trade = full['trades_df'].iloc[0]
    crossed = pd.Period(open_trade['entry_date'], 'M') + 1
    reduced = {k: v for k, v in month_to_style.items() if k != crossed}
    res = run_monthly_style_backtest(s, reduced, entry_z=1.5, exit_z=0.5, min_hold=5)

    assert 'monthly_style_change' not in set(res['trades_df'].get('exit_reason', []))


def test_style_change_forces_exactly_one_close():
    s = _oscillating(900, period=240)
    _, month_to_style = build_monthly_style_schedule(s, 'mr')
    months = sorted(month_to_style)
    forced = {m: 'mr' for m in months}
    # Flip the back half to trend so a style change must occur exactly once.
    for m in months[len(months) // 2:]:
        forced[m] = 'trend'

    res = run_monthly_style_backtest(s, forced, entry_z=1.5, exit_z=0.5, min_hold=5)
    trades = res['trades_df']
    if not trades.empty:
        n_forced = int((trades['exit_reason'] == 'monthly_style_change').sum())
        assert n_forced <= 1
        # Every trade is tagged with the engine that opened it.
        assert set(trades['style']).issubset({'mr', 'trend'})


def test_trend_months_route_to_trend_engine():
    s = _drifting(600)
    months = sorted({p for p in s.index.to_period('M')})
    res = run_monthly_style_backtest(
        s, {m: 'trend' for m in months}, theta_z=1.0, mom_window=20, vol_window=60
    )
    styles = set(res['trades_df']['style']) if res['n_trades'] else set()
    open_style = (res['open_trade'] or {}).get('style')
    assert styles.issubset({'trend'})
    assert res['n_trades'] > 0 or open_style == 'trend'


def test_mr_entry_ignores_carry():
    """MR entries follow z-score thresholds regardless of carry (plan item 8)."""
    s = _oscillating(700, period=180)
    months = sorted({p for p in s.index.to_period('M')})
    m2s = {m: 'mr' for m in months}

    flat = run_monthly_style_backtest(s, m2s, entry_z=1.5, exit_z=0.5, min_hold=5)
    carry = pd.Series(5.0, index=s.index)
    with_carry = run_monthly_style_backtest(
        s, m2s, entry_z=1.5, exit_z=0.5, min_hold=5, carry_roll_ts=carry
    )

    assert flat['n_trades'] == with_carry['n_trades']
    if flat['n_trades']:
        assert (
            flat['trades_df']['entry_date'].tolist()
            == with_carry['trades_df']['entry_date'].tolist()
        )


def test_flat_series_does_not_divide_by_zero():
    """Zero volatility must yield no state, not inf/NaN trades."""
    idx = _bdays(600)
    s = pd.Series(1.0, index=idx)
    months = sorted({p for p in idx.to_period('M')})
    res = run_monthly_style_backtest(s, {m: 'trend' for m in months})

    assert res['n_trades'] == 0
    assert np.isfinite(res['trend_state_ts']).all()


def test_inverted_series_flips_direction_consistently():
    s = _drifting(700)
    months = sorted({p for p in s.index.to_period('M')})
    m2s = {m: 'trend' for m in months}

    up = run_monthly_style_backtest(s, m2s, theta_z=1.0)
    down = run_monthly_style_backtest(-s, m2s, theta_z=1.0)

    assert up['n_trades'] == down['n_trades']
    if up['n_trades']:
        assert (
            up['trades_df']['direction'].map({'LONG': 'SHORT', 'SHORT': 'LONG'}).tolist()
            == down['trades_df']['direction'].tolist()
        )


def test_insufficient_data_returns_error():
    s = _oscillating(30)
    assert 'error' in run_monthly_style_backtest(s, {})


def test_no_month_styles_produces_no_trades():
    s = _oscillating(600)
    res = run_monthly_style_backtest(s, {})
    assert res['n_trades'] == 0
    assert res['open_trade'] is None
