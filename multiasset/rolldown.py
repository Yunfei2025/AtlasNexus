# -*- coding: utf-8 -*-
"""
CGB roll-down-aware tilt on top of the Stage-1 factor risk-parity allocation.

Implements the "simple pro-rata tilt" design in
docs/dev/rates_risk_budget_rolldown_approach1.md §7: Stage 1 (risk parity)
decides how much Level/Slope/Curvature risk to hold; this module decides
which tenor should carry a slice of that risk by tilting capital toward the
tenor with the best risk-adjusted carry + roll-down, funded pro-rata from
the rest of the book. It does not re-solve for the Stage-1 factor target,
so the resulting factor exposure drifts slightly from it — see
``factor_drift`` in :func:`run_rolldown_tilt`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pca_analyzer import CN_IR_TENORS, CN_DETERMINISTIC_WEIGHTS
from .utils import get_default_sensitivities

TENOR_YEARS: dict[str, float] = {'1Y': 1, '2Y': 2, '5Y': 5, '10Y': 10, '20Y': 20, '30Y': 30}


def cn_loading_matrix() -> np.ndarray:
    """Level/Slope/Curvature loadings for the CN_IR_TENORS grid, shape (6,3)."""
    return np.column_stack([CN_DETERMINISTIC_WEIGHTS[f] for f in ('Level', 'Slope', 'Curvature')])


def cn_durations(tenors: tuple[str, ...] = CN_IR_TENORS) -> np.ndarray:
    """Modified duration per tenor, from the production sensitivity table."""
    return np.array([get_default_sensitivities(t)['IRDL'] for t in tenors])


def carry_rolldown(
    curve: pd.Series,
    tenors: tuple[str, ...] = CN_IR_TENORS,
    funding_tenor: str = '1Y',
    roll_horizon_years: float = 0.25,
) -> pd.DataFrame:
    """Per-tenor carry + roll-down, in annualized bp per unit DV01.

    carry(T) = yield(T) - yield(funding_tenor)
    roll(T)  = duration(T) * [yield(T) - yield(T - roll_horizon)] * (1 / roll_horizon)

    ``curve`` is a yield series (in %) indexed by tenor string, covering at
    least ``tenors``. ``yield(T - roll_horizon)`` is linearly interpolated
    against the tenor-year grid.
    """
    durations = cn_durations(tenors)
    xs = np.array([TENOR_YEARS[t] for t in tenors])
    ys = curve.loc[list(tenors)].astype(float).values

    funding_rate = curve[funding_tenor]
    carry_bp = (ys - funding_rate) * 100

    roll_bp = np.empty(len(tenors))
    for i, t in enumerate(tenors):
        ty = TENOR_YEARS[t]
        y_shorter = np.interp(max(ty - roll_horizon_years, 0.01), xs, ys)
        roll_bp[i] = durations[i] * (ys[i] - y_shorter) * 100 * (1.0 / roll_horizon_years)

    return pd.DataFrame(
        {'duration': durations, 'carry_bp': carry_bp, 'roll_bp': roll_bp,
         'total_bp': carry_bp + roll_bp},
        index=list(tenors),
    )


def select_t_star(carry_roll: pd.DataFrame, level_vol: float) -> str:
    """Tenor with the best risk-adjusted carry + roll-down.

    ``level_vol`` scales ``total_bp`` per tenor by the risk (duration x
    level-factor vol) taken to hold it, so the pick isn't just "longest bond
    has the most carry".
    """
    risk_adj = carry_roll['total_bp'] / (carry_roll['duration'] * level_vol * 100 + 1e-9)
    return risk_adj.idxmax()


def tilt_weights(w_baseline: pd.Series, t_star: str, tilt_pct: float) -> pd.Series:
    """Move ``tilt_pct`` of gross DV01 onto ``t_star``, funded pro-rata.

    Funding is proportional to each other tenor's existing |weight|, which
    is what keeps the tilt's Level-factor drift at zero on the CN grid
    (equal Level loading across tenors) — see doc §7.1 for the derivation.
    Slope/Curvature drift is not zero and should be checked via
    :func:`factor_drift`.
    """
    gross_dv01 = w_baseline.abs().sum()
    sign = np.sign(w_baseline[t_star]) or 1.0
    tilt_amount = tilt_pct * gross_dv01 * sign

    funding_weights = w_baseline.abs().copy()
    funding_weights[t_star] = 0.0
    funding_shares = funding_weights / funding_weights.sum()

    w_tilted = w_baseline.copy()
    w_tilted[t_star] += tilt_amount
    w_tilted -= funding_shares * tilt_amount
    return w_tilted


def factor_drift(w: pd.Series, B: np.ndarray, e_star: np.ndarray, tenors: tuple[str, ...] = CN_IR_TENORS) -> pd.DataFrame:
    """Realized factor exposure of weights ``w`` vs. the Stage-1 target ``e_star``."""
    realized = B.T @ w.loc[list(tenors)].values
    drift = realized - e_star
    return pd.DataFrame(
        {'e_star': e_star, 'realized': realized, 'drift': drift,
         'drift_pct': np.where(e_star != 0, drift / e_star * 100, 0.0)},
        index=['Level', 'Slope', 'Curvature'],
    )


def run_rolldown_tilt(
    curve: pd.Series,
    w_baseline: pd.Series,
    e_star: np.ndarray,
    level_vol: float,
    tilt_pct: float = 0.20,
    funding_tenor: str = '1Y',
    tenors: tuple[str, ...] = CN_IR_TENORS,
) -> dict:
    """End-to-end: carry/roll table -> T* -> tilted weights -> drift check.

    ``w_baseline`` is the Stage-1, no-rolldown DV01 weight per tenor (e.g.
    minimum-norm solution of ``B.T @ w = e_star``). ``level_vol`` is the
    Level-factor daily vol used to risk-adjust the carry/roll ranking in
    :func:`select_t_star` (same ``sigma_k`` used to build ``e_star`` in
    Stage 1). Returns a plain dict of JSON-serializable pieces, suitable for
    ``BacktestResult.meta``.
    """
    B = cn_loading_matrix()
    cr = carry_rolldown(curve, tenors=tenors, funding_tenor=funding_tenor)

    t_star = select_t_star(cr, level_vol=level_vol)
    w_tilted = tilt_weights(w_baseline, t_star, tilt_pct)
    drift = factor_drift(w_tilted, B, e_star, tenors=tenors)

    return {
        't_star': t_star,
        'tilt_pct': tilt_pct,
        'carry_rolldown': cr.to_dict(orient='index'),
        'w_baseline': w_baseline.to_dict(),
        'w_tilted': w_tilted.to_dict(),
        'factor_drift': drift.to_dict(orient='index'),
    }
