# -*- coding: utf-8 -*-
"""Portfolio-table transformation helpers shared by the Run Analysis and
Add-to-Portfolio callbacks."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from multiasset.layout import get_cgb_otr_map


def prepare_summary_table_data(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Transform portfolio table into Beta Book Summary table format.

    Converts portfolio allocation data to the format expected by the Summary tab,
    with editable fields for Open Price, Open Date, and Volume (MM).
    Preserves existing user-entered data for positions being carried over.
    """
    if portfolio_df.empty:
        return portfolio_df

    summary_df = portfolio_df.copy()

    # Load existing user-entered data to preserve it
    user_data_map: dict = {}
    from .._common import _BETA_BOOK_USER_PARQUET
    if os.path.exists(_BETA_BOOK_USER_PARQUET):
        try:
            udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
            for _, r in udf.iterrows():
                key = (str(r.get('asset_name', '')), str(r.get('instrument', '')))
                user_data_map[key] = {
                    'open_price': str(r.get('open_price', r.get('open_yld', ''))),
                    'open_date': str(r.get('open_date', '')),
                    'volume': str(r.get('volume', '')),
                }
        except Exception:
            pass

    # Ensure Capital is in MM CNY format (as string with commas)
    if 'Capital (CNY)' in summary_df.columns:
        capital_vals = []
        for val in summary_df['Capital (CNY)']:
            try:
                # Convert from string to float, then to MM
                if isinstance(val, str):
                    capital_cny = float(val.replace(',', ''))
                else:
                    capital_cny = float(val)
                capital_mm = capital_cny / 1e6
                capital_vals.append(f"{capital_mm:,.2f}")
            except (ValueError, TypeError):
                capital_vals.append(str(val))
        summary_df['Capital (MM CNY)'] = capital_vals
        summary_df = summary_df.drop(columns=['Capital (CNY)'], errors='ignore')

    # Ensure Weight (%) is formatted correctly
    if 'Weight (%)' in summary_df.columns:
        weight_vals = []
        for val in summary_df['Weight (%)']:
            val_str = str(val).replace('%', '').strip()
            try:
                weight_vals.append(f"{float(val_str):.2f}%")
            except (ValueError, TypeError):
                weight_vals.append(str(val))
        summary_df['Weight (%)'] = weight_vals

    # Add editable fields, preserving existing user-entered data
    open_prices = []
    open_dates = []
    volumes = []
    for _, row in summary_df.iterrows():
        asset_name = str(row.get('Asset Name', ''))
        instrument = str(row.get('Instrument', ''))
        key = (asset_name, instrument)
        saved = user_data_map.get(key, {})
        open_prices.append(saved.get('open_price', ''))
        open_dates.append(saved.get('open_date', ''))
        volumes.append(saved.get('volume', ''))

    summary_df['Open Price'] = open_prices
    summary_df['Open Date'] = open_dates
    summary_df['Volume (MM)'] = volumes

    # Add read-only columns - initialize as empty
    for col in ['Close Price', 'MtM (MM CNY)']:
        if col not in summary_df.columns:
            summary_df[col] = ''

    # Remove DV01 column if present (not needed in Summary tab)
    summary_df = summary_df.drop(columns=['DV01 (MM CNY)', 'Sector'], errors='ignore')

    # Add timestamp for tracking when the summary was last updated
    summary_df['_timestamp'] = datetime.now().isoformat()

    return summary_df


def merge_with_existing_positions(new_portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Update Rates bond codes to the latest on-the-run instruments.

    Only substitutes OTR bond codes for Rates assets in the new portfolio.
    Does not carry over positions from previous runs — allocation is fully
    determined by today's signals each time.
    """
    if new_portfolio_df.empty:
        return new_portfolio_df

    result_df = new_portfolio_df.copy()
    otr_map = get_cgb_otr_map()

    for idx, row in result_df.iterrows():
        if row.get('Asset Type') == 'Rates':
            sector = row.get('Sector', '')
            if sector and sector in otr_map:
                result_df.at[idx, 'Instrument'] = otr_map[sector]

    return result_df
