# -*- coding: utf-8 -*-
"""Risk tab: the beta book is long-short, so totals must not net and directions must not be hard-coded BUY."""

import pytest

from web.tabs.risk.helpers import beta_direction, beta_long_short_totals
from web.tabs.risk.charts import build_inventory_summary


def test_direction_follows_the_sign_of_capital():
    assert beta_direction('-470.00') == 'SELL'
    assert beta_direction('2,860.00') == 'BUY'
    assert beta_direction(-1.0) == 'SELL' and beta_direction(0) == 'BUY'
    assert beta_direction('') == 'BUY' and beta_direction(None) == 'BUY' and beta_direction('N/A') == 'BUY'


ROWS = [
    {'Capital (MM CNY)': '2,860.00', 'Volume (MM)': '2800', 'MtM (MM CNY)': '+0.1500'},
    {'Capital (MM CNY)': '1,730.00', 'Volume (MM)': '1700', 'MtM (MM CNY)': '+0.0500'},
    {'Capital (MM CNY)': '-470.00', 'Volume (MM)': '450', 'MtM (MM CNY)': '-0.0200'},
    {'Capital (MM CNY)': '-40.00', 'Volume (MM)': '', 'MtM (MM CNY)': ''},
]


def test_totals_report_long_and_short_separately_without_netting():
    long_row, short_row = beta_long_short_totals(ROWS)
    assert long_row['Asset Name'].startswith('LONG') and short_row['Asset Name'].startswith('SHORT')
    assert long_row['Capital (MM CNY)'] == '4,590.00'            # 2860 + 1730, NOT 4080 (net of the shorts)
    assert short_row['Capital (MM CNY)'] == '510.00'             # 470 + 40, shown as a size
    assert long_row['Volume (MM)'] == '4,500.0' and short_row['Volume (MM)'] == '450.0'
    assert long_row['MtM (MM CNY)'] == '+0.1800'                 # P&L is additive: all rows
    assert 'MtM (MM CNY)' not in short_row


def test_all_long_book_has_a_single_total_row():
    rows = [r for r in ROWS if not r['Capital (MM CNY)'].startswith('-')]
    out = beta_long_short_totals(rows)
    assert len(out) == 1 and out[0]['Capital (MM CNY)'] == '4,590.00'
    assert beta_long_short_totals([]) == [{'Asset Name': 'LONG · capital used'}]


def test_sector_inventory_keeps_long_and_short_apart():
    beta = [{'Name': 'CN1Y', 'Sector': 'Rates', 'Capital (MM)': '2,860.00'},
            {'Name': 'CN10Y', 'Sector': 'Rates', 'Capital (MM)': '-470.00'},
            {'Name': 'Gold', 'Sector': 'Commodities', 'Capital (MM)': '100.00'}]
    div = build_inventory_summary(beta, [])
    text = str(div)
    assert '+2,860 / -470' in text            # Rates: long and short side by side, not +2,390
    assert '+2,390' not in text


def test_beta_mtm_falls_when_rates_rise_for_a_long_and_gains_for_a_short():
    from web.tabs.risk.helpers import beta_mtm_mm
    # 1000 MM, duration 5, open yield 2.00% -> close 2.10% (rates UP 10bp)
    long_mtm = beta_mtm_mm(1000, 5, 2.00, 2.10, '2,860.00')
    short_mtm = beta_mtm_mm(1000, 5, 2.00, 2.10, '-470.00')
    assert long_mtm < 0 < short_mtm                                   # long loses, short gains
    # 1000 MM x duration 5 -> DV01 0.5 MM/bp; 10bp -> 5.0 MM
    assert long_mtm == pytest.approx(-5.0) and short_mtm == pytest.approx(5.0)
    # rates DOWN: long gains
    assert beta_mtm_mm(1000, 5, 2.00, 1.90, '100') == pytest.approx(5.0)
    # missing inputs -> None, never a fabricated number
    assert beta_mtm_mm(None, 5, 2.0, 2.1, '1') is None and beta_mtm_mm(1000, 5, 0, 2.1, '1') is None


def test_gross_position_chart_keeps_long_and_short_apart():
    from web.tabs.risk.charts import build_gross_position_fig
    fig = build_gross_position_fig({
        'CN10Y': {'Long': 0.0, 'Short': -470.0, 'DV01Long': 0.0, 'DV01Short': -0.4},
        'CN1Y': {'Long': 2860.0, 'Short': 0.0, 'DV01Long': 0.27, 'DV01Short': 0.0},
        'T': {'Long': 300.0, 'Short': -120.0, 'DV01Long': 0.2, 'DV01Short': -0.1}})
    by_name = {t.name: dict(zip(t.y, t.x)) for t in fig.data}
    assert by_name['Long'] == {'CN10Y': 0.0, 'CN1Y': 2860.0, 'T': 300.0}
    assert by_name['Short'] == {'CN10Y': -470.0, 'CN1Y': 0.0, 'T': -120.0}      # T keeps +300 AND -120, not +180
    assert fig.layout.barmode == 'relative'
    assert build_gross_position_fig({}).layout.annotations                       # empty -> message, no crash


def test_gross_dv01_ladder_and_kpi():
    from web.tabs.risk.charts import build_dv01_ladder_gross_fig, build_kpi_cards, build_kpi_strip
    long_g = {'5Y': {'Bonds': 0.27, 'Swaps': 0.0, 'Futures': 0.0, 'Other': 0.0},
              '10Y': {'Bonds': 0.0, 'Swaps': 0.0, 'Futures': 0.2, 'Other': 0.0}}
    short_g = {'10Y': {'Bonds': -0.4, 'Swaps': 0.0, 'Futures': -0.1, 'Other': 0.0}}
    fig = build_dv01_ladder_gross_fig(long_g, short_g, ['5Y', '10Y'])
    labels = [a.text for a in fig.layout.annotations]
    assert 'gross 0.700<br>net -0.300' in labels                                  # 10Y: 0.2 long vs 0.5 short
    kpis = build_kpi_cards({'X': {'Beta': 100.0, 'Alpha': 0.0}}, {'5Y': {'Bonds': 0.27}, '10Y': {'Bonds': -0.4}},
                           ['5Y', '10Y'], {'beta': {'long': long_g, 'short': short_g}})
    assert kpis['dv01'] == pytest.approx(-0.13) and kpis['gross_dv01'] == pytest.approx(0.97)
    assert 'gross 0.97' in str(build_kpi_strip(kpis))
    assert 'gross_dv01' not in build_kpi_cards({}, {'5Y': {'Bonds': 0.1}}, ['5Y'])   # old call style unchanged
