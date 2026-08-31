# -*- coding: utf-8 -*-
"""Monthly style-routed backtest: one continuous, stateful pass over the history.

The monthly review assigns each calendar month a style (``mr`` or ``trend``); the
style is then held fixed for the whole month.  This module walks the daily series
once, routing each day's entry/exit logic through the style its month owns, and
carries position state across month boundaries.

Why a single pass rather than one backtest per month: both engines need a long
warm-up (120-day rolling z-score for MR, ``mom_window``/``vol_window`` for trend),
so month-local runs leave only a handful of usable days per slice and can never
hold a position across a review date.  Signals here are computed once on the full
history and only *routing* is monthly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ._carry import _carry_accrual
from ._direction import _direction_label
from ._metrics import annualized_sharpe, per_trade_sharpe
from .engine_trend import _z_momentum_state
from ._ou_mean import blended_mr_mean

MR_LOOKBACK = 120
MR_VOL_SPAN = 60

# Route 'trending' months to the trend engine?  Default False.
#
# Measured on the TenorSpread universe (2016-2026, unit positions, fixed
# preset parameters): momentum on these spreads is *negatively*
# autocorrelated at the horizon the trend engine trades -- corr(past 60d
# move, next 60d move) = -0.36 on CGB-10s30s, with a 43.9% directional hit
# rate at 60d.  The spreads do trend at 5-20 days (variance ratio ~1.2) and
# mean-revert beyond 60 days (VR ~0.54); the engine's ~16-day median hold
# with mom_window=30 sits in the crossover dead zone where neither effect is
# live.  Consequently the trend leg lost 509bp (Sharpe -0.37) on CGB-10s30s
# over 10y while the same book traded mean-reversion only returned +219bp,
# and across 14 instruments plain MR was positive on 13 with median Sharpe
# 0.49.  Routing 'trending' months to MR is therefore the default; set True
# to restore the previous behaviour.
ALLOW_TREND_STYLE_DEFAULT = False

_STYLE_ALIASES = {
    'mr': 'mr',
    'mean_reverting': 'mr',
    'mean-reverting': 'mr',
    'meanreversion': 'mr',
    'reversion': 'mr',
    'trend': 'trend',
    'trending': 'trend',
    'momentum': 'trend',
    'mom': 'trend',
}


def canonical_style(value: Any) -> str:
    """Resolve a style/regime alias to ``mr``, ``trend`` or ``skip``."""
    key = str(value or '').strip().lower().replace(' ', '_')
    return _STYLE_ALIASES.get(key, 'skip')


def _clean_series(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors='coerce').dropna().copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        parsed = pd.to_datetime(s.index, errors='coerce')
        s = s.loc[~parsed.isna()]
        s.index = parsed[~parsed.isna()]
    if getattr(s.index, 'tz', None) is not None:
        s.index = s.index.tz_localize(None)
    return s.sort_index()


def build_monthly_style_schedule(
    spread_ts: pd.Series,
    default_style: str = 'mr',
    *,
    uncertain_policy: str = 'carry_forward',
    allow_trend_style: bool = ALLOW_TREND_STYLE_DEFAULT,
) -> tuple[pd.DataFrame, Dict[pd.Period, str]]:
    """Classify each month's regime point-in-time and assign a fixed style.

    The review runs on the first available observation of each calendar month and
    sees only data up to and including that date.

    ``uncertain_policy``:
        ``carry_forward`` — hold the previous month's style; before any valid
        classification, fall back to ``default_style`` (the plan's rule 3).
        ``skip`` — assign no tradeable style, so the month opens no new position.

    ``allow_trend_style``: when False (the default, see
    ``ALLOW_TREND_STYLE_DEFAULT``), months classified 'trending' are routed to
    the MR engine instead of the trend engine.  The classification itself is
    unchanged and still recorded in the returned schedule (``regime``,
    ``regime_score``), so the audit trail and any regime display stay intact;
    only the *routing* decision changes.

    Returns the audit schedule and a ``{Period: style}`` routing map.
    """
    from curves.calibration.regime import DEFAULT_REGIME_WINDOW, compute_regime_features_dual

    s = _clean_series(spread_ts)
    if len(s) == 0:
        return pd.DataFrame(), {}

    default_style = canonical_style(default_style)
    if default_style == 'skip':
        default_style = 'mr'

    review_dates = s.index.to_series().groupby(s.index.to_period('M')).min()
    if review_dates is None or len(review_dates) == 0:
        return pd.DataFrame(), {}

    prev_style: Optional[str] = None
    rows: List[Dict[str, Any]] = []

    for review_date in review_dates.sort_values().tolist():
        hist = s.loc[:review_date]
        fallback_reason = ''
        score = np.nan

        if len(hist) >= DEFAULT_REGIME_WINDOW + 5:
            # A ~1yr long window is layered on top of the ~3mo short window
            # (compute_regime_features_dual) so a multi-quarter trend isn't
            # vetoed by a short-window consolidation pause inside it -- see
            # the combination rule in curves.calibration.regime. Falls back
            # to the short window alone until enough history accumulates.
            info = compute_regime_features_dual(hist)
            regime = str(info.get('regime', 'uncertain') or 'uncertain').strip().lower()
            score = float(info.get('regime_score', np.nan))
            regime_long = str(info.get('regime_long', 'uncertain') or 'uncertain').strip().lower()
            score_long = float(info.get('regime_score_long', np.nan))
        else:
            regime = 'insufficient_history'
            regime_long = 'insufficient_history'
            score_long = np.nan

        assigned_style = canonical_style(regime)
        if assigned_style == 'trend' and not allow_trend_style:
            # Trend routing is disabled: these spreads' momentum is negatively
            # autocorrelated at the horizon the trend engine trades, so a
            # 'trending' month is still traded mean-reversion. See
            # ALLOW_TREND_STYLE_DEFAULT for the measured rationale.
            assigned_style = 'mr'
            fallback_reason = 'trend->mr (trend routing disabled)'
        if assigned_style == 'skip':
            if uncertain_policy == 'skip':
                fallback_reason = f'{regime}->skip'
            elif prev_style is not None:
                assigned_style = prev_style
                fallback_reason = f'{regime}->previous_style'
            else:
                assigned_style = default_style
                fallback_reason = f'{regime}->default_style'

        rows.append({
            'review_date': pd.Timestamp(review_date),
            'regime': regime,
            'regime_score': score,
            'regime_long': regime_long,
            'regime_score_long': score_long,
            'assigned_style': assigned_style,
            'fallback_reason': fallback_reason,
        })
        if assigned_style in ('mr', 'trend'):
            prev_style = assigned_style

    schedule = pd.DataFrame(rows)
    month_to_style = {
        pd.Timestamp(r['review_date']).to_period('M'): r['assigned_style']
        for r in rows
        if r['assigned_style'] in ('mr', 'trend')
    }
    return schedule, month_to_style


def run_monthly_style_backtest(
    spread_ts: pd.Series,
    month_to_style: Dict[pd.Period, str],
    *,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    min_hold: int = 7,
    theta_z: float = 1.25,
    mom_window: int = 20,
    vol_window: int = 60,
    trailing_mult: float = 3.0,
    allow_short: bool = True,
    reentry_cooldown: int = 3,
    # ~5 trading weeks. The monthly router only re-reviews once per calendar
    # month, so a trend_state flip that happens early in a month can already
    # be 2-4 weeks stale by the time that month's review grants 'trend'
    # permission -- 15 (3 weeks) was tight enough to silently block entry
    # into a still-fresh trend leg for a full review cycle.
    trend_max_flip_age: int = 25,
    carry_roll_ts: Optional[pd.Series] = None,
    carry_roll_bp: float = 0.0,
    duration_mult: float = 1.0,
    borrow_cost_long_bp: float = 0.0,
    borrow_cost_short_bp: float = 0.0,
    spread_type: Optional[str] = None,
    tenor_ratio: float = 1.0,
    carry_roll_sell_ts: Optional[pd.Series] = None,
    mr_vol_span: int = MR_VOL_SPAN,
    ou_mean: Optional[float] = None,
) -> Dict[str, Any]:
    """Run a continuous backtest whose entry style is routed by month.

    ``month_to_style`` maps a monthly ``pd.Period`` to ``mr``/``trend``; months
    absent from the map (or mapped to anything else) open no new position, but an
    already-open position is *not* force-closed by the absence of a style — only a
    genuine change from one tradeable style to a different tradeable style closes
    it, with ``exit_reason='monthly_style_change'``, and only once the position
    has cleared ``min_hold`` (same holding-period protection as the other exits).

    ``ou_mean``: static OU long-run mean (``StatInfo['mean']``) used as the MR
    fair-value anchor in place of the plain rolling mean when the caller has
    established via ADF that the series is stationary — see the matching
    parameter/rationale in ``engine_mr.run_spread_backtest``. Note the monthly
    regime router (``compute_regime_features``) already independently decides
    *when* MR-style entries are allowed via its own trend/mean-reversion
    voting ensemble; ``ou_mean`` only changes *where* the MR anchor sits during
    those months, it does not change which months are eligible.
    """
    s = _clean_series(spread_ts)
    if s is None or len(s) < 60:
        return {'error': 'Insufficient data'}

    styles = {}
    for period, value in (month_to_style or {}).items():
        try:
            key = period if isinstance(period, pd.Period) else pd.Period(period, 'M')
        except Exception:
            continue
        styles[key] = canonical_style(value)

    # ---- Signals, computed once on the whole history -------------------------
    # Fair-value anchor: the OU long-run mean for the trailing STAT_WINDOW
    # months when the caller supplies one (ADF-confirmed stationary series,
    # see ``ou_mean`` docstring above), blended with a plain rolling(120) mean
    # for older history (``_ou_mean.blended_mr_mean`` — the OU mean is a
    # current-regime estimate and should not be projected back over years of
    # history it was never calibrated on). Either way the scale is an EWMA
    # volatility over the shorter mr_vol_span: a flat rolling(120) std blends
    # in whatever vol regime sits in the trailing year, so once the market
    # settles into a materially quieter range the same absolute price swing
    # can no longer clear a fixed entry_z threshold -- entries silently stop
    # even though the spread is still moving in relative terms. EWMA reacts
    # within its span instead of carrying stale high-vol history, which keeps
    # the z-score's entry rate roughly stable across vol regimes.
    rolling_mean = blended_mr_mean(s, ou_mean, lookback=MR_LOOKBACK)
    ewm_std = s.ewm(span=max(int(mr_vol_span), 2), min_periods=max(int(mr_vol_span), 2)).std()
    zscore = (s - rolling_mean) / ewm_std.replace(0, np.nan)
    zscore = zscore.replace([np.inf, -np.inf], np.nan)

    trend_state, z_mom, _sigma_mad = _z_momentum_state(
        s, theta_z=float(theta_z), mom_window=int(mom_window), vol_window=int(vol_window)
    )
    trend_state = trend_state.reindex(s.index).ffill().fillna(0.0)
    z_mom = z_mom.reindex(s.index)
    trend_vol = s.diff().rolling(int(vol_window)).std()

    # Bars since trend_state last flipped, and which flip "run" each bar
    # belongs to. The monthly router can grant 'trend' permission weeks after
    # the underlying flip actually happened (state changed mid-month but the
    # month wasn't reviewed/assigned trend until the next review date) --
    # entering fresh on a flip that is already stale, with no prior position
    # taken on it, risks buying a move that is largely over. flip_age gates
    # this *first* entry on a flip to a freshness window.
    #
    # It must NOT gate a *re*-entry on a flip we already traded: a position
    # opened promptly on a fresh flip and then stopped out on a pullback
    # (trailing stop) still has a live, correctly-directioned trend_state --
    # the "stale, already-over move" risk the age check exists for does not
    # apply, since we were already in the trade before it went stale. Without
    # this distinction, a signal that stays valid for months (as directional
    # curve trends often do) but gets trailing-stopped once early can lock
    # the strategy flat for the rest of the run: age keeps climbing past the
    # threshold and no re-entry is ever allowed until the state flips again,
    # even in the wrong direction.
    _flip = trend_state.ne(trend_state.shift()).to_numpy().copy()
    _flip[0] = True
    flip_age = np.zeros(len(trend_state), dtype=float)
    flip_run_id = np.zeros(len(trend_state), dtype=int)
    _since = 0
    _run = -1
    for _i in range(len(trend_state)):
        if _flip[_i]:
            _since = 0
            _run += 1
        flip_age[_i] = _since
        flip_run_id[_i] = _run
        _since += 1

    def _align(ts: Optional[pd.Series]) -> Optional[pd.Series]:
        if ts is None:
            return None
        t = ts.copy()
        if not isinstance(t.index, pd.DatetimeIndex):
            t.index = pd.to_datetime(t.index, errors='coerce')
        if getattr(t.index, 'tz', None) is not None:
            t.index = t.index.tz_localize(None)
        return t.reindex(s.index, method='ffill')

    cr_long = _align(carry_roll_ts)
    cr_sell = _align(carry_roll_sell_ts)
    cr_fallback = (carry_roll_bp or 0.0) / 100.0

    price_arr = s.to_numpy(dtype=float)
    idx_arr = s.index
    z_arr = zscore.to_numpy(dtype=float)
    st_arr = trend_state.to_numpy(dtype=float)
    vol_arr = trend_vol.to_numpy(dtype=float)
    periods = s.index.to_period('M')
    cr_long_arr = cr_long.to_numpy(dtype=float) if cr_long is not None else None
    cr_sell_arr = cr_sell.to_numpy(dtype=float) if cr_sell is not None else None

    def _cr_at(i: int, pos: int) -> float:
        arr = cr_sell_arr if (pos == -1 and cr_sell_arr is not None) else cr_long_arr
        if arr is None:
            return cr_fallback
        v = arr[i]
        return float(v) if np.isfinite(v) else 0.0

    # Warm-up: the first index at which *either* engine could act.  MR needs its
    # full rolling window; trend needs momentum + vol windows.
    trend_start = max(int(vol_window), int(mom_window)) + 1
    start_i = min(MR_LOOKBACK, trend_start)
    start_i = max(start_i, 1)
    if start_i >= len(s):
        return {'error': 'Insufficient data'}

    trades: List[Dict[str, Any]] = []
    position = 0
    entry_date = None
    entry_price = None
    entry_zscore = None
    entry_style = None
    best_fav = None
    cooldown = max(int(reentry_cooldown), 0)
    last_exit_index = -10 ** 9
    last_exit_dir = 0
    last_exit_flip_run = -1  # flip_run_id of the trend trade we last closed, if any
    realized_pnl = 0.0
    realized_capital = 0.0
    realized_carry = 0.0
    open_cr_sum = 0.0
    equity_dates: List[pd.Timestamp] = []
    equity_values: List[float] = []
    capital_values: List[float] = []
    carry_values: List[float] = []
    style_used: List[str] = []

    def _close(i: int, date, px: float, reason: str, exit_z_val: float) -> None:
        nonlocal position, entry_date, entry_price, entry_zscore, entry_style, best_fav
        nonlocal realized_pnl, realized_capital, realized_carry, open_cr_sum
        nonlocal last_exit_index, last_exit_dir, last_exit_flip_run

        days_held = (date - entry_date).days if entry_date is not None else 0
        price_pnl = (px - entry_price) * position * duration_mult
        carry_income = _carry_accrual(
            position, entry_date, date, days_held,
            carry_roll_ts, carry_roll_bp,
            borrow_cost_long_bp, borrow_cost_short_bp,
            spread_type, tenor_ratio, carry_roll_sell_ts,
        )
        realized_pnl += price_pnl + carry_income
        realized_capital += price_pnl * 100.0
        realized_carry += carry_income * 100.0
        open_cr_sum = 0.0
        direction = _direction_label(position)
        trades.append({
            'entry_date': entry_date,
            'exit_date': date,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': px,
            'entry_z': entry_zscore,
            'exit_z': exit_z_val,
            'spd_chg': (px - entry_price) * position * 100.0,
            'cr_acc': carry_income * 100.0,
            'duration': duration_mult,
            'days_held': days_held,
            'exit_reason': reason,
            'style': entry_style,
        })
        last_exit_index = i
        last_exit_dir = position
        last_exit_flip_run = int(flip_run_id[i]) if entry_style == 'trend' else -1
        position = 0
        entry_date = None
        entry_price = None
        entry_zscore = None
        entry_style = None
        best_fav = None

    prev_style = None
    for i in range(start_i, len(s)):
        date = idx_arr[i]
        px = float(price_arr[i])
        z = float(z_arr[i])
        st = float(st_arr[i])
        vol = float(vol_arr[i])
        style = styles.get(periods[i], 'skip')

        # ---- Monthly style change: close an open position that no longer
        # matches its month's assigned style.  A month with no tradeable style
        # ('skip') does not force a close; it only blocks new entries. Gated by
        # min_hold like the other trend/MR exits below -- otherwise a single
        # review month where the 60d regime vote dips into 'mean_reverting' or
        # 'uncertain' during a pullback inside a persistent trend force-closes
        # the position days into the trade, regardless of holding period.
        if position != 0:
            days_held = (date - entry_date).days if entry_date is not None else 0
            if (style in ('mr', 'trend') and entry_style != style and style != prev_style
                    and days_held >= min_hold):
                _close(i, date, px, 'monthly_style_change', z)

        # ---- Exits, evaluated with the style that opened the trade -----------
        if position != 0:
            days_held = (date - entry_date).days if entry_date is not None else 0

            if entry_style == 'trend':
                if best_fav is None:
                    best_fav = px
                best_fav = max(best_fav, px) if position == 1 else min(best_fav, px)

                trailing_stop = False
                if np.isfinite(vol) and vol > 0 and trailing_mult > 0:
                    move = (best_fav - px) if position == 1 else (px - best_fav)
                    # Gated by min_hold like the other trend exits: a trailing
                    # stop this tight (multiples of a 60d daily-change std)
                    # otherwise fires on ordinary pullbacks days into a trade
                    # that is part of a multi-year trend, well before the
                    # trend itself has actually turned.
                    trailing_stop = days_held >= min_hold and move >= trailing_mult * vol

                flip = (position == 1 and st < 0) or (position == -1 and st > 0)
                if trailing_stop:
                    _close(i, date, px, 'trailing', z)
                elif days_held >= min_hold and flip:
                    _close(i, date, px, 'flip', z)

            elif np.isfinite(z):
                exit_reason = None
                if days_held >= min_hold:
                    if position == 1 and z >= -exit_z:
                        exit_reason = 'target'
                    elif position == -1 and z <= exit_z:
                        exit_reason = 'target'
                if exit_reason is None:
                    if position == 1 and z < -stop_z:
                        exit_reason = 'stop_loss'
                    elif position == -1 and z > stop_z:
                        exit_reason = 'stop_loss'
                if exit_reason is not None:
                    _close(i, date, px, exit_reason, z)

        # ---- Entries, gated by the current month's style ---------------------
        if position == 0 and style in ('mr', 'trend'):
            if style == 'mr':
                if i >= MR_LOOKBACK and np.isfinite(z):
                    if z >= entry_z:
                        position = -1
                    elif z <= -entry_z:
                        position = 1
                    if position != 0:
                        entry_date, entry_price, entry_zscore, entry_style = date, px, z, 'mr'
            else:
                # Freshness only gates the *first* entry taken on a given
                # trend_state flip. A re-entry on the same still-active flip
                # (e.g. after a trailing-stop pullback exit) is not "chasing
                # a stale move" -- we were already in that exact trade, so it
                # bypasses the age check and only waits out reentry_cooldown.
                same_flip_reentry = last_exit_flip_run == flip_run_id[i]
                fresh_enough = same_flip_reentry or flip_age[i] <= trend_max_flip_age
                if i >= trend_start and fresh_enough:
                    can_long = not (last_exit_dir == 1 and (i - last_exit_index) <= cooldown)
                    can_short = not (last_exit_dir == -1 and (i - last_exit_index) <= cooldown)
                    if st > 0 and can_long:
                        position = 1
                    elif allow_short and st < 0 and can_short:
                        position = -1
                    if position != 0:
                        entry_date, entry_price, entry_style = date, px, 'trend'
                        entry_zscore = z if np.isfinite(z) else np.nan
                        best_fav = px

        # ---- Daily mark-to-market -------------------------------------------
        if position != 0 and entry_price is not None:
            open_cr_sum += _cr_at(i, position)
            open_carry_pct = position * open_cr_sum / 90.0
            if spread_type not in ('TenorSpread', 'BondCurve', 'BondSwap',
                                   'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'):
                bc = borrow_cost_long_bp if position == 1 else borrow_cost_short_bp
                days_open = (date - entry_date).days if entry_date else 0
                open_carry_pct -= abs(bc) / 100.0 * days_open / 365.0
            open_cap_pct = (px - entry_price) * position * duration_mult
            mtm = realized_pnl + open_cap_pct + open_carry_pct
            cap_daily = realized_capital + open_cap_pct * 100.0
            cr_daily = realized_carry + open_carry_pct * 100.0
        else:
            mtm = realized_pnl
            cap_daily = realized_capital
            cr_daily = realized_carry

        equity_dates.append(pd.Timestamp(date))
        equity_values.append(float(mtm))
        capital_values.append(float(cap_daily))
        carry_values.append(float(cr_daily))
        style_used.append(style)
        if style in ('mr', 'trend'):
            prev_style = style

    equity_ts = pd.Series(equity_values, index=pd.DatetimeIndex(equity_dates), name='equity_bp')

    open_trade = None
    if position != 0 and entry_price is not None and equity_dates:
        last_date = equity_dates[-1]
        last_price = float(price_arr[-1])
        days_open = (last_date - entry_date).days if entry_date else 0
        open_cap_bp = (last_price - entry_price) * position * duration_mult * 100.0
        open_carry_bp = open_cr_sum * position / 90.0 * 100.0
        direction = _direction_label(position)
        open_trade = {
            'entry_date': entry_date,
            'direction': direction,
            'entry_price': entry_price,
            'entry_z': entry_zscore,
            'current_date': last_date,
            'current_price': last_price,
            'days_held': days_open,
            'capital_open': open_cap_bp,
            'carry_open': open_carry_bp,
            'pnl_open': open_cap_bp + open_carry_bp,
            'style': entry_style,
            'status': 'OPEN',
        }

    style_ts = pd.Series(style_used, index=pd.DatetimeIndex(equity_dates), dtype=object, name='style')

    base = {
        'spread_ts': s,
        'zscore_ts': zscore,
        'composite_signal_ts': zscore,
        'trend_state_ts': trend_state,
        'norm_mom_ts': z_mom,
        'style_ts': style_ts,
        'carry_roll_ts': carry_roll_ts,
        'entry_z': entry_z,
        'exit_z': exit_z,
        'stop_z': stop_z,
        'theta_z': float(theta_z),
        'trend_max_flip_age': int(trend_max_flip_age),
        'open_trade': open_trade,
    }

    if not trades:
        base.update({
            'trades': [],
            'trades_df': pd.DataFrame(),
            'n_trades': 0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'avg_pnl': 0.0,
            'avg_hold': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'cum_pnl': np.array([]),
            'equity_ts': equity_ts * 100.0,
            'capital_ts': pd.Series(capital_values, index=pd.DatetimeIndex(equity_dates)),
            'carry_ts': pd.Series(carry_values, index=pd.DatetimeIndex(equity_dates)),
        })
        return base

    trades_df = pd.DataFrame(trades)
    trades_df['spd_chg'] = trades_df['spd_chg'].astype(float)
    trades_df['cr_acc'] = trades_df['cr_acc'].astype(float)
    trades_df['duration'] = trades_df['duration'].astype(float)
    trades_df['pnl_trade'] = trades_df['duration'] * trades_df['spd_chg'] + trades_df['cr_acc']
    trades_df['capital_cum'] = (trades_df['duration'] * trades_df['spd_chg']).cumsum()
    trades_df['carry_cum'] = trades_df['cr_acc'].cumsum()
    trades_df['pnl_cum'] = trades_df['pnl_trade'].cumsum()

    pnls = trades_df['pnl_trade'].to_numpy(dtype=float)
    n_trades = int(len(trades_df))
    equity_ts = equity_ts * 100.0
    eq_vals = equity_ts.dropna().to_numpy(dtype=float)
    max_dd = float((np.maximum.accumulate(eq_vals) - eq_vals).max()) if len(eq_vals) else 0.0
    std = float(np.nanstd(pnls))

    base.update({
        'trades': trades_df.to_dict('records'),
        'trades_df': trades_df,
        'n_trades': n_trades,
        'total_pnl': float(np.nansum(pnls)),
        'win_rate': float((pnls > 0).sum() / n_trades * 100.0),
        'avg_pnl': float(np.nanmean(pnls)),
        'avg_hold': float(trades_df['days_held'].mean()),
        'sharpe': annualized_sharpe(equity_ts),
        'sharpe_per_trade': per_trade_sharpe(pnls, n_trades),
        'max_drawdown': max_dd,
        'cum_pnl': np.nancumsum(pnls),
        'equity_ts': equity_ts,
        'capital_ts': pd.Series(capital_values, index=pd.DatetimeIndex(equity_dates)),
        'carry_ts': pd.Series(carry_values, index=pd.DatetimeIndex(equity_dates)),
    })
    return base
