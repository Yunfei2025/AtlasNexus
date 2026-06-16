# -*- coding: utf-8 -*-
"""
Configuration for multi-asset portfolio risk models.

@author: CMBC
"""
from typing import Dict, List, Optional, Tuple


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
    FLOOR_RATIO_BOND: float = 0.30   # bond floor = 30% of equal share
    FLOOR_RATIO_COMM: float = 0.20   # commodity/FX floor = 20% of equal share
    FLOOR_RATIO_FX:   float = 0.20
    CAP_RATIO_BOND:   float = 3.0    # bond cap = 3× equal share
    CAP_RATIO_COMM:   float = 2.0    # commodity cap = 2× equal share
    CAP_RATIO_FX:     float = 2.0

    # Hard absolute limits (override ratios when pool is very small/large)
    ABS_FLOOR_BOND: float = 0.01
    ABS_FLOOR_COMM: float = 0.02
    ABS_FLOOR_FX:   float = 0.02
    ABS_CAP_BOND:   float = 0.40
    ABS_CAP_COMM:   float = 0.30
    ABS_CAP_FX:     float = 0.30

    @classmethod
    def scaled_bounds(cls, n_assets: int) -> dict:
        """Return floor/cap per asset class scaled to pool size."""
        eq = 1.0 / max(n_assets, 1)
        return {
            'floor_bond': max(cls.ABS_FLOOR_BOND, eq * cls.FLOOR_RATIO_BOND),
            'floor_comm': max(cls.ABS_FLOOR_COMM, eq * cls.FLOOR_RATIO_COMM),
            'floor_fx':   max(cls.ABS_FLOOR_FX,   eq * cls.FLOOR_RATIO_FX),
            'cap_bond':   min(cls.ABS_CAP_BOND,   eq * cls.CAP_RATIO_BOND),
            'cap_comm':   min(cls.ABS_CAP_COMM,   eq * cls.CAP_RATIO_COMM),
            'cap_fx':     min(cls.ABS_CAP_FX,     eq * cls.CAP_RATIO_FX),
        }

    # Legacy flat constants kept for back-compat with any direct references
    MIN_WEIGHT_BOND: float = 0.03
    CAP_BOND: float = 0.40
    CAP_COMM: float = 0.30
    CAP_FX:   float = 0.30
    MIN_WEIGHT_COMM: float = 0.02
    MIN_WEIGHT_FX:   float = 0.02

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
    }
    # Default cap for any asset class not listed above
    CLASS_CAP_DEFAULT: float = 0.30

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


# Wind data retrieval configuration (used by retrieve.py)
tenorlist = ["1Y", "2M", "5Y", "10Y", "30Y"]
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


__all__ = ['RiskModelConfig', 'CURVE_CONFIG', 'SPREAD_CONFIG', 'ticker_dict', 'tenorlist']

