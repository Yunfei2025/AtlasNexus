# -*- coding: utf-8 -*-
"""Beta + Alpha book combination analytics for Summary > Books.

Combines the two books' *saved* backtest results into one synthetic
portfolio, to answer two questions:

  1. What capital split between the books maximizes risk-adjusted return?
  2. Are the two books actually diversifying each other, or duplicating risk?

Unit reconciliation is the crux. The two books measure P&L differently, and
consume capital differently:

  - Beta (multiasset historical allocation) is cumulative P&L in **million
    CNY** against an explicit ``total_capital``, unlevered: its notional and
    its capital commitment are the same MM figure.
  - Alpha (TenorSpread portfolio backtest) is cumulative P&L in **basis
    points** on notionally-unit positions, margined: a given capital
    commitment buys ``1 / margin_ratio`` MM of notional (``margin_ratio`` from
    ``estimate_alpha_book_margin_ratio``, typically well under 1), so its
    capital footprint is its **margin**, not its notional.

A naive 50/50 "capital split" that means beta-notional : alpha-notional
therefore compares unlike things -- it implicitly assumes alpha is unlevered
too, understating how much of the actual capital pool alpha is committing.
The split this module works in is **beta notional : alpha margin**: the
caller supplies ``alpha_margin_share`` (alpha's share of ``total_capital_mm``
as margin) and ``margin_ratio`` converts that into the notional weight the
return-blend math needs (``w = alpha_margin_share / margin_ratio``, which can
exceed 1.0 -- alpha notional bigger than the whole capital pool -- whenever
the book is meaningfully levered, which is the normal case).
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Rolling-correlation diagnostic (see docs/plans/portfolio_construction_beta_alpha.md
# §5.1). A single full-sample correlation can't distinguish "diversifying on
# average" from "diversifying except in the tail" -- both books are
# duration/curve-adjacent (Alpha core = TenorSpread bond-vs-curve/repo, Beta's
# Rates sleeve = duration-driven), so a rates-stress episode is exactly the
# scenario where the two could correlate hard while the full-sample number
# still looks fine.
#
# Window is 120 trading days (~half a year), not the 60d full-sample minimum
# gate below: at n=60 the standard error of a sample correlation is ~0.13,
# noisy enough to flag spurious "spikes" on noise alone; at n=120 it drops to
# ~0.09. Using the same 60d figure for both the floor and the rolling window
# would also mean the first rolling point needs the *entire* minimum-overlap
# history, leaving no room to see it move -- 120d keeps the rolling view a
# strict step above the floor. Still short enough that a multi-week
# stress-driven correlation shift shows up as a distinguishable bump rather
# than being smoothed into the full-sample average.
ROLLING_CORR_WINDOW = 120

# First-pass threshold for flagging a rolling-correlation spike, not tuned
# against real data yet -- revisit once this has been looked at against
# actual saved beta/alpha backtest history.
ROLLING_CORR_FLAG = 0.5


def estimate_alpha_book_margin_ratio(instruments: list[dict]) -> Optional[float]:
    """Weighted-average margin consumed per unit of alpha notional.

    ``instruments`` is the saved backtest result's instrument snapshot
    (``{ID, spread_type, weight, ...}``, risk-parity weights summing to ~1).
    Each instrument is backtested at unit notional, so its own margin per
    unit notional (from ``estimate_margin_mm``, a single-leg DV01 proxy —
    see its docstring for the ~2.5x netting-correction fit and uncertainty)
    weighted by its book weight gives the book's average margin ratio: the
    capital the alpha book actually ties up per unit of notional deployed.
    This is what lets "alpha capital" and "alpha notional" be converted into
    each other on the combination card, instead of treating the alpha
    capital input as an unrelated free parameter.
    """
    from web.tabs.alpha.data import estimate_margin_mm, _get_duration_mult

    if not instruments:
        return None
    total_w = 0.0
    weighted_margin = 0.0
    for inst in instruments:
        spread_type = inst.get('spread_type', 'TenorSpread')
        inst_id = inst.get('ID')
        weight = float(inst.get('weight') or 0.0)
        if not inst_id or weight <= 0:
            continue
        try:
            duration = _get_duration_mult(inst_id, spread_type)
            margin_per_unit = estimate_margin_mm(1.0, duration)
        except Exception:
            continue
        weighted_margin += weight * margin_per_unit
        total_w += weight
    if total_w <= 0:
        return None
    return weighted_margin / total_w


def _alpha_returns(alpha_result: dict) -> Optional[pd.Series]:
    """Daily fractional returns for the alpha book on one unit of notional.

    ``equity_ts`` is cumulative P&L in bp of a unit position, so the daily
    *change* in bp divided by 10000 is the day's return on one unit of
    notional. Scaling to an actual notional (or a margin-derived one, see
    module docstring) happens by multiplying this series by a weight, not
    here.
    """
    eq = alpha_result.get('equity_ts')
    if not isinstance(eq, pd.Series) or eq.empty:
        return None
    eq = eq.copy()
    eq.index = pd.to_datetime(eq.index)
    daily_bp = eq.sort_index().diff().dropna()
    if daily_bp.empty:
        return None
    return daily_bp / 10000.0


def _beta_returns(beta_result: dict) -> Optional[pd.Series]:
    """Daily fractional returns for the beta book on its own capital.

    ``equity_series`` is cumulative P&L in million CNY; ``total_capital`` is
    stored in the same million-CNY unit the dashboard's capital input uses.
    """
    rows = beta_result.get('equity_series')
    if not rows:
        return None
    try:
        idx = pd.to_datetime([r['date'] for r in rows])
        vals = pd.Series([float(r['value']) for r in rows], index=idx).sort_index()
    except (KeyError, TypeError, ValueError):
        return None
    capital = float(beta_result.get('total_capital') or 0.0)
    if capital <= 0:
        return None
    daily_pnl = vals.diff().dropna()
    if daily_pnl.empty:
        return None
    return daily_pnl / capital


def _metrics(returns: pd.Series) -> dict[str, float]:
    """Annualized Sharpe / vol / total return / max drawdown of a return series."""
    if returns is None or returns.empty or returns.std() == 0:
        return {'sharpe': float('nan'), 'vol': float('nan'), 'total_return': float('nan'),
                'ann_return': float('nan'), 'max_drawdown': float('nan')}
    vol = float(returns.std() * np.sqrt(TRADING_DAYS))
    sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS))
    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    n_years = len(returns) / TRADING_DAYS
    # equity.iloc[-1] can go non-positive for a leveraged combined series
    # (alpha_weight w above can exceed 1.0 -- see module docstring); a
    # fractional power of a non-positive base is undefined (numpy silently
    # yields nan), so treat "wiped out or worse" as -100% rather than nan.
    if n_years > 0 and equity.iloc[-1] > 0:
        ann_return = float(equity.iloc[-1] ** (1.0 / n_years) - 1.0)
    elif n_years > 0:
        ann_return = -1.0
    else:
        ann_return = float('nan')
    running_max = equity.cummax()
    max_dd = float(((equity - running_max) / running_max).min())
    return {'sharpe': sharpe, 'vol': vol, 'total_return': total_return,
            'ann_return': ann_return, 'max_drawdown': max_dd}


#  Margin allocated to Alpha is a capital CAP, not a target to fully deploy:
#  daily mark-to-market moves against the book consume margin headroom, and
#  running at 100% utilization means the very next adverse move breaches the
#  cap (a margin call / forced unwind) rather than being absorbed. Only this
#  fraction of the allocated margin is treated as usable when deriving
#  alpha's notional; the rest is a standing buffer, not "spare capital" to
#  size positions against.
MAX_MARGIN_UTILIZATION = 0.90

# Suggested splits (Max Sharpe / Risk Parity) are snapped to this tick size
# rather than reported at the sweep's native 1% resolution. This is a
# real-world capital allocation meant to be set roughly annually, not
# adjusted daily -- a split precise to 1% implies the underlying Sharpe
# estimate (from one finite, noisy sample of daily returns) can distinguish
# e.g. 61% from 62% margin share, which it cannot. Coarser ticks make the
# suggestion visibly a rough-and-ready number, not a false-precision output.
SUGGESTED_SPLIT_TICK = 0.05


# Backtest-window dropdown choices (Summary > Books > Portfolio Combination).
# 'MAX' keeps the full overlapping history; the year windows trim both books'
# return series to the trailing N*TRADING_DAYS calendar days before any
# metric (Sharpe, vol, PnL) is computed, so every number on the panel -- not
# just the chart -- reflects the selected window.
WINDOW_YEARS = {'1Y': 1, '2Y': 2, '5Y': 5, '10Y': 10, 'MAX': None}


def build_combination(
    beta_result: Optional[dict],
    alpha_result: Optional[dict],
    total_capital_mm: float,
    alpha_margin_share: float,
    max_margin_utilization: float = MAX_MARGIN_UTILIZATION,
    window: str = 'MAX',
) -> dict[str, Any]:
    """Align both books and analyse the combined portfolio.

    Capital is split as **beta notional : alpha margin**, not beta notional :
    alpha notional -- alpha is a margined book (``margin_ratio`` MM of margin
    per MM of notional, typically << 1), so its notional at a given capital
    commitment can be a large multiple of that capital. ``alpha_margin_share``
    (0..1) is alpha's share of ``total_capital_mm`` *allocated as margin
    capacity*; beta gets the remainder as its own notional (beta is
    unlevered, so its notional and its capital commitment are the same MM
    figure).

    That allocated margin is a cap, not a deployment target: only
    ``max_margin_utilization`` of it (default 90%) is treated as usable when
    sizing alpha's notional, leaving the rest as headroom against adverse
    mark-to-market moves rather than being sized into positions. Both the
    *usable* margin and its derived notional, and the *allocated* (unbuffered)
    margin, are returned separately so the UI can show what's earmarked
    versus what's actually put to work.

    Internally the usable margin is converted to the return-blend weight the
    Sharpe/vol maths actually needs -- alpha's notional as a fraction of total
    capital, ``w = (alpha_margin_share * max_margin_utilization) /
    margin_ratio`` -- since ``_alpha_returns`` is a return per unit of alpha
    notional. ``w`` can exceed 1.0 (alpha notional bigger than the whole
    capital pool) whenever ``margin_ratio < 1``, which is the normal,
    expected case for a margined book; it is not clipped.

    ``window`` trims both books' overlapping return series to the trailing
    N years (see ``WINDOW_YEARS``) before any metric is computed; ``'MAX'``
    (default) keeps the full overlap. Trimming happens after the overlap
    join, on the *joined* calendar, so a window like '1Y' means "the last
    year both books were live", not the last year of either alone.

    Returns ``{'error': str}`` when either book has no saved result, when
    their date ranges do not overlap enough to compare, or when the alpha
    book's margin ratio can't be estimated (required to convert margin share
    into a notional weight).
    """
    if not beta_result:
        return {'error': 'No saved Beta backtest. Run and save it in the Multi-Asset dashboard.'}
    if not alpha_result:
        return {'error': 'No saved Alpha backtest. Run and save it in Alpha > Backtest > Portfolio.'}

    margin_ratio = estimate_alpha_book_margin_ratio(alpha_result.get('instruments') or [])
    if margin_ratio is None or margin_ratio <= 0:
        return {'error': ("Can't estimate the Alpha book's margin ratio from its saved instrument "
                          "snapshot (needed to convert margin share into a notional weight) — "
                          "re-run and save the Alpha portfolio backtest.")}

    r_beta = _beta_returns(beta_result)
    r_alpha = _alpha_returns(alpha_result)
    if r_beta is None:
        return {'error': 'Saved Beta result has no usable equity series / capital base.'}
    if r_alpha is None:
        return {'error': 'Saved Alpha result has no usable equity series.'}

    # Inner join: only days both books were live are comparable. A union with
    # zero-fill would understate correlation and overstate diversification by
    # treating "book not running yet" as "book returned exactly 0".
    common = r_beta.index.intersection(r_alpha.index)
    if len(common) < 60:
        return {'error': (f'Only {len(common)} overlapping days between the two saved '
                          f'backtests — need at least 60 to compare. Re-run them over '
                          f'a common date range.')}
    r_beta = r_beta.reindex(common).astype(float)
    r_alpha = r_alpha.reindex(common).astype(float)

    years = WINDOW_YEARS.get(window, None)
    if years is not None:
        cutoff = common.max() - pd.Timedelta(days=int(years * 365.25))
        windowed = common[common >= cutoff]
        if len(windowed) < 60:
            return {'error': (f"Only {len(windowed)} overlapping days in the trailing {window} window "
                              f"— need at least 60 to compare. Pick a longer window.")}
        common = windowed
        r_beta = r_beta.reindex(common)
        r_alpha = r_alpha.reindex(common)

    m_beta = _metrics(r_beta)
    m_alpha = _metrics(r_alpha)

    util = float(np.clip(max_margin_utilization, 0.0, 1.0)) or MAX_MARGIN_UTILIZATION

    # Margin-based alpha metrics: r_alpha is return per unit of NOTIONAL (see
    # _alpha_returns); dividing notional by margin_ratio gives margin, so
    # scaling the return series by 1/margin_ratio would reprice it as return
    # per unit of margin IF the whole allocated margin were deployed. It
    # isn't -- only `util` (e.g. 90%) of allocated margin is usable, the rest
    # is a standing buffer that earns nothing (see MAX_MARGIN_UTILIZATION).
    # An allocation of 2B with 90% utilization means the return has to be
    # measured against the full 2B, not just the 1.8B actually deployed --
    # scaling by `util / margin_ratio` (not `1 / margin_ratio`) is what makes
    # that buffer show up as a drag on the book's margin-based return, and
    # it's the same scaling the combined blend already applies via `w` below
    # -- this just isolates it to the alpha book on its own so the two return
    # bases don't have to be inferred from the blend.
    m_alpha_margin = _metrics(r_alpha * util / margin_ratio)

    corr = float(r_beta.corr(r_alpha))
    rolling_corr = _rolling_correlation(r_beta, r_alpha)
    worst_window_corr = float(rolling_corr.max()) if rolling_corr is not None else None
    ms = float(np.clip(alpha_margin_share, 0.0, 1.0))
    # w is sized off USABLE margin (ms * util), not the full allocated margin
    # -- the untouched (1 - util) slice is a standing buffer, not deployed.
    w = (ms * util) / margin_ratio  # alpha notional as a fraction of total capital -- not clipped, see docstring
    r_combined = (1.0 - ms) * r_beta + w * r_alpha
    m_combined = _metrics(r_combined)

    # Diversification ratio: weighted-average standalone vol over realised
    # combined vol. >1 means the combination genuinely cancels risk; ~1 means
    # the books are effectively the same bet. Weighted by each book's actual
    # capital share (beta notional / alpha margin), matching r_combined above
    # -- not by the notional weight, which would overstate alpha's capital use.
    wavg_vol = (1.0 - ms) * m_beta['vol'] + ms * m_alpha['vol']
    div_ratio = float(wavg_vol / m_combined['vol']) if m_combined['vol'] else float('nan')

    # Margin-share sweep for the frontier chart / optimal points -- the x-axis
    # is what the UI actually controls (capital allocated to alpha as margin
    # capacity), each grid point converted to a notional weight via the same
    # margin_ratio and utilization buffer as the selected point above.
    grid = np.round(np.arange(0.0, 1.0001, 0.01), 4)
    sweep = []
    for gms in grid:
        gw = (gms * util) / margin_ratio
        m = _metrics((1.0 - gms) * r_beta + gw * r_alpha)
        sweep.append({'alpha_margin_share': float(gms), 'alpha_weight': float(gw),
                      'sharpe': m['sharpe'], 'vol': m['vol'],
                      'total_return': m['total_return'], 'max_drawdown': m['max_drawdown']})
    sweep_df = pd.DataFrame(sweep)

    # Max Sharpe is picked off a coarse SUGGESTED_SPLIT_TICK grid (e.g. 5%
    # ticks: 5/95, 10/90, ... 95/5), not the fine 1% sweep grid above -- see
    # SUGGESTED_SPLIT_TICK docstring. The fine sweep still drives the
    # frontier chart's curve; only the suggested number is coarsened.
    coarse_grid = np.round(np.arange(0.0, 1.0001, SUGGESTED_SPLIT_TICK), 4)
    coarse_sharpes = []
    for gms in coarse_grid:
        gw = (gms * util) / margin_ratio
        m = _metrics((1.0 - gms) * r_beta + gw * r_alpha)
        coarse_sharpes.append(m['sharpe'])
    coarse_sharpes = np.array(coarse_sharpes)
    best_coarse_idx = int(np.nanargmax(coarse_sharpes))
    max_sharpe_ms = float(coarse_grid[best_coarse_idx])
    max_sharpe_val = float(coarse_sharpes[best_coarse_idx])

    # Risk parity between the two books: equal risk contribution, in notional-
    # weight space (the return blend the vol/Sharpe maths sees), then
    # converted back to an allocated margin share for display/consistency
    # with ms/w above (inverting w = (ms * util) / margin_ratio), and snapped
    # to the same coarse tick as Max Sharpe for the same reason.
    rp_w = _risk_parity_weight(r_beta, r_alpha)
    rp_ms_raw = float(np.clip(rp_w * margin_ratio / util, 0.0, 1.0))
    rp_ms = float(np.round(rp_ms_raw / SUGGESTED_SPLIT_TICK) * SUGGESTED_SPLIT_TICK)
    rp_metrics = _metrics((1.0 - rp_ms) * r_beta + (rp_ms * util / margin_ratio) * r_alpha)

    total_capital_mm = float(total_capital_mm or 0.0)
    beta_notional_mm = (1.0 - ms) * total_capital_mm
    alpha_margin_allocated_mm = ms * total_capital_mm
    alpha_margin_usable_mm = alpha_margin_allocated_mm * util
    alpha_notional_mm = alpha_margin_usable_mm / margin_ratio

    # Total PnL in MM CNY over the selected window, net of cost -- both books'
    # equity series are already net of financing/borrow cost (see module
    # docstring), so total_return * capital-base is the net PnL directly, no
    # separate cost deduction needed. Each book's PnL is on ITS OWN capital
    # base -- beta notional, alpha's ALLOCATED margin (the full 2B in the
    # 20B/90-10 example, not the 1.8B actually deployed: m_alpha_margin's
    # return series already has the utilization buffer folded in via `util`,
    # so it's already "return against the whole allocation, buffer included"
    # -- multiplying by the usable-only slice would double-count the buffer
    # drag). Combined PnL is beta's PnL plus alpha's PnL scaled by margin
    # usage, which equals total_return on the whole capital pool since
    # combined returns are the same capital-weighted blend used for
    # m_combined above.
    pnl_beta_mm = m_beta['total_return'] * beta_notional_mm
    pnl_alpha_mm = m_alpha_margin['total_return'] * alpha_margin_allocated_mm
    pnl_combined_mm = m_combined['total_return'] * total_capital_mm

    return {
        'n_days': int(len(common)),
        'start': common.min(),
        'end': common.max(),
        'beta': m_beta,
        'alpha': m_alpha,
        'alpha_margin_metrics': m_alpha_margin,
        'combined': m_combined,
        'alpha_margin_share': ms,
        'alpha_weight': w,
        'max_margin_utilization': util,
        'correlation': corr,
        'rolling_correlation': rolling_corr,
        'rolling_correlation_window': ROLLING_CORR_WINDOW,
        'worst_window_correlation': worst_window_corr,
        'rolling_correlation_flag': ROLLING_CORR_FLAG,
        'diversification_ratio': div_ratio,
        'sweep': sweep_df,
        'max_sharpe_margin_share': max_sharpe_ms,
        'max_sharpe': max_sharpe_val,
        'risk_parity_margin_share': rp_ms,
        'risk_parity_weight': rp_w,
        'risk_parity': rp_metrics,
        'margin_ratio': margin_ratio,
        'total_capital_mm': total_capital_mm,
        'beta_notional_mm': beta_notional_mm,
        'alpha_margin_mm': alpha_margin_allocated_mm,
        'alpha_margin_usable_mm': alpha_margin_usable_mm,
        'alpha_notional_mm': alpha_notional_mm,
        'pnl_beta_mm': pnl_beta_mm,
        'pnl_alpha_mm': pnl_alpha_mm,
        'pnl_combined_mm': pnl_combined_mm,
        'window': window,
        'returns': {'beta': r_beta, 'alpha': r_alpha, 'combined': r_combined},
    }


def _rolling_correlation(
    r_beta: pd.Series,
    r_alpha: pd.Series,
    window: int = ROLLING_CORR_WINDOW,
) -> Optional[pd.Series]:
    """Rolling correlation of the two books' daily returns, or None if there
    isn't enough overlapping history for even one window's worth of points.

    Deliberately separate from the full-sample ``corr`` scalar in
    ``build_combination`` -- see ``ROLLING_CORR_WINDOW`` docstring for why the
    window is longer than the full-sample minimum-overlap gate.
    """
    if len(r_beta) < window:
        return None
    roll = r_beta.rolling(window).corr(r_alpha).dropna()
    return roll if not roll.empty else None


def _risk_parity_weight(r_beta: pd.Series, r_alpha: pd.Series) -> float:
    """Alpha weight at which both books contribute equal risk.

    Risk contribution of asset i is ``w_i * (Cov @ w)_i / portfolio_vol``.
    Scanned on a fine grid rather than solved analytically: the two-asset
    closed form ignores correlation, and a scan costs nothing at this size.
    """
    cov = np.cov(np.vstack([r_beta.values, r_alpha.values]))
    best_w, best_gap = 0.5, float('inf')
    for gw in np.arange(0.01, 1.0, 0.005):
        w_vec = np.array([1.0 - gw, gw])
        port_var = float(w_vec @ cov @ w_vec)
        if port_var <= 0:
            continue
        rc = w_vec * (cov @ w_vec) / np.sqrt(port_var)
        gap = abs(rc[0] - rc[1])
        if gap < best_gap:
            best_gap, best_w = gap, float(gw)
    return best_w
