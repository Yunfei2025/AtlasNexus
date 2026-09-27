# -*- coding: utf-8 -*-
"""Table/chart construction for the RFBT "Run Backtest" results panel:
the performance+IC metrics table and the per-factor 5-panel
(Level/Signal/Position/IC/PnL) stacked chart."""

from __future__ import annotations

from dash import html, dcc, dash_table
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ...data import THEME


def _sig_color(v):
    if v > 0:
        return THEME['success']
    if v < 0:
        return THEME['danger']
    return THEME['text_sub']


def build_metrics_table(results, factor_stats) -> "dash_table.DataTable":
    """Build the Performance & IC Statistics table.

    No blanket risk-free-rate deduction here: 'position' is a
    signal-strength scalar in [-1, 1] (or [0, 1] for long-only),
    not a leveraged capital allocation — it rarely approaches 1.0,
    so strategy_returns has a much smaller vol than a fully-invested
    portfolio would. Subtracting RiskModelConfig.RISK_FREE_RATE (2%,
    calibrated for compute_portfolio_metrics on an actual NAV series
    in backtest_hist.py) swamps this factor-level return/vol scale
    and produces wildly negative Sharpe unrelated to signal quality
    (e.g. -17 instead of -0.3 for the same P&L). RF-rate adjustment
    belongs at the portfolio/NAV level, not the per-factor diagnostic.

    As of docs/plans/beta_book_exposure_vs_capital.md Step 3,
    'strategy_returns' / 'strategy_returns_gross' /
    'strategy_returns_gross_of_funding' are IDENTICAL for every
    factor — no cost of any kind (transaction cost or funding) is
    modelled at the factor level any more; carry and funding both
    moved to the book level (multiasset/book/). NO funding hurdle
    is applied to Sharpe here, deliberately: this diagnostic's
    return series has no carry in it any more (Step 3 made it
    price-only), so there is nothing for a funding cost to net
    against — deducting one anyway double-penalises the signal
    (it would charge the cost of financing a position whose
    carry benefit was already stripped out). The funding hurdle
    belongs at the BOOK level (backtest_hist's "Sharpe
    (post-funding)"), where real notional is actually held and
    actually financed — see multiasset/book/funding.py.
    """
    from multiasset.factor_backtest import compute_metrics, get_factor_weighted_duration

    metric_rows = []
    for factor, df in results.items():
        m = compute_metrics(df, risk_free_rate=0.0, geometric_annualisation=True)
        # 'Sharpe(gr)' reads strategy_returns_gross — identical to
        # 'strategy_returns' for every factor today (no cost of any
        # kind, transaction or funding, is modelled at the factor
        # level any more), so 'Sharpe(gr)' == 'Sharpe' everywhere.
        # Left in place as the seam for when a real per-leg
        # transaction-cost model is reintroduced (see
        # factor_tx_cost_per_unit), at which point the two will
        # diverge again by that cost alone.
        if 'strategy_returns_gross' in df.columns:
            m_gross = compute_metrics(
                df.assign(strategy_returns=df['strategy_returns_gross']),
                risk_free_rate=0.0, geometric_annualisation=True,
            )
        else:
            m_gross = m
        # Ann Ret is the factor's own realized return. Prefers
        # the explicit gross_of_funding column (FactorModel); falls
        # back to strategy_returns_gross (MA/Bollinger/Momentum/
        # Z-Score) — both are identical to 'strategy_returns' now,
        # but kept as the explicit "pre-cost return" read for this
        # row rather than relying on that equivalence.
        if 'strategy_returns_gross_of_funding' in df.columns:
            ann_ret_col = 'strategy_returns_gross_of_funding'
        elif 'strategy_returns_gross' in df.columns:
            ann_ret_col = 'strategy_returns_gross'
        else:
            ann_ret_col = 'strategy_returns'
        m_ann_ret = compute_metrics(
            df.assign(strategy_returns=df[ann_ret_col]),
            risk_free_rate=0.0, geometric_annualisation=True,
        )
        # Buy & Hold reference: what the factor itself earned held
        # outright (position=1 always), i.e. 'returns' un-scaled by
        # the model's signal. 'Ann Ret' above is the STRATEGY's own
        # realized return (position-scaled — often << B&H when the
        # model sits flat or under-sized much of the time, e.g. an
        # avg |position| of 0.3 and flat 36% of days on IRDL.CN
        # nets ~1% vs B&H's ~2.9%, purely from position sizing, not
        # from carry/return being computed wrong). Shown side by
        # side so a low 'Ann Ret' isn't mistaken for a broken carry
        # calculation when it's really the model choosing not to be
        # fully invested.
        if 'returns' in df.columns:
            m_bh = compute_metrics(
                df.assign(strategy_returns=df['returns']),
                risk_free_rate=0.0, geometric_annualisation=True,
            )
        else:
            m_bh = {}
        avg_turnover = float(df['turnover'].abs().mean()) if 'turnover' in df.columns else 0.0
        # Max daily position move in B/day (position ±1 = ±10B → ×10). Feasibility check.
        if 'position' in df.columns:
            max_dpos_b = float(df['position'].diff().abs().max()) * 10.0
        else:
            max_dpos_b = 0.0
        s = factor_stats[factor]
        # Weighted duration — rates factors only (IRDL/IRSL/IRCV)
        w_dur = get_factor_weighted_duration(factor)
        dur_str = f"{w_dur:.2f}y" if w_dur is not None else '—'
        metric_rows.append({
            'Factor':    factor,
            'Duration':  dur_str,
            'Ann Ret':   f"{m_ann_ret.get('Ann. Return', 0):.2%}",
            'B&H Ann Ret': f"{m_bh.get('Ann. Return', 0):.2%}",
            'Ann Vol':   f"{m.get('Ann. Vol', 0):.2%}",
            'Sharpe':    f"{m.get('Sharpe', 0):.2f}",
            'Sharpe(gr)':f"{m_gross.get('Sharpe', 0):.2f}",
            'Avg Turn':  f"{avg_turnover:.2f}",
            'Max ΔPos (B/day)': f"{max_dpos_b:.2f}",
            'Max DD':    f"{m.get('Max Drawdown', 0):.2%}",
            'Win%':      f"{m.get('Win Rate', 0):.1%}",
            'Mean IC':   f"{s['mean_ic']:.4f}",
            'ICIR':      f"{s['icir']:.2f}",
            'IC t-stat': f"{s['ic_tstat']:.2f}",
            'IC Hit%':   f"{s['ic_hit']:.1%}",
            # IC at the ensemble's own IC-weighted blend horizon — the
            # columns above always grade next-day (H=1) accuracy, which
            # under-credits the model when H=5/20 dominate the blend.
            'Mean IC (eff-H)': (
                f"{s['mean_ic_effective_horizon']:.4f}"
                if s.get('mean_ic_effective_horizon') == s.get('mean_ic_effective_horizon')
                else '—'
            ),
            'Avg Horizon': (
                f"{s['avg_effective_horizon']:.1f}d"
                if s.get('avg_effective_horizon') == s.get('avg_effective_horizon')
                else '—'
            ),
        })

    return dash_table.DataTable(
        data=metric_rows,
        columns=[{'name': c, 'id': c} for c in metric_rows[0].keys()],
        style_cell={'textAlign': 'center', 'padding': '6px 8px',
                    'backgroundColor': 'var(--surface-input)',
                    'color': 'var(--text-primary)', 'border': 'none',
                    'fontSize': '11px'},
        style_header={'backgroundColor': 'var(--surface-panel)',
                      'fontWeight': 'bold', 'color': 'var(--accent-green)',
                      'border': 'none'},
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': 'var(--surface-sunken)'},
        ],
        style_table={'overflowX': 'auto', 'marginBottom': '16px'},
    )


def build_per_factor_charts(results, factor_stats) -> list:
    """Build one stacked 5-panel figure per factor: Level | Signal |
    Position | IC | PnL, all sharing an x-axis."""
    _panel_base = dict(
        template=THEME['chart_template'],
        paper_bgcolor=THEME['bg_main'],
        plot_bgcolor=THEME['bg_main'],
        font={'color': THEME['text_main']},
        hovermode='x unified',
        margin=dict(l=60, r=30, t=50, b=30),
    )

    per_factor_divs = []
    for factor, df in results.items():
        s = factor_stats[factor]
        ic_s = s['ic_rolling']
        pos_col = 'position' if 'position' in df.columns else 'signal'

        fig = make_subplots(
            rows=5, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.22, 0.16, 0.16, 0.22, 0.24],
            subplot_titles=[
                'Historical Level',
                'Signal Level  (−1 … +1, 0.2 tick)',
                'Position  (smoothed · ≤2B/day)',
                'Rolling 60-day IC',
                'Cumulative PnL',
            ],
        )

        # Row 1: factor level
        if 'level' in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df['level'].values, mode='lines',
                line={'color': THEME['accent'], 'width': 1.5},
                name='Level', showlegend=False,
            ), row=1, col=1)

        # Row 2: signal bar chart
        sig = df['signal'].dropna()
        bar_colors = [_sig_color(v) for v in sig.values]
        fig.add_trace(go.Bar(
            x=sig.index, y=sig.values,
            marker_color=bar_colors,
            name='Signal', showlegend=False,
        ), row=2, col=1)

        # Row 3: continuous position
        pos = df[pos_col].dropna()
        fig.add_trace(go.Scatter(
            x=pos.index, y=pos.values, mode='lines',
            line={'color': '#f39c12', 'width': 1.5},
            name='Position', showlegend=False,
            fill='tozeroy', fillcolor='rgba(243,156,18,0.10)',
        ), row=3, col=1)
        # zero line for position panel
        fig.add_hline(y=0, line_width=0.8, line_dash='dash',
                      line_color='gray', row=3, col=1)

        # Row 4: rolling IC (raw dotted + EWMA solid) + zero line
        if ic_s is not None and len(ic_s) > 0:
            fig.add_trace(go.Scatter(
                x=ic_s.index, y=ic_s.values, mode='lines',
                line={'color': '#9b59b6', 'width': 1, 'dash': 'dot'},
                opacity=0.55, name='IC (raw)', showlegend=False,
            ), row=4, col=1)
            ic_ewma = ic_s.ewm(span=20, min_periods=10).mean()
            fig.add_trace(go.Scatter(
                x=ic_ewma.index, y=ic_ewma.values, mode='lines',
                line={'color': '#9b59b6', 'width': 2},
                name='IC EWMA-20', showlegend=False,
            ), row=4, col=1)
            fig.add_hline(y=0, line_width=0.8, line_dash='dash',
                          line_color='gray', row=4, col=1)

        # Row 5: cumulative PnL (net) + gross if available
        cum = df['cumulative_returns'].dropna()
        fig.add_trace(go.Scatter(
            x=cum.index, y=cum.values, mode='lines',
            line={'color': THEME['success'], 'width': 2},
            name='PnL (net)', showlegend=False,
        ), row=5, col=1)
        if 'strategy_returns_gross' in df.columns:
            cum_gr = (1 + df['strategy_returns_gross'].fillna(0)).cumprod().reindex(cum.index)
            fig.add_trace(go.Scatter(
                x=cum_gr.index, y=cum_gr.values, mode='lines',
                line={'color': THEME['success'], 'width': 1, 'dash': 'dot'},
                opacity=0.55, name='PnL (gross)', showlegend=False,
            ), row=5, col=1)

        grid = dict(gridcolor=THEME['table_header'])
        fig.update_xaxes(**grid)
        fig.update_yaxes(**grid)
        fig.update_layout(
            height=900,
            title=dict(text=factor, font={'size': 14, 'color': THEME['accent']}),
            bargap=0,
            **_panel_base,
        )

        per_factor_divs.append(
            html.Div([
                dcc.Graph(figure=fig,
                          config={'displayModeBar': False},
                          style={'width': '100%'}),
            ], style={
                'backgroundColor': THEME['bg_card'],
                'border': f'1px solid {THEME["table_header"]}',
                'borderRadius': '8px',
                'padding': '12px',
                'marginBottom': '20px',
            })
        )
    return per_factor_divs


def build_run_results_children(results, factor_stats) -> html.Div:
    """Assemble the full results panel: metrics table + per-factor charts."""
    metrics_table = build_metrics_table(results, factor_stats)
    per_factor_divs = build_per_factor_charts(results, factor_stats)
    return html.Div([
        html.H6("Performance & IC Statistics",
                style={'color': THEME['accent'], 'marginBottom': '8px'}),
        metrics_table,
        html.H6("Factor Detail  —  Historical · Signal · Position · IC · PnL",
                style={'color': THEME['accent'],
                       'marginBottom': '12px', 'marginTop': '8px'}),
        html.Div(per_factor_divs),
    ])
