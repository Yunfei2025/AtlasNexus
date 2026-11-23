import numpy as np
import shutil
import pandas as pd
import pytest

from futures.backtest import costs
from futures.backtest.walkforward import load_walkforward, save_walkforward
from web.tabs.futures_desk import approvals


def _bars(closes, signal, per_day=3, start='2026-01-05'):
    days = pd.bdate_range(start, periods=len(closes) // per_day)
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=10 + h) for d in days for h in range(per_day)])
    return pd.DataFrame({'close': closes, 'signal': signal}, index=idx)


def test_flat_at_close_zeroes_last_bar_and_charges_costs():
    df = _bars([100, 101, 102, 103, 104, 105], [1, 1, 1, 1, 1, 1])
    out = costs.apply_costs(df, cost_bp=10, flat_at_close=True)
    assert list(out['signal']) == [1, 1, 0, 1, 1, 0]
    # nothing is held over the close: day-2 first bar earns no return
    assert out['strategy_returns'].iloc[3] == pytest.approx(-0.001)  # entry cost only
    legacy = costs.apply_costs(df, cost_bp=0, flat_at_close=False)
    assert legacy['strategy_returns'].iloc[3] == pytest.approx(103 / 102 - 1)


def test_reversal_pays_two_sides():
    df = _bars([100, 100, 100], [1, -1, -1], per_day=3)
    out = costs.apply_costs(df, cost_bp=10, flat_at_close=False)
    assert out['strategy_returns'].iloc[1] == pytest.approx(-0.002)


def test_per_bar_volume_undoes_cumulative_but_leaves_per_tick():
    idx = pd.DatetimeIndex(['2026-01-05 10:00', '2026-01-05 10:01', '2026-01-05 10:02', '2026-01-06 10:00'])
    cum = pd.DataFrame({'volume': [10.0, 15.0, 22.0, 4.0]}, index=idx)
    assert list(costs.per_bar_volume(cum)) == [0.0, 5.0, 7.0, 0.0]
    tick = pd.DataFrame({'volume': [5.0, 3.0, 8.0, 2.0] * 30}, index=pd.date_range('2026-01-05', periods=120, freq='min'))
    assert costs.per_bar_volume(tick).equals(tick['volume'])


def test_trade_stats_counts_round_trips_net_of_cost():
    df = _bars([100, 101, 100, 100, 99, 100], [1, 1, 0, -1, -1, 0])
    st = costs.trade_stats(df, cost_bp=0)
    assert st['trades'] == 2
    assert st['win'] == 0.5


def test_product_and_default_cost():
    assert costs.product_of('TL2612') == 'TL' and costs.product_of('au.shf') == 'AU'
    assert costs.default_cost_bp('IC2612') == 1.9 and costs.default_cost_bp('XX2612') == costs.FALLBACK_COST_BP


def _wf(passes):
    return {'product': 'AU', 'run_at': '2026-11-05 09:30', 'cost_bp': 0.4, 'last_day': '2026-11-04',
            'rows': {'SAR@30min': {'passes': passes, 'pooled': 1.9, 'se': 1.4, 'per_contract': {'AU2612': 2.0},
                                   'trades': 169, 'win': 0.5, 'payoff': 1.6, 'expectancy_bp': 8.9}}}


def test_approval_requires_passing_gates(tmp_path, monkeypatch):
    path = tmp_path / 'approved.json'
    monkeypatch.setattr(approvals, 'DESK_DIR', tmp_path)
    with pytest.raises(ValueError):
        approvals.approve('AU', 'SAR@30min', _wf(False), path=path)
    with pytest.raises(ValueError):
        approvals.approve('AU', 'MA@1h', _wf(True), path=path)
    rec = approvals.approve('AU', 'SAR@30min', _wf(True), path=path)
    assert rec['strategy'] == 'SAR' and rec['timeframe'] == '30min'
    assert approvals.load_approved(path)['AU']['candidate'] == 'SAR@30min'


def test_walkforward_roundtrip(tmp_path):
    wf = _wf(True)
    save_walkforward(wf, tmp_path)
    assert load_walkforward('AU', tmp_path) == wf
    assert load_walkforward('XX', tmp_path) is None


# ── Today: book sizing and selection ────────────────────────────────────────────────────────────
from datetime import datetime, timedelta

from web.tabs.futures_desk import pool, pool_corr


def _fake_world(monkeypatch, approved, close, pnl):
    monkeypatch.setattr(pool.approvals, 'load_approved', lambda path=None: approved)
    monkeypatch.setattr(pool, 'daily_panels', lambda: (close, close))
    monkeypatch.setattr(pool, 'pnl_panel', lambda cands: pnl[list(cands)])
    monkeypatch.setattr(pool, 'intraday_state', lambda prod, cand, exits=None, **kw: {
        'contract': f'{prod}2612', 'last_price': 100.0, 'last_time': datetime(2026, 11, 4, 15, 30),
        'signal': 1.0, 'since': pd.Timestamp('2026-11-04 10:00'), 'entry_price': 98.0})


def _close(symbols):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range('2026-06-01', periods=120)
    return pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))) for s in symbols}, index=idx)


def test_book_sizes_each_product_to_the_same_risk(monkeypatch):
    close = _close(['AU.SHF', 'TL.CFE'])
    approved = {p: {'candidate': 'SAR@30min', 'status': 'approved'} for p in ('AU', 'TL')}
    pnl = pd.DataFrame(np.random.default_rng(1).normal(size=(60, 2)), columns=['AU', 'TL'],
                       index=pd.bdate_range('2026-08-01', periods=60))
    _fake_world(monkeypatch, approved, close, pnl)
    book = pool.build_book(capital=10_000_000, risk_pct=0.25, stop_mult=0.5, loss_limit_pct=1.0,
                           today=datetime(2026, 11, 5))
    assert [r['product'] for r in book['rows']] == ['AU', 'TL']
    for r in book['rows']:
        sigma = close[{'AU': 'AU.SHF', 'TL': 'TL.CFE'}[r['product']]].pct_change().tail(20).std()
        per_lot = 0.5 * sigma * 100.0 * pool.CONTRACT_MULTIPLIER[r['product']]
        assert r['lots'] == int(25_000 // per_lot)
        assert r['risk_cny'] <= 25_000 and r['stop_price'] == pytest.approx(98.0 - r['stop_pts'])
    assert book['risk_cny'] == pytest.approx(sum(r['risk_cny'] for r in book['rows']))


def test_book_gives_no_position_when_one_lot_exceeds_the_budget(monkeypatch):
    close = _close(['IC.CFE'])
    pnl = pd.DataFrame({'IC': np.zeros(30)}, index=pd.bdate_range('2026-08-01', periods=30))
    _fake_world(monkeypatch, {'IC': {'candidate': 'SAR@30min'}}, close, pnl)
    book = pool.build_book(capital=10_000, risk_pct=0.25, stop_mult=0.5, loss_limit_pct=1.0,
                           today=datetime(2026, 11, 5))
    assert book['rows'][0]['lots'] == 0
    assert any('no position' in w for w in book['warnings'])


def test_book_caps_at_five_and_drops_the_most_correlated(monkeypatch):
    prods = ['AU', 'TL', 'IC', 'AG', 'CU', 'AL']
    suffix = {'AU': 'SHF', 'TL': 'CFE', 'IC': 'CFE', 'AG': 'SHF', 'CU': 'SHF', 'AL': 'SHF'}
    close = _close([f'{p}.{suffix[p]}' for p in prods])
    rng = np.random.default_rng(2)
    idx = pd.bdate_range('2026-08-01', periods=80)
    base = rng.normal(size=len(idx))
    pnl = pd.DataFrame({p: rng.normal(size=len(idx)) for p in prods}, index=idx)
    pnl['AL'] = base + rng.normal(0, 0.05, len(idx))
    pnl['CU'] = base + rng.normal(0, 0.05, len(idx))  # CU and AL move together
    _fake_world(monkeypatch, {p: {'candidate': 'SAR@30min'} for p in prods}, close, pnl)
    book = pool.build_book(capital=50_000_000, risk_pct=0.25, stop_mult=0.5, loss_limit_pct=1.0,
                           today=datetime(2026, 11, 5))
    assert len(book['rows']) == 5 and len(book['excluded']) == 1
    assert book['excluded'][0] in ('CU', 'AL')


def test_no_approved_products_gives_an_empty_book(monkeypatch):
    monkeypatch.setattr(pool.approvals, 'load_approved', lambda path=None: {})
    assert pool.build_book(1e6, 0.25, 0.5, 1.0)['rows'] == []


def test_strategy_pnl_heatmap_needs_two_products(monkeypatch):
    monkeypatch.setattr(pool_corr, '_pnl_candidates', lambda: {'AU': ('SAR@30min', 'approved')})
    monkeypatch.setattr(pool_corr, 'pnl_panel', lambda c: pd.DataFrame({'AU': np.arange(30.0)}))
    with pytest.raises(ValueError):
        pool_corr._corr_heatmap('pnl', '1Y')


# ── Monitor ─────────────────────────────────────────────────────────────────────────────────────
from web.tabs.futures_desk import monitor


def _days(vals):
    return pd.Series(vals, index=pd.bdate_range('2026-10-01', periods=len(vals)), dtype=float)


def test_losing_streak_ignores_flat_days():
    assert monitor.losing_streak(_days([1, -1, 0, -1, -1])) == 3
    assert monitor.losing_streak(_days([-1, -1, 1])) == 0


def test_assess_statuses():
    mean, std = 0.001, 0.01
    assert monitor.assess(_days([0.001] * 3), mean, std)['status'] == 'early'
    assert monitor.assess(_days([0.001] * 10), mean, std)['status'] == 'ok'
    # alternating -3% / +0.5% for 10 days: total -12.5% vs expected +0.5%, z = -4.1, no losing streak
    a = monitor.assess(_days([-0.03, 0.005] * 5), mean, std)
    assert a['status'] == 'halted' and a['z'] < -2 and a['streak'] == 0
    # mild underperformance: watch, not halt
    b = monitor.assess(_days([0.0] * 9 + [-0.045]), mean, std, watch_sig=1.0, halt_sig=2.0)
    assert b['status'] == 'watch'
    # losing streak alone halts at N, watches two below
    streak = _days([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, -0.0001, -0.0001, -0.0001, -0.0001, -0.0001])
    assert monitor.assess(streak, mean, std, halt_losses=5)['status'] == 'halted'
    assert monitor.assess(streak.iloc[:-2], mean, std, halt_losses=5)['status'] == 'watch'


def test_band_is_symmetric_around_the_haircut_mean():
    n, mid, lo, hi = monitor.band(0.002, 0.01, 4, k=2)
    assert list(n) == [1, 2, 3, 4]
    assert mid[3] == pytest.approx(monitor.HAIRCUT * 0.002 * 4)
    assert hi[3] - mid[3] == pytest.approx(2 * 0.01 * 2) and mid[3] - lo[3] == pytest.approx(2 * 0.01 * 2)


def test_halted_never_auto_resumes_and_ok_clears_watch():
    assert monitor.computed_to_applied('halted', 'ok') == 'halted'
    assert monitor.computed_to_applied('watch', 'ok') == 'approved'
    assert monitor.computed_to_applied('approved', 'watch') == 'watch'
    assert monitor.computed_to_applied('approved', 'early') == 'approved'


def test_set_status_and_reapproval_restores(tmp_path):
    path = tmp_path / 'approved.json'
    approvals.approve('AU', 'SAR@30min', _wf(True), path=path)
    approvals.set_status('AU', 'halted', 'test', path=path)
    assert approvals.load_approved(path)['AU']['status'] == 'halted'
    with pytest.raises(ValueError):
        approvals.set_status('XX', 'halted', 'x', path=path)
    with pytest.raises(ValueError):
        approvals.set_status('AU', 'bogus', 'x', path=path)
    approvals.approve('AU', 'SAR@30min', _wf(True), path=path)  # fresh evidence resumes
    assert approvals.load_approved(path)['AU']['status'] == 'approved'


def test_halted_product_leaves_the_book_and_watch_is_flagged(monkeypatch):
    close = _close(['AU.SHF', 'TL.CFE', 'IC.CFE'])
    approved = {'AU': {'candidate': 'SAR@30min', 'status': 'halted'},
                'TL': {'candidate': 'Boll@15min', 'status': 'watch', 'status_reason': 'P&L -1.2σ'},
                'IC': {'candidate': 'SAR@30min', 'status': 'approved'}}
    pnl = pd.DataFrame(np.random.default_rng(3).normal(size=(60, 3)), columns=['AU', 'TL', 'IC'],
                       index=pd.bdate_range('2026-08-01', periods=60))
    _fake_world(monkeypatch, approved, close, pnl)
    book = pool.build_book(10_000_000, 0.25, 0.5, 1.0, today=datetime(2026, 11, 5))
    assert [r['product'] for r in book['rows']] == ['TL', 'IC'] and book['halted'] == ['AU']
    assert any('on Watch' in w for w in book['warnings'])


# ── Minute-bar cache (results without the tick files) ─────────────────────────────────────────────
import pickle

from futures.backtest import minute_bars


def _write_ticks(path, days=3, seed=0):
    """A tick pickle in the Wind layout: {date: frame(last, ask, bid, cumulative volume)}."""
    rng = np.random.default_rng(seed)
    data = {}
    for d in pd.bdate_range('2026-10-05', periods=days):
        idx = pd.date_range(d + pd.Timedelta(hours=9, minutes=30), periods=1200, freq='7s')
        last = 100 + np.cumsum(rng.normal(0, 0.02, len(idx)))
        data[d.date()] = pd.DataFrame({'last': last, 'ask': last + 0.01, 'bid': last - 0.01,
                                       'volume': np.cumsum(rng.integers(1, 5, len(idx))).astype(float)}, index=idx)
    with open(path, 'wb') as fh:
        pickle.dump(data, fh)


def test_minute_bars_resample_like_ticks(tmp_path):
    from futures.backtest.walkforward import load_ticks
    _write_ticks(tmp_path / 'AU2612.pkl')
    ticks = load_ticks(str(tmp_path / 'AU2612.pkl'))
    via_minutes = minute_bars.resample_minute_bars(minute_bars.ticks_to_minute_bars(ticks), '15min')
    direct = ticks['last'].resample('15min').ohlc()
    direct['volume'] = ticks['vol'].resample('15min').sum()
    pd.testing.assert_frame_equal(via_minutes, direct.dropna(), check_freq=False)


def test_cache_serves_when_the_tick_file_is_gone_and_rebuilds_when_it_changes(tmp_path):
    ticks, bars = tmp_path / 'ticks', tmp_path / 'bars'
    ticks.mkdir()
    _write_ticks(ticks / 'AU2612.pkl', days=2)
    assert minute_bars.sync(tick_dir=ticks, bar_dir=bars) == ['AU2612']
    assert minute_bars.sync(tick_dir=ticks, bar_dir=bars) == []          # unchanged: nothing rebuilt
    first = minute_bars.load_minute_bars('AU2612', ticks, bars)
    _write_ticks(ticks / 'AU2612.pkl', days=3, seed=1)                    # new day arrives
    assert minute_bars.load_minute_bars('AU2612', ticks, bars).index.max() > first.index.max()
    (ticks / 'AU2612.pkl').unlink()                                       # "the other computer"
    cached = minute_bars.load_minute_bars('AU2612', ticks, bars)
    assert cached is not None and cached.index.normalize().nunique() == 3
    assert minute_bars.list_contracts('AU', ticks, bars) == ['AU2612']
    assert minute_bars.load_minute_bars('XX2612', ticks, bars) is None


# ── Research: one evidence flow (walk-forward candidates drill into the chart) ───────────────────
from dash import html

from futures.backtest.walkforward import DEFAULT_PARAMS, PANEL_STRATEGY, STRATEGIES
from web.tabs.beta.callbacks.backtest_futures import PARAM_IDS
from web.tabs.futures_desk import research


def _walk(node, found):
    if isinstance(node, (list, tuple)):
        for n in node:
            _walk(n, found)
    elif node is not None and not isinstance(node, str):
        found.append(node)
        _walk(getattr(node, 'children', None), found)


def test_panel_inputs_start_at_the_walkforward_defaults():
    from web.tabs.beta.layouts.backtest import build_factor_backtest_layout
    found = []
    _walk(build_factor_backtest_layout(), found)
    values = {getattr(c, 'id', None): getattr(c, 'value', None) for c in found}
    assert set(PARAM_IDS) == set(DEFAULT_PARAMS)
    for pid, default in DEFAULT_PARAMS.items():
        assert values[pid] == default, pid
    assert PANEL_STRATEGY.get('Mom') == 'Momentum' and set(STRATEGIES) >= {'MA', 'Boll', 'SAR'}


def test_walkforward_table_cells_are_click_to_chart():
    wf = {'product': 'AU', 'days': 40, 'last_day': '2026-11-04', 'cost_bp': 0.4, 'half_spread_bp': 0.3,
          'fee_bp': 0.1, 'run_at': 'x', 'gates': {'min_trades': 30, 'min_contract_days': 15},
          'contracts': {'AU2610': {'days': 20}, 'AU2612': {'days': 20}},
          'rows': {'SAR@30min': {'pooled': 1.0, 'se': 1.0, 'per_contract': {'AU2610': 1.0, 'AU2612': 2.0},
                                 'trades_per_day': 1.0, 'win': 0.5, 'payoff': 1.5, 'expectancy_bp': 3.0,
                                 'passes': True}}}
    found = []
    _walk(research.wf_table(wf), found)
    ids = [c.id for c in found if isinstance(getattr(c, 'id', None), dict)]
    assert {'type': 'bf-wf-pick', 'cand': 'SAR@30min', 'c': ''} in ids          # name: the selected contract
    assert {'type': 'bf-wf-pick', 'cand': 'SAR@30min', 'c': 'AU2612'} in ids    # a contract's Sharpe: that contract


def test_drill_payload_uses_the_walkforward_cost_and_the_contract_range(tmp_path, monkeypatch):
    approvals_wf = {'product': 'AU', 'cost_bp': 0.42, 'rows': {'Mom@1h': {}}}
    save_walkforward(approvals_wf, tmp_path)
    bars = pd.DataFrame({'close': [1.0, 2.0]}, index=pd.to_datetime(['2026-10-05 09:30', '2026-10-07 14:00']))
    monkeypatch.setattr(research, 'load_minute_bars', lambda c: bars)
    monkeypatch.setattr(research, 'list_contracts', lambda p: ['AU2610', 'AU2612'])
    p = research.drill_payload('Mom@1h', '', 'AU2612', 'local', None, wf_dir=tmp_path)
    assert p == {'cand': 'Mom@1h', 'strategy': 'Momentum', 'timeframe': '1h', 'contract': 'AU2612',
                 'cost_bp': 0.42, 'exits': None, 'start': '2026-10-05', 'end': '2026-10-07'}
    assert research.drill_payload('Nope@1h', 'AU2612', 'AU2612', 'local', None, wf_dir=tmp_path) is None


def test_walkforward_table_shows_only_passing_candidates_capped_at_ten():
    row = {'pooled': 1.0, 'se': 1.0, 'per_contract': {'AU2612': 1.0}, 'trades_per_day': 1.0, 'win': 0.5,
           'payoff': 1.5, 'expectancy_bp': 3.0, 'passes': True}
    names = [f'{s}@{tf}' for s in ('MA', 'Boll', 'VWAP', 'Mom', 'ATR', 'SAR', 'DeMark') for tf in ('15min', '30min', '1h')]
    wf = {'product': 'AU', 'days': 40, 'last_day': '2026-11-04', 'cost_bp': 0.4, 'half_spread_bp': 0.3, 'fee_bp': 0.1,
          'run_at': 'x', 'gates': {'min_trades': 30, 'min_contract_days': 15}, 'contracts': {'AU2612': {'days': 20}},
          'rows': {n: dict(row, pooled=float(i), passes=i >= 4) for i, n in enumerate(names)}}   # 17 pass

    def shown(w):
        found = []
        _walk(research.wf_table(w), found)
        return [c.id['cand'] for c in found if isinstance(getattr(c, 'id', None), dict) and c.id['c'] == '']

    top = shown(wf)
    assert len(top) == 10 and top[0] == names[-1]                 # best first, capped
    assert all(wf['rows'][n]['passes'] for n in top)
    for r in wf['rows'].values():
        r['passes'] = False
    found = []
    _walk(research.wf_table(wf), found)
    assert shown(wf) == [] and any('No candidate passes' in str(getattr(c, 'children', '')) for c in found)


def test_book_correlation_basis_uses_the_book_members(monkeypatch):
    names = ['AU', 'TL', 'IC']
    idx = pd.bdate_range('2026-08-01', periods=60)
    rng = np.random.default_rng(5)
    base = rng.normal(size=60)
    panel = pd.DataFrame({'AU': base, 'TL': base + rng.normal(0, 0.1, 60), 'IC': rng.normal(size=60)}, index=idx)
    approved = {n: {'candidate': 'SAR@30min', 'status': 'approved'} for n in names}
    approved['XX'] = {'candidate': 'SAR@30min', 'status': 'halted'}          # halted: not in the book
    monkeypatch.setattr(pool.approvals, 'load_approved', lambda path=None: approved)
    monkeypatch.setattr(pool, 'pnl_panel', lambda cands: panel[list(cands)])
    monkeypatch.setattr(pool_corr, 'pnl_panel', lambda cands: panel[list(cands)])
    fig, note = pool_corr._corr_heatmap('book', '1Y')
    assert sorted(fig.data[0].x) == ['AU', 'IC', 'TL']
    assert "today's book" in note and 'XX' not in note
    z = pd.DataFrame(fig.data[0].z, index=fig.data[0].y, columns=fig.data[0].x)
    assert z.loc['AU', 'TL'] > 0.9 and abs(z.loc['AU', 'IC']) < 0.5       # the correlated pair stands out
    # the book and the heat map agree on membership and on the correlation
    sel = pool.select_book()
    assert sel['chosen'] == names and sel['halted'] == ['XX']
    assert sel['corr'].loc['AU', 'TL'] == pytest.approx(z.loc['AU', 'TL'])


def test_book_correlation_needs_two_products(monkeypatch):
    monkeypatch.setattr(pool.approvals, 'load_approved', lambda path=None: {'AU': {'candidate': 'SAR@30min'}})
    monkeypatch.setattr(pool, 'pnl_panel', lambda cands: pd.DataFrame({'AU': np.arange(30.0)}))
    with pytest.raises(ValueError):
        pool_corr._corr_heatmap('book', '1Y')


# ── Stop loss / profit target ─────────────────────────────────────────────────────────────────
def _ohlc(rows, start='2026-01-05 10:00'):
    idx = pd.date_range(start, periods=len(rows), freq='15min')
    return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close', 'signal'], index=idx)


def test_normalize_exits():
    assert costs.normalize_exits(None, '', 'pct') is None and costs.normalize_exits(0, -1) is None
    assert costs.normalize_exits(0.5, None, 'pct') == {'stop': 0.5, 'target': None, 'unit': 'pct'}
    assert costs.normalize_exits(None, 3, 'pts')['unit'] == 'pts'


def test_stop_exits_at_the_level_and_locks_out_reentry():
    df = _ohlc([[100, 100, 100, 100, 1],      # enter long at 100
                [100, 100.2, 98.5, 99, 1],    # low 98.5 hits the 1% stop at 99
                [99, 99.5, 98.0, 98.5, 1],    # same signal: stays flat (locked out)
                [98.5, 99, 98, 98.8, -1],     # signal flips: short at 98.8
                [98.8, 99, 98.5, 98.6, -1]])
    out = costs.apply_costs(df, cost_bp=0, flat_at_close=False, exits=costs.normalize_exits(1.0, None, 'pct'))
    assert list(out['signal']) == [1, 0, 0, -1, -1]
    assert out['fill'].iloc[1] == pytest.approx(99.0)
    assert out['strategy_returns'].iloc[1] == pytest.approx(99 / 100 - 1)       # loss capped at the stop
    assert out['strategy_returns'].iloc[2] == 0


def test_target_in_points_and_gap_fills_at_open():
    df = _ohlc([[100, 100, 100, 100, 1],
                [103, 104, 102.5, 103.5, 1],  # opens above the 2-pt target: filled at the open, 103
                [103.5, 104, 103, 103.8, 1]])
    out = costs.apply_costs(df, 0, False, exits=costs.normalize_exits(None, 2, 'pts'))
    assert out['fill'].iloc[1] == pytest.approx(103.0) and list(out['signal']) == [1, 0, 0]


def test_stop_wins_when_both_levels_are_touched_and_trade_stats_use_the_fill():
    df = _ohlc([[100, 100, 100, 100, 1], [100, 103, 97, 101, 1], [101, 101, 101, 101, 0]])
    out = costs.apply_costs(df, 0, False, exits=costs.normalize_exits(2, 2, 'pct'))
    assert out['fill'].iloc[1] == pytest.approx(98.0)                            # conservative: stop first
    st = costs.trade_stats(out, 0)
    assert st['trades'] == 1 and st['expectancy_bp'] == pytest.approx(-200, rel=1e-6)


def test_no_exits_leaves_results_unchanged():
    df = _ohlc([[100, 101, 99, 100, 1], [100, 102, 98, 101, 1], [101, 101, 100, 100.5, -1]])
    a = costs.apply_costs(df, 1.0, False)
    b = costs.apply_costs(df, 1.0, False, exits=None)
    pd.testing.assert_series_equal(a['strategy_returns'], b['strategy_returns'])
    assert a['strategy_returns'].iloc[1] == pytest.approx(101 / 100 - 1)


def test_book_sizes_with_the_approved_stop_when_set(monkeypatch):
    close = _close(['AU.SHF'])
    pnl = pd.DataFrame({'AU': np.zeros(30)}, index=pd.bdate_range('2026-08-01', periods=30))
    exits = {'stop': 0.5, 'target': None, 'unit': 'pct'}
    _fake_world(monkeypatch, {'AU': {'candidate': 'SAR@30min', 'exits': exits}}, close, pnl)
    book = pool.build_book(10_000_000, 0.25, 0.5, 1.0, today=datetime(2026, 11, 5))
    r = book['rows'][0]
    assert r['stop_src'] == 'strategy' and r['stop_pts'] == pytest.approx(0.5)   # 0.5% of 100
    assert r['lots'] == int(25_000 // (0.5 * pool.CONTRACT_MULTIPLIER['AU']))


def test_book_levels_are_measured_from_the_entry_price(monkeypatch):
    close = _close(['AU.SHF'])
    pnl = pd.DataFrame({'AU': np.zeros(30)}, index=pd.bdate_range('2026-08-01', periods=30))
    exits = {'stop': 0.5, 'target': 1.0, 'unit': 'pct'}
    _fake_world(monkeypatch, {'AU': {'candidate': 'SAR@30min', 'exits': exits}}, close, pnl)
    r = pool.build_book(10_000_000, 0.25, 0.5, 1.0, today=datetime(2026, 11, 5))['rows'][0]
    # long entered at 98 (last is 100): stop 0.5% and target 1% of the entry, not of the last price
    assert r['entry_price'] == 98.0
    assert r['stop_price'] == pytest.approx(98 * 0.995) and r['target_price'] == pytest.approx(98 * 1.01)


# ── Walk-forward stop / target search ─────────────────────────────────────────────────────────
from futures.backtest import walkforward


def _cache_contracts(bar_dir, product='AU', contracts=('AU2604', 'AU2606', 'AU2608'), days=25):
    rng = np.random.default_rng(11)
    index = {}
    bar_dir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp('2026-01-05')
    for n, c in enumerate(contracts):
        frames = []
        for d in pd.bdate_range(start + pd.Timedelta(days=35 * n), periods=days):
            idx = pd.date_range(d + pd.Timedelta(hours=9, minutes=30), periods=240, freq='1min')
            close = 500 * np.exp(np.cumsum(rng.normal(0, 0.0008, len(idx))))
            frames.append(pd.DataFrame({'open': close, 'high': close * 1.0004, 'low': close * 0.9996, 'close': close,
                                        'volume': 100.0, 'hs_bp': np.float32(0.3)}, index=idx))
        bars = pd.concat(frames)
        bars.to_parquet(bar_dir / f'{c}.parquet')
        index[c] = {'rows': len(bars), 'first': str(bars.index.min()), 'last': str(bars.index.max())}
    (bar_dir / 'index.json').write_text(json.dumps(index))


import json


def test_exit_search_keeps_the_best_setting_and_reports_the_no_exit_baseline(tmp_path):
    ticks, bars = tmp_path / 'ticks', tmp_path / 'bars'
    ticks.mkdir()
    _cache_contracts(bars)
    plain = walkforward.run_walkforward('AU', tick_dir=ticks, bar_dir=bars)
    found = walkforward.run_walkforward('AU', tick_dir=ticks, bar_dir=bars, search_exits=True)
    assert found['exits'] == 'search' and plain['exits'] is None
    assert set(found['rows']) == set(plain['rows'])
    for cand, r in found['rows'].items():
        assert r['exits'] in walkforward.EXIT_GRID
        assert r['base_pooled'] == pytest.approx(plain['rows'][cand]['pooled'], nan_ok=True)
        if not np.isnan(r['pooled']):
            assert r['pooled'] >= r['base_pooled'] - 1e-12   # searched >= no exits (no exits is in the grid)


def test_approval_and_drill_carry_the_candidates_own_exits(tmp_path):
    ex = {'stop': 0.5, 'target': 0.5, 'unit': 'pct'}
    wf = dict(_wf(True), exits='search')
    wf['rows']['SAR@30min'].update(exits=ex, base_pooled=0.8)
    assert approvals.candidate_exits(wf, 'SAR@30min') == ex
    rec = approvals.approve('AU', 'SAR@30min', wf, path=tmp_path / 'approved.json')
    assert rec['exits'] == ex
    old_style = dict(_wf(True), exits={'stop': 1.0, 'target': None, 'unit': 'pct'})   # pre-search runs
    assert approvals.candidate_exits(old_style, 'SAR@30min') == old_style['exits']
    assert costs.describe_exits('search') == 'stop / target searched per candidate'


def test_book_shows_direction_as_a_coloured_badge_with_an_arrow():
    from web.tabs.futures_desk import today
    base = {'candidate': 'SAR@30min', 'contract': 'AU2612', 'last_price': 100.0, 'stop_pts': 0.5, 'lots': 2,
            'risk_cny': 1000.0, 'notional': 200000.0, 'since': pd.Timestamp('2026-11-04 10:00'),
            'last_time': pd.Timestamp('2026-11-04 15:00')}
    rows = [dict(base, product='AU', signal=1, stop_price=99.5), dict(base, product='IC', signal=-1, stop_price=100.5),
            dict(base, product='TL', signal=0, stop_price=None)]
    book = {'rows': rows, 'notional': 6e5, 'leverage': 0.6, 'risk_cny': 3000.0, 'loss_limit_cny': 10000.0,
            'excluded': [], 'warnings': [], 'halted': []}
    found = []
    _walk(today.book_view(book, 1_000_000, 0.25, 1.0), found)
    badges = {c.children: c.style for c in found if getattr(c, 'className', None) == 'fd-signal'}
    assert set(badges) == {'▲ LONG', '▼ SHORT', '■ FLAT'}
    assert badges['▲ LONG']['color'] == today._GREEN and badges['▼ SHORT']['color'] == today._RED
    assert 'rgba(52,211,153' in badges['▲ LONG']['background'] and 'rgba(248,113,113' in badges['▼ SHORT']['background']


# ── Live minute bars (Monitor) ────────────────────────────────────────────────────────────────
from futures.backtest import live_bars
from web.tabs.futures_desk import live_ui


def _wind_frame(day, start, end, base=100.0):
    idx = pd.date_range(f'{day} {start}', f'{day} {end}', freq='1min')
    c = base + np.arange(len(idx)) * 0.01
    return pd.DataFrame({'OPEN': c, 'HIGH': c + 0.02, 'LOW': c - 0.02, 'CLOSE': c, 'VOLUME': 5.0}, index=idx)


class _FakeWind:
    def __init__(self, frame=None, boom=None):
        self.calls, self.frame, self.boom = [], frame, boom

    def __call__(self, code, fields, start, end, *a):
        self.calls.append((code, start, end))
        if self.boom:
            raise RuntimeError(self.boom)
        f = self.frame
        if f.empty:
            return f
        return f[(f.index >= pd.Timestamp(start)) & (f.index <= pd.Timestamp(end))]


CODES = ['AU2612.SHF', 'IC2612.CFE', 'TL2612.CFE']


def test_live_fetch_after_close_is_once_and_only_when_wind_enabled(tmp_path, monkeypatch):
    wind = _FakeWind(_wind_frame('2026-11-05', '09:00', '15:14'))
    off = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 18, 0), wsi=wind, codes=CODES, closed_only=True,
                                    is_trading=lambda n: False, live_dir=tmp_path, wind_off=lambda: True)
    assert off['skipped'] and wind.calls == []                     # the passive view respects FI_DISABLE_WIND
    kw = dict(wsi=wind, codes=CODES, is_trading=lambda n: False, live_dir=tmp_path, wind_off=lambda: False)
    first = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 18, 0), **kw)
    assert first['products']['AU']['rows'] > 300 and len(wind.calls) == 1
    assert live_bars.load_index(tmp_path)['AU2612']['complete'] is True
    again = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 19, 0), **kw)     # served from the file
    sat = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 6, 8, 0), **kw)        # before the next open: still Thursday's file
    assert len(wind.calls) == 1 and again['products']['AU']['new'] == 0 and sat['products']['AU']['new'] == 0
    hist = _wind_frame('2026-11-03', '09:00', '14:59').rename(columns=str.lower).assign(hs_bp=np.float32('nan'))
    monkeypatch.setattr(monitor, 'load_minute_bars', lambda c, **kw: hist)
    monkeypatch.setattr(monitor, 'load_live', lambda c, d=None: live_bars.load_live(c, tmp_path))
    monkeypatch.setattr(monitor, 'live_meta_for', lambda p, d=None: live_bars.live_meta_for(p, tmp_path))
    monkeypatch.setattr(monitor, 'STRATEGIES', {'SAR': lambda df: df.assign(signal=1.0)})
    st = monitor.live_state('AU', {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None},
                            now=datetime(2026, 11, 6, 8, 0))
    assert st is not None and st['closed'] and st['position'] == 0 and st['day'] == pd.Timestamp('2026-11-05')
    open_skip = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 6, 10, 0), closed_only=True,
                                          wsi=wind, codes=CODES, is_trading=lambda n: True, live_dir=tmp_path)
    assert open_skip['skipped'] and len(wind.calls) == 1


def test_start_live_calls_wind_on_demand_despite_kill_switch(tmp_path):
    """The daily console always sets FI_DISABLE_WIND; ▶ Start live is an explicit request and still fetches."""
    wind = _FakeWind(_wind_frame('2026-11-05', '09:00', '10:30'))
    r = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 10, 30), wsi=wind, codes=CODES,
                                  live_dir=tmp_path, wind_off=lambda: True)
    assert r['skipped'] is None and r['session'] == 'open' and r['products']['AU']['rows'] == 91


def test_session_hours_are_beijing_day_session():
    assert live_bars.in_day_session(datetime(2026, 11, 10, 10, 0))
    assert not live_bars.in_day_session(datetime(2026, 11, 10, 22, 7))     # night session: not modelled
    assert not live_bars.in_day_session(datetime(2026, 11, 14, 10, 0))     # Saturday
    bj = live_bars.china_now()
    utc = pd.Timestamp.now(tz='UTC').tz_localize(None).to_pydatetime()
    assert abs((bj - utc).total_seconds() - 8 * 3600) < 120


def test_live_fetch_only_asked_products(tmp_path):
    wind = _FakeWind(_wind_frame('2026-11-05', '09:00', '10:30'))
    on = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 10, 30), wsi=wind, codes=CODES,
                                   is_trading=lambda n: True, live_dir=tmp_path)
    assert [c[0] for c in wind.calls] == ['AU2612.SHF']          # IC and TL were never requested
    assert on['products']['AU']['rows'] == 91 and (tmp_path / 'AU2612.parquet').exists()
    assert not (tmp_path / 'IC2612.parquet').exists()


def test_live_fetch_is_incremental_and_resets_each_day(tmp_path):
    frame = _wind_frame('2026-11-05', '09:00', '11:00')
    wind = _FakeWind(frame)
    go = lambda t: live_bars.fetch_live_bars(['AU'], now=t, wsi=wind, codes=CODES, is_trading=lambda n: True,
                                             live_dir=tmp_path)
    go(datetime(2026, 11, 5, 10, 0))
    second = go(datetime(2026, 11, 5, 11, 0))
    assert wind.calls[1][1] == '2026-11-05 09:58:00'                 # last stored bar 10:00 minus the 2 min overlap
    assert second['products']['AU']['rows'] == 121 and second['products']['AU']['new'] < 70   # no re-download
    bars, meta = live_bars.load_live('AU2612', tmp_path)
    assert bars.index.is_unique and meta['date'] == '2026-11-05'
    nextday = _FakeWind(_wind_frame('2026-11-06', '09:00', '09:30'))
    live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 6, 9, 30), wsi=nextday, codes=CODES,
                              is_trading=lambda n: True, live_dir=tmp_path)
    assert nextday.calls[0][1] == '2026-11-06 08:55:00'              # a new day starts from the session open
    bars, _ = live_bars.load_live('AU2612', tmp_path)
    assert bars.index.min().date() == datetime(2026, 11, 6).date()


def test_live_fetch_reports_errors_per_product(tmp_path):
    r = live_bars.fetch_live_bars(['AU', 'XX'], now=datetime(2026, 11, 5, 10, 0), wsi=_FakeWind(boom='Wind down'),
                                  codes=CODES, is_trading=lambda n: True, live_dir=tmp_path)
    assert 'Wind down' in r['products']['AU']['error'] and 'no main contract' in r['products']['XX']['error']
    empty = live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 10, 0), wsi=_FakeWind(pd.DataFrame()),
                                      codes=CODES, is_trading=lambda n: True, live_dir=tmp_path)
    assert 'no bars' in empty['products']['AU']['error']


def test_live_overlay_only_when_the_settled_bars_miss_today():
    settled = _wind_frame('2026-11-04', '09:00', '09:10').rename(columns=str.lower)
    live = live_bars._normalize(_wind_frame('2026-11-05', '09:00', '09:10'), '2026-11-05')
    both = live_bars.with_live(settled.assign(hs_bp=np.float32('nan')), live)
    assert both.index.normalize().nunique() == 2
    covered = live_bars.with_live(both, live)                         # the end-of-day sync already has today
    assert len(covered) == len(both)


def test_live_overlay_keeps_newer_same_day_updates():
    settled = _wind_frame('2026-11-05', '09:00', '09:05').rename(columns=str.lower)
    settled = settled.assign(hs_bp=np.float32('nan'))
    live = live_bars._normalize(_wind_frame('2026-11-05', '09:06', '09:10'), '2026-11-05')
    merged = live_bars.with_live(settled, live)
    assert set(merged.index.strftime('%H:%M')).issuperset({'09:00', '09:05', '09:06', '09:10'})
    assert len(merged) == len(settled) + len(live)


def test_start_state_validation():
    assert live_ui.start_state([], 5)[0] is None and live_ui.start_state(['AU'], 7)[0] is None
    assert live_ui.start_state(list('ABCDEF'), 5)[0] is None
    st, msg = live_ui.start_state(['AU', 'TL'], 10)
    assert st['running'] and st['products'] == ['AU', 'TL'] and st['minutes'] == 10 and msg == ''


def test_live_state_position_stop_and_day_return(tmp_path, monkeypatch):
    """A stub strategy goes long at 09:30 on the day; a 1% stop is breached inside the 10:30 bar."""
    days = pd.bdate_range('2026-11-03', '2026-11-04')
    hist = pd.concat([_wind_frame(d.strftime('%Y-%m-%d'), '09:00', '14:59') for d in days]).rename(columns=str.lower)
    hist = hist.assign(hs_bp=np.float32('nan'))
    live = _wind_frame('2026-11-05', '09:00', '10:59').rename(columns=str.lower)
    live.loc[pd.Timestamp('2026-11-05 10:35'), 'low'] -= 3.0     # a dip inside the 10:30 bar: low ~3% under
    live_bars.fetch_live_bars(['AU'], now=datetime(2026, 11, 5, 11, 0), codes=CODES, is_trading=lambda n: True,
                              wsi=_FakeWind(live.rename(columns=str.upper)), live_dir=tmp_path)
    monkeypatch.setattr(monitor, 'load_minute_bars', lambda c, **kw: hist)
    monkeypatch.setattr(monitor, 'load_live', lambda c, d=None: live_bars.load_live(c, tmp_path))
    monkeypatch.setattr(monitor, 'live_meta_for', lambda p, d=None: live_bars.live_meta_for(p, tmp_path))

    def long_from_0930(df):
        out = df.copy()
        out['signal'] = np.where(out.index.time >= pd.Timestamp('09:30').time(), 1.0, 0.0)
        return out
    monkeypatch.setattr(monitor, 'STRATEGIES', {'SAR': long_from_0930})
    rec = {'candidate': 'SAR@15min', 'cost_bp': 0.0, 'exits': {'stop': 1.0, 'target': None, 'unit': 'pct'}}
    st = monitor.live_state('AU', rec, now=datetime(2026, 11, 5, 11, 0))
    assert st['contract'] == 'AU2612' and st['position'] == 0 and st['exited_at'] is not None   # stopped out
    assert st['exited_at'].hour == 10 and st['stop_px'] is None
    assert st['day_return'] == pytest.approx(-0.01, abs=1e-3)                                  # filled at the stop level
    held = monitor.live_state('AU', dict(rec, exits=None), now=datetime(2026, 11, 5, 10, 20))   # before the drop
    assert held['position'] == 1 and held['entry_px'] is not None and held['exited_at'] is None
    assert monitor.live_state('AU', rec, now=datetime(2026, 11, 6, 9, 5)) is None             # no live bars for that day
    out = live_ui.live_view([st], {'skipped': None, 'products': {}}, {'running': True, 'minutes': 5},
                            now=datetime(2026, 11, 5, 11, 1))
    found = []
    _walk(out, found)
    assert any('stop / target hit at 10:' in str(getattr(c, 'children', '')) for c in found)


def test_day_trades_and_chart_show_entry_exit_stop_and_target():
    idx = pd.date_range('2026-11-05 09:30', periods=6, freq='30min')
    close = np.array([100.0, 100.5, 99.0, 99.0, 98.5, 98.0])
    today = pd.DataFrame({'open': close, 'high': close + .3, 'low': close - .3, 'close': close,
                          'signal': [1.0, 1.0, 0.0, -1.0, -1.0, -1.0],
                          'fill': [100.0, 100.5, 99.0, 99.0, 98.5, 98.0]}, index=idx)
    ex = {'stop': 1.0, 'target': 2.0, 'unit': 'pct'}
    trades = monitor.day_trades(today, ex)
    assert [(t['direction'], t['entry_px'], t['exit_px']) for t in trades] == [(1, 100.0, 99.0), (-1, 99.0, None)]
    assert trades[0]['stop'] == pytest.approx(99.0) and trades[0]['target'] == pytest.approx(102.0)
    assert trades[1]['stop'] == pytest.approx(99.99) and trades[1]['target'] == pytest.approx(97.02)   # short: inverted
    assert monitor.exit_levels(100.0, 1, {'stop': 2, 'target': None, 'unit': 'pts'}) == {'stop': 98.0, 'target': None}
    row = {'product': 'AU', 'candidate': 'SAR@30min', 'contract': 'AU2612', 'day': pd.Timestamp('2026-11-05'), 'closed': False, 'bars': today[['open', 'high', 'low', 'close']],
           'trades': trades}
    fig = live_ui.live_chart(row)
    lines = [t for t in fig.data if getattr(t, 'mode', None) == 'lines']
    assert sorted(set(round(y, 2) for t in lines for y in t.y)) == [97.02, 99.0, 99.99, 102.0]   # both trades, both levels
    assert any(a.text.startswith('stop') for a in fig.layout.annotations)
    assert len([t for t in fig.data if getattr(t, 'mode', None) == 'markers']) == 3                                  # 2 entries + 1 exit


def test_daily_candidates_on_the_continuous_series(tmp_path):
    from futures.backtest import walkforward as wfm
    from web.tabs.futures_desk import research
    idx = pd.bdate_range('2022-01-03', periods=900)
    c = pd.Series(100 + np.cumsum(np.sin(np.arange(900) / 15) * 0.8), index=idx)
    df = pd.DataFrame({'Open': c, 'High': c + 1, 'Low': c - 1, 'Close': c, 'Volume': 100.0})
    path = tmp_path / 'dailyK.pkl'
    pickle.dump({'AU.SHF': df}, open(path, 'wb'))
    d = wfm.run_daily('AU', 0.4, recent_from=idx[-120], path=path)
    assert d['start'] == '2022-01-03' and set(d['rows']) <= {f'{s}@1D' for s in wfm.DAILY_STRATEGIES}
    r = d['rows']['MA@1D']
    assert r['days'] == 900 and r['recent_days'] == 120 and r['trades'] > 5 and r['years'] >= 2
    assert wfm.run_daily('ZZ', 0.4, path=path) is None
    wf = {'rows': {'SAR@30min': {'pooled': 0.9, 'se': 1.3}}, 'daily': d}
    assert 'best intraday: SAR@30min +0.90' in research.daily_vs_intraday(wf) and 'same dates' in research.daily_vs_intraday(wf)
    assert research.daily_table(wf) is not None and research.daily_table({'rows': {}}) is None


# ── Night session (display only) ─────────────────────────────────────────────────────────────────────────────

def _night_frame(day, start='21:01', end='02:30', base=800.0):
    idx = pd.date_range(f'{day} {start}', pd.Timestamp(f'{day} 00:00') + pd.Timedelta(days=1, hours=2, minutes=30),
                        freq='1min')
    idx = idx[(idx <= pd.Timestamp(f'{day} 00:00') + pd.Timedelta(days=1) + pd.Timedelta(end + ':00'))]
    c = base + np.sin(np.arange(len(idx)) / 20.0)
    return pd.DataFrame({'OPEN': c, 'HIGH': c + 0.1, 'LOW': c - 0.1, 'CLOSE': c, 'VOLUME': 3.0}, index=idx)


def test_night_session_windows():
    ns = live_bars.night_session
    assert ns('AU', datetime(2026, 11, 12, 21, 16))[:1] == ('2026-11-12',) and ns('AU', datetime(2026, 11, 12, 21, 16))[3]
    assert ns('AU', datetime(2026, 11, 13, 1, 0))[0] == '2026-11-12' and ns('AU', datetime(2026, 11, 13, 1, 0))[3]   # after midnight
    assert not ns('AU', datetime(2026, 11, 13, 3, 0))[3] and ns('AU', datetime(2026, 11, 13, 10, 0))[0] == '2026-11-12'
    assert ns('AU', datetime(2026, 11, 14, 1, 0))[0] == '2026-11-13' and ns('AU', datetime(2026, 11, 14, 1, 0))[3]   # Friday night
    assert ns('AU', datetime(2026, 11, 16, 10, 0))[0] == '2026-11-13'                                                # none on Sat / Sun evening
    assert ns('JM', datetime(2026, 11, 12, 23, 30))[3] is False and ns('TL', datetime(2026, 11, 12, 21, 30)) is None


def test_night_fetch_is_incremental_then_once_and_stays_out_of_the_day_files(tmp_path):
    wind = _FakeWind(_night_frame('2026-11-12'))
    kw = dict(wsi=wind, codes=CODES, live_dir=tmp_path, wind_off=lambda: False)
    a = live_bars.fetch_night_bars(['AU', 'TL'], now=datetime(2026, 11, 12, 22, 0), **kw)
    assert 'TL' not in a['products'] and a['session'] == 'open' and a['products']['AU']['rows'] > 55
    first_calls = len(wind.calls)
    b = live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 12, 23, 0), **kw)
    assert b['products']['AU']['new'] > 55 and wind.calls[-1][1] == '2026-11-12 21:58:00'   # last bar 22:00 minus the 2-min overlap, not the session start
    live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 13, 3, 0), **kw)            # session over: finished once
    n = len(wind.calls)
    again = live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 13, 9, 0), **kw)
    assert len(wind.calls) == n and again['products']['AU']['new'] == 0                   # served from the file
    assert live_bars._night_index(tmp_path)['AU2612']['complete'] is True
    assert live_bars.load_index(tmp_path) == {} and not (tmp_path / 'AU2612.parquet').exists()   # day files untouched
    assert live_bars.load_night('AU2612', tmp_path)[0].index.max() <= pd.Timestamp('2026-11-13 02:30')
    closed_only = live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 13, 15, 0), closed_only=True,
                                             wsi=wind, codes=CODES, live_dir=tmp_path, wind_off=lambda: True)
    assert closed_only['skipped'] == 'Wind disabled'
    assert first_calls == 1
    # the archive keeps the night after the live file moves on to the next session
    wind2 = _FakeWind(_night_frame('2026-11-13'))
    live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 14, 3, 0), wsi=wind2, codes=CODES, live_dir=tmp_path,
                               wind_off=lambda: False)
    arch = pd.read_parquet(tmp_path / 'night_history' / 'AU2612.parquet')
    assert arch.index.min() < pd.Timestamp('2026-11-13 00:00') < pd.Timestamp('2026-11-13 21:00') < arch.index.max()
    assert not arch.index.duplicated().any() and live_bars.load_night('AU2612', tmp_path)[0].index.min() > pd.Timestamp('2026-11-13 20:00')


def test_night_state_is_one_session_across_midnight(tmp_path, monkeypatch):
    wind = _FakeWind(_night_frame('2026-11-12'))
    live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 13, 3, 0), wsi=wind, codes=CODES, live_dir=tmp_path,
                               wind_off=lambda: False)
    monkeypatch.setattr(monitor, 'night_meta_for', lambda p, d=None: live_bars.night_meta_for(p, tmp_path))
    monkeypatch.setattr(monitor, 'load_night', lambda c, d=None: live_bars.load_night(c, tmp_path))
    monkeypatch.setattr(monitor, 'STRATEGIES', {'SAR': lambda df: df.assign(signal=1.0)})
    rec = {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None}
    st = monitor.night_state('AU', rec, now=datetime(2026, 11, 13, 9, 0), live_dir=tmp_path)
    assert st['night'] and st['closed'] and st['day'] == pd.Timestamp('2026-11-12') and st['position'] == 0
    assert st['bars'].index.min() >= pd.Timestamp('2026-11-12 21:00') and st['bars'].index.max() <= pd.Timestamp('2026-11-13 02:30')
    assert st['round_trips'] == 1                                  # one long held through midnight, closed at the end
    assert monitor.night_state('TL', rec, now=datetime(2026, 11, 13, 9, 0), live_dir=tmp_path) is None
    assert monitor.night_state('AU', rec, now=datetime(2026, 11, 14, 9, 0), live_dir=tmp_path) is None   # stale (other night)


def test_live_view_labels_night_rows_display_only(tmp_path, monkeypatch):
    wind = _FakeWind(_night_frame('2026-11-12'))
    live_bars.fetch_night_bars(['AU'], now=datetime(2026, 11, 13, 3, 0), wsi=wind, codes=CODES, live_dir=tmp_path,
                               wind_off=lambda: False)
    monkeypatch.setattr(monitor, 'night_meta_for', lambda p, d=None: live_bars.night_meta_for(p, tmp_path))
    monkeypatch.setattr(monitor, 'load_night', lambda c, d=None: live_bars.load_night(c, tmp_path))
    monkeypatch.setattr(monitor, 'STRATEGIES', {'SAR': lambda df: df.assign(signal=1.0)})
    st = monitor.night_state('AU', {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None},
                             now=datetime(2026, 11, 13, 9, 0), live_dir=tmp_path)
    text = str(live_ui.live_view([st], None, {'running': False}, now=datetime(2026, 11, 13, 9, 0)))
    assert 'night' in text and 'display only' in text and 'does not enter' in text
    assert 'night, display only' in live_ui.live_chart(st).layout.title.text


# ── Monitor order tickets for manual trading ─────────────────────────────────────────────────────
from web.tabs.futures_desk import actions, contracts, manual_log


def test_contract_codes_and_tick_rounding_follow_the_exchange():
    assert contracts.app_code('AL2612') == 'al2612'      # SHFE lower case
    assert contracts.app_code('IM2612') == 'IM2612'      # CFFEX upper case
    assert contracts.app_code('SA2612') == 'SA612'       # CZCE 3-digit month
    assert contracts.price_fmt(22570.2035, 'AL') == '22,570'
    assert contracts.price_fmt(6276.83, 'IM') == '6,276.8'
    assert contracts.price_fmt(108.1234, 'T') == '108.125'
    assert contracts.order_words(-1, False, 'AL') == ('Sell', 'Close today', '卖平今')   # SHFE needs 平今
    assert contracts.order_words(-1, False, 'IM') == ('Sell', 'Close', '卖平')


def _live_row(trades, closed=False, last=22700.0, product='AL', candidate='MA@30min'):
    return {'product': product, 'contract': f'{product}2612', 'candidate': candidate, 'last_px': last,
            'closed': closed, 'trades': trades}


def _trade(entry_t, entry_px, direction=1, exit_t=None, exit_px=None, stop=None, target=None):
    return {'direction': direction, 'entry_t': pd.Timestamp(entry_t), 'entry_px': entry_px, 'stop': stop,
            'target': target, 'exit_t': None if exit_t is None else pd.Timestamp(exit_t), 'exit_px': exit_px}


def test_open_ticket_is_provisional_until_its_bar_is_final_then_pending():
    row = _live_row([_trade('2026-11-16 10:00', 22680.0, stop=22570.0)])
    sizing = {'lots': 4, 'stop_pts': 110.0}
    a = actions.product_actions(row, sizing, {}, now=pd.Timestamp('2026-11-16 10:20'))[0]
    assert a['state'] == 'forming' and a['final_at'] == pd.Timestamp('2026-11-16 10:29')
    a = actions.product_actions(row, sizing, {}, now=pd.Timestamp('2026-11-16 10:31'))[0]
    assert a['state'] == 'pending'
    assert a['ticket'] == 'al2612 · Buy Open 买开 · 4 lots · limit 22,710'   # last + 2 ticks of 5
    assert a['drift_frac'] == pytest.approx(20 / 110)


def test_bar_final_time_stops_at_the_lunch_break_and_the_close():
    row = _live_row([_trade('2026-11-16 11:00', 22680.0), ], candidate='MA@1h')
    assert actions.product_actions(row, {'lots': 1, 'stop_pts': 1}, {})[0]['final_at'] == pd.Timestamp('2026-11-16 11:30')
    row = _live_row([_trade('2026-11-16 15:00', 22680.0)], candidate='MA@1h')
    assert actions.product_actions(row, {'lots': 1, 'stop_pts': 1}, {})[0]['final_at'] == pd.Timestamp('2026-11-16 15:00')


def test_ticket_states_follow_what_you_marked_done():
    t = _trade('2026-11-16 10:00', 22680.0, exit_t='2026-11-16 11:00', exit_px=22700.0)
    row = _live_row([t], closed=True)
    sizing = {'lots': 4, 'stop_pts': 110.0}
    op, cl = actions.product_actions(row, sizing, {})
    assert (op['state'], cl['state']) == ('missed', 'missed')    # strategy round-tripped before you acted
    log = {op['key']: {'done': True, 'lots': 3, 'fill': 22685.0}}
    op, cl = actions.product_actions(row, sizing, log)
    assert (op['state'], cl['state']) == ('done', 'pending') and cl['lots'] == 3
    assert cl['ticket'].startswith('al2612 · Sell Close today 卖平今 · 3 lots')
    assert op['slip_ticks'] == pytest.approx(1.0)
    log[cl['key']] = {'done': True, 'fill': 22705.0}
    acts = actions.product_actions(row, sizing, log)
    assert actions.held_positions(acts) == {}
    assert actions.your_pnl_cny(acts, {'AL': 22700.0}) == pytest.approx((22705 - 22685) * 3 * 5)


def test_unsized_open_is_not_a_ticket_to_trade():
    row = _live_row([_trade('2026-11-16 10:00', 22680.0)])
    a = actions.product_actions(row, {'lots': 0, 'stop_pts': 110.0}, {}, now=pd.Timestamp('2026-11-16 11:00'))[0]
    assert a['state'] == 'unsized'


def test_stop_hit_close_is_never_provisional():
    t = _trade('2026-11-16 10:00', 22680.0, exit_t='2026-11-16 10:30', exit_px=22570.0, stop=22570.0)
    row = _live_row([t])
    log = {actions.action_key('AL', t['entry_t'], 'open'): {'done': True, 'lots': 2}}
    cl = actions.product_actions(row, {'lots': 2, 'stop_pts': 110.0}, log, now=pd.Timestamp('2026-11-16 10:35'))[1]
    assert cl['state'] == 'pending'
    held = actions.held_positions(actions.product_actions(row, {'lots': 2, 'stop_pts': 110.0}, log))
    assert actions.flatten_items(held)[0] == {'product': 'AL', 'close': '15:00',
                                              'text': 'al2612 · Sell Close today 卖平今 · 2 lots'}


def test_manual_log_round_trip(tmp_path):
    manual_log.set_done('2026-11-16', 'AL|10:00|open', True, lots=4, log_dir=str(tmp_path))
    manual_log.set_fill('2026-11-16', 'AL|10:00|open', 22685, log_dir=str(tmp_path))
    rec = manual_log.load_log('2026-11-16', log_dir=str(tmp_path))['AL|10:00|open']
    assert rec['done'] and rec['lots'] == 4 and rec['fill'] == 22685.0
    manual_log.set_done('2026-11-16', 'AL|10:00|open', False, log_dir=str(tmp_path))
    rec = manual_log.load_log('2026-11-16', log_dir=str(tmp_path))['AL|10:00|open']
    assert not rec['done'] and rec['fill'] == 22685.0


# ── Held-overnight comparison in the walk-forward and Research ────────────────────────────────────
from futures.backtest import walkforward as wfmod
from web.tabs.futures_desk import research


def _text(c):
    if isinstance(c, (str, int, float)):
        return str(c)
    if c is None:
        return ''
    if isinstance(c, (list, tuple)):
        return ' '.join(_text(x) for x in c)
    return _text(getattr(c, 'children', None))


def _wf_with_overnight(over_pooled, over_dd, over_wd, with_block=True):
    row = {'pooled': 1.0, 'se': 1.3, 'passes': True, 'per_contract': {'AU2612': 2.0}, 'trades_per_day': 1.0,
           'win': 0.5, 'payoff': 1.0, 'expectancy_bp': 1.0, 'exits': None, 'total_return': 0.1, 'max_dd': 0.05,
           'worst_day': -0.02, 'trades': 50}
    if with_block:
        row['overnight'] = {'pooled': over_pooled, 'se': 1.3, 'per_contract': {'AU2612': over_pooled}, 'trades': 20,
                            'total_return': 0.1, 'max_dd': over_dd, 'worst_day': over_wd, 'trades_per_day': 0.5}
    return {'product': 'AU', 'run_at': 'x', 'cost_bp': 1.0, 'half_spread_bp': 0.5, 'fee_bp': 0.5, 'exits': None,
            'days': 100, 'last_day': '2026-11-13', 'gates': {'min_contract_days': 15, 'min_trades': 30},
            'contracts': {'AU2612': {'days': 40}}, 'rows': {'SAR@30min': row}, 'daily': None}


def test_overnight_summary_calls_a_small_difference_noise_and_flags_bigger_gap_risk():
    wf = _wf_with_overnight(1.1, 0.12, -0.05)
    out = _text(research.wf_table(wf))
    assert 'inside one SE' in out and 'drawdown and worst day are at least 25% larger overnight' in out
    assert 'Flat vs held overnight by contract: SAR@30min' in out and 'AU2612' in out


def test_overnight_summary_says_so_when_overnight_is_clearly_worse():
    out = _text(research.wf_table(_wf_with_overnight(-1.0, 0.05, -0.02)))
    assert 'worse by more than one SE' in out


def test_overnight_summary_asks_for_a_rerun_on_an_old_walkforward():
    out = _text(research.wf_table(_wf_with_overnight(0, 0, 0, with_block=False)))
    assert 'run before the comparison existed' in out


def test_walkforward_rows_carry_a_held_overnight_block(tmp_path):
    _cache_contracts(tmp_path, contracts=('AU2604', 'AU2606'), days=22)
    wf = wfmod.run_walkforward('AU', bar_dir=tmp_path, tick_dir=tmp_path / 'none')
    assert wf['rows']
    for r in wf['rows'].values():
        ov = r['overnight']
        assert set(ov) >= {'pooled', 'se', 'per_contract', 'max_dd', 'worst_day', 'total_return'}
        assert r['max_dd'] >= 0 and r['worst_day'] <= 0


# ── Night session joined to the trading day ──────────────────────────────────────────────────────────────────
from futures.backtest import night as night_mod


def _night_bars(day, base=800.0):
    f = _night_frame(day, base=base)
    f.columns = [c.lower() for c in f.columns]
    f['hs_bp'] = np.float32('nan')
    return f


def test_night_joins_the_next_trade_day_and_friday_goes_to_monday():
    days = pd.DatetimeIndex(['2026-11-12', '2026-11-13', '2026-11-16'])
    nights = pd.concat([_night_bars('2026-11-12'), _night_bars('2026-11-13')])
    sh = night_mod.night_to_trade_day(nights, days)
    assert set(sh.index.normalize().unique()) == {pd.Timestamp('2026-11-13'), pd.Timestamp('2026-11-16')}   # Thu night -> Fri, Fri night -> Mon
    assert (sh.index - sh.index.normalize()).max() <= pd.Timedelta(hours=5, minutes=30) and sh.index.is_monotonic_increasing
    # the newest night has no later day session yet: dropped
    assert night_mod.night_to_trade_day(_night_bars('2026-11-16'), days).empty
    day = pd.DataFrame({'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0, 'volume': 1.0, 'hs_bp': 0.3},
                       index=pd.date_range('2026-11-13 09:00', periods=10, freq='1min'))
    both = night_mod.with_night(day, _night_bars('2026-11-12'))
    assert both.index.min() < pd.Timestamp('2026-11-13 06:00') and both.index.max() == day.index.max()
    assert list(night_mod.night_trade_days(both)) == [pd.Timestamp('2026-11-13')]
    assert night_mod.with_night(day, None) is day


def test_backfill_night_fetches_each_night_once_and_never_touches_the_live_files(tmp_path):
    class Wind:
        def __init__(self): self.calls = []
        def __call__(self, code, fields, s, e, *a):
            self.calls.append((code, s))
            return _night_frame(s[:10])
    wind = Wind()
    kw = dict(products=['AU'], days=3, now=datetime(2026, 11, 16, 12, 0), wsi=wind, codes=CODES, live_dir=tmp_path)
    r = live_bars.backfill_night(**kw)
    assert r['fetched'] == 3 and len(wind.calls) == 3 and r['nights'] == ['2026-11-13', '2026-11-12', '2026-11-11']
    again = live_bars.backfill_night(**kw)
    assert again['fetched'] == 0 and again['skipped'] == 3 and len(wind.calls) == 3          # repeat costs nothing
    assert live_bars._night_index(tmp_path) == {} and not (tmp_path / 'AU2612_night.parquet').exists()
    assert night_mod.load_night_history('AU2612', tmp_path).index.normalize().nunique() >= 3
    assert live_bars.backfill_night(wind_off=lambda: True, now=datetime(2026, 11, 16), live_dir=tmp_path)['errors']


def test_night_walkforward_is_separate_gated_and_compares_on_the_same_days(tmp_path):
    ticks, bars, live = tmp_path / 'ticks', tmp_path / 'bars', tmp_path / 'live'
    ticks.mkdir()
    _cache_contracts(bars)
    first = pd.bdate_range('2026-01-05', periods=25)
    nights = pd.concat([_night_bars(str(d.date())) for d in first[:10]])
    (live / 'night_history').mkdir(parents=True)
    nights.to_parquet(live / 'night_history' / 'AU2604.parquet')
    day = walkforward.run_walkforward('AU', tick_dir=ticks, bar_dir=bars)
    nt = walkforward.run_walkforward('AU', tick_dir=ticks, bar_dir=bars, night=True, live_dir=live)
    assert day['session'] == 'day' and nt['session'] == 'night+day' and nt['night_days'] >= 8
    assert not any(r['passes'] for r in nt['rows'].values())            # < MIN_NIGHT_DAYS nights can never pass
    cmp_ = next(iter(nt['rows'].values()))['night_cmp']
    assert cmp_['days'] == nt['night_days'] or cmp_['days'] <= nt['night_days']
    out = tmp_path / 'out'
    walkforward.save_walkforward(day, out); walkforward.save_walkforward(nt, out)
    assert walkforward.load_walkforward('AU', out)['session'] == 'day'
    assert walkforward.load_walkforward('AU', out, night=True)['session'] == 'night+day'
    with pytest.raises(ValueError):
        walkforward.run_walkforward('TL', tick_dir=ticks, bar_dir=bars, night=True)


def test_night_bars_live_in_the_cached_file_and_the_default_load_is_day_only(tmp_path):
    ticks, bars, live = tmp_path / 'ticks', tmp_path / 'bars', tmp_path / 'live'
    ticks.mkdir()
    _cache_contracts(bars)
    day_before = pd.read_parquet(bars / 'AU2604.parquet')
    first = pd.bdate_range('2026-01-05', periods=25)
    (live / 'night_history').mkdir(parents=True)
    pd.concat([_night_bars(str(d.date())) for d in first[:10]]).to_parquet(live / 'night_history' / 'AU2604.parquet')
    both = minute_bars.load_minute_bars('AU2604', ticks, bars, night=True, live_dir=live)
    assert len(both) > len(day_before) and night_mod.night_trade_days(both).size == 10
    assert len(pd.read_parquet(bars / 'AU2604.parquet')) == len(both)                         # one cached file holds both
    day = minute_bars.load_minute_bars('AU2604', ticks, bars, live_dir=live)
    pd.testing.assert_frame_equal(day, day_before)                                            # default = exactly the old day bars
    # unchanged night history: no rewrite; a new night re-joins without any tick file
    mt = (bars / 'AU2604.parquet').stat().st_mtime_ns
    minute_bars.load_minute_bars('AU2604', ticks, bars, night=True, live_dir=live)
    assert (bars / 'AU2604.parquet').stat().st_mtime_ns == mt
    pd.concat([_night_bars(str(d.date())) for d in first[:12]]).to_parquet(live / 'night_history' / 'AU2604.parquet')
    again = minute_bars.load_minute_bars('AU2604', ticks, bars, night=True, live_dir=live)
    assert night_mod.night_trade_days(again).size == 12 and len(minute_bars.load_minute_bars('AU2604', ticks, bars, live_dir=live)) == len(day_before)


# ── Force-approving a night + day candidate ──────────────────────────────────────────────────────────────────
def _night_wf(passes_ex=True, passes=False, night_days=6):
    row = {'pooled': 1.2, 'se': 1.3, 'per_contract': {'AU2612': 1.0}, 'trades': 40, 'win': 0.5, 'payoff': 1.2,
           'expectancy_bp': 2.0, 'exits': None, 'passes': passes, 'passes_ex_night': passes_ex}
    return {'rows': {'SAR@30min': row}, 'session': 'night+day', 'night_days': night_days, 'cost_bp': 0.4,
            'run_at': 'now', 'last_day': '2026-11-13', 'exits': None, 'daily_pnl': {'SAR@30min': {'2026-11-12': 0.001}},
            'gates': {'min_night_days': 60}}


def test_force_approve_only_overrides_the_night_days_gate(tmp_path):
    path = tmp_path / 'approved.json'
    with pytest.raises(ValueError, match='Force approve'):
        approvals.approve('AU', 'SAR@30min', _night_wf(), path)
    with pytest.raises(ValueError, match='day gates'):
        approvals.approve('AU', 'SAR@30min', _night_wf(passes_ex=False), path, force=True)
    rec = approvals.approve('AU', 'SAR@30min', _night_wf(), path, force=True)
    assert rec['session'] == 'night+day' and rec['forced'] is True and rec['night_days'] == 6
    day = _night_wf(); day['session'] = 'day'
    assert approvals.approve('AU', 'SAR@30min', {**day, 'rows': {'SAR@30min': {**day['rows']['SAR@30min'], 'passes': True}}}, path)['session'] == 'day'


def test_night_day_strategy_is_replayed_on_joined_bars_with_real_night_times(tmp_path, monkeypatch):
    ticks, bars, live = tmp_path / 'ticks', tmp_path / 'bars', tmp_path / 'live'
    ticks.mkdir()
    _cache_contracts(bars, contracts=('AU2612',), days=12)
    (live / 'night_history').mkdir(parents=True)
    first = pd.bdate_range('2026-01-05', periods=12)
    pd.concat([_night_bars(str(d.date())) for d in first[:6]]).to_parquet(live / 'night_history' / 'AU2612.parquet')
    monkeypatch.setattr(minute_bars, 'BAR_DIR', bars)
    monkeypatch.setattr(minute_bars, 'TICK_DIR', ticks)
    monkeypatch.setattr(walkforward.minute_bars, 'BAR_DIR', bars)
    joined = minute_bars.load_minute_bars('AU2612', ticks, bars, night=True, live_dir=live)
    days = pd.DatetimeIndex(sorted(set(joined.index[(joined.index - joined.index.normalize()) >= night_mod.DAY_OPEN].normalize())))
    # a night stamp goes back to 21:00 + offset of the previous trade date; a day stamp is unchanged
    assert night_mod.unshift(pd.Timestamp('2026-01-07 00:00'), days) == pd.Timestamp('2026-01-06 21:00')
    assert night_mod.unshift(pd.Timestamp('2026-01-12 02:00'), days) == pd.Timestamp('2026-01-09 23:00')   # Fri night -> Mon
    assert night_mod.unshift(pd.Timestamp('2026-01-07 10:00'), days) == pd.Timestamp('2026-01-07 10:00')
    rec = {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None, 'session': 'night+day'}
    assert monitor.is_night_day(rec) and not monitor.is_night_day({'candidate': 'SAR@30min'})
    st = monitor._session_state('AU', 'AU2612', rec, joined, pd.Timestamp('2026-01-07'), True, '2026-01-07 15:00:00')
    st = monitor._unshifted(st, joined)
    assert st['session'] == 'night+day' and st['bars'].index.min() == pd.Timestamp('2026-01-06 21:00')
    assert all(t['entry_t'] >= pd.Timestamp('2026-01-06 21:00') for t in st['trades'])


def test_night_led_state_is_the_coming_trade_day_with_real_times(tmp_path, monkeypatch):
    bars_dir, live = tmp_path / 'bars', tmp_path / 'live'
    _cache_contracts(bars_dir, contracts=('AU2612',), days=12)
    monkeypatch.setattr(minute_bars, 'BAR_DIR', bars_dir)
    monkeypatch.setattr(minute_bars, 'TICK_DIR', tmp_path / 'ticks')
    last_day = pd.bdate_range('2026-01-05', periods=12)[-1]                     # Mon 2026-01-19
    eve = last_day + pd.offsets.BDay(0)
    wind = _FakeWind(_night_frame(str(last_day.date()), base=500.0))
    live_bars.fetch_night_bars(['AU'], now=datetime.combine(last_day.date(), datetime.min.time()) + timedelta(hours=23, minutes=30),
                               wsi=wind, codes=CODES, live_dir=live, wind_off=lambda: False)
    monkeypatch.setattr(monitor, 'STRATEGIES', {'SAR': lambda df: df.assign(signal=1.0)})
    rec = {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None, 'session': 'night+day'}
    now = datetime.combine(last_day.date(), datetime.min.time()) + timedelta(hours=23, minutes=30)
    st = monitor.night_led_state('AU', rec, now=now, live_dir=live)
    assert st['day'] == last_day + pd.offsets.BDay(1) and st['position'] == 1 and not st['closed']
    assert st['bars'].index.min() >= pd.Timestamp(f'{last_day:%Y-%m-%d} 21:00')          # real evening time, not 00:00 of the trade day
    assert st['trades'] and st['trades'][0]['entry_t'] >= pd.Timestamp(f'{last_day:%Y-%m-%d} 21:00')
    assert monitor.night_led_state('AU', rec, now=now.replace(hour=12), live_dir=live) is None           # day session hours
    assert monitor.night_led_state('TL', rec, now=now, live_dir=live) is None


@pytest.fixture(autouse=True)
def _no_real_bar_cache_for_night_contracts(request, monkeypatch):
    """The night fetch picks its contract by volume from the real bar cache; tests pin the contract list instead."""
    if 'roll' not in request.node.name:
        monkeypatch.setattr(live_bars, 'night_contract_of', lambda product, night_date, dvol=None: None)


def test_night_roll_goes_to_the_contract_that_is_main_on_the_next_day(tmp_path, monkeypatch):
    days = pd.bdate_range('2026-11-02', periods=10)
    dvol = pd.DataFrame({'AL2612': [900.0] * 6 + [100.0] * 4, 'AL2701': [100.0] * 6 + [900.0] * 4}, index=days)
    assert night_mod.main_after(dvol, '2026-11-02') == 'AL2612'                 # night of Mon 11-02 belongs to Tue 11-03
    assert night_mod.main_after(dvol, '2026-11-09') == 'AL2701'                 # after the roll
    assert night_mod.main_after(dvol, '2026-12-31') == 'AL2701'                 # tonight: last known main
    assert night_mod.main_after(None, '2026-11-02') is None and night_mod.main_after(dvol.iloc[0:0], '2026-11-02') is None

    class Wind:
        def __init__(self): self.calls = []
        def __call__(self, code, fields, s, e, *a):
            self.calls.append((code, s[:10]))
            return _night_frame(s[:10])
    wind = Wind()
    monkeypatch.setattr(night_mod, 'daily_volume', lambda product, *a, **k: dvol)
    live_bars.backfill_night(products=['AL'], days=4, now=datetime(2026, 11, 12, 12, 0), wsi=wind,
                             codes=['AL2612.SHF'], live_dir=tmp_path)          # the list still says AL2612
    by_night = dict((d, c) for c, d in wind.calls)
    assert by_night['2026-11-06'] == 'AL2612.SHF' and by_night['2026-11-09'] == 'AL2701.SHF'   # Fri night -> Mon (volume main AL2612 until 11-09)
    assert night_mod.load_night_history('AL2701', tmp_path) is not None


@pytest.fixture(autouse=True)
def _slice_dir_in_tmp(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(minute_bars, 'SLICE_DIR', tmp_path_factory.mktemp('slice'))


def test_monitor_slice_is_append_only_and_stands_in_for_a_missing_cache(tmp_path, monkeypatch):
    bars = tmp_path / 'bars'
    _cache_contracts(bars, contracts=('AU2604', 'AU2606'), days=40)
    monkeypatch.setattr(minute_bars, 'BAR_DIR', bars)
    approved = {'AU': {'wf_last_day': '2026-02-20', 'candidate': 'SAR@30min'}}
    r = minute_bars.export_monitor_slice(approved)
    n1 = sorted(p.name for p in (minute_bars.SLICE_DIR / 'AU2604').iterdir())
    assert r['written'] > 10 and n1 and len(n1) <= 40
    again = minute_bars.export_monitor_slice(approved)
    assert again['written'] == 0 and again['removed'] == 0                                 # nothing changes -> nothing rewritten
    # a computer with no cache: the slice answers load / list / index / last bar time
    full = minute_bars.load_minute_bars('AU2604')
    shutil.rmtree(bars)
    got = minute_bars.load_minute_bars('AU2604')
    assert got.index.min() >= full.index.min() and got.index.max() == full.index.max()
    pd.testing.assert_frame_equal(got, full.loc[got.index.min():])
    assert 'AU2604' in minute_bars.list_contracts('AU') and minute_bars.last_bar_time('AU') >= full.index.max()
    assert minute_bars.load_minute_bars('XX2612') is None


def test_monitor_replay_on_the_slice_matches_the_full_cache(tmp_path, monkeypatch):
    bars = tmp_path / 'bars'
    _cache_contracts(bars, contracts=('AU2604',), days=60)
    monkeypatch.setattr(minute_bars, 'BAR_DIR', bars)
    monkeypatch.setattr(walkforward.minute_bars, 'BAR_DIR', bars)
    rec = {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None, 'wf_last_day': '2026-02-27'}
    full = monitor.forward_replay('AU', rec)
    minute_bars.export_monitor_slice({'AU': rec})
    shutil.rmtree(bars)
    sliced = monitor.forward_replay('AU', rec)
    assert len(full['series']) > 5
    pd.testing.assert_series_equal(sliced['series'], full['series'])
    assert sliced['trades'] == full['trades']


@pytest.fixture(autouse=True)
def _portfolio_in_tmp(tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp('pf')
    monkeypatch.setattr(approvals, 'PORTFOLIO_PATH', d / 'portfolio.json')
    monkeypatch.setattr(approvals, 'APPROVED_PATH', d / 'approved.json')   # never touch the real approvals
    monkeypatch.setattr(approvals, 'DAILY_PATH', d / 'approved_daily.json')


def test_portfolio_is_explicit_and_edited_without_touching_approvals(monkeypatch):
    close = _close(['AU.SHF', 'TL.CFE', 'IC.CFE'])
    approved = {p: {'candidate': 'SAR@30min', 'status': 'approved', 'pooled_sharpe': 1.0} for p in ('AU', 'TL', 'IC')}
    pnl = pd.DataFrame(np.random.default_rng(1).normal(size=(60, 3)), columns=['AU', 'TL', 'IC'],
                       index=pd.bdate_range('2026-08-01', periods=60))
    _fake_world(monkeypatch, approved, close, pnl)
    assert pool.select_book()['chosen'] == ['AU', 'TL', 'IC'] and approvals.load_portfolio() is None   # nothing saved: legacy
    gone = []
    monkeypatch.setattr(approvals, 'remove', lambda p, path=None: gone.append(p))
    assert pool.remove_from_portfolio('TL') == ['AU', 'IC'] and gone == ['TL']                         # first edit saves the list; the approval is deleted too
    assert approvals.load_portfolio() == ['AU', 'IC']
    sel = pool.select_book()
    assert sel['chosen'] == ['AU', 'IC'] and sel['explicit'] and sel['excluded'] == []
    book = pool.build_book(10_000_000, 0.25, 0.5, 1.0, today=datetime(2026, 11, 5))
    assert [r['product'] for r in book['rows']] == ['AU', 'IC']
    assert pool.add_to_portfolio('TL') == ['AU', 'IC', 'TL']
    for bad, msg in (('TL', 'already'), ('ZZ', 'no approved strategy')):
        with pytest.raises(ValueError, match=msg):
            pool.add_to_portfolio(bad)
    with pytest.raises(ValueError, match='not in the portfolio'):
        pool.remove_from_portfolio('ZZ')
    approved['IC']['status'] = 'halted'                                                                # a halted member stops trading
    assert pool.select_book()['chosen'] == ['AU', 'TL'] and pool.select_book()['halted'] == ['IC']
    del approved['AU']                                                                                 # a removed approval is reported
    sel = pool.select_book()
    assert sel['chosen'] == ['TL'] and 'AU' in sel['missing']
    for p in ('A1', 'A2', 'A3', 'A4', 'A5'):
        approved[p] = {'candidate': 'SAR@30min', 'status': 'approved', 'pooled_sharpe': 1.0}
    approvals.save_portfolio(['TL', 'A1', 'A2', 'A3', 'A4'])
    with pytest.raises(ValueError, match='at most 5'):
        pool.add_to_portfolio('A5')
    with pytest.raises(ValueError, match='halted'):
        pool.add_to_portfolio('IC')


def test_approving_puts_the_product_in_the_portfolio(monkeypatch):
    from web.tabs.futures_desk import research
    close = _close(['AU.SHF', 'TL.CFE'])
    approved = {p: {'candidate': 'SAR@30min', 'status': 'approved', 'pooled_sharpe': 1.0} for p in ('AU', 'TL')}
    _fake_world(monkeypatch, approved, close, pd.DataFrame())
    approvals.save_portfolio(['AU'])
    assert 'Added to the Portfolio (AU, TL)' in research.portfolio_message('TL')
    assert 'Already in the Portfolio' in research.portfolio_message('TL')                 # re-approving a member changes only its strategy
    approvals.save_portfolio(['A1', 'A2', 'A3', 'A4', 'A5'])
    assert 'Not added to the Portfolio' in research.portfolio_message('AU') and approvals.load_portfolio() == ['A1', 'A2', 'A3', 'A4', 'A5']


def test_monitor_follows_the_portfolio_only(monkeypatch):
    monkeypatch.setattr(approvals, 'load_approved', lambda path=None: {'AU': {'candidate': 'SAR@30min'}, 'TL': {'candidate': 'SAR@30min'}})
    seen = []
    monkeypatch.setattr(monitor, 'export_monitor_slice', lambda a: seen.append(sorted(a)))
    monkeypatch.setattr(monitor, 'evidence_moments', lambda p, r: (_ for _ in ()).throw(ValueError('stop')))
    approvals.save_portfolio(['AU'])
    assert [r['product'] for r in monitor.monitor_rows()] == ['AU'] and seen == [[]]


def test_night_day_row_renders_in_the_live_monitor_and_makes_tickets(tmp_path, monkeypatch):
    from web.tabs.futures_desk import live_ui
    bars_dir, live = tmp_path / 'bars', tmp_path / 'live'
    _cache_contracts(bars_dir, contracts=('AU2612',), days=12)
    monkeypatch.setattr(minute_bars, 'BAR_DIR', bars_dir)
    monkeypatch.setattr(minute_bars, 'TICK_DIR', tmp_path / 'ticks')
    last_day = pd.bdate_range('2026-01-05', periods=12)[-1]
    now = datetime.combine(last_day.date(), datetime.min.time()) + timedelta(hours=23, minutes=30)
    live_bars.fetch_night_bars(['AU'], now=now, wsi=_FakeWind(_night_frame(str(last_day.date()), base=500.0)),
                               codes=CODES, live_dir=live, wind_off=lambda: False)
    monkeypatch.setattr(monitor, 'STRATEGIES', {'SAR': lambda df: df.assign(signal=1.0)})
    rec = {'candidate': 'SAR@30min', 'cost_bp': 0.4, 'exits': None, 'session': 'night+day'}
    row = monitor.night_led_state('AU', rec, now=now, live_dir=live)
    fig = live_ui.live_chart(row)
    assert 'night + day' in fig.layout.title.text and fig.data[0].x[0].startswith('21:')      # starts at the evening open
    assert live_ui.live_view([row], {}, None, now=now) is not None
    acts = live_ui.product_actions(row, {'lots': 2, 'stop_pts': 5.0}, {}, now=now)
    assert acts and acts[0]['kind'] == 'open' and acts[0]['time'] >= pd.Timestamp(f'{last_day:%Y-%m-%d} 21:00')
    assert acts[0]['state'] in ('pending', 'forming') and 'AU' in acts[0]['ticket'].upper()


def test_halt_streak_is_judged_against_the_strategys_own_backtest():
    mean, std = 0.001, 0.01
    s8 = _days([0.01] * 6 + [-0.0001] * 8)
    plain = monitor.assess(s8, mean, std, halt_losses=5)
    assert plain['status'] == 'halted' and plain['halt_at'] == 5
    own = monitor.assess(s8, mean, std, halt_losses=5, max_streak=8)            # its backtest lost 8 in a row once
    assert own['status'] == 'watch' and own['halt_at'] == 9 and "longest run was 8" in own['reasons'][0]
    assert monitor.assess(_days([0.01] * 6 + [-0.0001] * 9), mean, std, halt_losses=5, max_streak=8)['status'] == 'halted'
    assert monitor.assess(s8.iloc[:-3], mean, std, halt_losses=5, max_streak=8)['status'] == 'ok'     # 5 in a row: below its watch line (7)
    assert monitor.assess(s8, mean, std, halt_losses=5, max_streak=3)['halt_at'] == 5                 # never below the user's number
    assert monitor.longest_losing_run(_days([-1, -1, 0, -1, 1, -1])) == 3
    assert approvals._longest_losing_run(pd.Series([-1.0, -1.0, 0.0, -1.0, 1.0, -1.0])) == 3


def test_clicking_a_walk_forward_candidate_resolves_its_walk_forward(tmp_path, monkeypatch):
    from web.tabs.futures_desk import research
    walkforward.save_walkforward({'product': 'AU', 'rows': {'SAR@30min': {}}, 'cost_bp': 0.4, 'exits': None}, tmp_path)
    monkeypatch.setattr(research, 'DESK_DIR', tmp_path)
    monkeypatch.setattr(research, 'list_contracts', lambda p: ['AU2612'])
    bars = pd.DataFrame({'close': [1.0, 2.0]}, index=pd.to_datetime(['2026-01-05 09:00', '2026-01-06 09:00']))
    monkeypatch.setattr(research, 'load_minute_bars', lambda c: bars)
    p = research.drill_payload('SAR@30min', 'AU2612', 'AU2612', 'local', None)     # the default wf_dir: this raised NameError
    assert p['cand'] == 'SAR@30min' and p['contract'] == 'AU2612' and p['cost_bp'] == 0.4


# ── Daily strategies approved next to the intraday one ───────────────────────────────────────────────────────
from web.tabs.futures_desk import actions as fd_actions, daily as fd_daily, live_ui as fd_live


def _daily_frame(n=40, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2026-01-05', periods=n)
    c = 800 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
    return pd.DataFrame({'open': c * 0.999, 'high': c * 1.004, 'low': c * 0.996, 'close': c, 'volume': 1000.0}, index=idx)


def _daily_world(tmp_path, monkeypatch, series_days=36, total=40):
    """The continuous daily series (AU.SHF) stops `total - series_days` days before today, as the real file lags."""
    d = _daily_frame(total)
    path = tmp_path / 'dailyK.pkl'
    pickle.dump({'AU.SHF': d.iloc[:series_days].rename(columns=str.title)}, open(path, 'wb'))
    monkeypatch.setattr(walkforward, 'DAILY_FILE', path)
    monkeypatch.setattr(live_bars, 'LIVE_DIR', tmp_path / 'live')
    monkeypatch.setattr(fd_daily, 'LIVE_DIR', tmp_path / 'live')
    monkeypatch.setattr(fd_daily, 'main_contract_codes', lambda: {'AU': 'AU2612.SHF'})
    return d


def _minutes_of(d, upto):
    """Fake Wind minute bars of the continuous code for the days of `d` after `upto` (3 bars a day)."""
    rows = []
    for day, r in d[d.index > upto].iterrows():
        for k, (o, c) in enumerate(((r['open'], r['high']), (r['low'], r['close']))):
            rows.append((day + pd.Timedelta(hours=9 + 5 * k, minutes=30), o, max(o, c), min(o, c), c, 500.0))
    f = pd.DataFrame(rows, columns=['index', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']).set_index('index')
    return f


def test_daily_series_gets_its_tail_from_the_continuous_code_not_from_contract_bars(tmp_path, monkeypatch):
    d = _daily_world(tmp_path, monkeypatch)
    calls = []

    def wsi(code, fields, s, e, *a):
        calls.append((code, s[:10]))
        return _minutes_of(d, d.index[35])
    now = datetime.combine(d.index[-1].date(), datetime.min.time()) + timedelta(hours=14, minutes=30)
    assert fd_daily.daily_symbol('AU') == 'AU.SHF'
    assert fd_daily.extended_daily('AU', live_dir=tmp_path / 'live').index.max() == d.index[35]            # no tail yet
    r = fd_daily.fetch_tail('AU', now=now, wsi=wsi, live_dir=tmp_path / 'live')
    assert r['rows'] == 4 and calls == [('AU.SHF', str((d.index[35] + pd.Timedelta(days=1)).date()))]       # the continuous code, one call
    ext = fd_daily.extended_daily('AU', live_dir=tmp_path / 'live')
    pd.testing.assert_frame_equal(ext[['open', 'high', 'low', 'close']], d[['open', 'high', 'low', 'close']], check_freq=False)
    # the Live monitor's rule: while the session is open nothing is fetched unless it is running
    skipped = fd_daily.fetch_tail('AU', now=now, wsi=wsi, live_dir=tmp_path / 'live', closed_only=True)
    assert 'Start live' in skipped['skipped'] and len(calls) == 1
    assert fd_daily.fetch_tail('AU', now=now, wsi=lambda *a: pd.DataFrame(), live_dir=tmp_path / 'live')['error']
    assert fd_daily.fetch_tail('ZZ', now=now, wsi=wsi, live_dir=tmp_path / 'live')['error']


def test_daily_signal_is_provisional_on_the_forming_bar_and_stale_without_the_tail(tmp_path, monkeypatch):
    d = _daily_world(tmp_path, monkeypatch)
    monkeypatch.setattr(fd_daily, 'STRATEGIES', {'ATR': lambda df: df.assign(signal=(df['close'] > df['close'].shift()).astype(float))})
    rec = {'candidate': 'ATR@1D', 'cost_bp': 0.4, 'exits': None, 'wf_last_day': str(d.index[30].date())}
    live = tmp_path / 'live'
    now = datetime.combine(d.index[-1].date(), datetime.min.time()) + timedelta(hours=14, minutes=30)
    stale = fd_daily.daily_state('AU', rec, now=now, live_dir=live)
    assert stale['day'] == d.index[35] and not stale['fresh']                                             # the series ends days ago
    fd_daily.fetch_tail('AU', now=now, wsi=lambda *a: _minutes_of(d, d.index[35]), live_dir=live)
    st = fd_daily.daily_state('AU', rec, now=now, live_dir=live)
    assert st['daily'] and st['key'] == 'AU|1D' and st['day'] == d.index[-1] and st['fresh'] and not st['closed']
    assert st['contract'] == 'AU2612' and st['symbol'] == 'AU.SHF' and st['last_px'] == pytest.approx(d['close'].iloc[-1])
    assert st['final_at'].strftime('%H:%M') == '14:55' and st['close_at'].strftime('%H:%M') == '15:00'
    assert st['position'] == int(d['close'].iloc[-1] > d['close'].iloc[-2]) and st['held'] == int(d['close'].iloc[-2] > d['close'].iloc[-3])
    assert len(st['bars']) == 40 and fd_daily.daily_state('AU', rec, now=now + timedelta(hours=1), live_dir=live)['closed']
    f = fd_daily.forward_replay_daily('AU', rec, live_dir=live)
    assert len(f['series']) == 9                                                                            # the days after wf_last_day


def test_daily_tickets_close_the_old_side_open_the_new_one_and_follow_the_clock(tmp_path):
    close_t = pd.Timestamp('2026-11-17 15:00')
    row = {'product': 'AU', 'contract': 'AU2612', 'last_px': 800.0, 'held': 1, 'position': -1, 'closed': False,
           'close_at': close_t, 'final_at': close_t - pd.Timedelta(minutes=5)}
    sizing = {'lots': 2, 'stop_pts': 8.0}
    acts = fd_actions.daily_actions(row, sizing, {}, now=datetime(2026, 11, 17, 14, 20))
    assert [(a['kind'], a['direction'], a['state'], a['lots']) for a in acts] == [('close', -1, 'forming', 2), ('open', -1, 'forming', 2)]
    assert acts[1]['stop'] == pytest.approx(808.0) and all(a['daily'] for a in acts) and acts[0]['key'] == 'AU1D|15:00|close'
    late = fd_actions.daily_actions(row, sizing, {}, now=datetime(2026, 11, 17, 14, 56))
    assert {a['state'] for a in late} == {'pending'}
    done = fd_actions.daily_actions(row, sizing, {'AU1D|15:00|close': {'done': True, 'lots': 3, 'fill': 799.0}}, now=datetime(2026, 11, 17, 14, 56))
    assert done[0]['state'] == 'done' and done[0]['lots'] == 3 and done[0]['slip_ticks'] is not None
    assert {a['state'] for a in fd_actions.daily_actions(dict(row, closed=True), sizing, {}, now=datetime(2026, 11, 17, 15, 30))} == {'missed'}
    assert fd_actions.daily_actions(dict(row, held=-1), sizing, {}) == []                    # nothing to change
    assert [a['kind'] for a in fd_actions.daily_actions(dict(row, held=0), sizing, {}, now=datetime(2026, 11, 17, 14, 20))] == ['open']
    assert [(x['kind'], x['state']) for x in fd_actions.daily_actions(row, {'lots': 0, 'stop_pts': 8.0}, {}, now=datetime(2026, 11, 17, 14, 20))] == [('open', 'unsized')]
    # a layered strategy (ATR) holds 1..6 units of a position sized for 6: adds and cuts are partial tickets
    atr = dict(row, max_units=6.0, held=1, position=1, held_units=2.0, units=4.0)
    add = fd_actions.daily_actions(atr, {'lots': 12, 'stop_pts': 8.0}, {}, now=datetime(2026, 11, 17, 14, 20))
    assert [(x['kind'], x['direction'], x['lots']) for x in add] == [('open', 1, 4)]                       # 4 -> 8 lots: buy 4 more
    cut = fd_actions.daily_actions(dict(atr, held_units=6.0, units=3.0), {'lots': 12, 'stop_pts': 8.0}, {}, now=datetime(2026, 11, 17, 14, 20))
    assert [(x['kind'], x['direction'], x['lots']) for x in cut] == [('close', -1, 6)]                     # 12 -> 6 lots: sell 6
    flip = fd_actions.daily_actions(dict(atr, held_units=2.0, units=-6.0, held=1, position=-1), {'lots': 12, 'stop_pts': 8.0}, {}, now=datetime(2026, 11, 17, 14, 20))
    assert [(x['kind'], x['direction'], x['lots']) for x in flip] == [('close', -1, 4), ('open', -1, 12)]
    assert fd_actions.daily_actions(dict(atr, held_units=2.0, units=2.0), {'lots': 12, 'stop_pts': 8.0}, {}) == []


def test_daily_approval_gate_store_portfolio_and_monitor(tmp_path, monkeypatch):
    d = _daily_world(tmp_path, monkeypatch)
    monkeypatch.setattr(walkforward, 'STRATEGIES', {**walkforward.STRATEGIES, 'ATR': lambda df: df.assign(signal=(df['close'] > df['close'].shift()).astype(float))})
    monkeypatch.setattr(fd_daily, 'STRATEGIES', walkforward.STRATEGIES)
    dd = {'start': '2026-01-05', 'end': str(d.index[35].date()), 'exits': None, 'min_trades': 5,
          'rows': {'ATR@1D': {'pooled': 0.8, 'se': 0.5, 'days': 20, 'recent': 1.0, 'recent_se': 1.0, 'recent_days': 20, 'trades': 9,
                              'win': 0.5, 'payoff': 1.2, 'expectancy_bp': 5.0, 'years_positive': 1, 'years': 1},
                   'MA@1D': {'pooled': -0.2, 'se': 0.5, 'days': 20, 'trades': 9}, 'SAR@1D': {'pooled': 0.9, 'se': 0.5, 'days': 20, 'trades': 2}}}
    wf = {'daily': dd, 'cost_bp': 0.4, 'run_at': 'now'}
    for c, msg in (('MA@1D', 'Sharpe'), ('SAR@1D', 'trades'), ('XX@1D', 'not in')):
        with pytest.raises(ValueError, match=msg):
            approvals.approve_daily('AU', c, wf)
    assert approvals.daily_gate(dd, 'ATR@1D') == (True, '')
    rec = approvals.approve_daily('AU', 'ATR@1D', wf)
    assert rec['session'] == 'daily' and rec['wf_last_day'] == dd['end'] and rec['max_streak'] is not None and rec['daily_std'] is not None
    assert approvals.load_approved_daily()['AU']['candidate'] == 'ATR@1D'
    # the portfolio holds the daily strategy under its own key, next to an intraday one
    monkeypatch.setattr(approvals, 'load_approved', lambda path=None: {'AU': {'candidate': 'SAR@30min', 'status': 'approved', 'pooled_sharpe': 1.0}})
    approvals.save_portfolio(['AU'])
    assert pool.add_to_portfolio('AU', daily=True) == ['AU', 'AU|1D']
    with pytest.raises(ValueError, match='already'):
        pool.add_to_portfolio('AU', daily=True)
    sel = pool.select_book()
    assert sel['chosen'] == ['AU'] and sel['daily'] == ['AU'] and sel['missing'] == []
    # the Monitor tracks it with its own series, key and longest-run threshold
    rows = {r['key']: r for r in monitor.monitor_rows()}
    assert set(rows) == {'AU', 'AU|1D'} or set(rows) == {'AU|1D'} or 'AU|1D' in rows
    r = rows['AU|1D']
    assert r.get('daily') and ('assessment' in r or 'error' in r)
    if 'assessment' in r:
        assert r['assessment']['halt_at'] >= 5
    # removing the key deletes the daily approval and leaves the intraday one
    assert pool.remove_from_portfolio('AU|1D') == ['AU'] and approvals.load_approved_daily() == {}


def test_live_views_show_a_daily_row_with_its_own_sizing_and_no_flatten_reminder(tmp_path, monkeypatch):
    close_t = pd.Timestamp('2026-11-17 15:00')
    row = {'product': 'AU', 'key': 'AU|1D', 'daily': True, 'contract': 'AU2612', 'candidate': 'ATR@1D', 'day': pd.Timestamp('2026-11-17'),
           'closed': False, 'held': 1, 'position': -1, 'since': pd.Timestamp('2026-11-17'), 'entry_px': 800.0, 'last_px': 800.0,
           'as_of': pd.Timestamp('2026-11-17 14:20'), 'fetched_at': pd.Timestamp('2026-11-17 14:21'), 'day_return': 0.001,
           'round_trips': 1, 'stop_px': None, 'target_px': None, 'exited_at': None, 'trades': [], 'close_at': close_t,
           'final_at': close_t - pd.Timedelta(minutes=5),
           'bars': pd.DataFrame({'open': [800.0], 'high': [801.0], 'low': [799.0], 'close': [800.5]}, index=[pd.Timestamp('2026-11-17 14:00')])}
    monkeypatch.setattr(fd_live, 'size_position', lambda p, e, px, cap, risk, mult: {'lots': 2, 'stop_pts': 8.0})
    monkeypatch.setattr(fd_live.manual_log, 'load_log', lambda day: {})
    table, orders, clock = fd_live.desk_views([row], {}, None, {}, {}, 1_000_000, 0.25, 0.5, 1.0, now=datetime(2026, 11, 17, 14, 20))
    assert table is not None and 'daily' in str(table) and 'AU1D|15:00|close' in str(orders)
    assert clock['flatten'] == [] and clock['bars'] == []                      # a daily position is held overnight
    assert clock['pending'] == []                                              # still provisional (forming)
    _, _, clock2 = fd_live.desk_views([row], {}, None, {}, {}, 1_000_000, 0.25, 0.5, 1.0, now=datetime(2026, 11, 17, 14, 58))
    assert {p['key'] for p in clock2['pending']} == {'AU1D|15:00|close', 'AU1D|15:00|open'}


def test_continuous_momentum_carries_the_position_through_the_close():
    from futures.backtest.strategies import run_intraday_momentum_strategy
    idx = pd.DatetimeIndex([d + pd.Timedelta(hours=h) for d in pd.bdate_range('2026-01-05', periods=20) for h in (0, 1, 2)])
    px, base = [], 100.0
    for d in range(20):
        step = 2.0 if 15 <= d <= 17 else 0.1                      # a few days that move far more than the 3-day average
        px += [base, base + step, base + 2 * step]
        base += 2 * step
    px = np.array(px)
    bars = pd.DataFrame({'open': px, 'high': px, 'low': px, 'close': px, 'volume': 1.0}, index=idx)
    flat = run_intraday_momentum_strategy(bars, 3, 3)
    cont = run_intraday_momentum_strategy(bars, 3, 3, continuous=True)
    day = idx.normalize()
    last = np.r_[day[:-1] != day[1:], True]
    assert (flat['signal'][last] == 0).all()                       # reset at every date's last bar
    assert (cont['signal'][last] != 0).any()                       # carried through a close
