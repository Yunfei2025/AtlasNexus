import numpy as np
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
from datetime import datetime

from web.tabs.futures_desk import pool, pool_corr


def _fake_world(monkeypatch, approved, close, pnl):
    monkeypatch.setattr(pool.approvals, 'load_approved', lambda path=None: approved)
    monkeypatch.setattr(pool, 'daily_panels', lambda: (close, close))
    monkeypatch.setattr(pool, 'pnl_panel', lambda cands: pnl[list(cands)])
    monkeypatch.setattr(pool, 'intraday_state', lambda prod, cand, exits=None: {
        'contract': f'{prod}2612', 'last_price': 100.0, 'last_time': datetime(2026, 11, 4, 15, 30),
        'signal': 1.0, 'since': pd.Timestamp('2026-11-04 10:00')})


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
        assert r['risk_cny'] <= 25_000 and r['stop_price'] == pytest.approx(100.0 - r['stop_pts'])
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
    monkeypatch.setattr(monitor, 'load_minute_bars', lambda c: hist)
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
    monkeypatch.setattr(monitor, 'load_minute_bars', lambda c: hist)
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
