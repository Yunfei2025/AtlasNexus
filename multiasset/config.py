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

