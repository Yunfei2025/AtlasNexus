# -*- coding: utf-8 -*-
"""Chart, KPI-grid, and holdings-table builders for the Historical Portfolio
Allocation backtest. Moved verbatim from backtest_hist.py:227-234, 821-1013
— no behaviour change. Takes the plain dict returned by
orchestrator.run_historical_allocation() and produces Dash objects."""

from __future__ import annotations

import plotly.graph_objects as go
from dash import html, dash_table

from ...data import THEME


def empty_figure(title="Click 'Run Historical Analysis' to start") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title,
        template=THEME['chart_template'],
        paper_bgcolor=THEME['bg_main'],
        plot_bgcolor=THEME['bg_main'],
        font={'color': THEME['text_main']},
    )
    return fig


def error_figure(message: str) -> go.Figure:
    return go.Figure().update_layout(title=f"Error: {message}", template=THEME['chart_template'])


def warning_figure(title: str, annotation_text: str | None = None, themed: bool = True) -> go.Figure:
    """`themed=False` reproduces the plain `title` + `template`-only layout
    the original used for a few error sites (e.g. "No risk factor data
    available") — `themed=True` (default) adds paper/plot background + font,
    matching the sites that used the fuller layout."""
    fig = go.Figure()
    if themed:
        layout_kwargs = dict(
            title=title,
            template=THEME['chart_template'],
            paper_bgcolor=THEME['bg_main'],
            plot_bgcolor=THEME['bg_main'],
            font={'color': THEME['text_main']},
        )
    else:
        layout_kwargs = dict(title=title, template=THEME['chart_template'])
    if annotation_text:
        layout_kwargs['annotations'] = [{
            'text': annotation_text,
            'xref': 'paper', 'yref': 'paper', 'x': 0.5, 'y': 0.5,
            'showarrow': False, 'font': {'size': 14, 'color': THEME['warning']},
            'align': 'center',
        }]
    fig.update_layout(**layout_kwargs)
    return fig


def build_allocation_figure(df_history, all_assets_ever, display_start, display_end) -> go.Figure:
    fig_alloc = go.Figure()
    for asset_name in sorted(all_assets_ever):
        if asset_name in df_history.columns:
            fig_alloc.add_trace(go.Scatter(
                x=df_history['Date'],
                y=df_history[asset_name].fillna(0),
                mode='lines+markers',
                name=asset_name,
                stackgroup='one'
            ))

    fig_alloc.update_layout(
        title=f"Historical Portfolio Allocation ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
        xaxis_title="Date",
        yaxis_title="Allocation (Million CNY)",
        hovermode='x unified',
        template=THEME['chart_template'],
        height=400,
        paper_bgcolor=THEME['bg_main'],
        plot_bgcolor=THEME['bg_main'],
        font={'color': THEME['text_main']},
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main'], 'size': 10}),
        xaxis=dict(gridcolor=THEME['table_header']),
        yaxis=dict(gridcolor=THEME['table_header'])
    )
    return fig_alloc


def build_pnl_figure(df_pnl, all_assets_ever, display_start, display_end,
                     nav_series=None, nav_net_series=None) -> go.Figure:
    fig_pnl = go.Figure()
    if not df_pnl.empty:
        # Add stacked area traces for each asset
        for asset_name in sorted(all_assets_ever):
            if asset_name in df_pnl.columns:
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'],
                    y=df_pnl[asset_name].fillna(0),
                    mode='none',
                    name=asset_name,
                    stackgroup='pnl',
                    fillcolor=None,
                    hovertemplate=f'<b>{asset_name}</b><br>Date: %{{x|%Y-%m-%d}}<br>PnL: %{{y}} Million CNY<extra></extra>'
                ))

        # Add a line trace at the top to show total boundary
        fig_pnl.add_trace(go.Scatter(
            x=df_pnl['Date'],
            y=df_pnl['Total'],
            mode='lines',
            name='Total',
            showlegend=False,
            line=dict(color='rgba(255,255,255,0.3)', width=2),
            hovertemplate='<b>Total PnL</b><br>Date: %{x|%Y-%m-%d}<br>PnL: %{y} Million CNY<extra></extra>'
        ))

    fig_pnl.update_layout(
        title=f"Cumulative PnL by Asset ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
        xaxis_title="Date",
        yaxis_title="Cumulative PnL (Million CNY)",
        hovermode='x unified',
        template=THEME['chart_template'],
        height=450,
        paper_bgcolor=THEME['bg_main'],
        plot_bgcolor=THEME['bg_main'],
        font={'color': THEME['text_main']},
        showlegend=False,
        xaxis=dict(gridcolor=THEME['table_header']),
        yaxis=dict(gridcolor=THEME['table_header'])
    )

    if nav_series is not None and nav_net_series is not None:
        fig_pnl.add_trace(go.Scatter(
            x=df_pnl['Date'],
            y=nav_series.round(2),
            mode='lines',
            name='NAV gross (base 1000)',
            yaxis='y2',
            line=dict(color='#FFD700', width=2.5, dash='solid'),
            hovertemplate='<b>NAV (gross)</b>: %{y:.1f}<extra></extra>',
        ))
        fig_pnl.add_trace(go.Scatter(
            x=df_pnl['Date'],
            y=nav_net_series.round(2),
            mode='lines',
            name='NAV net of tx costs (base 1000)',
            yaxis='y2',
            line=dict(color='#FFD700', width=1.5, dash='dot'),
            hovertemplate='<b>NAV (net)</b>: %{y:.1f}<extra></extra>',
        ))
        fig_pnl.update_layout(
            yaxis2=dict(
                title='NAV (base 1000)',
                overlaying='y',
                side='right',
                showgrid=False,
                tickfont=dict(color='#FFD700'),
                title_font=dict(color='#FFD700'),
            ),
            showlegend=True,
        )

    return fig_pnl


def build_metrics_kpis(metrics: dict) -> html.Div:
    annualized_return = metrics['annualized_return']
    sharpe_ratio = metrics['sharpe_ratio']
    sharpe_net = metrics['sharpe_net']
    max_drawdown = metrics['max_drawdown']

    kpi_cells = [
        ("Ann. Return", f"{annualized_return:.2%}",
         'var(--positive)' if annualized_return >= 0 else 'var(--negative)'),
        ("Sharpe (gross)", f"{sharpe_ratio:.2f}",
         'var(--positive)' if sharpe_ratio >= 1 else ('var(--accent-amber)' if sharpe_ratio >= 0 else 'var(--negative)')),
        ("Sharpe (net tx)", f"{sharpe_net:.2f}",
         'var(--positive)' if sharpe_net >= 1 else ('var(--accent-amber)' if sharpe_net >= 0 else 'var(--negative)')),
        ("Max Drawdown", f"{max_drawdown:.2%}", 'var(--negative)'),
        ("# Rebalances", f"{metrics['n_rebalances']}", 'var(--text-primary)'),
        ("Ann. Turnover", f"{metrics['ann_turnover']:.0%}", 'var(--text-primary)'),
        ("Total Tx Cost (MM)", f"{metrics['total_tx_cost_m']:.2f}", 'var(--text-secondary)'),
    ]
    return html.Div([
        html.Div([
            html.Div(label, className='an-kpi-cell__label'),
            html.Div(value, className='an-kpi-cell__value', style={'color': color}),
        ], className='an-kpi-cell')
        for label, value, color in kpi_cells
    ], className='an-kpi-grid')


def build_holdings_table(asset_holdings_rows) -> html.Div:
    return html.Div([
        html.H5("📅 Monthly Asset Holdings", style={'color': THEME['text_main'], 'marginBottom': '10px', 'marginTop': '20px'}),
        dash_table.DataTable(
            data=asset_holdings_rows,
            columns=[
                {'name': 'Month', 'id': 'Date'},
                {'name': '# Assets', 'id': 'Asset Count'},
                {'name': 'Holdings', 'id': 'Holdings'},
            ],
            style_cell={
                'textAlign': 'left',
                'padding': '8px 10px',
                'fontFamily': 'Arial, sans-serif',
                'backgroundColor': THEME['table_row_odd'],
                'color': THEME['text_main'],
                'border': 'none',
                'fontSize': '12px',
                'whiteSpace': 'normal',
                'height': 'auto',
            },
            style_cell_conditional=[
                {'if': {'column_id': 'Date'}, 'width': '80px'},
                {'if': {'column_id': 'Asset Count'}, 'width': '80px', 'textAlign': 'center'},
                {'if': {'column_id': 'Holdings'}, 'minWidth': '300px'},
            ],
            style_header={
                'backgroundColor': THEME['table_header'],
                'color': THEME['text_main'],
                'fontWeight': 'bold',
                'textAlign': 'left',
                'border': 'none'
            },
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
            ],
            style_table={'overflowX': 'auto', 'maxHeight': '400px', 'overflowY': 'auto'}
        )
    ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})
