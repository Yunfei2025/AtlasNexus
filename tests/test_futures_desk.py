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
    monkeypatch.setattr(pool, 'intraday_state', lambda prod, cand: {
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
                 'cost_bp': 0.42, 'start': '2026-10-05', 'end': '2026-10-07'}
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
