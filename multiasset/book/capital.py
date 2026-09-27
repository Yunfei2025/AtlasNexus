# -*- coding: utf-8 -*-
"""Long-only, unlevered capital constraint with a utilisation buffer.

See docs/plans/beta_book_exposure_vs_capital.md Step 7. The substantive
change from the pre-refactor behaviour: the old code (backtest_hist.py's
former Step C) ALWAYS renormalised weights to sum(abs(w)) == 1, so the book
was always 100% invested regardless of how bearish the signal was — a
bearish day could only rotate exposure between assets, never de-risk.
weights_to_notional instead preserves the signal's own scale (gross <
max_utilisation stays as-is) and only scales DOWN when gross exceeds the
ceiling — so a day where every factor's signal points bearish genuinely
shrinks deployed capital, with the remainder earning the cash rate (see
multiasset.book.funding.cash_return_daily).
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd

from multiasset.config import RiskModelConfig


def weights_to_notional(
    weights: pd.Series,
    total_capital: float,
    max_utilisation: float = RiskModelConfig.CAPITAL_UTILISATION_MAX,
    asset_class_of: dict | None = None,
    signed_classes: Sequence[str] = ('fx',),
) -> pd.Series:
    """Long-only (except `signed_classes`) notional sizing under a capital
    utilisation ceiling.

    1. Clip long-only at 0, EXCEPT assets in `signed_classes` (FX keeps its
       existing signed [-cap, +cap] bound from rebuild_asset_weights's own
       clip step — decision #6 of the plan: a currency view is inherently
       two-sided, so FX is the one exception to "long-only everywhere").
       `asset_class_of` maps asset_name -> class label using the SAME lower-
       case convention as Stage2Context.asset_class_of ('comm', 'fx',
       'credit', 'bond' — see factor_optimizer.py's _stage1_context);
       assets not in `asset_class_of` are treated as long-only by default.
    2. gross = weights.abs().sum()
    3. SCALE-PRESERVING: if gross <= max_utilisation, notional = weights *
       total_capital (unchanged scale — this is the case that lets the book
       de-risk: a lightly-positioned day stays lightly deployed, it is NOT
       scaled back up to full investment).
       Otherwise, notional = weights * total_capital * (max_utilisation / gross)
       (scaled down proportionally so the ceiling holds exactly).
    4. Invariant: notional.abs().sum() <= max_utilisation * total_capital + eps,
       enforced on THIS call alone — for a full daily backtest, call this
       once per day (see docs/plans/beta_book_exposure_vs_capital.md Step 4's
       daily_weights_from_context output, one row per day), not once per
       month, so a single day where several factors' daily coefficients
       spike together is still caught and scaled back, independent of how
       the reference (monthly) budget was sized.
    """
    if weights.empty:
        return weights.copy()

    w = weights.copy()
    # Long-only clip, per asset — every class except `signed_classes` (FX)
    # is floored at 0; assets missing from `asset_class_of` default to
    # long-only.
    if asset_class_of:
        clipped = {}
        for name, v in w.items():
            cls = asset_class_of.get(name)
            if cls in signed_classes:
                clipped[name] = v
            else:
                clipped[name] = max(v, 0.0)
        w = pd.Series(clipped, index=w.index)
    else:
        w = w.clip(lower=0.0)

    gross = float(w.abs().sum())
    if gross <= max_utilisation or gross <= 1e-12:
        scale = 1.0
    else:
        scale = max_utilisation / gross

    return w * total_capital * scale


def gross_utilisation(notional: pd.DataFrame | pd.Series) -> pd.Series | float:
    """sum(|notional|) — either per-day (DataFrame -> Series, axis=1) or a
    single day's total (Series -> float). Convenience for verifying the
    Step-7 invariant / reporting deployed-capital utilisation."""
    if isinstance(notional, pd.DataFrame):
        return notional.abs().sum(axis=1)
    return float(notional.abs().sum())
