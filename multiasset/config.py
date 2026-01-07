# -*- coding: utf-8 -*-
"""
Created on Tue Nov 25 20:23:03 2025

@author: CMBC
"""

wdstring = "G0000886,G0000887,G0000889,G0000891,G0000893,\
G1235655,G1235656,G1235659,G1235664,G1235668,\
V8579294,K3585162,A6910824,A5540027,A1410477,\
G1306752,G4161196,G0006352,G0006353,G1306755"
wdlist = wdstring.split(",")

def build_ticker_dict(countrylist, tenorlist):
    """
    Build a ticker mapping dict[country] -> list of tickers per tenor.
    Expects countrylist and tenorlist to be sequences of equal grid size.
    """
    mapping = {}
    i = 0
    for c in countrylist:
        mapping[c] = []
        for _ in tenorlist:
            mapping[c].append(wdlist[i])
            i += 1
    return mapping

# Safe default: don't execute build at import-time unless the required
# variables exist in globals (prevents NameError on import).
ticker_dict = {}
try:  # only build if countrylist/tenorlist are defined by the caller
    countrylist  # type: ignore[name-defined]
    tenorlist    # type: ignore[name-defined]
except NameError:
    pass
else:
    ticker_dict = build_ticker_dict(countrylist, tenorlist)  # type: ignore[name-defined]

sensitivities = {
        '1Y': {'IRDL': 0.95, 'FXDL': 1.0},   # Short end: all level, no slope
        '2Y': {'IRDL': 1.90, 'FXDL': 1.0},   # Slight slope exposure (legacy)
        '5Y': {'IRDL': 4.50, 'FXDL': 1.0},   # Balanced
        '10Y': {'IRDL': 8.50, 'FXDL': 1.0},  # More slope
        '30Y': {'IRDL': 17.0, 'FXDL': 1.0},  # Long end: high slope
    }

class RiskModelConfig:
    """Configuration for risk/volatility modeling parameters."""
    # Lookback for factor volatility estimation (calendar months)
    FACTOR_VOL_LOOKBACK_MONTHS: int = 3
    # EWMA lambda (decay) for daily data (commonly 0.94)
    FACTOR_VOL_EWMA_LAMBDA: float = 0.94

__all__ = [
    'wdlist', 'ticker_dict', 'sensitivities', 'RiskModelConfig', 'build_ticker_dict'
]