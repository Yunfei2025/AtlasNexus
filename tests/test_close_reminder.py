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


def test_nothing_booked_means_no_trades_but_the_refresh_flags_still_apply():
    rows = [_beta('A', 500, None, opened=''), _beta('B', -200, None, opened='')]
    p = beta_rebalance_plan(rows, TODAY, snapshot_ts='2026-11-03 08:00:00', model_month='2026-10')
    assert p['status'] == 'not_booked' and p['trades'] == []
    assert p['targets_stale'] and p['rp_due']


def test_instruments_inside_the_zone_are_left_alone_and_a_full_lot_is_a_trade():
    p = beta_rebalance_plan([_beta('A', 500, 500), _beta('B', -200, 195)], TODAY)
    assert p['status'] == 'ok' and p['trades'] == [] and p['deltas'] == {'A': 0.0, 'B': -5.0}   # 5MM < the 10MM bond lot
    p = beta_rebalance_plan([_beta('A', 500, 500), _beta('B', -200, 190)], TODAY)
    assert p['status'] == 'due' and [t['name'] for t in p['trades']] == ['B']                    # exactly one lot


def test_zone_scales_with_capital_but_never_below_one_lot():
    rows = [_beta('A', 500, 450), _beta('B', 500, 340)]                    # 50MM and 160MM off
    p = beta_rebalance_plan(rows, TODAY, zone_pct=0.01, capital_mm=10_000.0)                   # zone 100MM
    assert p['zone_mm'] == 100.0 and [t['name'] for t in p['trades']] == ['B']
    p = beta_rebalance_plan(rows, TODAY, zone_pct=0.01, capital_mm=100.0)                      # 1MM -> floor of one lot
    assert p['zone_mm'] == 10.0 and {t['name'] for t in p['trades']} == {'A', 'B'}
    assert beta_rebalance_plan(rows, TODAY)['zone_mm'] == 10.0                                 # capital unknown -> one lot


def test_trades_carry_the_delta_back_to_target_and_shorts_use_the_targets_sign():
    rows = [_beta('A', 500, 450), _beta('B', -200, 200), _beta('C', 30, 30)]   # B: held 200 on a short target = -200
    p = beta_rebalance_plan(rows, TODAY)
    assert [(t['name'], t['delta_mm']) for t in p['trades']] == [('A', 50.0)]
    assert p['deltas']['B'] == 0.0


def test_daily_flag_targets_must_come_from_the_last_business_day():
    base = [_beta('A', 100, 100)]
    assert not beta_rebalance_plan(base, TODAY, snapshot_ts='2026-11-10 07:30:00')['targets_stale']       # today
    assert beta_rebalance_plan(base, TODAY, snapshot_ts='2026-11-09 18:00:00')['targets_stale']           # Mon run, today Tue: refresh daily
    assert beta_rebalance_plan(base, TODAY, snapshot_ts='2026-11-06 18:00:00')['targets_stale']           # Fri, today is Tue
    sat = pd.Timestamp('2026-11-14')                                                                      # Saturday
    assert not beta_rebalance_plan(base, sat, snapshot_ts='2026-11-13 20:00:00')['targets_stale']         # Friday's run is current
    assert beta_rebalance_plan(base, sat, snapshot_ts='2026-11-12 20:00:00')['targets_stale']
    assert not beta_rebalance_plan(base, TODAY, snapshot_ts=None)['targets_stale']                        # unknown -> no false alarm
    assert not beta_rebalance_plan(base, TODAY, snapshot_ts='unknown')['targets_stale']


def test_monthly_flag_follows_the_month_of_the_budgets():
    base = [_beta('A', 100, 100)]
    assert beta_rebalance_plan(base, TODAY, model_month='2026-10')['rp_due']
    assert not beta_rebalance_plan(base, TODAY, model_month='2026-11')['rp_due']
    assert not beta_rebalance_plan(base, TODAY, model_month=None)['rp_due']


def test_target_zero_closes_what_is_held_and_missing_rows_are_flagged():
    p = beta_rebalance_plan([_beta('A', 0, 120), _beta('B', 300, None, opened='')], TODAY)
    assert 'unbooked' in p['reasons'] and 'trade' in p['reasons'] and p['status'] == 'due'
    assert p['deltas']['A'] == -120.0
    assert {t['name'] for t in p['trades']} == {'A', 'B'}


def test_drift_is_dv01_weighted_and_informational():
    rows = [_beta('A', 500, 500, dur='1.0'), _beta('B', 200, 80, dur='10.0')]
    p = beta_rebalance_plan(rows, TODAY)
    assert p['drift'] == pytest.approx(120 * 10 / (500 * 1 + 200 * 10))


def test_lots_differ_by_asset_class_and_total_rows_are_ignored():
    rows = [_beta('FX', 5, 0.5, typ='FX', dur=''), _beta('BOND', 5, 0, typ='Rates'), _beta('X', 100, 100),
            {'Asset Type': 'TOTAL', 'Capital (MM CNY)': '999', 'Volume (MM)': '1'}]
    p = beta_rebalance_plan(rows, TODAY)
    assert {t['name'] for t in p['trades']} == {'FX'}                      # 4.5 >= 1MM FX lot; 5 < 10MM bond lot
    assert set(p['deltas']) == {'FX', 'BOND', 'X'}
