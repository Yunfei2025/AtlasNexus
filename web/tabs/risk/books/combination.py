# -*- coding: utf-8 -*-
"""Beta + Alpha book combination analytics for Summary > Books.

Combines the two books' *saved* backtest results into one synthetic
portfolio, to answer two questions:

  1. What capital split between the books maximizes risk-adjusted return?
  2. Are the two books actually diversifying each other, or duplicating risk?

Unit reconciliation is the crux. The two books measure P&L differently:

  - Beta (multiasset historical allocation) is cumulative P&L in **million
    CNY** against an explicit ``total_capital``.
  - Alpha (TenorSpread portfolio backtest) is cumulative P&L in **basis
    points** on notionally-unit positions -- it carries no capital base, so
    "593bp" alone says nothing about how much capital it consumed.

Neither is a return until divided by a capital base, so a "50/50 split" is
not even well-defined until the caller supplies the alpha book's notional.
``alpha_capital_mm`` is that input: alpha bp convert to CNY as
``pnl_bp / 10000 * alpha_capital_mm``, after which both books are daily
return series on their own capital and can be weighted.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252


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


def _alpha_returns(alpha_result: dict, alpha_capital_mm: float) -> Optional[pd.Series]:
    """Daily fractional returns for the alpha book on ``alpha_capital_mm``.

    ``equity_ts`` is cumulative P&L in bp of a unit position, so the daily
    *change* in bp divided by 10000 is the day's return on one unit of
    notional -- independent of the capital base. Scaling by capital cancels
    out, but is kept explicit so the CNY P&L series below stays derivable.
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
        return {'sharpe': float('nan'), 'vol': float('nan'),
                'total_return': float('nan'), 'max_drawdown': float('nan')}
    vol = float(returns.std() * np.sqrt(TRADING_DAYS))
    sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS))
    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    running_max = equity.cummax()
    max_dd = float(((equity - running_max) / running_max).min())
    return {'sharpe': sharpe, 'vol': vol,
            'total_return': total_return, 'max_drawdown': max_dd}


def build_combination(
    beta_result: Optional[dict],
    alpha_result: Optional[dict],
    alpha_capital_mm: float,
    alpha_weight: float,
) -> dict[str, Any]:
    """Align both books and analyse the combined portfolio.

    ``alpha_weight`` is the alpha book's share of total capital (0..1); beta
    takes the remainder. Returns a dict with per-book metrics, the combined
    metrics at the requested weight, a full weight sweep (for the frontier
    chart), and the diversification statistics.

    Returns ``{'error': str}`` when either book has no saved result, or when
    their date ranges do not overlap enough to compare.
    """
    if not beta_result:
        return {'error': 'No saved Beta backtest. Run and save it in the Multi-Asset dashboard.'}
    if not alpha_result:
        return {'error': 'No saved Alpha backtest. Run and save it in Alpha > Backtest > Portfolio.'}

    r_beta = _beta_returns(beta_result)
    r_alpha = _alpha_returns(alpha_result, alpha_capital_mm)
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

    m_beta = _metrics(r_beta)
    m_alpha = _metrics(r_alpha)

    corr = float(r_beta.corr(r_alpha))
    w = float(np.clip(alpha_weight, 0.0, 1.0))
    r_combined = (1.0 - w) * r_beta + w * r_alpha
    m_combined = _metrics(r_combined)

    # Diversification ratio: weighted-average standalone vol over realised
    # combined vol. >1 means the combination genuinely cancels risk; ~1 means
    # the books are effectively the same bet.
    wavg_vol = (1.0 - w) * m_beta['vol'] + w * m_alpha['vol']
    div_ratio = float(wavg_vol / m_combined['vol']) if m_combined['vol'] else float('nan')

    # Weight sweep for the frontier chart / optimal points.
    grid = np.round(np.arange(0.0, 1.0001, 0.01), 4)
    sweep = []
    for gw in grid:
        m = _metrics((1.0 - gw) * r_beta + gw * r_alpha)
        sweep.append({'alpha_weight': float(gw), 'sharpe': m['sharpe'],
                      'vol': m['vol'], 'total_return': m['total_return'],
                      'max_drawdown': m['max_drawdown']})
    sweep_df = pd.DataFrame(sweep)

    best_idx = sweep_df['sharpe'].idxmax()
    max_sharpe_w = float(sweep_df.loc[best_idx, 'alpha_weight'])
    max_sharpe_val = float(sweep_df.loc[best_idx, 'sharpe'])

    # Risk parity between the two books: equal risk contribution. With two
    # assets this has a closed form only when uncorrelated; solve on the grid
    # instead so the correlation term is respected.
    rp_w = _risk_parity_weight(r_beta, r_alpha)
    rp_metrics = _metrics((1.0 - rp_w) * r_beta + rp_w * r_alpha)

    # Suggested alpha capital from the book's own DV01-based margin ratio: if
    # this book runs at unit-notional-per-instrument scaled by
    # alpha_capital_mm, its actual margin usage is
    # alpha_capital_mm * margin_ratio -- shown so the manual capital input
    # can be sanity-checked against a real (if approximate) margin model,
    # not just guessed. None when the instrument snapshot can't support the
    # estimate (e.g. an old saved result predating this field).
    margin_ratio = estimate_alpha_book_margin_ratio(alpha_result.get('instruments') or [])
    implied_margin_mm = margin_ratio * alpha_capital_mm if margin_ratio is not None else None

    return {
        'n_days': int(len(common)),
        'start': common.min(),
        'end': common.max(),
        'beta': m_beta,
        'alpha': m_alpha,
        'combined': m_combined,
        'alpha_weight': w,
        'correlation': corr,
        'diversification_ratio': div_ratio,
        'sweep': sweep_df,
        'max_sharpe_weight': max_sharpe_w,
        'max_sharpe': max_sharpe_val,
        'risk_parity_weight': rp_w,
        'risk_parity': rp_metrics,
        'margin_ratio': margin_ratio,
        'implied_margin_mm': implied_margin_mm,
        'returns': {'beta': r_beta, 'alpha': r_alpha, 'combined': r_combined},
    }


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
