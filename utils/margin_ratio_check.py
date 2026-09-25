"""Re-validation check for estimate_margin_mm's netting-correction multiplier.

See docs/plans/portfolio_construction_beta_alpha.md §6b and
web/tabs/alpha/data/duration.py's _MARGIN_NETTING_MULTIPLIER docstring for
what this is correcting and why. Run this periodically (see the checklist
in the plan doc) and compare its output against _MARGIN_NETTING_MULTIPLIER's
current value (2.5, fit 2026-09-15) -- this script does not change the
constant itself, it only reports whether a re-fit looks warranted.

Usage:
  python utils/margin_ratio_check.py
  python utils/margin_ratio_check.py --min-rows 15   # warn below this sample size

Method (mirrors the original fit): for every row in
summary_alpha_portfolio.parquet, compute the single-leg DV01 proxy
(estimate_margin_mm's DV01 term only, un-multiplied) from that row's
notional_mm and _duration, then take actual_margin_mm / single_leg_estimate.
Report the median (what the constant is set from -- robust to long-tenor
outliers) and the distribution around it, so a drift can be seen rather than
just a single number silently accepted or rejected.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from settings.paths import DIR_INPUT
from web.tabs.alpha.data.duration import (
    _MARGIN_TENOR_STRESS_BP,
    _MARGIN_MIN_RATE,
    _MARGIN_NETTING_MULTIPLIER,
)

_SUMMARY_ALPHA_PARQUET = Path(DIR_INPUT) / 'summary_alpha_portfolio.parquet'


def _single_leg_dv01_estimate(notional_mm: float, duration_mult: float) -> float:
    """The un-multiplied DV01 term of estimate_margin_mm -- i.e. what the
    proxy would say before _MARGIN_NETTING_MULTIPLIER corrects it."""
    notional_mm = abs(float(notional_mm))
    duration_mult = max(0.01, float(duration_mult))
    stress_bp = next(stress for tenor, stress in _MARGIN_TENOR_STRESS_BP if duration_mult <= tenor)
    dv01_k = notional_mm * duration_mult / 10.0
    return dv01_k * stress_bp / 1000.0


def compute_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Return a frame of {ID, spread_type, ratio} for rows with usable data.

    A row is usable when it has a positive notional, a positive actual
    margin, and a resolvable duration -- rows that only ever hit the
    notional floor (actual_margin == notional_mm * _MARGIN_MIN_RATE) are
    excluded, same as the original fit: the floor branch never touches the
    netting multiplier, so it carries no information about it and would
    silently pull any ratio computed from it towards 1.0 for the wrong
    reason.
    """
    required = {'notional_mm', 'margin_mm', '_duration'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"summary_alpha_portfolio.parquet is missing columns: {sorted(missing)}")

    rows = []
    for _, row in df.iterrows():
        notional = pd.to_numeric(row.get('notional_mm'), errors='coerce')
        actual_margin = pd.to_numeric(row.get('margin_mm'), errors='coerce')
        duration = pd.to_numeric(row.get('_duration'), errors='coerce')
        if pd.isna(notional) or pd.isna(actual_margin) or pd.isna(duration):
            continue
        if notional <= 0 or actual_margin <= 0:
            continue

        floor_mm = abs(notional) * _MARGIN_MIN_RATE
        if np.isclose(actual_margin, floor_mm, rtol=1e-6):
            continue  # floor-bound row, uninformative about the multiplier

        single_leg = _single_leg_dv01_estimate(notional, duration)
        if single_leg <= 0:
            continue

        rows.append({
            'ID': row.get('ID', ''),
            'spread_type': row.get('spread_type', ''),
            'notional_mm': notional,
            'margin_mm': actual_margin,
            'duration': duration,
            'ratio': actual_margin / single_leg,
        })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--min-rows', type=int, default=15,
                         help="Warn if fewer than this many usable rows are found (default 15; "
                              "the original fit used 25).")
    parser.add_argument('--drift-threshold', type=float, default=0.25,
                         help="Warn if the current median ratio differs from "
                              "_MARGIN_NETTING_MULTIPLIER by more than this fraction (default 0.25 = 25%%).")
    args = parser.parse_args()

    if not _SUMMARY_ALPHA_PARQUET.exists():
        print(f"[margin_ratio_check] {_SUMMARY_ALPHA_PARQUET} not found -- "
              f"run the Alpha scan/allocation workflow first to produce a snapshot.")
        return 1

    df = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
    ratios = compute_ratios(df)

    n = len(ratios)
    print(f"summary_alpha_portfolio.parquet: {len(df)} total rows, {n} usable "
          f"(non-floor-bound) rows for the margin-ratio fit.")

    if n == 0:
        print("[margin_ratio_check] No usable rows -- cannot compute a ratio. "
              "Re-run once the book has non-floor-bound margined positions.")
        return 1

    if n < args.min_rows:
        print(f"[margin_ratio_check] WARNING: only {n} usable rows (original fit used 25) "
              f"-- treat this result as indicative, not a re-fit basis.")

    median_ratio = float(ratios['ratio'].median())
    mean_ratio = float(ratios['ratio'].mean())
    q1, q3 = ratios['ratio'].quantile([0.25, 0.75])
    lo, hi = ratios['ratio'].min(), ratios['ratio'].max()

    print(f"\nCurrent _MARGIN_NETTING_MULTIPLIER: {_MARGIN_NETTING_MULTIPLIER}")
    print(f"Re-derived median ratio:            {median_ratio:.3f}")
    print(f"  mean:  {mean_ratio:.3f}")
    print(f"  IQR:   {q1:.3f} - {q3:.3f}")
    print(f"  range: {lo:.3f} - {hi:.3f}  (n={n})")

    drift = abs(median_ratio - _MARGIN_NETTING_MULTIPLIER) / _MARGIN_NETTING_MULTIPLIER
    print(f"\nDrift from current constant: {drift * 100:.1f}%")
    if n >= args.min_rows and drift > args.drift_threshold:
        print(f"[margin_ratio_check] WARNING: drift exceeds {args.drift_threshold * 100:.0f}% "
              f"threshold with an adequate sample -- consider re-fitting "
              f"_MARGIN_NETTING_MULTIPLIER in web/tabs/alpha/data/duration.py.")
    else:
        print("[margin_ratio_check] Within tolerance (or sample too small to act on) -- "
              "no change recommended.")

    print("\nPer-instrument detail:")
    with pd.option_context('display.max_rows', None, 'display.width', 140):
        print(ratios[['spread_type', 'ID', 'notional_mm', 'margin_mm', 'duration', 'ratio']]
              .sort_values('ratio', ascending=False).to_string(index=False))

    non_fit_types = sorted(set(ratios['spread_type']) - {'TenorSpread', 'SwapSpread'})
    if non_fit_types:
        print(f"\nNote: {non_fit_types} weren't part of the original fit sample "
              f"(TenorSpread/SwapSpread only, 2026-09-15) -- a bond-vs-curve row like "
              f"TBondCurve carries a different margin regime (bond notional/repo haircut, "
              f"not a derivative DV01 charge) and its ratio here is not comparable to the "
              f"others; consider excluding such rows when judging drift, not just averaging "
              f"them in.")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
