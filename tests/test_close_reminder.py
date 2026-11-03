# -*- coding: utf-8 -*-
"""Summary > Books close / rebalance reminders: the alpha close ticket and the beta rebalance plan."""

import pandas as pd
import pytest

from web.tabs.risk.books.close_reminder import alpha_close_ticket, beta_rebalance_plan, format_ticket

TODAY = pd.Timestamp('2026-11-10')


def _alpha(direction='BUY', volume='100', cap='100.0', l1='240203.IB', l2='260018.IB', l3='', r2='2.100', r3=''):
    return {'ID': 'CGB-1s2s', 'Direction': direction, 'Volume (mm)': volume, 'Capital (MM CNY)': cap,
            'Leg 1': l1, 'Leg 2': l2, 'Leg 3': l3, 'Ratio (V2/V1)': r2, 'Ratio (V3/V1)': r3}


def test_closing_a_buy_sells_leg1_and_buys_the_hedge_legs():
    tk = alpha_close_ticket(_alpha('BUY'))
    assert [(t['leg'], t['side'], t['volume_mm']) for t in tk] == [('240203.IB', 'SELL', 100.0), ('260018.IB', 'BUY', 210.0)]
    assert format_ticket(tk) == 'SELL 100.0 MM 240203.IB · BUY 210.0 MM 260018.IB'


def test_closing_a_sell_is_the_mirror_image_and_a_fly_has_three_legs():
    tk = alpha_close_ticket(_alpha('SELL', l3='260021.IB', r2='0.500', r3='0.500'))
    assert [(t['side'], t['volume_mm']) for t in tk] == [('BUY', 100.0), ('SELL', 50.0), ('SELL', 50.0)]


def test_unbooked_trade_uses_target_size_and_is_marked_indicative():
    tk = alpha_close_ticket(_alpha('SELL', volume='', cap='-80.0', r2='1.000'))
    assert [t['volume_mm'] for t in tk] == [80.0, 80.0]
    assert not any(t['booked'] for t in tk)
    assert all(t['booked'] for t in alpha_close_ticket(_alpha()))


def test_ticket_skips_legs_it_cannot_size_instead_of_guessing():
    assert alpha_close_ticket(_alpha(r2='')) == [{'leg': '240203.IB', 'side': 'SELL', 'volume_mm': 100.0, 'booked': True}]
    assert alpha_close_ticket(_alpha(direction='')) == []
    assert alpha_close_ticket(_alpha(volume='', cap='')) == []


def _beta(name, target, held, dur='4.0', opened='2026-11-03', typ='Rates'):
    return {'Asset Type': typ, 'Instrument': name, 'Capital (MM CNY)': f'{target:,.2f}', 'Duration': dur,
            'Volume (MM)': '' if held is None else str(held), 'Open Date': opened}


def test_nothing_booked_means_nothing_to_rebalance():
    p = beta_rebalance_plan([_beta('A', 500, None, opened=''), _beta('B', -200, None, opened='')], TODAY)
    assert p['status'] == 'not_booked' and p['trades'] == []


def test_on_schedule_book_inside_the_month_is_ok():
    p = beta_rebalance_plan([_beta('A', 500, 500), _beta('B', -200, 195)], TODAY)       # booked this month, tiny drift
    assert p['status'] == 'ok' and p['reasons'] == []
    assert p['trades'] == []                                                            # B is 5MM off: under the 10MM bond lot
    assert p['deltas'] == {'A': 0.0, 'B': -5.0}
    # a full lot off target is a trade even when the book is otherwise on schedule
    assert [t['name'] for t in beta_rebalance_plan([_beta('A', 500, 500), _beta('B', -200, 190)], TODAY)['trades']] == ['B']


def test_a_new_month_makes_the_rebalance_due_and_lists_trades_back_to_target():
    rows = [_beta('A', 500, 450, opened='2026-10-02'), _beta('B', -200, 200, opened='2026-10-02'),
            _beta('C', 30, 30, opened='2026-10-02')]
    p = beta_rebalance_plan(rows, TODAY)
    assert p['status'] == 'due' and p['reasons'] == ['month']
    assert p['last_booked'] == pd.Timestamp('2026-10-02')
    names = {t['name']: t['delta_mm'] for t in p['trades']}
    assert names == {'A': 50.0}                                                          # C on target; B is a magnitude held short
    assert p['deltas']['B'] == 0.0                                                       # held 200 on a short target = -200


def test_off_cycle_drift_trigger_is_dv01_weighted():
    # B (dur 10) is 60% off target; A (dur 1) on target: DV01 drift = 0.6*200*10 / (500*1 + 200*10)
    rows = [_beta('A', 500, 500, dur='1.0'), _beta('B', 200, 80, dur='10.0')]
    p = beta_rebalance_plan(rows, TODAY, drift_trigger=0.4)
    assert p['drift'] == pytest.approx(120 * 10 / (500 * 1 + 200 * 10))
    assert p['status'] == 'due' and p['reasons'] == ['drift']
    assert beta_rebalance_plan(rows, TODAY, drift_trigger=0.6)['status'] == 'ok'


def test_target_zero_closes_what_is_held_and_missing_rows_are_flagged():
    p = beta_rebalance_plan([_beta('A', 0, 120), _beta('B', 300, None, opened='')], TODAY)
    assert 'unbooked' in p['reasons'] and p['status'] == 'due'
    assert p['deltas']['A'] == -120.0
    assert {t['name'] for t in p['trades']} == {'A', 'B'}


def test_lots_differ_by_asset_class():
    rows = [_beta('FX', 5, 0.5, typ='FX', dur=''), _beta('BOND', 5, 0, typ='Rates', opened='2026-11-03'), _beta('X', 100, 100)]
    p = beta_rebalance_plan(rows, TODAY)
    assert {t['name'] for t in p['trades']} == {'FX'}                                    # 4.5 >= 1MM FX lot; 5 < 10MM bond lot


def test_total_rows_are_ignored():
    rows = [_beta('A', 100, 100), {'Asset Type': 'TOTAL', 'Capital (MM CNY)': '999', 'Volume (MM)': '1'}]
    assert beta_rebalance_plan(rows, TODAY)['deltas'] == {'A': 0.0}
