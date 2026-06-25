# -*- coding: utf-8 -*-
"""Build the FICC monthly report panel (本期资产配置（风险预算权重）) and the
report-data.json payload from the cached Backtest > Portfolio results, then
render/download the PDF via web.services.report_render.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dash import dash_table, dcc, html
from dash.dependencies import Input, Output, State

from multiasset.data import (
    calculate_daily_returns_series, get_asset_type, get_asset_yield_series, load_raw_market_data,
)
from multiasset.factor_backtest import compute_portfolio_metrics
from web.services.artifacts import project_root
from web.services.report_render import render_report_pdf

from ..data import THEME

REPORT_DIR = project_root() / "docs" / "report"
REPORT_DATA_PATH = REPORT_DIR / "report-data.json"
REPORT_PDF_PATH = REPORT_DIR / "CMBC_FICC_Allocation_index.pdf"

_ASSET_CLASS_GROUP = {
    'Rates': '固定收益',
    'Spread': '固定收益',
    'FX': '外汇',
    'Commodities': '大宗商品',
    'Equities': '权益',
}
_GROUP_COLORS = {
    '固定收益': '#0B2447',
    '外汇': '#2EC4B6',
    '大宗商品': '#E0A458',
    '权益': '#7A6FBE',
}
_SEGMENT_PALETTE = ['#0B2447', '#2E4D7B', '#2EC4B6', '#45A0C9', '#E0A458', '#C97B3D', '#7A6FBE', '#9C8AD1']


def build_allocation_panel(weights_final: dict, weights_prev: dict | None,
                            start_date: str, end_date: str) -> html.Div:
    """本期资产配置（风险预算权重） — current weights, Δ vs prior rebalance, start/end prices."""
    market_data = load_raw_market_data()
    weights_prev = weights_prev or {}
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    rows = []
    for name, weight in sorted(weights_final.items(), key=lambda kv: -kv[1]):
        prev_w = weights_prev.get(name, 0.0)
        asset_type = get_asset_type(name)
        price_label = "Yield (%)" if asset_type in ('Rates', 'Spread') else "Price"

        try:
            series, *_ = get_asset_yield_series(name, market_data)
        except Exception:
            series = None

        start_px = end_px = None
        if series is not None and not series.empty:
            s = series.sort_index()
            s.index = pd.to_datetime(s.index)
            asof_start = s.asof(start_ts)
            asof_end = s.asof(end_ts)
            start_px = float(asof_start) if pd.notna(asof_start) else None
            end_px = float(asof_end) if pd.notna(asof_end) else None

        start_str = f"{start_px:.4f}" if start_px is not None else "N/A"
        end_str = f"{end_px:.4f}" if end_px is not None else "N/A"
        rows.append({
            'Asset': name,
            'Weight (%)': round(weight * 100, 1),
            'Δ vs Prior (pp)': round((weight - prev_w) * 100, 1),
            'Price @ Start': f"{start_str} ({price_label})",
            'Price @ End': f"{end_str} ({price_label})",
        })

    if not rows:
        return html.Div("No allocation data available — run the backtest first.",
                         style={'color': THEME['warning'], 'padding': '15px'})

    df = pd.DataFrame(rows)
    df = df[['Asset', 'Weight (%)', 'Δ vs Prior (pp)', 'Price @ Start', 'Price @ End']]

    table = dash_table.DataTable(
        data=df.to_dict('records'),
        columns=[{'name': c, 'id': c} for c in df.columns],
        style_cell={
            'textAlign': 'left', 'padding': '8px 10px', 'fontFamily': 'Arial, sans-serif',
            'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'],
            'border': 'none', 'fontSize': '12px',
        },
        style_header={
            'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
            'fontWeight': 'bold', 'textAlign': 'left', 'border': 'none',
        },
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
            {'if': {'filter_query': '{Δ vs Prior (pp)} > 0', 'column_id': 'Δ vs Prior (pp)'},
             'color': THEME['success']},
            {'if': {'filter_query': '{Δ vs Prior (pp)} < 0', 'column_id': 'Δ vs Prior (pp)'},
             'color': THEME['danger']},
        ],
        style_table={'overflowX': 'auto'},
    )

    return html.Div([
        html.H5(f"📊 本期资产配置（风险预算权重） — {pd.Timestamp(end_date).strftime('%Y-%m-%d')} 生效",
                style={'color': THEME['text_main'], 'marginBottom': '10px'}),
        html.P(f"价格验证区间：{start_ts.strftime('%Y-%m-%d')}（期初） ~ {end_ts.strftime('%Y-%m-%d')}（期末）。"
               f"国债/利差类资产展示的是到期收益率（%），外汇/商品展示现价。",
               style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic',
                      'marginBottom': '10px'}),
        table,
    ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})


def _last_month_slice(nav_dates: list[str], nav_values: list[float]) -> tuple[pd.Series, pd.Series]:
    """Split a NAV series into (last 1 calendar month, trailing 12 months)."""
    s = pd.Series(nav_values, index=pd.to_datetime(nav_dates)).sort_index()
    if s.empty:
        return s, s
    last_date = s.index[-1]
    month_start = last_date.replace(day=1)
    monthly = s[s.index >= month_start]
    twelve_m_start = last_date - pd.DateOffset(months=12)
    trailing = s[s.index >= twelve_m_start]
    return monthly, trailing


def _asset_color_map(*weight_dicts: dict) -> dict[str, str]:
    """Stable name -> color assignment shared across both periods' donuts, grouped by asset class."""
    all_names: dict[str, float] = {}
    for weights in weight_dicts:
        for name, w in weights.items():
            all_names[name] = max(all_names.get(name, 0.0), w)

    by_group: dict[str, list[str]] = {}
    for name, w in all_names.items():
        group = _ASSET_CLASS_GROUP.get(get_asset_type(name), '其他')
        by_group.setdefault(group, []).append(name)

    color_map = {}
    color_i = 0
    for group in ['固定收益', '外汇', '大宗商品', '权益', '其他']:
        for name in sorted(by_group.get(group, []), key=lambda n: -all_names[n]):
            color_map[name] = _SEGMENT_PALETTE[color_i % len(_SEGMENT_PALETTE)]
            color_i += 1
    return color_map


def _donut_segments(weights: dict, color_map: dict[str, str]) -> list[dict]:
    by_group: dict[str, list[tuple[str, float]]] = {}
    for name, w in weights.items():
        group = _ASSET_CLASS_GROUP.get(get_asset_type(name), '其他')
        by_group.setdefault(group, []).append((name, w))

    segments = []
    for group in ['固定收益', '外汇', '大宗商品', '权益', '其他']:
        for name, w in sorted(by_group.get(group, []), key=lambda kv: -kv[1]):
            segments.append({
                'name': name,
                'value': round(w * 100, 1),
                'color': color_map.get(name, _SEGMENT_PALETTE[0]),
                'group': group,
            })
    return segments


def _allocation_changes(weights_final: dict, weights_prev: dict) -> list[dict]:
    """Per-asset weight change (本期变动, pp) — union of assets held this period or last."""
    names = sorted(
        set(weights_final) | set(weights_prev),
        key=lambda n: -(weights_final.get(n, 0.0) - weights_prev.get(n, 0.0)),
    )
    deltas = [round((weights_final.get(n, 0.0) - weights_prev.get(n, 0.0)) * 100, 1) for n in names]
    max_abs_delta = max((abs(d) for d in deltas), default=1.0) or 1.0
    return [
        {'name': name, 'delta': delta, 'maxAbsDelta': max_abs_delta}
        for name, delta in zip(names, deltas)
    ]


def _returns_table_groups(weights: dict, month_start: pd.Timestamp, month_end: pd.Timestamp) -> list[dict]:
    """Per-asset total return over the period, with start/end price (yield for Rates/Spread),
    grouped like the donut segments, for verification alongside the return figure."""
    market_data = load_raw_market_data()
    by_group: dict[str, list[dict]] = {}
    max_abs_ret = 0.0
    asset_rets = {}
    asset_px = {}
    for name in weights:
        df = calculate_daily_returns_series(name, market_data, month_start, month_end)
        ret = float(df['total'].sum()) if not df.empty and 'total' in df else 0.0
        asset_rets[name] = ret
        max_abs_ret = max(max_abs_ret, abs(ret))

        asset_type = get_asset_type(name)
        is_yield = asset_type in ('Rates', 'Spread')
        try:
            series, *_ = get_asset_yield_series(name, market_data)
        except Exception:
            series = None
        start_px = end_px = None
        if series is not None and not series.empty:
            s = series.sort_index()
            s.index = pd.to_datetime(s.index)
            asof_start = s.asof(month_start)
            asof_end = s.asof(month_end)
            start_px = float(asof_start) if pd.notna(asof_start) else None
            end_px = float(asof_end) if pd.notna(asof_end) else None
        fmt = (lambda v: f"{v:.4f}%") if is_yield else (lambda v: f"{v:.4f}")
        asset_px[name] = {
            'start': fmt(start_px) if start_px is not None else 'N/A',
            'end': fmt(end_px) if end_px is not None else 'N/A',
        }
    max_abs_ret = max(max_abs_ret, 1e-6)

    for name, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        group = _ASSET_CLASS_GROUP.get(get_asset_type(name), '其他')
        ret = asset_rets.get(name, 0.0)
        px = asset_px.get(name, {'start': 'N/A', 'end': 'N/A'})
        by_group.setdefault(group, []).append({
            'asset': name,
            'return': f"{ret:+.2%}",
            'returnClass': 'pos' if ret >= 0 else 'neg',
            'barWidth': round(min(abs(ret) / max_abs_ret, 1.0) * 50, 1),
            'priceStart': px['start'],
            'priceEnd': px['end'],
        })

    return [{'group': g, 'items': items} for g, items in by_group.items() if items]


def _cum_return_points(*series_list: pd.Series) -> list[list[tuple[float, float]]]:
    """Map daily NAV series to cumulative-return curves sharing one y-scale, in the
    template's 300x90 viewBox (x:0-300, y:2-85, inverted). Each series is rebased to
    its own first value so multiple lines (gross/net) share a common 0%-return origin."""
    cum_series = []
    for s in series_list:
        s = s.dropna()
        if len(s) < 2:
            cum_series.append(pd.Series(dtype=float))
            continue
        cum_series.append(s / s.iloc[0] - 1.0)

    all_vals = [v for s in cum_series for v in s.values]
    if not all_vals:
        return [[] for _ in series_list]
    lo, hi = min(all_vals), max(all_vals)
    span = max(hi - lo, 1e-9)

    result = []
    for s in cum_series:
        if len(s) < 2:
            result.append([])
            continue
        n = len(s)
        points = [
            ((i / (n - 1)) * 300.0, 85.0 - ((v - lo) / span) * 75.0)
            for i, v in enumerate(s.values)
        ]
        result.append(points)
    return result


def build_report_data(*, weights_final: dict, weights_prev: dict | None,
                       nav_gross: pd.Series, nav_net: pd.Series,
                       start_date: str, end_date: str, rebalance_date: str,
                       alloc_mode: str, commentary_lines: list[str]) -> dict:
    """Assemble a report-data.json-shaped dict from cached backtest results.

    The "period" reviewed by the KPIs and returns table is the backtest's own
    start_date -> end_date window (not a calendar-month slice) — for short
    backtests (e.g. a single month with one rebalance) this still lets the
    report show real daily-data-driven PnL between period start and end.
    """
    weights_prev = weights_prev or {}
    period_gross = nav_gross[(nav_gross.index >= pd.Timestamp(start_date)) &
                              (nav_gross.index <= pd.Timestamp(end_date))]
    period_net = nav_net[(nav_net.index >= pd.Timestamp(start_date)) &
                          (nav_net.index <= pd.Timestamp(end_date))]
    _, trailing_gross = _last_month_slice(
        list(map(str, nav_gross.index)), list(nav_gross.values))

    perf_period = compute_portfolio_metrics(period_gross) if len(period_gross) > 1 else {}
    perf_12m = compute_portfolio_metrics(trailing_gross) if len(trailing_gross) > 1 else {}

    month_ret_gross = (period_gross.iloc[-1] / period_gross.iloc[0] - 1) if len(period_gross) > 1 else 0.0
    month_ret_net = (period_net.iloc[-1] / period_net.iloc[0] - 1) if len(period_net) > 1 else 0.0
    max_dd_month = perf_period.get('Max Drawdown', 0.0) or 0.0
    sharpe_12m = perf_12m.get('Sharpe', 0.0) or 0.0
    report_period_label = f"{pd.Timestamp(start_date).strftime('%Y-%m-%d')} 至 {pd.Timestamp(end_date).strftime('%Y-%m-%d')}"
    report_month_label = f"{pd.Timestamp(start_date).strftime('%Y 年 %-m 月')}"

    kpis = [
        {"label": "FICC-RP 月度收益", "value": f"{month_ret_gross:+.2%}",
         "valueClass": "pos" if month_ret_gross >= 0 else "neg",
         "delta": "基准指数（纯风险预算）", "accent": False},
        {"label": "FICC-RP 净收益（扣除交易成本）", "value": f"{month_ret_net:+.2%}",
         "valueClass": "pos" if month_ret_net >= 0 else "neg",
         "delta": "扣除交易成本后", "accent": True},
        {"label": "月内最大回撤", "value": f"{max_dd_month:.2%}",
         "valueClass": "neg", "delta": "本期回测窗口内"},
        {"label": "滚动 12 月夏普比率", "value": f"{sharpe_12m:.2f}",
         "valueClass": "", "delta": "FICC-RP"},
        {"label": "本月再平衡", "value": pd.Timestamp(rebalance_date).strftime('%Y-%m-%d'),
         "valueClass": "", "delta": "常规月度再平衡"},
    ]

    color_map = _asset_color_map(weights_final, weights_prev)
    segments = _donut_segments(weights_final, color_map)
    segments_prev = _donut_segments(weights_prev, color_map)
    allocation_changes = _allocation_changes(weights_final, weights_prev)

    # Risk contribution by asset class — weight-proportional (no covariance data cached)
    by_group_weight: dict[str, float] = {}
    for name, w in weights_final.items():
        group = _ASSET_CLASS_GROUP.get(get_asset_type(name), '其他')
        by_group_weight[group] = by_group_weight.get(group, 0.0) + w
    total_w = sum(by_group_weight.values()) or 1.0
    risk_contribution = [
        {"name": g, "percentage": round(w / total_w * 100), "color": _GROUP_COLORS.get(g, '#7A6FBE')}
        for g, w in sorted(by_group_weight.items(), key=lambda kv: -kv[1])
    ]

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if start_ts < end_ts:
        returns_table = _returns_table_groups(weights_final, start_ts, end_ts)
        returns_period_label = f"{start_ts.strftime('%Y-%m-%d')} ~ {end_ts.strftime('%Y-%m-%d')}"
    else:
        returns_table = []
        returns_period_label = report_period_label

    rp_points, net_points = _cum_return_points(period_gross, period_net)
    nav_chart = {"rp": rp_points, "net": net_points}

    markers = ["①", "②", "③", "④"]
    commentary = [{"marker": markers[i], "text": line} for i, line in enumerate(commentary_lines[:4])]

    return {
        "report": {
            "title": "民生FICC配置指数",
            "subtitle": "CMBC FICC Allocation Index · 风险预算驱动的 FICC 系统化配置策略",
            "reportMonth": report_month_label,
            "reportPeriod": report_period_label,
            "returnsPeriod": returns_period_label,
            "publishDate": datetime.now().strftime('%Y-%m-%d'),
        },
        "kpis": kpis,
        "allocation": {
            "effectiveDate": pd.Timestamp(rebalance_date).strftime('%Y-%m-%d'),
            "segments": segments,
            "segmentsPrev": segments_prev,
            "changes": allocation_changes,
        },
        "returns": returns_table,
        "riskContribution": risk_contribution,
        "navChart": nav_chart,
        "commentary": commentary,
        "footer": "本报告基于民生FICC配置指数规则化编制流程自动生成（回测数据），数据来源：中债登、CFETS、上期所/INE、LME。历史表现不代表未来收益，不构成投资建议。",
    }


def register_report_export_callbacks(app):
    @app.callback(
        Output('risk-budget-allocation-panel', 'children'),
        Output('report-commentary-input', 'value'),
        Output('report-commentary-container', 'style'),
        Input('backtest-results-store', 'data'),
        prevent_initial_call=True,
    )
    def render_allocation_panel(results):
        if not results:
            return html.Div(), "", {'display': 'none'}

        weights_final = results['weights_final']
        weights_prev = results.get('weights_prev')
        panel = build_allocation_panel(
            weights_final, weights_prev, results['start_date'], results['end_date'])

        largest = max(weights_final.items(), key=lambda kv: kv[1]) if weights_final else (None, 0)
        deltas = {k: weights_final[k] - (weights_prev or {}).get(k, 0.0) for k in weights_final}
        biggest_move = max(deltas.items(), key=lambda kv: abs(kv[1])) if deltas else (None, 0)
        draft = [
            f"{largest[0]} 为本期最大权重资产，占比 {largest[1] * 100:.1f}%。" if largest[0] else "",
            f"{biggest_move[0]} 权重较上次再平衡变动 {biggest_move[1] * 100:+.1f}pp，为本期最大调整。" if biggest_move[0] else "",
            f"本期回测区间 {results['start_date']} 至 {results['end_date']}，按月再平衡，风险预算权重保持均衡配置。",
            "下期展望：建议关注跨资产相关性与利率方向变化，作为下一次风险预算再平衡的关键变量。",
        ]
        return panel, "\n".join(draft), {'display': 'block', 'backgroundColor': THEME['bg_card'],
                                          'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}

    @app.callback(
        Output('report-meta-store', 'data'),
        Output('dl-report-button', 'disabled'),
        Output('report-status-message', 'children'),
        Input('gen-report-button', 'n_clicks'),
        State('backtest-results-store', 'data'),
        State('report-commentary-input', 'value'),
        prevent_initial_call=True,
    )
    def generate_report(n_clicks, results, commentary_text):
        if not results:
            return None, True, html.Span(
                "⚠️ Run the backtest first (no results cached).", style={'color': THEME['warning']})

        try:
            nav_gross = pd.Series(results['nav_gross_values'],
                                   index=pd.to_datetime(results['nav_dates']))
            nav_net = pd.Series(results['nav_net_values'],
                                 index=pd.to_datetime(results['nav_dates']))
            commentary_lines = [l for l in (commentary_text or "").split("\n") if l.strip()]

            report_data = build_report_data(
                weights_final=results['weights_final'],
                weights_prev=results.get('weights_prev'),
                nav_gross=nav_gross,
                nav_net=nav_net,
                start_date=results['start_date'],
                end_date=results['end_date'],
                rebalance_date=results['rebalance_date'],
                alloc_mode=results.get('alloc_mode', 'risk_parity'),
                commentary_lines=commentary_lines,
            )

            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(REPORT_DATA_PATH, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)

            render_report_pdf(report_data, REPORT_PDF_PATH)

            return (
                {'path': str(REPORT_PDF_PATH)},
                False,
                html.Span(f"✅ Report generated: {REPORT_PDF_PATH.name}", style={'color': THEME['success']}),
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return None, True, html.Span(f"❌ Error: {e}", style={'color': THEME['danger']})

    @app.callback(
        Output('report-download', 'data'),
        Input('dl-report-button', 'n_clicks'),
        State('report-meta-store', 'data'),
        prevent_initial_call=True,
    )
    def download_report(n_clicks, meta):
        if not meta or not meta.get('path'):
            return None
        path = Path(meta['path'])
        if not path.exists():
            return None
        return dcc.send_file(str(path))
