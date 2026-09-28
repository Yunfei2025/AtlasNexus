# -*- coding: utf-8 -*-
"""Regression tests for Beta Book capital mapping."""

from __future__ import annotations

import pandas as pd

from web.tabs.risk.books.beta_table import _normalize_beta_capital_columns


def test_beta_capital_mm_is_rebuilt_from_cny_snapshot_values():
    df = pd.DataFrame([
        {'Asset Type': 'Rates', 'Capital (CNY)': '4,070,000,000.00'},
        {'Asset Type': 'FX', 'Capital (CNY)': '1,230,000,000.00'},
        {'Asset Type': 'TOTAL', 'Capital (Million CNY)': '123.45'},
    ])

    out = _normalize_beta_capital_columns(df)

    assert out.loc[0, 'Capital (MM CNY)'] == '4,070.00'
    assert out.loc[1, 'Capital (MM CNY)'] == '1,230.00'
    assert out.loc[2, 'Capital (MM CNY)'] == '123.45'


def test_beta_capital_mm_uses_existing_million_cny_when_present():
    df = pd.DataFrame([
        {'Asset Type': 'Rates', 'Capital (MM CNY)': '', 'Capital (CNY)': '2,500,000,000.00'},
        {'Asset Type': 'FX', 'Capital (MM CNY)': '10.50'},
    ])

    out = _normalize_beta_capital_columns(df)

    assert out.loc[0, 'Capital (MM CNY)'] == '2,500.00'
    assert out.loc[1, 'Capital (MM CNY)'] == '10.50'
