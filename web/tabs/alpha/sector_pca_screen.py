# -*- coding: utf-8 -*-
"""Candidate-pair screener for the Sector PCA spread (SectorPCASpread).

SectorPCASpread ranks every instrument (TBond/CBond tenors, FR007S/SHI3MS
swap tenors) by its residual Z-score against a common 2-factor (level+slope)
PCA fit across the whole panel -- see curves/generators/stat.py::
compute_pca_spreads. That single common yardstick is the point: it lets us
compare "how oversold/overbought" instruments are across sectors on one
scale, which no per-sector or per-tenor decomposition would preserve.

The failure mode of trading straight off that ranking is that extremity is
exactly what the screen selects for, and a large residual can mean either
(a) noise around a relationship that reliably holds -> reverts, our trade,
or (b) the relationship itself just repriced -> the residual keeps going,
and the ranking hands it to us every day while it bleeds. Rank alone cannot
tell these apart. The checks below use only data the pipeline already
computes (plus per-instrument R^2, added alongside this module) to bias the
picks toward (a):

  1. Gap-to-field:  the top pick must be meaningfully more extreme than the
     runner-up, not just nominally top-ranked in a flat cross-section.
  2. Turning, not falling: require the residual to have stopped making new
     extremes recently (its own N-day slope has flattened/reversed) -- don't
     fade a residual that is still actively widening.
  3. Model fit (R^2): drop instruments the 2-PC reconstruction doesn't
     describe well -- a big residual on a name the model never explained is
     idiosyncratic noise, not a deviation from a relationship, so there is
     nothing for it to revert to.
  4. Stationarity/halflife: reuse OU_calibrate's own verdict -- require
     'stationary' == 'YES' and a finite, sane halflife.
  5. Pair-level (not leg-level) re-check: everything above is re-run on the
     *constructed spread* (long cheap leg, short rich leg), since that is
     the series actually held, and its Z/half-life are not simply the
     difference of the two legs' Z-scores.

Duration note: the most-oversold and most-overbought names are often at
opposite ends of the curve (short vs long tenor) because that's where
residual variance concentrates. That pair is a duration trade wearing an RV
costume and loads on the same slope factor (PC2) the residual didn't fully
remove. flag_duration_mismatch() surfaces this; it does not veto the pair,
since a duration view may be intended -- it's a caveat to weigh, not a rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

import curves.calibration.stat as st
from web.tabs.alpha.data import load_spread_data, load_spread_timeseries

SPREAD_TYPE = "SectorPCASpread"

# Screening thresholds. Set once on defensible grounds (not tuned on this
# spread's own backtest -- see [[alpha-backtest-no-param-tuning]]).
MIN_ABS_ZSCORE = 2.0          # floor: matches ZSCORE_ENTRY_THRESHOLD elsewhere in the book
MIN_GAP_TO_RUNNER_UP = 0.5    # top pick's |Z| must clear the next name by this much
TURN_LOOKBACK_DAYS = 10       # window used to check the residual has stopped extending
MIN_R2 = 0.5                  # per-instrument PCA reconstruction fit required to trust reversion
MAX_HALFLIFE_DAYS = 30.0      # OU halflife beyond this is "drifting", not "reverting"
MIN_LEG_CORR_GAP = 0.3        # legs' residuals must not be too tightly co-moving (see below)


def _tenor_years(ticker: str) -> Optional[float]:
    """Parse the tenor (in years) out of a SectorPCASpread ticker, for the
    duration-mismatch caveat only -- not a hedge-ratio computation.

    Tickers: 'TBond-10.0Y', 'CBond-7.0Y' (tenor after the dash), 'FR007S5Y.IR'
    / 'FR007S3M.IR' / 'SHI3MS4Y.IR' (tenor is the trailing Y/M token right
    before '.IR', NOT the '3M' embedded in 'FR007'/'SHI3M' themselves), or a
    bare index like 'FR007.IR' (no tenor). A naive "first N(Y|M) anywhere in
    the string" regex misparses SHI3MS4Y.IR as 3M -- anchor on the specific
    known formats instead.
    """
    m = re.match(r'^(?:TBond|CBond)-(\d+(?:\.\d+)?)Y$', ticker)
    if m:
        return float(m.group(1))
    m = re.match(r'^(?:FR007S|SHI3MS)(\d+(?:\.\d+)?)(Y|M)\.IR$', ticker, re.IGNORECASE)
    if m:
        val, unit = float(m.group(1)), m.group(2).upper()
        return val / 12.0 if unit == "M" else val
    return None


@dataclass
class LegScreen:
    ticker: str
    zscore: float
    r2: Optional[float]
    stationary: Optional[str]
    halflife: Optional[float]
    turned: bool
    passes: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class PairCandidate:
    cheap: LegScreen      # oversold -> buy
    rich: LegScreen       # overbought -> sell
    gap_ok: bool
    spread_zscore: Optional[float]
    spread_stationary: Optional[str]
    spread_halflife: Optional[float]
    leg_corr: Optional[float]
    duration_mismatch: bool
    passes: bool
    reasons: List[str] = field(default_factory=list)


def _residual_turned(series: pd.Series, lookback: int = TURN_LOOKBACK_DAYS) -> bool:
    """True if the residual has stopped making new extremes over `lookback`
    days -- i.e. it looks like it's turning, not still running away.

    Concretely: today's value is not the most extreme (largest |value|) of
    the trailing window, OR the sign of its recent change has flipped
    relative to the sign of the level itself (a positive residual that's now
    falling, or a negative one that's now rising).
    """
    s = series.dropna()
    if len(s) < max(3, lookback // 2):
        return False
    window = s.iloc[-lookback:]
    last = window.iloc[-1]
    most_extreme = window.abs().idxmax()
    if window.index[-1] != most_extreme:
        return True
    # Still the extreme point of the window -- check short-term slope
    recent_slope = window.iloc[-1] - window.iloc[max(0, len(window) - 3)]
    return (last > 0 and recent_slope < 0) or (last < 0 and recent_slope > 0)


def _screen_leg(ticker: str, stat_info: pd.DataFrame, resid_ts: pd.DataFrame) -> LegScreen:
    reasons: List[str] = []
    row = stat_info.loc[ticker] if ticker in stat_info.index else None
    z = float(row.get("Zscore", np.nan)) if row is not None and "Zscore" in row else np.nan
    if np.isnan(z):
        # Zscore may not be persisted on StatInfo directly (it's often computed
        # at the realtime-snapshot layer); fall back to (last - mean)/ewm_vol.
        if row is not None and ticker in resid_ts.columns:
            s = resid_ts[ticker].dropna()
            mean = float(row.get("mean", s.mean())) if row is not None else s.mean()
            vol = float(row.get("ewm_vol", s.std())) if row is not None else s.std()
            z = (s.iloc[-1] - mean) / vol if vol else np.nan

    r2 = float(row["R2"]) if row is not None and "R2" in row and pd.notna(row["R2"]) else None
    stationary = str(row["stationary"]) if row is not None and "stationary" in row and pd.notna(row["stationary"]) else None
    halflife = float(row["halflife"]) if row is not None and "halflife" in row and pd.notna(row["halflife"]) else None

    turned = _residual_turned(resid_ts[ticker]) if ticker in resid_ts.columns else False

    passes = True
    if np.isnan(z) or abs(z) < MIN_ABS_ZSCORE:
        passes = False
        reasons.append(f"|Z|={z:.2f} below floor {MIN_ABS_ZSCORE}")
    if r2 is None or r2 < MIN_R2:
        passes = False
        reasons.append(f"R2={r2!r} below {MIN_R2} -- residual not a deviation from a held relationship")
    if stationary != "YES":
        passes = False
        reasons.append(f"stationary={stationary!r} -- OU calibration doesn't call this mean-reverting")
    if halflife is None or not np.isfinite(halflife) or halflife > MAX_HALFLIFE_DAYS:
        passes = False
        reasons.append(f"halflife={halflife!r} exceeds {MAX_HALFLIFE_DAYS}d -- drifting, not reverting")
    if not turned:
        passes = False
        reasons.append("residual still extending -- has not turned in the last "
                        f"{TURN_LOOKBACK_DAYS}d, don't fade a move still in progress")

    return LegScreen(ticker=ticker, zscore=z, r2=r2, stationary=stationary,
                      halflife=halflife, turned=turned, passes=passes, reasons=reasons)


def screen_sector_pca_pairs(top_n: int = 3) -> List[PairCandidate]:
    """Rank SectorPCASpread instruments by |Z|, then screen candidate
    oversold/overbought pairs for signs the residual is reverting (not
    repricing). Returns up to `top_n` pairs, most-defensible first (fewest
    failed checks, largest gap-to-field), including pairs that fail some
    checks so the caller can see why a nominally-extreme pair was skipped.
    """
    stat_info = load_spread_data(SPREAD_TYPE)
    resid_ts = load_spread_timeseries(SPREAD_TYPE)
    if stat_info is None or resid_ts is None or stat_info.empty or resid_ts.empty:
        return []

    # Zscore may live only on a realtime snapshot elsewhere in the app; if
    # StatInfo lacks it, derive from resid_ts directly (see _screen_leg).
    if "Zscore" not in stat_info.columns:
        stat_info = stat_info.copy()
        stat_info["Zscore"] = np.nan

    legs = {t: _screen_leg(t, stat_info, resid_ts) for t in stat_info.index if t in resid_ts.columns}
    if len(legs) < 2:
        return []

    # Sign convention: `zscore` here is a single instrument's own YIELD
    # residual (spot yield vs. the 2-PC reconstruction), not a two-leg spread
    # difference. A POSITIVE residual means the instrument's yield sits
    # ABOVE what the common factors predict -- i.e. it is CHEAP (yield too
    # high / price too low) -- so it should be BOUGHT. A NEGATIVE residual
    # means yield sits below prediction -- i.e. RICH (yield too low / price
    # too high) -- so it should be SOLD. This matches the yield-based
    # convention used everywhere else in the book (see
    # YIELD_BASED_SPREAD_TYPES's docstring and alpha_candidates.py's
    # composite_z: "BUY profits when the spread falls, so an extreme HIGH
    # z-score is a BUY" -- here the "spread" is the instrument's own yield
    # vs. its PCA-implied fair value). Was inverted before 2026-09-19 (zscore
    # < 0 was wrongly treated as oversold/BUY); e.g. TBond-8.0Y with z=-1.77
    # (yield below predicted -> rich) must be SOLD, not bought.
    ranked = sorted(legs.values(), key=lambda l: -abs(l.zscore) if not np.isnan(l.zscore) else -np.inf)
    cheap_legs = [l for l in ranked if not np.isnan(l.zscore) and l.zscore > 0]  # yield too high -> BUY
    rich_legs = [l for l in ranked if not np.isnan(l.zscore) and l.zscore < 0]   # yield too low -> SELL

    candidates: List[PairCandidate] = []
    for cheap in cheap_legs[:top_n]:
        for rich in rich_legs[:top_n]:
            reasons: List[str] = []

            # Gap-to-field: compare this leg's |Z| against the next-ranked
            # name on the SAME side, not the opposite side, since sides are
            # sorted independently -- a flat cross-section on one side alone
            # is enough to make its "extreme" pick unreliable.
            def _gap_ok(leg: LegScreen, same_side: List[LegScreen]) -> bool:
                idx = next((i for i, l in enumerate(same_side) if l.ticker == leg.ticker), None)
                if idx is None or idx + 1 >= len(same_side):
                    return True  # nothing to compare against -- don't penalize
                runner_up = same_side[idx + 1]
                return abs(leg.zscore) - abs(runner_up.zscore) >= MIN_GAP_TO_RUNNER_UP

            gap_ok = _gap_ok(cheap, cheap_legs) and _gap_ok(rich, rich_legs)
            if not gap_ok:
                reasons.append(f"gap-to-runner-up < {MIN_GAP_TO_RUNNER_UP} on one side -- "
                               "flat cross-section, 'most extreme' may just be noise")

            # Pair-level re-check on the constructed spread (long cheap, short rich),
            # not just the two legs independently.
            spread_series = (resid_ts[cheap.ticker] - resid_ts[rich.ticker]).dropna()
            spread_stat = st.OU_calibrate(spread_series.to_frame("spread"))
            spread_row = spread_stat.loc["spread"] if "spread" in spread_stat.index else None
            spread_stationary = str(spread_row["stationary"]) if spread_row is not None and pd.notna(spread_row.get("stationary")) else None
            spread_halflife = float(spread_row["halflife"]) if spread_row is not None and pd.notna(spread_row.get("halflife")) else None
            s_mean = float(spread_row["mean"]) if spread_row is not None and pd.notna(spread_row.get("mean")) else spread_series.mean()
            s_vol = float(spread_row["ewm_vol"]) if spread_row is not None and pd.notna(spread_row.get("ewm_vol")) else spread_series.std()
            spread_z = (spread_series.iloc[-1] - s_mean) / s_vol if s_vol else None

            if spread_stationary != "YES":
                reasons.append(f"constructed spread stationary={spread_stationary!r} -- "
                               "legs' individual reversion doesn't imply the pair reverts")
            if spread_halflife is None or not np.isfinite(spread_halflife) or spread_halflife > MAX_HALFLIFE_DAYS:
                reasons.append(f"constructed spread halflife={spread_halflife!r} exceeds {MAX_HALFLIFE_DAYS}d")

            # Legs shouldn't be too tightly co-moving -- if their residuals are
            # highly correlated, the spread is small/noisy even when both legs
            # look individually extreme.
            common_idx = resid_ts[[cheap.ticker, rich.ticker]].dropna().index
            leg_corr = None
            if len(common_idx) > 20:
                leg_corr = float(resid_ts.loc[common_idx, cheap.ticker].corr(resid_ts.loc[common_idx, rich.ticker]))
                if leg_corr is not None and (1.0 - abs(leg_corr)) < MIN_LEG_CORR_GAP:
                    reasons.append(f"leg residual corr={leg_corr:.2f} too high -- "
                                   "spread may be small/noisy despite extreme-looking legs")

            cheap_tenor = _tenor_years(cheap.ticker)
            rich_tenor = _tenor_years(rich.ticker)
            duration_mismatch = (
                cheap_tenor is not None and rich_tenor is not None
                and abs(cheap_tenor - rich_tenor) >= 5.0
            )
            if duration_mismatch:
                reasons.append(f"tenor gap {cheap_tenor:g}Y vs {rich_tenor:g}Y -- "
                               "this is a duration trade in RV clothing (loads on the slope "
                               "factor PC2 doesn't fully remove); not a veto, but weigh it")

            passes = cheap.passes and rich.passes and gap_ok and spread_stationary == "YES" \
                and spread_halflife is not None and np.isfinite(spread_halflife) and spread_halflife <= MAX_HALFLIFE_DAYS

            candidates.append(PairCandidate(
                cheap=cheap, rich=rich, gap_ok=gap_ok,
                spread_zscore=spread_z, spread_stationary=spread_stationary,
                spread_halflife=spread_halflife, leg_corr=leg_corr,
                duration_mismatch=duration_mismatch, passes=passes,
                reasons=cheap.reasons + rich.reasons + reasons,
            ))

    # Most-extreme pair first (combined |Z| of both legs), so the ordering
    # reads as "1st extreme buy/sell, then 2nd, then 3rd" -- not grouped by
    # pass/fail first, which used to let a weakly-extreme-but-clean pair
    # outrank a genuinely more extreme one. Pass/fail is still visible on
    # each card (pill + border color + reasons list), just no longer the
    # primary sort key.
    candidates.sort(key=lambda c: -(abs(c.cheap.zscore) + abs(c.rich.zscore)))
    return candidates[:top_n]
