# -*- coding: utf-8 -*-
"""Summary > Books > Portfolio Combination rendering callbacks."""

from __future__ import annotations

from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go

from web.tabs.beta.data import THEME
from .combination import build_combination, MAX_MARGIN_UTILIZATION

# THEME (beta palette) has no 'purple' key -- define the risk-parity marker
# colour locally rather than reaching into the alpha palette.
_RP_COLOR = '#7c70d6'


def _stat(value: str, label: str, color: str, border: bool = True) -> html.Div:
    style = {'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center',
             'padding': '4px 20px'}
    if border:
        style['borderRight'] = f'1px solid {THEME["table_header"]}'
    return html.Div([
        html.Span(value, style={'fontSize': '18px', 'fontWeight': '700', 'color': color}),
        html.Span(label, style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '2px'}),
    ], style=style)


def _metric_card(title: str, metrics: dict, accent: str, extra=None) -> html.Div:
    def row(label, value):
        return html.Div([
            html.Span(label, style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            html.Span(value, style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600'}),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'})

    return html.Div([
        html.Div(title, style={'color': THEME['text_sub'], 'fontSize': '11px',
                                'textTransform': 'uppercase', 'letterSpacing': '.06em',
                                'marginBottom': '6px'}),
        html.Div(f"{metrics['sharpe']:.2f}", style={'fontSize': '22px', 'fontWeight': '700',
                                                     'color': accent, 'marginBottom': '8px'}),
        row('Ann. Vol', f"{metrics['vol'] * 100:.2f}%"),
        row('Total Return', f"{metrics['total_return'] * 100:+.2f}%"),
        row('Max Drawdown', f"{metrics['max_drawdown'] * 100:.2f}%"),
    ] + ([extra] if extra is not None else []), style={
        'backgroundColor': THEME['bg_main'], 'padding': '12px 14px', 'borderRadius': '6px',
        'border': f'1px solid {THEME["table_header"]}', 'flex': '1', 'minWidth': '170px',
    })


def register_combination_callbacks(app):
    """Render the Portfolio Combination strip + expanded analysis."""

    @app.callback(
        [Output('summary-combo-strip', 'children'),
         Output('summary-combo-body', 'children'),
         Output('summary-combo-margin-hint', 'children')],
        [Input('summary-combo-total-capital', 'value'),
         Input('summary-combo-alpha-margin-share', 'value'),
         Input('summary-combo-refresh', 'n_clicks')],
    )
    def _render_combination(total_capital_mm, alpha_margin_share_pct, _refresh_clicks):
        # Imported here, not at module scope: both loaders touch the
        # filesystem, and the saved files can be rewritten by the Alpha /
        # Multi-Asset tabs while this session is open -- re-reading on every
        # callback keeps the card in step with the latest save.
        from web.tabs.alpha.data import load_portfolio_backtest_result
        from multiasset.storage import load_last_backtest_result

        beta_result = load_last_backtest_result()
        alpha_result = load_portfolio_backtest_result()

        total_capital = float(total_capital_mm) if total_capital_mm else 0.0
        margin_share = float(alpha_margin_share_pct or 0) / 100.0

        result = build_combination(beta_result, alpha_result, total_capital, margin_share,
                                    max_margin_utilization=MAX_MARGIN_UTILIZATION)

        if 'error' in result:
            strip = html.Span(result['error'], style={'color': THEME['warning'], 'fontSize': '12px'})
            body = html.Div(result['error'], style={'color': THEME['warning'], 'fontSize': '12px',
                                                     'padding': '12px 0'})
            return strip, body, ""

        combined = result['combined']
        corr = result['correlation']
        div_ratio = result['diversification_ratio']
        ms = result['alpha_margin_share']
        w = result['alpha_weight']

        formula = html.Div([
            html.Div(
                f"Return = {1 - ms:.2f} × Beta + {w:.2f} × Alpha "
                f"= {1 - ms:.2f} × {result['beta']['total_return'] * 100:+.1f}% "
                f"+ {w:.2f} × {result['alpha']['total_return'] * 100:+.1f}% "
                f"= {combined['total_return'] * 100:+.1f}%",
            ),
            html.Div(
                f"Alpha's return-blend weight ({w:.2f}) is its USABLE margin ({ms:.2f} × "
                f"{util * 100:.0f}% utilization cap) ÷ its margin ratio "
                f"({result['margin_ratio'] * 100:.1f}%) — it's a margined book, so its notional "
                f"(and its return contribution) is a multiple of the capital it ties up. Only "
                f"{util * 100:.0f}% of the allocated margin is sized into positions; the rest is "
                f"headroom against adverse mark-to-market moves, not spare capital.",
                style={'marginTop': '3px'},
            ),
            html.Div(
                f"Return adds linearly; Sharpe/vol don't (correlation {corr:+.2f} → "
                f"{div_ratio:.2f}x diversification benefit shrinks combined vol below "
                f"the weighted-average of the two books' vols).",
                style={'marginTop': '3px', 'fontStyle': 'italic'},
            ),
        ], style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginTop': '8px',
                  'paddingTop': '8px', 'borderTop': f'1px solid {THEME["table_header"]}'})

        total_capital_mm = result['total_capital_mm']
        beta_notional_mm = result['beta_notional_mm']
        alpha_margin_mm = result['alpha_margin_mm']
        alpha_margin_usable_mm = result['alpha_margin_usable_mm']
        alpha_notional_mm = result['alpha_notional_mm']
        util = result['max_margin_utilization']

        # --- Collapsed strip: the three headline answers ---
        strip = html.Div([
            _stat(f"{combined['sharpe']:.2f}", 'Combined Sharpe', THEME['accent']),
            _stat(f"{(1 - ms) * 100:.0f}/{ms * 100:.0f}", 'Beta Notional / Alpha Margin', THEME['text_main']),
            _stat(f"{corr:+.2f}", 'Correlation',
                  THEME['success'] if corr < 0.3 else THEME['warning']),
            _stat(f"{div_ratio:.2f}x", 'Diversification', THEME['success'] if div_ratio > 1.1 else THEME['text_sub'],
                  border=False),
        ], style={'display': 'flex', 'alignItems': 'center'})

        # --- Capital allocation: beta's notional and alpha's margin at the
        # requested split (both drawn from the same total_capital_mm pool),
        # plus alpha's own notional derived from its margin ratio.
        alloc_card = html.Div([
            html.Div("Capital Allocation", style={'color': THEME['text_sub'], 'fontSize': '11px',
                                                   'textTransform': 'uppercase', 'letterSpacing': '.06em',
                                                   'marginBottom': '8px'}),
            html.Div(f"{total_capital_mm:,.0f} MM CNY total", style={
                'fontSize': '20px', 'fontWeight': '700', 'color': THEME['text_main'], 'marginBottom': '10px'}),
            html.Div([
                html.Span('Beta notional', style={'color': THEME['accent'], 'fontSize': '11px', 'fontWeight': '600'}),
                html.Span(f"{beta_notional_mm:,.0f} MM  ({(1 - ms) * 100:.0f}%)",
                          style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Alpha margin (cap)', style={'color': THEME['warning'], 'fontSize': '11px', 'fontWeight': '600'}),
                html.Span(f"{alpha_margin_mm:,.0f} MM  ({ms * 100:.0f}%)",
                          style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Alpha margin (usable)', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{alpha_margin_usable_mm:,.0f} MM  ({util * 100:.0f}% of cap)",
                          style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Alpha notional', style={'color': THEME['warning'], 'fontSize': '11px'}),
                html.Span(f"{alpha_notional_mm:,.0f} MM  ({result['margin_ratio'] * 100:.1f}% margin ratio)",
                          style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
        ], style={'backgroundColor': THEME['bg_main'], 'padding': '12px 14px', 'borderRadius': '6px',
                  'border': f'1px solid {THEME["table_header"]}', 'flex': '1', 'minWidth': '190px'})

        # --- Combined-book backtest: the headline chart, own row, full width ---
        combined_chart = go.Figure()
        eq_combined = ((1.0 + result['returns']['combined']).cumprod() - 1.0) * 100.0
        combined_chart.add_trace(go.Scatter(
            x=eq_combined.index, y=eq_combined.values, mode='lines',
            name=f'Combined ({(1 - ms) * 100:.0f}/{ms * 100:.0f})', fill='tozeroy',
            line={'color': THEME['success'], 'width': 2.4},
            fillcolor='rgba(47,157,107,0.10)',
        ))
        for key, color, label in (
            ('beta', THEME['accent'], 'Beta book'),
            ('alpha', THEME['warning'], 'Alpha book'),
        ):
            series = result['returns'][key]
            equity = ((1.0 + series).cumprod() - 1.0) * 100.0
            combined_chart.add_trace(go.Scatter(
                x=equity.index, y=equity.values, mode='lines', name=label,
                line={'color': color, 'width': 1.2, 'dash': 'dot'},
            ))
        combined_chart.update_layout(
            title={'text': 'Combined Book Backtest', 'font': {'size': 12, 'color': THEME['text_sub']}},
            xaxis={'title': '', 'gridcolor': THEME['bg_card'], 'tickformat': '%b\n%Y'},
            yaxis={'title': 'Cumulative return (%)', 'gridcolor': THEME['bg_card']},
            template='plotly_dark', paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
            height=320, margin={'l': 55, 'r': 20, 't': 40, 'b': 35},
            legend={'orientation': 'h', 'y': 1.12, 'x': 0, 'font': {'size': 10}},
        )

        # --- Frontier: combined Sharpe across every margin share (secondary) ---
        sweep = result['sweep']
        frontier = go.Figure()
        frontier.add_trace(go.Scatter(
            x=sweep['alpha_margin_share'] * 100, y=sweep['sharpe'],
            mode='lines', name='Combined Sharpe',
            line={'color': THEME['accent'], 'width': 2},
        ))
        for wt, color, label in (
            (result['max_sharpe_margin_share'], THEME['success'], 'Max Sharpe'),
            (result['risk_parity_margin_share'], _RP_COLOR, 'Risk Parity'),
            (ms, THEME['warning'], 'Selected'),
        ):
            frontier.add_vline(x=wt * 100, line_dash='dot', line_color=color,
                               annotation_text=label, annotation_position='top',
                               annotation_font={'size': 9, 'color': color})
        frontier.update_layout(
            title={'text': 'Diversification Frontier', 'font': {'size': 12, 'color': THEME['text_sub']}},
            xaxis={'title': 'Alpha margin share of capital (%)', 'gridcolor': THEME['bg_card']},
            yaxis={'title': 'Combined Sharpe', 'gridcolor': THEME['bg_card']},
            template='plotly_dark', paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
            height=320, margin={'l': 55, 'r': 20, 't': 40, 'b': 45}, showlegend=False,
        )

        rp_ms = result['risk_parity_margin_share']
        ms_best = result['max_sharpe_margin_share']
        reco = html.Div([
            html.Div("Suggested Splits", style={'color': THEME['text_sub'], 'fontSize': '11px',
                                                 'textTransform': 'uppercase', 'letterSpacing': '.06em',
                                                 'marginBottom': '8px'}),
            html.Div([
                html.Span('Max Sharpe', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{(1 - ms_best) * 100:.0f}/{ms_best * 100:.0f} → {result['max_sharpe']:.2f}",
                          style={'color': THEME['success'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Risk Parity', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{(1 - rp_ms) * 100:.0f}/{rp_ms * 100:.0f} → {result['risk_parity']['sharpe']:.2f}",
                          style={'color': _RP_COLOR, 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Selected', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{(1 - ms) * 100:.0f}/{ms * 100:.0f} → {combined['sharpe']:.2f}",
                          style={'color': THEME['warning'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div("Splits are Beta notional / Alpha margin share.",
                     style={'fontSize': '9px', 'color': THEME['text_sub'], 'marginTop': '6px', 'fontStyle': 'italic'}),
        ], style={'backgroundColor': THEME['bg_main'], 'padding': '12px 14px', 'borderRadius': '6px',
                  'border': f'1px solid {THEME["table_header"]}', 'flex': '1', 'minWidth': '170px'})

        overlap = html.Div(
            f"Overlapping window: {result['start']:%Y-%m-%d} → {result['end']:%Y-%m-%d} "
            f"({result['n_days']} days). Correlation {corr:+.2f}, diversification ratio "
            f"{div_ratio:.2f}x (weighted-average standalone vol ÷ realised combined vol; "
            f">1 means the books genuinely offset each other).",
            style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginTop': '10px'},
        )

        body = html.Div([
            # Row 1: per-book metrics + capital allocation + suggested splits (5 cards)
            html.Div([
                _metric_card('Beta Book', result['beta'], THEME['accent']),
                _metric_card('Alpha Book', result['alpha'], THEME['warning']),
                _metric_card('Combined', combined, THEME['success'], extra=formula),
                alloc_card,
                reco,
            ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap', 'marginBottom': '14px'}),
            # Row 2: diversification frontier (1) : combined-book backtest (3)
            html.Div([
                html.Div([dcc.Graph(figure=frontier, config={'displayModeBar': False})],
                         style={'flex': '1', 'minWidth': '260px'}),
                html.Div([dcc.Graph(figure=combined_chart, config={'displayModeBar': False})],
                         style={'flex': '3', 'minWidth': '400px'}),
            ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap'}),
            overlap,
        ])

        margin_ratio = result.get('margin_ratio')
        alpha_notional_mm = result.get('alpha_notional_mm')
        if margin_ratio is not None and alpha_notional_mm is not None:
            margin_hint = (
                f"DV01-based estimate: this book's margin ratio is ~{margin_ratio * 100:.2f}% of "
                f"notional, so {alpha_margin_mm:,.0f}MM margin implies ~{alpha_notional_mm:,.0f}MM "
                f"notional deployed. Single-leg proxy with a fitted 2.5x netting correction — see "
                f"estimate_margin_mm, treat as approximate."
            )
        else:
            margin_hint = ""

        return strip, body, margin_hint
