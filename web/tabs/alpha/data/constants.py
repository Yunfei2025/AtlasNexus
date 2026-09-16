# -*- coding: utf-8 -*-
"""Theme tokens and spread-type/category definitions for the Alpha Book."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from curves.utils.file import loadPKL
from settings.paths import DIR_INPUT

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
        'description': (
            'Curve slope, cross-curve, and bond/CD-vs-repo spreads (e.g. 5s10s, CDBCGB, '
            'LGBCGB, CGBRepo7d), plus Repo7d-1y5y, Shi3M-1y5y, Repo7d-3m1y, Basis-1y and '
            'Basis-5y carried over from SwapSpread for this core portfolio'
        ),
        'style': 'Mixed',
    },
    'Bond-Futures': {
        'label': 'Cash-and-Carry (IRR − Repo)',
        'types': ['NetBasis'],
        'description': 'CTD implied repo (IRR) minus FR007 funding cost',
        'style': 'Carry',
    },
    'Futures-Term': {
        'label': 'Calendar Spread',
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
        'label': 'Sector PCA',
        'types': ['SectorPCASpread'],
        'description': 'Cross-asset relative value from PCA',
        'style': 'MeanReversion',
    },
    'Binary-Spread': {
        'label': 'Binary Regression',
        'types': ['BinarySpread'],
        'description': 'Pairwise bond spread regression',
        'style': 'MeanReversion',
    },
    'New-Issue': {
        'label': 'New-Issue OTR/OFR Event',
        'types': ['BondNewIssue'],
        'description': (
            'OTR vs 1st off-the-run new-issue roll-pressure event, gated per '
            '(asset_class, tenor_bucket); see docs/dev/tbondcurve-30y-otr-ofr-plan.md'
        ),
        'style': 'EventDriven',
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

# Spread types whose value is a yield/rate difference (YTM-based), as opposed to a
# price difference (e.g. TermBasis = front-minus-next futures close, in price points).
# For YTM-based spreads, LONG = expecting the spread to fall/narrow (you're
# economically long the richer/higher-yielding leg's price, i.e. short its yield).
# For price-based spreads, LONG keeps the default convention: profit when the
# spread (price difference) rises/widens.
YIELD_BASED_SPREAD_TYPES = {
    'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap',
    'SwapSpread', 'TenorSpread', 'NetBasis', 'FuturesSwap',
    'SectorPCASpread', 'BinarySpread', 'BondNewIssue',
}

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
    """No-op mask (kept for callers' shape) -- IRS butterfly IDs such as
    Repo7d-1y2y5y or Shi3M-3m6m9m used to be filtered out here because the
    leg-resolution machinery only supported 2 legs. resolve_legs3() /
    fly_leg_dv01_ratios() (web/tabs/alpha/data/legs.py, 2026-09-10) now
    resolve all 3 legs with a DV01-neutral belly/wings sign convention, so
    these IDs are no longer excluded from scanning/scoring.
    """
    if isinstance(labels, pd.Series):
        return pd.Series(True, index=labels.index, dtype=bool)
    return np.ones(len(labels), dtype=bool)


def _build_tenor_spread_timeseries(cnbd_data: object) -> dict[str, pd.Series]:
    """Build tenor spread time series from CNBD key-rate history."""
    if not isinstance(cnbd_data, dict) or 'CGB' not in cnbd_data or 'CDB' not in cnbd_data:
        return {}
    try:
        result = {
            'CGB-1s2s': cnbd_data['CGB']['中债国债到期收益率:2年'] - cnbd_data['CGB']['中债国债到期收益率:1年'],
            'CGB-2s5s': cnbd_data['CGB']['中债国债到期收益率:5年'] - cnbd_data['CGB']['中债国债到期收益率:2年'],
            'CGB-5s10s': cnbd_data['CGB']['中债国债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CGB-10s20s': cnbd_data['CGB']['中债国债到期收益率:20年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CGB-10s30s': cnbd_data['CGB']['中债国债到期收益率:30年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CDB-1s2s': cnbd_data['CDB']['中债国开债到期收益率:2年'] - cnbd_data['CDB']['中债国开债到期收益率:1年'],
            'CDB-2s5s': cnbd_data['CDB']['中债国开债到期收益率:5年'] - cnbd_data['CDB']['中债国开债到期收益率:2年'],
            'CDB-5s10s': cnbd_data['CDB']['中债国开债到期收益率:10年'] - cnbd_data['CDB']['中债国开债到期收益率:5年'],
            # No CDB-10s30s / CDBCGB-30y — no tradeable CDB 30y bond exists,
            # even though the CNBD curve carries a yield at that tenor.
            'CDBCGB-5y': cnbd_data['CDB']['中债国开债到期收益率:5年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CDBCGB-10y': cnbd_data['CDB']['中债国开债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            # Curve flies (butterflies): equal-weighted -1/+2/-1 on short/belly/long
            # wings. CDB capped at 10y — no tradeable CDB 20y/30y bond.
            'CGB-1s2s5s': -cnbd_data['CGB']['中债国债到期收益率:1年'] + 2*cnbd_data['CGB']['中债国债到期收益率:2年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CGB-2s5s10s': -cnbd_data['CGB']['中债国债到期收益率:2年'] + 2*cnbd_data['CGB']['中债国债到期收益率:5年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CGB-5s7s10s': -cnbd_data['CGB']['中债国债到期收益率:5年'] + 2*cnbd_data['CGB']['中债国债到期收益率:7年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CGB-5s10s20s': -cnbd_data['CGB']['中债国债到期收益率:5年'] + 2*cnbd_data['CGB']['中债国债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:20年'],
            'CGB-10s20s30s': -cnbd_data['CGB']['中债国债到期收益率:10年'] + 2*cnbd_data['CGB']['中债国债到期收益率:20年'] - cnbd_data['CGB']['中债国债到期收益率:30年'],
            'CDB-1s2s5s': -cnbd_data['CDB']['中债国开债到期收益率:1年'] + 2*cnbd_data['CDB']['中债国开债到期收益率:2年'] - cnbd_data['CDB']['中债国开债到期收益率:5年'],
            'CDB-2s5s10s': -cnbd_data['CDB']['中债国开债到期收益率:2年'] + 2*cnbd_data['CDB']['中债国开债到期收益率:5年'] - cnbd_data['CDB']['中债国开债到期收益率:10年'],
            'CDB-5s7s10s': -cnbd_data['CDB']['中债国开债到期收益率:5年'] + 2*cnbd_data['CDB']['中债国开债到期收益率:7年'] - cnbd_data['CDB']['中债国开债到期收益率:10年'],
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

            if isinstance(icp, pd.DataFrame):
                if 'FR007S3M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):3个月' in icp.columns:
                    result['NCDRepo7d-3m'] = icp['中债商业银行同业存单到期收益率(AAA):3个月'] - swap_ts['FR007S3M.IR']
                if 'FR007S6M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):6个月' in icp.columns:
                    result['NCDRepo7d-6m'] = icp['中债商业银行同业存单到期收益率(AAA):6个月'] - swap_ts['FR007S6M.IR']
                if 'FR007S9M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):9个月' in icp.columns:
                    result['NCDRepo7d-9m'] = icp['中债商业银行同业存单到期收益率(AAA):9个月'] - swap_ts['FR007S9M.IR']
                if 'FR007S1Y.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):1年' in icp.columns:
                    result['NCDRepo7d-1y'] = icp['中债商业银行同业存单到期收益率(AAA):1年'] - swap_ts['FR007S1Y.IR']

        for _key in _CGB_30Y_DEPENDENT_INSTRUMENTS:
            if _key in result and isinstance(result[_key], pd.Series):
                result[_key] = _truncate_cgb_30y_series(result[_key])

        # IRS-curve-slope instruments the user wants included in this "core
        # portfolio" category even though they are also computed under
        # SwapSpread (curves.calibration.irs.spreads.irsSpreads) — a
        # deliberate duplication, not a bug: TenorSpread and SwapSpread serve
        # different books and each should be independently backtestable/
        # scannable with this instrument in it. Mirrors the same block in
        # curves/generators/stat.py's EOD Tenor-spds.pkl generator (kept in
        # sync so the live snapshot / Individual Spread tab / Default
        # portfolio see the same instruments as the historical pickle).
        # Sourced from IRS-pxspds.pkl (SHI3M curve data isn't in
        # loadCNBDTS's cnbd_data, so these can't be rebuilt from the
        # CGB/CDB/SwapTS series above). Kept under their native
        # Repo7d-/Shi3M-/Basis- names, not renamed to this category's
        # "NsMs" convention, for consistency with SwapSpread.
        _irs_extra_cols = ['Repo7d-1y5y', 'Shi3M-1y5y', 'Repo7d-3m1y', 'Basis-1y', 'Basis-5y']
        try:
            _irs_pxspds = loadPKL(str(DIR_INPUT / 'IRS-pxspds.pkl'))
        except Exception:
            _irs_pxspds = None
        if isinstance(_irs_pxspds, dict):
            _irs_spread = _irs_pxspds.get('Spread')
            if isinstance(_irs_spread, pd.DataFrame):
                for _col in _irs_extra_cols:
                    if _col in _irs_spread.columns:
                        result[_col] = pd.to_numeric(_irs_spread[_col], errors='coerce')

        return result
    except Exception:
        return {}


# CGB-30y was thinly traded before ~2021-07: the raw CNBD 30y yield node
# repeatedly prints an isolated single-day jump (3-4x the same day's 10y/20y
# move, e.g. +15bp on 2018-08-17 vs +3-4bp on the other two legs) that
# partially reverts over the following days -- a stale/thin-liquidity data
# artifact, not a real curve move (confirmed by comparing all three legs:
# genuine curve events like the Feb-Mar 2020 rally move all three legs
# together). Any spread/fly built off this node inherits the artifact
# amplified by its coefficient, so every series that uses it is truncated to
# start once 30y liquidity normalized -- applied both when rebuilding from
# raw CNBD data (this module) and when reading the pre-built snapshot pickle
# (see loaders.load_spread_timeseries), since the pickle path is what's
# actually used day to day and bypasses this function entirely.
CGB_30Y_TRUNCATE_START = pd.Timestamp('2021-07-01')
_CGB_30Y_DEPENDENT_INSTRUMENTS = ('CGB-10s30s', 'CGB-10s20s30s', 'LGBCGB-30y')


def _truncate_cgb_30y_series(s: pd.Series) -> pd.Series:
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx, errors='coerce')
    return s.loc[idx >= CGB_30Y_TRUNCATE_START]
