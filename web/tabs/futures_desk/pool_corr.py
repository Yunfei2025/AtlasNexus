# -*- coding: utf-8 -*-
"""Futures Desk > Today: correlation of the futures pool and its 5 least-correlated members."""

from __future__ import annotations

import glob
import os

from dash.dependencies import Input, Output
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from web.tabs.beta.data import THEME

from . import approvals
from .pool import daily_panels, least_correlated, pnl_panel, select_book

CORR_TOP_N = 5
CORR_LOOKBACK_DAYS = {'6M': 126, '1Y': 252, '3Y': 756}


def _pnl_candidates():
    """Product -> (candidate, why) for every stored walk-forward run: the approved strategy, else the
    best passing candidate, else the best pooled Sharpe (flagged as not passing)."""
    from futures.backtest.walkforward import load_walkforward
    approved = approvals.load_approved()
    out = {}
    for path in sorted(glob.glob(str(approvals.DESK_DIR / 'wf_*.json'))):
        prod = os.path.basename(path)[3:-5]
        rows = (load_walkforward(prod, approvals.DESK_DIR) or {}).get('rows') or {}
        if not rows:
            continue
        cand = (approved.get(prod) or {}).get('candidate')
        why = 'approved'
        if cand not in rows:
            passing = [k for k, r in rows.items() if r['passes']]
            cand = max(passing or rows, key=lambda k: rows[k]['pooled'])
            why = 'best passing' if passing else 'best, not passing'
        out[prod] = (cand, why)
    return out


def _book_corr():
    """Strategy-P&L correlation among the members of today's book (blank where two have too little overlap)."""
    sel = select_book()
    corr = sel['corr']
    if corr is None or len(sel['chosen']) < 2:
        raise ValueError("today's book needs at least 2 approved products with walk-forward P&L")
    names = sel['chosen']
    off = corr.where(~pd.DataFrame(np.eye(len(names), dtype=bool), index=names, columns=names)).abs()
    what = "strategy P&L of today's book: " + ", ".join(f"{p} {sel['candidates'][p]}" for p in names)
    if sel['excluded']:
        what += f" (not in book, more correlated: {', '.join(sel['excluded'])})"
    return corr, names, float(np.nanmean(off.values)), what, pnl_panel(sel['candidates'])


def _corr_heatmap(basis, lookback):
    if basis == 'book':
        corr, names, mean_abs, what, series = _book_corr()
    elif basis == 'pnl':
        cands = _pnl_candidates()
        series = pnl_panel({p: c for p, (c, _) in cands.items()})
        if series.shape[1] < 2:
            raise ValueError("Strategy P&L needs walk-forward runs for at least 2 products (Research tab)")
        corr = series.corr(min_periods=20).fillna(1.0)
        n = min(CORR_TOP_N, len(corr))
        names, mean_abs = least_correlated(corr, n)
        what = "strategy P&L of " + ", ".join(f"{p} {cands[p][0]} ({cands[p][1]})" for p in names)
    else:
        panel = daily_panels()[0]
        window = panel.tail(CORR_LOOKBACK_DAYS.get(lookback, 252) + 1)
        series = window.pct_change(fill_method=None).iloc[1:] if basis == 'returns' else window
        # Drop symbols listed mid-window; tolerate data gaps (pairwise correlation over overlapping days)
        series = series.dropna(axis=1, thresh=int(len(series) * 0.75))
        corr = series.corr(min_periods=20).fillna(1.0)  # no overlap -> treat as correlated
        if len(corr) < CORR_TOP_N:
            raise ValueError(f"only {len(corr)} futures with enough history in {lookback}")
        names, mean_abs = least_correlated(corr, CORR_TOP_N)
        what = 'daily returns' if basis == 'returns' else 'price levels'
    sub = corr.loc[names, names].mask(pd.DataFrame(np.eye(len(names), dtype=bool), index=names, columns=names))
    labels = [s.split('.')[0] for s in names]
    # Diverging blue (-1) / gray (0) / red (+1)
    fig = go.Figure(go.Heatmap(
        z=sub.values, x=labels, y=labels, zmin=-1, zmax=1,
        colorscale=[[0, '#3987e5'], [0.5, '#383835'], [1, '#e66767']],
        text=sub.map(lambda v: '' if pd.isna(v) else f'{v:.2f}').values, texttemplate='%{text}',
        textfont={'size': 10, 'color': '#e9eef8'},
        hovertemplate='%{y} / %{x}<br>ρ = %{z:.2f}<extra></extra>',
        xgap=2, ygap=2, colorbar={'thickness': 8, 'len': 0.9, 'tickfont': {'size': 9}},
    ))
    fig.update_layout(
        height=230, template=THEME['chart_template'],
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font={'color': '#e9eef8', 'size': 10}, margin=dict(l=36, r=6, t=6, b=24),
        yaxis={'autorange': 'reversed'},
    )
    last = series.index.max()
    note = f"{len(series)} days to {last:%Y-%m-%d} · {what} · mean |ρ| {mean_abs:.2f} · from {len(corr)} names"
    return fig, note


def register_pool_corr_callbacks(app):
    @app.callback(
        [Output('bf-corr-graph', 'figure'), Output('bf-corr-note', 'children'), Output('bf-corr-badge', 'children')],
        [Input('fd-data-stamp', 'data'),
         Input('bf-corr-basis', 'value'),
         Input('bf-corr-lookback', 'value')],
    )
    def bf_update_correlation(_stamp, basis, lookback):
        badge = "book members" if basis == 'book' else f"{CORR_TOP_N} least correlated"
        try:
            fig, note = _corr_heatmap(basis, lookback)
        except Exception as e:
            return go.Figure(), f"Correlation unavailable: {e}", badge
        return fig, note, badge
