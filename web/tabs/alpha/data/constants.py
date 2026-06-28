# -*- coding: utf-8 -*-
"""Theme tokens and spread-type/category definitions for the Alpha Book."""

from __future__ import annotations

import re

import pandas as pd

# ---------------------------------------------------------------------------
# Theme / Style constants — mirrors web/assets/colors.css design tokens.
# Alpha Book accent is amber (--accent-amber), not blue.
# ---------------------------------------------------------------------------
THEME = {
    'bg_main': '#0e1d3a',     # --navy-800 / --surface-sunken-ish working bg
    'bg_card': '#122a4c',     # --navy-700 / --surface-panel
    'bg_raised': '#102544',   # --navy-750 / --surface-raised
    'bg_input': '#17345c',    # --navy-600 / --surface-input
    'text_main': '#e9eef8',   # --text-primary
    'text_sub': '#a4b6d2',    # --text-secondary
    'border': '#2a517f',      # --border-strong
    'border_sub': '#1e3a5f',  # --border-default
    'accent': '#e0a23c',      # --accent-amber (Alpha Book accent)
    'blue': '#3d8bd4',        # --accent-blue (Run/Refresh actions)
    'cyan': '#45b6e6',        # --accent-cyan
    'purple': '#7c70d6',      # --accent-purple (checkbox/radio/slider accent)
    'success': '#2f9d6b',     # --accent-green
    'warning': '#e0a23c',     # --accent-amber
    'danger': '#d56b6b',      # --negative
    'table_header': '#17345c',
    'table_row_even': '#122a4c',
    'table_row_odd': '#0e1d3a',
}

# ---------------------------------------------------------------------------
# Spread type definitions
# ---------------------------------------------------------------------------
SPREAD_CATEGORIES = {
    'Bond-Curve': {
        'label': 'Bond vs Model Curve',
        'types': ['TBondCurve', 'CBondCurve'],
        'description': 'Treasury/Policybank bond yield vs fitted curve',
        'style': 'MeanReversion',
    },
    'Bond-Swap': {
        'label': 'Bond vs Swap',
        'types': ['TBondSwap', 'CBondSwap'],
        'description': 'Bond yield vs interpolated swap rate',
        'style': 'Mixed',
    },
    'Swap-Spread': {
        'label': 'Swap Spreads',
        'types': ['SwapSpread'],
        'description': 'IRS spread trades (box, basis)',
        'style': 'Mixed',
    },
    'Tenor-Spread': {
        'label': 'Curve & Cross-Asset Spreads',
        'types': ['TenorSpread'],
        'description': 'Curve slope, cross-curve, and bond/CD-vs-repo spreads (e.g. 5s10s, CDBCGB, LGBCGB, CGBRepo7d)',
        'style': 'Mixed',
    },
    'Bond-Futures': {
        'label': 'Bond vs Futures (IRR − Repo)',
        'types': ['NetBasis'],
        'description': 'CTD implied repo (IRR) minus FR007 funding cost',
        'style': 'Carry',
    },
    'Futures-Term': {
        'label': 'Futures Term Basis',
        'types': ['TermBasis'],
        'description': 'Near vs far futures contract spread',
        'style': 'MeanReversion',
    },
    'Futures-Swap': {
        'label': 'Futures vs Swap (FYTM − IRS)',
        'types': ['FuturesSwap'],
        'description': 'Futures implied YTM minus matched-tenor FR007 IRS rate',
        'style': 'Mixed',
    },
    'PCA-Spread': {
        'label': 'Multi-Asset PCA',
        'types': ['PCASpread'],
        'description': 'Cross-asset relative value from PCA',
        'style': 'MeanReversion',
    },
    'Binary-Spread': {
        'label': 'Binary Regression',
        'types': ['BinarySpread'],
        'description': 'Pairwise bond spread regression',
        'style': 'MeanReversion',
    },
}

# Flatten for dropdown
SPREAD_TYPE_OPTIONS = []
for _cat, _info in SPREAD_CATEGORIES.items():
    for _stype in _info['types']:
        SPREAD_TYPE_OPTIONS.append({
            'label': f"{_info['label']} ({_stype})",
            'value': _stype,
            'category': _cat,
        })

# Default z-score thresholds
ZSCORE_ENTRY_THRESHOLD = 2.0
ZSCORE_EXIT_THRESHOLD = 0.5
MAX_CORRELATION_THRESHOLD = 0.6

# Instrument selector prefix for non-spread (macro) series
MACRO_PREFIX = "MACRO|"
_SWAP_SPREAD_BUTTERFLY_PATTERN = re.compile(r"^(?:Repo7d|Shi3M)-(?:\d+[my]){3,}$", re.IGNORECASE)

# Global state for diversified trade recommendations
DIVERSIFIED_TRADE_RECOMMENDATIONS = {
    'trades': [],
    'timestamp': None,
}


def _exclude_swapspread_butterflies(labels: pd.Index | pd.Series):
    """Return mask that excludes IRS butterfly IDs such as Repo7d-1y2y5y or Shi3M-3m6m9m."""
    text = labels.astype(str)
    return ~text.str.match(_SWAP_SPREAD_BUTTERFLY_PATTERN)


def _build_tenor_spread_timeseries(cnbd_data: object) -> dict[str, pd.Series]:
    """Build tenor spread time series from CNBD key-rate history."""
    if not isinstance(cnbd_data, dict) or 'CGB' not in cnbd_data or 'CDB' not in cnbd_data:
        return {}
    try:
        result = {
            'CGB-5s10s': cnbd_data['CGB']['中债国债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CGB-10s30s': cnbd_data['CGB']['中债国债到期收益率:30年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CDB-5s10s': cnbd_data['CDB']['中债国开债到期收益率:10年'] - cnbd_data['CDB']['中债国开债到期收益率:5年'],
            'CDB-10s30s': cnbd_data['CDB']['中债国开债到期收益率:30年'] - cnbd_data['CDB']['中债国开债到期收益率:10年'],
            'CDBCGB-5y': cnbd_data['CDB']['中债国开债到期收益率:5年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CDBCGB-10y': cnbd_data['CDB']['中债国开债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CDBCGB-30y': cnbd_data['CDB']['中债国开债到期收益率:30年'] - cnbd_data['CGB']['中债国债到期收益率:30年'],
        }

        # LGB (local government bond) vs CGB cross-sector spreads.
        lgb = cnbd_data.get('LGB')
        if isinstance(lgb, pd.DataFrame):
            cgb = cnbd_data['CGB']
            if '中国:地方政府债到期收益率(AAA):5年' in lgb.columns and '中债国债到期收益率:5年' in cgb.columns:
                result['LGBCGB-5y'] = lgb['中国:地方政府债到期收益率(AAA):5年'] - cgb['中债国债到期收益率:5年']
            if '中国:地方政府债到期收益率(AAA):10年' in lgb.columns and '中债国债到期收益率:10年' in cgb.columns:
                result['LGBCGB-10y'] = lgb['中国:地方政府债到期收益率(AAA):10年'] - cgb['中债国债到期收益率:10年']
            if '中国:地方政府债到期收益率(AAA):30年' in lgb.columns and '中债国债到期收益率:30年' in cgb.columns:
                result['LGBCGB-30y'] = lgb['中国:地方政府债到期收益率(AAA):30年'] - cgb['中债国债到期收益率:30年']

        # MTN (medium-term note) vs CGB cross-sector spreads.
        mtn = cnbd_data.get('MTN')
        if isinstance(mtn, pd.DataFrame):
            cgb = cnbd_data['CGB']
            if '中债中短期票据到期收益率(AAA):1年' in mtn.columns and '中债国债到期收益率:1年' in cgb.columns:
                result['MTNCGB-1y'] = mtn['中债中短期票据到期收益率(AAA):1年'] - cgb['中债国债到期收益率:1年']
            if '中债中短期票据到期收益率(AAA):3年' in mtn.columns and '中债国债到期收益率:3年' in cgb.columns:
                result['MTNCGB-3y'] = mtn['中债中短期票据到期收益率(AAA):3年'] - cgb['中债国债到期收益率:3年']
            if '中债中短期票据到期收益率(AAA):5年' in mtn.columns and '中债国债到期收益率:5年' in cgb.columns:
                result['MTNCGB-5y'] = mtn['中债中短期票据到期收益率(AAA):5年'] - cgb['中债国债到期收益率:5年']

        swap_ts = cnbd_data.get('SwapTS')
        icp = cnbd_data.get('ICP')

        if isinstance(swap_ts, pd.DataFrame):
            cgb = cnbd_data['CGB']
            if 'FR007S1Y.IR' in swap_ts.columns and '中债国债到期收益率:1年' in cgb.columns:
                result['CGBRepo7d-1y'] = cgb['中债国债到期收益率:1年'] - swap_ts['FR007S1Y.IR']
            if 'FR007S2Y.IR' in swap_ts.columns and '中债国债到期收益率:2年' in cgb.columns:
                result['CGBRepo7d-2y'] = cgb['中债国债到期收益率:2年'] - swap_ts['FR007S2Y.IR']
            if 'FR007S5Y.IR' in swap_ts.columns and '中债国债到期收益率:5年' in cgb.columns:
                result['CGBRepo7d-5y'] = cgb['中债国债到期收益率:5年'] - swap_ts['FR007S5Y.IR']
            if 'FR007S10Y.IR' in swap_ts.columns and '中债国债到期收益率:10年' in cgb.columns:
                result['CGBRepo7d-10y'] = cgb['中债国债到期收益率:10年'] - swap_ts['FR007S10Y.IR']

            if isinstance(icp, pd.DataFrame):
                if 'FR007S3M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):3个月' in icp.columns:
                    result['ICPRepo7d-3m'] = icp['中债商业银行同业存单到期收益率(AAA):3个月'] - swap_ts['FR007S3M.IR']
                if 'FR007S6M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):6个月' in icp.columns:
                    result['ICPRepo7d-6m'] = icp['中债商业银行同业存单到期收益率(AAA):6个月'] - swap_ts['FR007S6M.IR']
                if 'FR007S9M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):9个月' in icp.columns:
                    result['ICPRepo7d-9m'] = icp['中债商业银行同业存单到期收益率(AAA):9个月'] - swap_ts['FR007S9M.IR']
                if 'FR007S1Y.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):1年' in icp.columns:
                    result['ICPRepo7d-1y'] = icp['中债商业银行同业存单到期收益率(AAA):1年'] - swap_ts['FR007S1Y.IR']

        return result
    except Exception:
        return {}
