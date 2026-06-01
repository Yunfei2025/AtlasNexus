# -*- coding: utf-8 -*-
"""Swap real-time quote frame helpers (bid/ofr/mid with fallback)."""

import re

import numpy as np
import pandas as pd


_LEGACY_REPO_PREFIX = re.compile(r'^Repo-', re.IGNORECASE)


def _normalize_legacy_repo_label(value):
    if isinstance(value, str):
        return _LEGACY_REPO_PREFIX.sub('Repo7d-', value)
    return value


def _normalize_legacy_repo_frame(swap_rt: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(swap_rt, pd.DataFrame):
        return swap_rt
    out = swap_rt.copy()
    if out.index.dtype == object:
        out.index = out.index.map(_normalize_legacy_repo_label)
    if out.columns.dtype == object:
        out.columns = out.columns.map(_normalize_legacy_repo_label)
    return out


def get_swap_quote_frame(swap_rt, tickers=None, threshold_bp=10, fallback_quotes=None):
    """Return Bid/Ofr/Mid swap quotes with guarded realtime fallbacks."""
    swap_rt = _normalize_legacy_repo_frame(swap_rt)
    cols = ['买价收益率', '卖价收益率', '成交收益率']
    if tickers is None:
        quote_frame = swap_rt.loc[:, cols].copy()
    else:
        quote_frame = swap_rt.reindex(index=tickers, columns=cols).copy()

    quote_frame = quote_frame.apply(pd.to_numeric, errors='coerce')
    bid_quotes = quote_frame['买价收益率'].copy()
    ofr_quotes = quote_frame['卖价收益率'].copy()
    traded_yield = quote_frame['成交收益率'].copy()

    mid_quotes = (bid_quotes + ofr_quotes) / 2
    quote_spread_bp = (ofr_quotes - bid_quotes).abs() * 100
    deviation_bp = (mid_quotes - traded_yield).abs() * 100
    use_trade_mask = traded_yield.notna() & (mid_quotes.isna() | (deviation_bp > threshold_bp))
    mid_quotes.loc[use_trade_mask] = traded_yield.loc[use_trade_mask]

    if fallback_quotes is not None:
        fallback_series = pd.Series(fallback_quotes).reindex(mid_quotes.index)
        unreasonable_mid = mid_quotes.isna() | ~np.isfinite(mid_quotes) | (mid_quotes < 0) | (mid_quotes > 10)
        use_fallback_mask = fallback_series.notna() & traded_yield.isna() & (unreasonable_mid | (quote_spread_bp > threshold_bp))
        mid_quotes.loc[use_fallback_mask] = fallback_series.loc[use_fallback_mask]

    invalid_bid = bid_quotes.isna() | ~np.isfinite(bid_quotes) | (bid_quotes < 0) | (bid_quotes > 10)
    invalid_ofr = ofr_quotes.isna() | ~np.isfinite(ofr_quotes) | (ofr_quotes < 0) | (ofr_quotes > 10)
    bid_quotes.loc[invalid_bid & mid_quotes.notna()] = mid_quotes.loc[invalid_bid & mid_quotes.notna()]
    ofr_quotes.loc[invalid_ofr & mid_quotes.notna()] = mid_quotes.loc[invalid_ofr & mid_quotes.notna()]

    return pd.DataFrame({
        'Bid': bid_quotes,
        'Ofr': ofr_quotes,
        'Mid': mid_quotes,
    })


def get_swap_mid_quotes(swap_rt, tickers=None, threshold_bp=10, fallback_quotes=None):
    """Return swap mid quotes with 成交收益率 and historical fallback for bad bid-offer quotes."""
    return get_swap_quote_frame(
        swap_rt,
        tickers=tickers,
        threshold_bp=threshold_bp,
        fallback_quotes=fallback_quotes,
    )['Mid']
