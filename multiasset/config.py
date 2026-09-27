# -*- coding: utf-8 -*-
"""
Configuration for multi-asset portfolio risk models.

@author: CMBC
"""
from typing import Dict, List, Optional, Tuple

import numpy as np


class RiskModelConfig:
    """Configuration for risk/volatility modeling parameters."""
    # Lookback for factor volatility estimation (calendar months)
    FACTOR_VOL_LOOKBACK_MONTHS: int = 3
    # EWMA lambda (decay) for daily data (commonly 0.94)
    FACTOR_VOL_EWMA_LAMBDA: float = 0.94

    # ── Optimizer bounds ──────────────────────────────────────────────────────
    # Floors and caps scale with pool size so they remain sensible whether
    # the user selects 3 assets or 15+.
    #
    #   floor = max(abs_floor, equal_share × FLOOR_RATIO)
    #   cap   = min(abs_cap,   equal_share × CAP_RATIO)
    #
    # Ratios are class-specific; absolute limits are hard safety rails.
    FLOOR_RATIO_BOND:   float = 0.30   # bond floor = 30% of equal share
    FLOOR_RATIO_CREDIT: float = 0.10   # credit floor = 10% of equal share (DV01 already controls long-end)
    FLOOR_RATIO_COMM:   float = 0.20   # commodity/FX floor = 20% of equal share
    FLOOR_RATIO_FX:     float = 0.20
    CAP_RATIO_BOND:     float = 3.0    # bond cap = 3× equal share
    CAP_RATIO_CREDIT:   float = 4.0    # credit cap = 4× equal share (short tenors can dominate DV01-weighted)
    CAP_RATIO_COMM:     float = 2.0    # commodity cap = 2× equal share
    CAP_RATIO_FX:       float = 2.0

    # Hard absolute limits (override ratios when pool is very small/large)
    ABS_FLOOR_BOND:   float = 0.01
    ABS_FLOOR_CREDIT: float = 0.01
    ABS_FLOOR_COMM:   float = 0.02
    ABS_FLOOR_FX:     float = 0.02
    ABS_CAP_BOND:     float = 0.40
    ABS_CAP_CREDIT:   float = 0.65   # short tenors (1Y) can legitimately be 60%+ DV01-weighted
    ABS_CAP_COMM:     float = 0.30
    ABS_CAP_FX:       float = 0.30

    @classmethod
    def scaled_bounds(cls, n_assets: int, n_bond_groups: Optional[int] = None,
                       n_credit_groups: Optional[int] = None) -> dict:
        """Return floor/cap per asset class scaled to pool size.

        Bond/credit CAPS scale off the number of independent RATE GROUPS
        (e.g. all 6 CN tenors sharing IRDL.CN/IRSL.CN/IRCV.CN count as ONE
        group), not the number of individual tenor assets. A per-tenor cap
        sized off `1/n_assets` is too tight whenever a group has more than
        one tenor: e.g. for a 10-asset pool with one 6-tenor CN group, the
        old `eq = 1/10` gave every tenor the same 0.30 cap as a single
        commodity, so short-duration tenors (which legitimately want a large
        DV01-weighted share) were pinned at that cap regardless of the
        risk-parity signal. Sizing the cap off `n_bond_groups` (here 1, plus
        any ungrouped single-tenor bonds) instead gives the group as a whole
        the concentration allowance of one bond *position* — the group's
        internal DV01/tilt split (`_two_stage_weights`) still determines each
        tenor's individual share, so no single tenor can actually consume the
        whole widened cap unless the shape genuinely puts most of the DV01
        there.

        Bond/credit FLOORS intentionally keep scaling off `n_assets` (not
        `n_bond_groups`): floors exist to stop the optimizer from zeroing out
        an individual instrument, which is still a per-tenor concern — e.g. a
        6-tenor group with `n_bond_groups=1` should not force every tenor to
        hold >=30%, that would sum to >100%. Only the ceiling scales with
        grouping.

        Commodity/FX bounds are unaffected (no multi-instrument grouping there)
        and continue to scale off `n_assets` for both floor and cap.

        Args:
            n_assets: total individual assets in the pool (drives comm/FX
                bounds and both bond/credit floors).
            n_bond_groups: number of independent rate-bounding units for bond
                CAPS (each multi-tenor country group counts as 1; each
                ungrouped single-tenor bond counts as 1). Defaults to
                `n_assets` (no grouping benefit) when not supplied, preserving
                old behaviour for callers that haven't been updated.
            n_credit_groups: same, for credit caps (universe groups).
        """
        eq = 1.0 / max(n_assets, 1)
        eq_bond_cap = 1.0 / max(n_bond_groups if n_bond_groups is not None else n_assets, 1)
        eq_credit_cap = 1.0 / max(n_credit_groups if n_credit_groups is not None else n_assets, 1)
        return {
            'floor_bond':   max(cls.ABS_FLOOR_BOND,   eq * cls.FLOOR_RATIO_BOND),
            'floor_credit': max(cls.ABS_FLOOR_CREDIT, eq * cls.FLOOR_RATIO_CREDIT),
            'floor_comm':   max(cls.ABS_FLOOR_COMM,   eq * cls.FLOOR_RATIO_COMM),
            'floor_fx':     max(cls.ABS_FLOOR_FX,     eq * cls.FLOOR_RATIO_FX),
            'cap_bond':     min(cls.ABS_CAP_BOND,     eq_bond_cap * cls.CAP_RATIO_BOND),
            'cap_credit':   min(cls.ABS_CAP_CREDIT,   eq_credit_cap * cls.CAP_RATIO_CREDIT),
            'cap_comm':     min(cls.ABS_CAP_COMM,     eq * cls.CAP_RATIO_COMM),
            'cap_fx':       min(cls.ABS_CAP_FX,       eq * cls.CAP_RATIO_FX),
        }

    # Legacy flat constants kept for back-compat with any direct references
    MIN_WEIGHT_BOND: float = 0.03
    CAP_BOND: float = 0.40
    CAP_COMM: float = 0.30
    CAP_FX:   float = 0.30
    MIN_WEIGHT_COMM: float = 0.02
    MIN_WEIGHT_FX:   float = 0.02

    # ── Stage-2 tenor tilt (factor risk-parity optimizer) ─────────────────────
    # Ridge weight (lambda) pulling the intra-group tenor split back toward the
    # DV01-equalised prior (1/duration).  Larger => closer to pure DV01 (flatter,
    # more stable); smaller => tenor shares chase the group's realised
    # level/slope/curvature budget split more aggressively (more responsive,
    # noisier). See FactorRiskParityOptimizer._tilt_group_shape.
    TENOR_TILT_LAMBDA: float = 4.0

    # ── Vol^0.5 budget fallback ───────────────────────────────────────────────
    # Estimated annual volatility (%) for assets with missing factor-vol data
    # (e.g. commodity factors before sufficient data is available)
    ESTIMATED_FALLBACK_VOL: float = 15.0

    # ── Backtest / signal floors ──────────────────────────────────────────────
    # Minimum non-zero signal level for factor-scaling mode (prevents near-zero allocations)
    SIGNAL_FLOOR: float = 0.2
    # Risk-free rate used in backtest Sharpe calculation (annualised, decimal)
    RISK_FREE_RATE: float = 0.02

    # ── Per-asset-class weight caps used in factor-scaling backtest ───────────
    # Live path uses the optimizer bounds; backtest caps must match.
    CLASS_CAPS: dict = {
        'Commodities': 0.15,
        'FX':          0.20,
        'Rates':       0.40,
        'Spread':      0.40,
        'Credit':      0.40,
    }
    # Default cap for any asset class not listed above
    CLASS_CAP_DEFAULT: float = 0.30

    # ── Capital constraint (docs/plans/beta_book_exposure_vs_capital.md
    #    Step 7) ─────────────────────────────────────────────────────────
    # Long-only, unlevered ceiling on deployed capital: sum(|notional|) <=
    # CAPITAL_UTILISATION_MAX * total_capital. The 5% buffer below 1.0
    # accounts for settlement timing, coupon reinvestment lag, and the
    # practical impossibility of ever hitting exactly 100% deployment.
    # Before this step, the book was always fully invested (weights summed
    # to exactly 1.0 every day) regardless of how bearish the signal was —
    # this is what lets a bearish day genuinely de-risk instead of only
    # rotating exposure between assets.
    CAPITAL_UTILISATION_MAX: float = 0.95

    # ── Sleeve DV01 target (factor_scaling mode only) ───────────────────────
    # Same convention as the Portfolio tab's "max_duration" input
    # (web/tabs/beta/callbacks/portfolio_run/_run_analysis.py): book DV01 <=
    # MAX_DV01_PER_CAPITAL * total_capital / 1e10, i.e. a 10BN book's DV01
    # may reach 5 * 1e10/1e10 = 5 MM CNY per bp. signed_sleeve_weights_daily
    # produces weights that are DV01-equalised PER FACTOR UNIT (sum to the
    # factor's own budget share), not sized to any capital/risk target —
    # orchestrator.py scales the whole day's sleeve notional up toward this
    # DV01 budget (capped separately by CAPITAL_UTILISATION_MAX gross), since
    # otherwise the book sits at ~10% utilisation regardless of what capital
    # or risk the user actually wants deployed. Measured: for this pool's
    # sleeve construction (Level/Slope/Curvature spread across all 6 CN
    # tenors, never concentrated in the long end), CAPITAL_UTILISATION_MAX
    # binds on ~95%+ of days at any target above ~5 — a higher target
    # (e.g. the original 10) is unreachable without leverage this book
    # doesn't take, so it just leaves MORE days gross-capped without moving
    # the achieved DV01. 5 is the level a 95%-gross, no-leverage book can
    # actually get close to on an ordinary day.
    MAX_DV01_PER_CAPITAL: float = 5.0

    # ── Short-end carry floor (factor_scaling mode only) ────────────────────
    # IRSL/IRCV's steepener/curvature trades short one end of the curve and
    # go long the other; a net short position on the SHORT end pays away
    # carry instead of collecting it, and — being short duration — earns
    # little capital-gain P&L to compensate (measured: the signed book gave
    # up ~0.92%/yr of capital vs. a same-risk-size steady-long benchmark,
    # almost entirely from short-end days). These tenors' NET summed weight
    # (across all factors) is floored at 0 in signed_sleeve_weights_daily —
    # dropped from the trade on a day it would go net short, not re-expressed
    # via another instrument (no IRS asset exists in this codebase yet; the
    # user's intent is to eventually hedge this via a 1-5Y swap instead of a
    # cash bond). CN10Y/CN20Y/CN30Y stay fully signed.
    SHORT_END_LONG_ONLY_TENORS: tuple = ('CN1Y', 'CN2Y', 'CN5Y')

    # ── Transaction cost (docs/plans/beta_book_exposure_vs_capital.md
    #    Step 8) ─────────────────────────────────────────────────────────
    # Basis points per unit ONE-WAY turnover (round-trip = 2x), charged on
    # DAILY notional deltas now that positions can move daily (Step 4) —
    # previously 0.5bp charged only at monthly rebalance dates. Lowered
    # alongside the cadence change since a real desk re-hedging daily in
    # small increments pays materially less per adjustment than a monthly
    # rebalance moving the whole book at once.
    TX_COST_BP: float = 0.1

    # ── Portfolio construction ────────────────────────────────────────────────
    # Standard lot size for bond positions (CNY)
    LOT_SIZE_BOND_CNY: int = 10_000_000
    # Standard lot size for FX/commodity positions
    LOT_SIZE_OTHER_CNY: int = 1_000_000


# Configuration: country -> (pickle_file, pickle_key or None, list of columns or None)
# If columns is None, use all columns in the DataFrame.
CURVE_CONFIG: Dict[str, Tuple[str, Optional[str], Optional[List[str]]]] = {
    'CN': (
        'database-px.pkl',
        'CGB',
        [
            '中债国债到期收益率:1年',
            '中债国债到期收益率:2年',
            '中债国债到期收益率:5年',
            '中债国债到期收益率:10年',
            '中债国债到期收益率:20年',
            '中债国债到期收益率:30年',
        ],
    ),
    # Other countries are loaded from fxcurve_ts.pkl (handled as default)
}

# Configuration for spread curves: spread_type -> (pickle_file, pickle_key, list of columns)
SPREAD_CONFIG: Dict[str, Tuple[str, str, List[str]]] = {
    'IRS': (
        'database-px.pkl',
        'IRS',
        [
            'FR007S1Y.IR',
            'FR007S2Y.IR',
            'FR007S5Y.IR',
        ],
    ),
    'CDB': (
        'database-px.pkl',
        'CDB',
        [
            '中债国开债到期收益率:1年',
            '中债国开债到期收益率:2年',
            '中债国开债到期收益率:5年',
            '中债国开债到期收益率:10年',
            '中债国开债到期收益率:30年',
        ],
    ),
}

# Configuration for credit spread curves: universe -> (pickle_file, pickle_key,
# [(own_yield_col, matching_cgb_col, tenor_years), ...]).
# Each universe's own yield curve is subtracted from the CGB (China Govt Bond)
# yield at the matching tenor to produce the credit spread series that feeds
# CRDL/CRSL/CRCV. CGB columns always come from database-px.pkl['CGB'].
CREDIT_CONFIG: Dict[str, Tuple[str, str, List[Tuple[str, str, float]]]] = {
    'CDB': (
        'database-px.pkl',
        'CDB',
        [
            ('中债国开债到期收益率:1年', '中债国债到期收益率:1年', 1.0),
            ('中债国开债到期收益率:2年', '中债国债到期收益率:2年', 2.0),
            ('中债国开债到期收益率:5年', '中债国债到期收益率:5年', 5.0),
            ('中债国开债到期收益率:10年', '中债国债到期收益率:10年', 10.0),
            ('中债国开债到期收益率:30年', '中债国债到期收益率:30年', 30.0),
        ],
    ),
    'LGB': (
        'database-px.pkl',
        'LGB',
        [
            ('中国:地方政府债到期收益率(AAA):1年', '中债国债到期收益率:1年', 1.0),
            ('中国:地方政府债到期收益率(AAA):3年', '中债国债到期收益率:3年', 3.0),
            ('中国:地方政府债到期收益率(AAA):5年', '中债国债到期收益率:5年', 5.0),
            ('中国:地方政府债到期收益率(AAA):10年', '中债国债到期收益率:10年', 10.0),
            ('中国:地方政府债到期收益率(AAA):30年', '中债国债到期收益率:30年', 30.0),
        ],
    ),
    'MTN': (
        'database-px.pkl',
        'MTN',
        [
            ('中债中短期票据到期收益率(AAA):1年', '中债国债到期收益率:1年', 1.0),
            ('中债中短期票据到期收益率(AAA):2年', '中债国债到期收益率:2年', 2.0),
            ('中债中短期票据到期收益率(AAA):3年', '中债国债到期收益率:3年', 3.0),
            ('中债中短期票据到期收益率(AAA):4年', '中债国债到期收益率:4年', 4.0),
            ('中债中短期票据到期收益率(AAA):5年', '中债国债到期收益率:5年', 5.0),
        ],
    ),
    # 'NCD': factor-code universe name for CD (Negotiable Certificate of
    # Deposit / interbank NCD) yields. Renamed from the legacy 'ICP' code —
    # the pickle sub-key below stays 'ICP' (that's database-px.pkl's own
    # internal key, not renamed as part of this — see multiasset.config
    # module scope note).
    'NCD': (
        'database-px.pkl',
        'ICP',
        [
            ('中债商业银行同业存单到期收益率(AAA):3个月', '中债国债到期收益率:3个月', 0.25),
            ('中债商业银行同业存单到期收益率(AAA):6个月', '中债国债到期收益率:6个月', 0.5),
            ('中债商业银行同业存单到期收益率(AAA):9个月', '中债国债到期收益率:9个月', 0.75),
            ('中债商业银行同业存单到期收益率(AAA):1年', '中债国债到期收益率:1年', 1.0),
        ],
    ),
}

# Universes that get Level + Slope only (too few tenors for a butterfly curvature read).
CREDIT_NO_CURVATURE = {'NCD'}


def get_credit_weights(tenor_years: List[float], include_curvature: bool = True) -> Dict[str, np.ndarray]:
    """Derive Level/Slope/(Curvature) weights for a credit spread curve.

    Weights are computed in log-tenor space (a 1Y->2Y gap counts the same as
    a 10Y->20Y gap), which is the standard fixed-income convention for slope
    and butterfly curvature and generalizes cleanly to the uneven tenor grids
    used by CDB/LGB/MTN/ICP (unlike IR's hand-picked, evenly-indexed weights).

    Args:
        tenor_years: Tenor points in years, e.g. [1, 2, 5, 10, 30].
        include_curvature: Whether to also compute a Curvature weight vector.

    Returns:
        Dict with 'Level', 'Slope', and optionally 'Curvature' weight arrays
        (each sums to 1 for Level, 0 for Slope/Curvature).
    """
    tenors = np.asarray(tenor_years, dtype=float)
    n = len(tenors)
    log_t = np.log(tenors)

    weights = {'Level': np.full(n, 1.0 / n)}

    span = log_t.max() - log_t.min()
    if span > 0:
        pos = 2 * (log_t - log_t.min()) / span - 1
        pos = pos - pos.mean()
        weights['Slope'] = pos / np.sum(np.abs(pos)) * 2.0
    else:
        weights['Slope'] = np.zeros(n)

    if include_curvature and n >= 3:
        center = (log_t.max() + log_t.min()) / 2
        dist = np.abs(log_t - center)
        belly_idx = int(np.argmin(dist))
        weight_mag = 1.0 / (1.0 + dist)
        sign = np.where(np.arange(n) == belly_idx, -1.0, 1.0)
        curv = sign * weight_mag
        curv = curv - curv.mean()
        if np.sum(np.abs(curv)) > 0:
            curv = curv / np.sum(np.abs(curv))
        weights['Curvature'] = curv

    return weights


# Wind data retrieval configuration (used by retrieve.py)
tenorlist = ["1Y", "2Y", "5Y", "10Y", "30Y"]
countrylist = ["US", "JP", "DE", "UK"]

wdstring = "G0000886,G0000887,G0000889,G0000891,G0000893,\
G1235655,G1235656,G1235659,G1235664,G1235668,\
V8579294,K3585162,A6910824,A5540027,A1410477,\
G1306752,G4161196,G0006352,G0006353,G1306755"
wdlist = wdstring.split(",")

ticker_dict = {}
i = 0
for c in countrylist:
    ticker_dict[c] = []
    for t in tenorlist:
        ticker_dict[c].append(wdlist[i])
        i += 1


__all__ = [
    'RiskModelConfig', 'CURVE_CONFIG', 'SPREAD_CONFIG',
    'CREDIT_CONFIG', 'CREDIT_NO_CURVATURE', 'get_credit_weights',
    'ticker_dict', 'tenorlist',
]

