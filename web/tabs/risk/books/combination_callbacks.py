# -*- coding: utf-8 -*-
"""Summary > Books > Portfolio Combination rendering callbacks."""

from __future__ import annotations

from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go

from web.tabs.beta.data import THEME
from .combination import build_combination

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
        [Input('summary-combo-alpha-capital', 'value'),
         Input('summary-combo-alpha-weight', 'value'),
         Input('summary-combo-refresh', 'n_clicks')],
    )
    def _render_combination(alpha_capital_mm, alpha_weight_pct, _refresh_clicks):
        # Imported here, not at module scope: both loaders touch the
        # filesystem, and the saved files can be rewritten by the Alpha /
        # Multi-Asset tabs while this session is open -- re-reading on every
        # callback keeps the card in step with the latest save.
        from web.tabs.alpha.data import load_portfolio_backtest_result
        from multiasset.storage import load_last_backtest_result

        beta_result = load_last_backtest_result()
        alpha_result = load_portfolio_backtest_result()

        capital = float(alpha_capital_mm) if alpha_capital_mm else 0.0
        weight = float(alpha_weight_pct or 0) / 100.0

        result = build_combination(beta_result, alpha_result, capital, weight)

        if 'error' in result:
            strip = html.Span(result['error'], style={'color': THEME['warning'], 'fontSize': '12px'})
            body = html.Div(result['error'], style={'color': THEME['warning'], 'fontSize': '12px',
                                                     'padding': '12px 0'})
            return strip, body, ""

        combined = result['combined']
        corr = result['correlation']
        div_ratio = result['diversification_ratio']
        w = result['alpha_weight']

        formula = html.Div([
            html.Div(
                f"Return = {1 - w:.2f} × Beta + {w:.2f} × Alpha "
                f"= {1 - w:.2f} × {result['beta']['total_return'] * 100:+.1f}% "
                f"+ {w:.2f} × {result['alpha']['total_return'] * 100:+.1f}% "
                f"= {combined['total_return'] * 100:+.1f}%",
            ),
            html.Div(
                f"Return adds linearly; Sharpe/vol don't (correlation {corr:+.2f} → "
                f"{div_ratio:.2f}x diversification benefit shrinks combined vol below "
                f"the weighted-average of the two books' vols).",
                style={'marginTop': '3px', 'fontStyle': 'italic'},
            ),
        ], style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginTop': '8px',
                  'paddingTop': '8px', 'borderTop': f'1px solid {THEME["table_header"]}'})

        # Beta capital is implied: alpha_capital_mm is alpha's notional base,
        # and the requested split fixes beta's share of the *same* total.
        # total = alpha_capital / w  (undefined at w=0 -- beta is then the
        # whole book and its own capital comes from its saved backtest).
        if w > 0:
            total_capital_mm = capital / w
            beta_capital_mm = total_capital_mm - capital
        else:
            beta_capital_mm = float(beta_result.get('total_capital') or 0.0)
            total_capital_mm = beta_capital_mm

        # --- Collapsed strip: the three headline answers ---
        strip = html.Div([
            _stat(f"{combined['sharpe']:.2f}", 'Combined Sharpe', THEME['accent']),
            _stat(f"{(1 - w) * 100:.0f}/{w * 100:.0f}", 'Beta / Alpha', THEME['text_main']),
            _stat(f"{corr:+.2f}", 'Correlation',
                  THEME['success'] if corr < 0.3 else THEME['warning']),
            _stat(f"{div_ratio:.2f}x", 'Diversification', THEME['success'] if div_ratio > 1.1 else THEME['text_sub'],
                  border=False),
        ], style={'display': 'flex', 'alignItems': 'center'})

        # --- Capital allocation: how much CNY sits in each book at the
        # requested split, plus what that book's saved-backtest capital was.
        alloc_card = html.Div([
            html.Div("Capital Allocation", style={'color': THEME['text_sub'], 'fontSize': '11px',
                                                   'textTransform': 'uppercase', 'letterSpacing': '.06em',
                                                   'marginBottom': '8px'}),
            html.Div(f"{total_capital_mm:,.0f} MM CNY total", style={
                'fontSize': '20px', 'fontWeight': '700', 'color': THEME['text_main'], 'marginBottom': '10px'}),
            html.Div([
                html.Span('Beta', style={'color': THEME['accent'], 'fontSize': '11px', 'fontWeight': '600'}),
                html.Span(f"{beta_capital_mm:,.0f} MM  ({(1 - w) * 100:.0f}%)",
                          style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Alpha', style={'color': THEME['warning'], 'fontSize': '11px', 'fontWeight': '600'}),
                html.Span(f"{capital:,.0f} MM  ({w * 100:.0f}%)",
                          style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
        ], style={'backgroundColor': THEME['bg_main'], 'padding': '12px 14px', 'borderRadius': '6px',
                  'border': f'1px solid {THEME["table_header"]}', 'flex': '1', 'minWidth': '190px'})

        # --- Combined-book backtest: the headline chart, own row, full width ---
        combined_chart = go.Figure()
        eq_combined = ((1.0 + result['returns']['combined']).cumprod() - 1.0) * 100.0
        combined_chart.add_trace(go.Scatter(
            x=eq_combined.index, y=eq_combined.values, mode='lines',
            name=f'Combined ({(1 - w) * 100:.0f}/{w * 100:.0f})', fill='tozeroy',
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

        # --- Frontier: combined Sharpe across every weight (secondary) ---
        sweep = result['sweep']
        frontier = go.Figure()
        frontier.add_trace(go.Scatter(
            x=sweep['alpha_weight'] * 100, y=sweep['sharpe'],
            mode='lines', name='Combined Sharpe',
            line={'color': THEME['accent'], 'width': 2},
        ))
        for wt, color, label in (
            (result['max_sharpe_weight'], THEME['success'], 'Max Sharpe'),
            (result['risk_parity_weight'], _RP_COLOR, 'Risk Parity'),
            (w, THEME['warning'], 'Selected'),
        ):
            frontier.add_vline(x=wt * 100, line_dash='dot', line_color=color,
                               annotation_text=label, annotation_position='top',
                               annotation_font={'size': 9, 'color': color})
        frontier.update_layout(
            title={'text': 'Diversification Frontier', 'font': {'size': 12, 'color': THEME['text_sub']}},
            xaxis={'title': 'Alpha share of capital (%)', 'gridcolor': THEME['bg_card']},
            yaxis={'title': 'Combined Sharpe', 'gridcolor': THEME['bg_card']},
            template='plotly_dark', paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
            height=240, margin={'l': 55, 'r': 20, 't': 40, 'b': 45}, showlegend=False,
        )

        rp_w = result['risk_parity_weight']
        ms_w = result['max_sharpe_weight']
        reco = html.Div([
            html.Div("Suggested Splits", style={'color': THEME['text_sub'], 'fontSize': '11px',
                                                 'textTransform': 'uppercase', 'letterSpacing': '.06em',
                                                 'marginBottom': '8px'}),
            html.Div([
                html.Span('Max Sharpe', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{(1 - ms_w) * 100:.0f}/{ms_w * 100:.0f} → {result['max_sharpe']:.2f}",
                          style={'color': THEME['success'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Risk Parity', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{(1 - rp_w) * 100:.0f}/{rp_w * 100:.0f} → {result['risk_parity']['sharpe']:.2f}",
                          style={'color': _RP_COLOR, 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
            html.Div([
                html.Span('Selected', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Span(f"{(1 - w) * 100:.0f}/{w * 100:.0f} → {combined['sharpe']:.2f}",
                          style={'color': THEME['warning'], 'fontSize': '11px', 'fontWeight': '600'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'}),
        ], style={'backgroundColor': THEME['bg_main'], 'padding': '12px 14px', 'borderRadius': '6px',
                  'border': f'1px solid {THEME["table_header"]}', 'flex': '1', 'minWidth': '190px'})

        overlap = html.Div(
            f"Overlapping window: {result['start']:%Y-%m-%d} → {result['end']:%Y-%m-%d} "
            f"({result['n_days']} days). Correlation {corr:+.2f}, diversification ratio "
            f"{div_ratio:.2f}x (weighted-average standalone vol ÷ realised combined vol; "
            f">1 means the books genuinely offset each other).",
            style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginTop': '10px'},
        )

        body = html.Div([
            # Row 1: per-book metrics + capital allocation
            html.Div([
                _metric_card('Beta Book', result['beta'], THEME['accent']),
                _metric_card('Alpha Book', result['alpha'], THEME['warning']),
                _metric_card('Combined', combined, THEME['success'], extra=formula),
                alloc_card,
            ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap', 'marginBottom': '14px'}),
            # Row 2: combined-book backtest, full width, the headline chart
            html.Div([dcc.Graph(figure=combined_chart, config={'displayModeBar': False})],
                     style={'marginBottom': '14px'}),
            # Row 3: diversification frontier + suggested splits
            html.Div([
                html.Div([dcc.Graph(figure=frontier, config={'displayModeBar': False})],
                         style={'flex': '1', 'minWidth': '320px'}),
                reco,
            ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap'}),
            overlap,
        ])

        margin_ratio = result.get('margin_ratio')
        implied_margin = result.get('implied_margin_mm')
        if margin_ratio is not None and implied_margin is not None:
            margin_hint = (
                f"DV01-based estimate: this book's margin ratio is ~{margin_ratio * 100:.2f}% of "
                f"notional, so {capital:,.0f}MM notional ties up ~{implied_margin:,.1f}MM in margin. "
                f"Single-leg proxy with a fitted 2.5x netting correction — see estimate_margin_mm, "
                f"treat as approximate."
            )
        else:
            margin_hint = ""

        return strip, body, margin_hint
