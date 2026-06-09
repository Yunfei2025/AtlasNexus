# -*- coding: utf-8 -*-
"""
Data utilities for Multi-Asset Dashboard.

Functions for loading and processing market data.
"""
import pandas as pd
import numpy as np
import os
import pickle
from settings.paths import DIR_INPUT


def _load_fx_curve_artifact():
    file_path = os.path.join(DIR_INPUT, "fxcurve_ts.pkl")
    try:
        return pd.read_pickle(file_path)
    except Exception:
        try:
            with open(file_path, 'rb') as file:
                return pickle.load(file)
        except Exception:
            raise FileNotFoundError(f"Cannot load fxcurve_ts.pkl from {DIR_INPUT}")


def _load_macro_artifact():
    macro_path = os.path.join(DIR_INPUT, 'macro-px.pkl')
    try:
        return pd.read_pickle(macro_path)
    except Exception as exc:
        print(f"Warning: could not load macro data from {macro_path}: {exc}")
        return {
            "fx": pd.DataFrame(),
            "commodity": pd.DataFrame(),
        }


def _get_macro_frame(macro_data, key: str) -> pd.DataFrame:
    if not isinstance(macro_data, dict):
        return pd.DataFrame()
    frame = macro_data.get(key)
    if isinstance(frame, pd.DataFrame):
        return frame
    return pd.DataFrame()


def load_raw_market_data():
    """Load raw market data for PnL calculation."""
    # Load FX Curves (Foreign Yields)
    fx_curves = _load_fx_curve_artifact()
    
    # Load China Yields
    cn_data_ts = pd.read_pickle(os.path.join(DIR_INPUT, "database-px.pkl"))
    cn_data = {}
    for k in ["CDB","CGB","IRS","ICP"]:
        cn_data[k] = cn_data_ts[k]
    
    # Load Macro Data (FX and Commodities)
    macro_data = _load_macro_artifact()
    
    return fx_curves, cn_data, macro_data


def get_asset_type(asset_name):
    """Categorize asset by type."""
    if asset_name.startswith('HEDGE_'):
        return 'Hedge'
    if asset_name in ['Gold', 'Aluminium', 'Copper', 'Crude_Oil']:
        return 'Commodities'
    elif asset_name in ['USDCNY', 'EURCNY', 'JPYCNY', 'GBPCNY']:
        return 'FX'
    elif any(x in asset_name for x in ['IRS', 'CDB', 'ICP']):
        return 'Spread'
    elif any(x in asset_name for x in ['US', 'EU', 'UK', 'JP', 'CN']):
        return 'Rates'
    else:
        return 'Equities'


def get_universe(asset_name):
    """Get the universe/country for the asset."""
    if asset_name.startswith('HEDGE_'):
        return 'IRS Swap' if 'IRS' in asset_name else 'CGB Treasury'
    if 'US' in asset_name:
        return 'US Gov Bond'
    elif 'EU' in asset_name:
        return 'DE Gov Bond'
    elif 'UK' in asset_name:
        return 'UK Gov Bond'
    elif 'JP' in asset_name:
        return 'Japan Gov Bond'
    elif 'CN' in asset_name:
        return 'China Gov Bond'
    elif asset_name == 'Gold':
        return 'AU'
    elif asset_name == 'Aluminium':
        return 'AL'
    elif asset_name == 'Copper':
        return 'CU'
    elif asset_name == 'Crude_Oil':
        return 'SC'
    else:
        return 'N/A'


def get_sector(asset_name):
    """Get the sector/tenor for the asset."""
    for tenor in ['30Y', '20Y', '10Y', '5Y', '2Y', '1Y']:  # longest first to avoid partial matches
        if tenor in asset_name:
            return tenor
    return 'N/A'


def get_asset_yield_series(asset_name, market_data):
    """
    Get the yield/price time series for an asset.
    Returns: (series, duration, country, is_bond)
    """
    fx_curves, cn_data, macro_data = market_data
    
    asset_type = get_asset_type(asset_name)
    universe = get_universe(asset_name)
    sector = get_sector(asset_name)
    
    if asset_type == 'Commodities':
        ticker_map = {
            'Gold': 'AU.SHF',
            'Aluminium': 'AL.SHF',
            'Copper': 'CU.SHF',
            'Crude_Oil': 'SC.INE'
        }
        ticker = ticker_map.get(asset_name)
        commodity_data = _get_macro_frame(macro_data, "commodity")
        if ticker and ticker in commodity_data.columns:
            return commodity_data[ticker], 0, None, False
        return None, 0, None, False
        
    elif asset_type == 'Rates':
        country_map = {
            'China Gov Bond': 'CN',
            'US Gov Bond': 'US',
            'DE Gov Bond': 'EU',
            'UK Gov Bond': 'UK',
            'Japan Gov Bond': 'JP'
        }
        country = country_map.get(universe)
        if not country:
            return None, 0, None, True
            
        duration = float(sector.replace('Y', ''))
        
        if country == 'CN':
            tenor_map = {
                '1Y': '中债国债到期收益率:1年',
                '2Y': '中债国债到期收益率:2年',
                '5Y': '中债国债到期收益率:5年',
                '10Y': '中债国债到期收益率:10年',
                '20Y': '中债国债到期收益率:20年',
                '30Y': '中债国债到期收益率:30年'
            }
            col = tenor_map.get(sector)
            return cn_data["CGB"][col], duration, country, True
        else:
            key = f"{country}{sector}"
            if key in fx_curves[country].columns:
                return fx_curves[country][key], duration, country, True
            return None, duration, country, True
    
    elif asset_type == 'Spread':
        spread_type = {
            'Interest Rate Swap': 'IRS',
            'China Development Bond': 'CDB',
            'Interbank Commercial Paper': 'ICP',
            #'Local Treasury': 'LGB',
        }
        spread = spread_type.get(universe)
        if not spread:
            return None, 0, None, True
            
        duration = float(sector.replace('Y', ''))
        
        if spread_type == 'CDB':
            tenor_map = {
                '1Y': '中债国开债到期收益率:1年',
                '2Y': '中债国开债到期收益率:2年',
                '5Y': '中债国开债到期收益率:5年',
                '10Y': '中债国开债到期收益率:10年',
                '20Y': '中债国开债到期收益率:20年',
                '30Y': '中债国开债到期收益率:30年'
            }
            col = tenor_map.get(sector)
            spread_ts = cn_data["CDB"][col] - cn_data["CGB"][col]
            return spread_ts, duration, spread, True
        elif spread_type == 'IRS':
            tenor_map = {
                '1Y': 'FR007S1Y.IR',
                '2Y': 'FR007S2Y.IR',
                '5Y': 'FR007S5Y.IR',
            }
            col = tenor_map.get(sector)
            spread_ts = cn_data["IRS"][col] - cn_data["CGB"][col]
            return spread_ts, duration, spread, True
        elif spread_type == 'ICP':
            tenor_map = {
                '1Y': '中债商业银行同业存单到期收益率(AAA):1年',
            }
            col = tenor_map.get(sector)
            spread_ts = cn_data["ICP"][col] - cn_data["CGB"][col]
            return spread_ts, duration, spread, True
        else:
            key = f"{spread}{sector}"
            if key in fx_curves[spread].columns:
                return fx_curves[spread][key], duration, spread, True
            return None, duration, spread, True

    elif asset_type == 'FX':
        # FX spot rates from macro data
        fx_map = {
            'USDCNY': 'USDCNY.IB',
            'EURCNY': 'EURCNY.IB',
            'JPYCNY': 'JPYCNY.IB',
            'GBPCNY': 'GBPCNY.IB'
        }
        fx_ticker = fx_map.get(asset_name)
        if fx_ticker:
            fx_data = _get_macro_frame(market_data[2], "fx")
            if fx_ticker in fx_data.columns:
                return fx_data[fx_ticker], 0, None, False  # FX is not a bond, duration=0
        return None, 0, None, False

    return None, 0, None, False


def get_fx_series(country, market_data):
    """Get FX series for a country."""
    _, _, macro_data = market_data
    fx_data = _get_macro_frame(macro_data, "fx")
    fx_map = {
        'US': 'USDCNY.IB',
        'EU': 'EURCNY.IB',
        'UK': 'GBPCNY.IB',
        'JP': 'JPYCNY.IB'
    }
    fx_ticker = fx_map.get(country)
    if fx_ticker and fx_ticker in fx_data.columns:
        return fx_data[fx_ticker]
    return None


def calculate_daily_returns_series(asset_name, market_data, start_date, end_date):
    """
    Calculate daily return series for an asset.
    Returns DataFrame with columns: ['Date', 'carry', 'capital', 'fx', 'total']
    
    For bonds:
    - Carry = daily yield / 365 (actual daily accrual)
    - Capital = -Duration * daily yield change
    - FX = daily FX return (for foreign bonds)
    
    For commodities:
    - total = daily price return
    """
    series, duration, country, is_bond = get_asset_yield_series(asset_name, market_data)
    
    if series is None:
        return pd.DataFrame()
    
    # Ensure index is DatetimeIndex for proper date comparisons
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)
    
    # Ensure start_date and end_date are Timestamps
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    
    # Filter to date range
    mask = (series.index >= start_ts) & (series.index <= end_ts)
    series = series.loc[mask].dropna()
    
    if series.empty or len(series) < 2:
        return pd.DataFrame()
    
    result = pd.DataFrame(index=series.index)
    result['Date'] = result.index

    asset_type = get_asset_type(asset_name)

    if is_bond:
        # Bond returns: carry + yield-change capital gain
        # (No roll-down: we track key tenor yields, not aging bonds)

        # Carry: daily coupon accrual based on key tenor yield
        result['carry'] = series / 100.0 / 365

        # Capital gain from yield changes: -ModifiedDuration * ΔYield
        # Using proper modified duration (not tenor), which adjusts with yield level
        n = duration
        y = (series / 100.0).clip(lower=0.001)  # avoid division by zero
        modified_duration = (1 - (1 + y) ** (-n)) / (y * (1 + y))
        yield_change = series.diff() / 100.0  # Convert from % to decimal
        result['capital'] = -modified_duration * yield_change

        # FX return (for foreign bonds)
        if country and country != 'CN':
            fx_series = get_fx_series(country, market_data)
            if fx_series is not None:
                # Ensure index is DatetimeIndex
                if not isinstance(fx_series.index, pd.DatetimeIndex):
                    fx_series.index = pd.to_datetime(fx_series.index)
                
                # Filter FX series by date range (create new mask for fx_series index)
                fx_mask = (fx_series.index >= start_ts) & (fx_series.index <= end_ts)
                fx_filtered = fx_series.loc[fx_mask].dropna()
                fx_ret = fx_filtered.pct_change()
                # Align with result index
                result['fx'] = fx_ret.reindex(result.index).fillna(0)
            else:
                result['fx'] = 0.0
        else:
            result['fx'] = 0.0

        # Total return (local + FX)
        # R_total = carry + capital + fx
        result['total'] = result['carry'] + result['capital'] + result['fx']

    elif asset_type == 'FX':
        # FX returns - simple price return (percentage change of spot rate)
        result['carry'] = 0.0
        result['capital'] = 0.0
        result['fx'] = 0.0
        result['total'] = series.pct_change()

    else:
        # Commodity returns - simple price return
        result['carry'] = 0.0
        result['capital'] = 0.0
        result['fx'] = 0.0
        result['total'] = series.pct_change()
    
    # Drop first row (NaN from diff/pct_change)
    result = result.iloc[1:]
    
    return result.reset_index(drop=True)


def calculate_asset_monthly_return(asset_name, start_date, end_date, market_data):
    """
    Calculate monthly return components for an asset.
    Returns: (total_return, carry_return, price_return, fx_return)
    """
    fx_curves, cn_data, macro_data = market_data
    
    # 1. Determine Asset Type and Parameters
    asset_type = get_asset_type(asset_name)
    universe = get_universe(asset_name)
    sector = get_sector(asset_name)  # Tenor for bonds
    
    if asset_type == 'Commodities':
        # Commodity Logic
        ticker_map = {
            'Gold': 'AU.SHF',
            'Aluminium': 'AL.SHF',
            'Copper': 'CU.SHF',
            'Crude_Oil': 'SC.INE'
        }
        ticker = ticker_map.get(asset_name)
        if not ticker:
            return 0.0, 0.0, 0.0, 0.0
            
        commodity_data = _get_macro_frame(macro_data, "commodity")
        if ticker not in commodity_data.columns:
            return 0.0, 0.0, 0.0, 0.0

        price_series = commodity_data[ticker]
        
        # Get prices
        try:
            p_start = price_series.asof(start_date)
            p_end = price_series.asof(end_date)
            
            if pd.isna(p_start) or pd.isna(p_end):
                return 0.0, 0.0, 0.0, 0.0
                
            total_ret = (p_end - p_start) / p_start
            return total_ret, 0.0, total_ret, 0.0
            
        except Exception:
            return 0.0, 0.0, 0.0, 0.0
            
    elif asset_type == 'Rates':
        # Bond Logic
        # Map universe to country code
        country_map = {
            'China Gov Bond': 'CN',
            'US Gov Bond': 'US',
            'DE Gov Bond': 'EU',  # Using EU for DE
            'UK Gov Bond': 'UK',
            'Japan Gov Bond': 'JP'
        }
        country = country_map.get(universe)
        if not country:
            return 0.0, 0.0, 0.0, 0.0
            
        # Get Yield Data
        try:
            if country == 'CN':
                # Map tenor to column name
                tenor_map = {
                    '1Y': '中债国债到期收益率:1年',
                    '2Y': '中债国债到期收益率:2年',
                    '5Y': '中债国债到期收益率:5年',
                    '10Y': '中债国债到期收益率:10年',
                    '20Y': '中债国债到期收益率:20年',
                    '30Y': '中债国债到期收益率:30年'
                }
                col = tenor_map.get(sector)
                if not col or col not in cn_data.columns:
                    # Fallback or skip
                    if sector == '2Y': col = '中债国债到期收益率:1年'  # Approx
                    elif sector == '20Y': col = '中债国债到期收益率:10年'  # Approx
                    elif sector == '30Y': col = '中债国债到期收益率:10年'  # Approx
                    else: return 0.0, 0.0, 0.0, 0.0
                
                yield_series = cn_data[col]
            else:
                # Foreign curves
                key = f"{country}{sector}"
                if key not in fx_curves[country].columns:
                    return 0.0, 0.0, 0.0, 0.0
                yield_series = fx_curves[country][key]
            
            # Get Yields (in %)
            y_start = yield_series.asof(start_date)
            y_end = yield_series.asof(end_date)
            
            if pd.isna(y_start) or pd.isna(y_end):
                return 0.0, 0.0, 0.0, 0.0
            
            # Duration Approximation
            duration = float(sector.replace('Y', ''))
            
            # 1. Carry Return (Coupon Income)
            # Approx: Yield * Time Fraction
            # Time fraction = 1/12 for monthly
            carry_ret = (y_start / 100.0) * (1/12)
            
            # 2. Capital Gain (Price Change due to Yield Change)
            # Approx: -Duration * Delta Yield
            capital_ret = -duration * (y_end - y_start) / 100.0
            
            # 3. FX Return (for foreign bonds)
            fx_ret = 0.0
            if country != 'CN':
                fx_map = {
                    'US': 'USDCNY.IB',
                    'EU': 'EURCNY.IB',
                    'UK': 'GBPCNY.IB',
                    'JP': 'JPYCNY.IB'
                }
                fx_ticker = fx_map.get(country)
                fx_data = _get_macro_frame(macro_data, "fx")
                if fx_ticker and fx_ticker in fx_data.columns:
                    fx_series = fx_data[fx_ticker]
                    fx_start = fx_series.asof(start_date)
                    fx_end = fx_series.asof(end_date)
                    if not pd.isna(fx_start) and not pd.isna(fx_end):
                        fx_ret = (fx_end - fx_start) / fx_start
            
            # Total Return (Approx)
            # R_total = (1 + R_local) * (1 + R_fx) - 1
            # R_local = Carry + Capital
            r_local = carry_ret + capital_ret
            total_ret = (1 + r_local) * (1 + fx_ret) - 1
            
            return total_ret, carry_ret, capital_ret, fx_ret
            
        except Exception as e:
            # print(f"Error calc return for {asset_name}: {e}")
            return 0.0, 0.0, 0.0, 0.0
            
    return 0.0, 0.0, 0.0, 0.0
