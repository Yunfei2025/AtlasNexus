# -*- coding: utf-8 -*-
"""Summary > Books > Portfolio Combination rendering callbacks."""

from __future__ import annotations

from dash import dcc, html
from dash.dependencies import Input, Output, State
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


def _metric_card(title: str, metrics: dict, accent: str, pnl_mm: float,
                  margin_ann_return: Optional[float] = None, extra=None) -> html.Div:
    def row(label, value):
        return html.Div([
            html.Span(label, style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            html.Span(value, style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600'}),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'padding': '2px 0'})

    pnl_color = THEME['success'] if pnl_mm >= 0 else THEME['danger']

    # margin_ann_return (Alpha only): the book's annualized return on its own
    # usable MARGIN rather than its notional -- what the capital it actually
    # ties up earned, as opposed to 'Ann. Return' above (notional-based,
    # unlevered, comparable to Beta's own capital-based figure). See
    # build_combination's m_alpha_margin for the derivation.
    margin_row = (
        [row('Ann. Return (on margin)', f"{margin_ann_return * 100:+.2f}%")]
        if margin_ann_return is not None else []
    )

    return html.Div([
        html.Div(title, style={'color': THEME['text_sub'], 'fontSize': '11px',
                                'textTransform': 'uppercase', 'letterSpacing': '.06em',
                                'marginBottom': '6px'}),
        html.Div(f"{metrics['sharpe']:.2f}", style={'fontSize': '22px', 'fontWeight': '700',
                                                     'color': accent, 'marginBottom': '4px'}),
        html.Div(f"{pnl_mm:+,.1f} MM CNY", style={'fontSize': '13px', 'fontWeight': '600',
                                                   'color': pnl_color, 'marginBottom': '8px'}),
        row('Ann. Vol', f"{metrics['vol'] * 100:.2f}%"),
        row('Ann. Return', f"{metrics['ann_return'] * 100:+.2f}%"),
    ] + margin_row + [
        row('Total Return', f"{metrics['total_return'] * 100:+.2f}%"),
        row('Total PnL (net of cost)', f"{pnl_mm:+,.1f} MM"),
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
         Output('summary-combo-margin-hint', 'children'),
         Output('summary-combo-formula', 'children')],
        [Input('summary-combo-total-capital', 'value'),
         Input('summary-combo-alpha-margin-share', 'value'),
         Input('summary-combo-refresh', 'n_clicks'),
         Input('summary-combo-run', 'n_clicks')],
        [State('summary-combo-window', 'value')],
    )
    def _render_combination(total_capital_bn, alpha_margin_share_pct, _refresh_clicks, _run_clicks, window):
        # Imported here, not at module scope: both loaders touch the
        # filesystem, and the saved files can be rewritten by the Alpha /
        # Multi-Asset tabs while this session is open -- re-reading on every
        # callback keeps the card in step with the latest save.
        from web.tabs.alpha.data import load_portfolio_backtest_result
        from multiasset.storage import load_last_backtest_result

        beta_result = load_last_backtest_result()
        alpha_result = load_portfolio_backtest_result()

        # UI input is BN CNY (billions); build_combination and everything it
        # returns (beta_notional_mm, alpha_margin_mm, pnl_*_mm, ...) works in
        # MM CNY, so convert once here at the boundary.
        total_capital = (float(total_capital_bn) if total_capital_bn else 0.0) * 1000.0
        window = window or 'MAX'

        # Margin share is a fixed, explicit split (default 10%, set on the
        # input itself) -- NOT auto-recomputed to the max-Sharpe point.
        # Auto-optimizing here used to mean switching the backtest window
        # silently changed the split too (a different window has different
        # realized vol/correlation, and because alpha is margined a small
        # shift in optimal margin share is a much larger shift in notional
        # weight), making "the split changed" indistinguishable from "the
        # window changed". A cleared input falls back to the same fixed 10%
        # default rather than re-optimizing. The max-Sharpe/risk-parity
        # points for the current window are still surfaced in "Suggested
        # Splits" below for reference -- they're just not auto-applied.
        margin_share = float(alpha_margin_share_pct) / 100.0 if alpha_margin_share_pct is not None else 0.10

        result = build_combination(beta_result, alpha_result, total_capital, margin_share,
                                    max_margin_utilization=MAX_MARGIN_UTILIZATION, window=window)

        if 'error' in result:
            strip = html.Span(result['error'], style={'color': THEME['warning'], 'fontSize': '12px'})
            body = html.Div(result['error'], style={'color': THEME['warning'], 'fontSize': '12px',
                                                     'padding': '12px 0'})
            return strip, body, "", ""

        combined = result['combined']
        corr = result['correlation']
        rolling_corr = result['rolling_correlation']
        worst_corr = result['worst_window_correlation']
        corr_window = result['rolling_correlation_window']
        corr_flag = result['rolling_correlation_flag']
        div_ratio = result['diversification_ratio']
        ms = result['alpha_margin_share']
        w = result['alpha_weight']
        util = result['max_margin_utilization']

        # Blend-math note -- rendered into 'summary-combo-formula' at the top
        # of the panel (see layout.py), not inside the Combined card: it
        # explains where every card's numbers come from, not just Combined's.
        formula = html.Div([
            html.Div(
                f"Return = {1 - ms:.2f} × Beta + {w:.2f} × Alpha "
                f"= {1 - ms:.2f} × {result['beta']['total_return'] * 100:+.1f}% "
                f"+ {w:.2f} × {result['alpha']['total_return'] * 100:+.1f}% "
                f"= {combined['total_return'] * 100:+.1f}%",
            ),
            html.Div(
                f"Alpha's return-blend weight ({w:.2f}) is its usable margin ÷ its margin ratio "
                f"({result['margin_ratio'] * 100:.1f}%).",
                style={'marginTop': '3px'},
            ),
            html.Div(
                f"Return adds linearly; Sharpe/vol don't (correlation {corr:+.2f} → "
                f"{div_ratio:.2f}x diversification benefit shrinks combined vol below "
                f"the weighted-average of the two books' vols).",
                style={'marginTop': '3px', 'fontStyle': 'italic'},
            ),
        ])

        total_capital_mm = result['total_capital_mm']
        beta_notional_mm = result['beta_notional_mm']
        alpha_margin_mm = result['alpha_margin_mm']
        alpha_margin_usable_mm = result['alpha_margin_usable_mm']
        alpha_notional_mm = result['alpha_notional_mm']

        # --- Collapsed strip: the three headline answers ---
        strip = html.Div([
            _stat(f"{combined['sharpe']:.2f}", 'Combined Sharpe', THEME['accent']),
            _stat(f"{combined['ann_return'] * 100:+.2f}%", 'Ann. Return', THEME['text_main']),
            _stat(f"{(1 - ms) * 100:.0f}/{ms * 100:.0f}", 'Beta Notional / Alpha Margin', THEME['text_main']),
            _stat(f"{corr:+.2f}", 'Correlation',
                  THEME['success'] if corr < 0.3 else THEME['warning']),
            _stat(f"{div_ratio:.2f}x", 'Diversification', THEME['success'] if div_ratio > 1.1 else THEME['text_sub'],
                  border=worst_corr is not None),
        ] + ([
            _stat(f"{worst_corr:+.2f}", f'Worst {corr_window}d Corr.',
                  THEME['danger'] if worst_corr >= corr_flag else THEME['text_sub'],
                  border=False),
        ] if worst_corr is not None else []), style={'display': 'flex', 'alignItems': 'center'})

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
        # Subtitle names the window/day-count the curve was fit on -- this
        # frontier is a statistic of one finite sample (realized vol/Sharpe/
        # correlation over exactly these days), not a fixed reference curve:
        # a different window (different realized correlation especially,
        # amplified further at higher margin share since alpha's notional
        # weight w = ms*util/margin_ratio grows fast with ms) can reshape it
        # substantially. Naming the window makes that sample-dependence
        # visible instead of implying the curve is stable across periods.
        window_label = result.get('window', 'MAX')
        window_text = 'full history' if window_label == 'MAX' else window_label
        frontier.update_layout(
            title={'text': f'Diversification Frontier — {window_text} ({result["n_days"]}d)',
                   'font': {'size': 12, 'color': THEME['text_sub']}},
            xaxis={'title': 'Alpha margin share of capital (%)', 'gridcolor': THEME['bg_card']},
            yaxis={'title': 'Combined Sharpe', 'gridcolor': THEME['bg_card']},
            template='plotly_dark', paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
            height=320, margin={'l': 55, 'r': 20, 't': 40, 'b': 45}, showlegend=False,
        )

        # --- Rolling correlation: is the diversification stable over time, or
        # does the full-sample number hide a stress-period spike? See
        # docs/plans/portfolio_construction_beta_alpha.md §5.1.
        if rolling_corr is not None and not rolling_corr.empty:
            rolling_chart = go.Figure()
            rolling_chart.add_hrect(
                y0=corr_flag, y1=1.0, fillcolor='rgba(213,107,107,0.10)', line_width=0,
            )
            rolling_chart.add_trace(go.Scatter(
                x=rolling_corr.index, y=rolling_corr.values, mode='lines',
                name=f'{corr_window}d rolling correlation',
                line={'color': THEME['accent'], 'width': 1.6},
            ))
            rolling_chart.add_hline(y=corr_flag, line_dash='dot', line_color=THEME['danger'],
                                     annotation_text=f'flag ≥ {corr_flag:+.1f}',
                                     annotation_position='top left',
                                     annotation_font={'size': 9, 'color': THEME['danger']})
            rolling_chart.add_hline(y=corr, line_dash='dot', line_color=THEME['text_sub'],
                                     annotation_text='full-sample',
                                     annotation_position='bottom left',
                                     annotation_font={'size': 9, 'color': THEME['text_sub']})
            rolling_chart.update_layout(
                title={'text': f'{corr_window}d Rolling Beta↔Alpha Correlation',
                       'font': {'size': 12, 'color': THEME['text_sub']}},
                xaxis={'title': '', 'gridcolor': THEME['bg_card'], 'tickformat': '%b\n%Y'},
                yaxis={'title': 'Correlation', 'gridcolor': THEME['bg_card'], 'range': [-1, 1]},
                template='plotly_dark', paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
                height=260, margin={'l': 55, 'r': 20, 't': 40, 'b': 35}, showlegend=False,
            )
            rolling_corr_section = dcc.Graph(figure=rolling_chart, config={'displayModeBar': False})
        else:
            rolling_corr_section = html.Div(
                f"Not enough overlapping history for a {corr_window}d rolling-correlation view yet "
                f"({result['n_days']} days available) — full-sample correlation above is the only "
                f"diversification read until more saved-backtest history accumulates.",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic',
                       'padding': '30px', 'textAlign': 'center'},
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

        worst_corr_note = (
            f" Worst {corr_window}d window seen: {worst_corr:+.2f}"
            f"{' (≥ flag)' if worst_corr >= corr_flag else ''}."
            if worst_corr is not None else ""
        )
        overlap = html.Div(
            f"Overlapping window: {result['start']:%Y-%m-%d} → {result['end']:%Y-%m-%d} "
            f"({result['n_days']} days). Correlation {corr:+.2f}, diversification ratio "
            f"{div_ratio:.2f}x (weighted-average standalone vol ÷ realised combined vol; "
            f">1 means the books genuinely offset each other)." + worst_corr_note +
            " The Diversification Frontier is fit on this same window only — expect it to "
            "reshape materially when the window changes (realized correlation is a noisy "
            "estimate on finite daily samples, and its effect is amplified at higher margin "
            "share since alpha's notional weight grows fast with margin share). Treat its "
            "curve as \"what this sample says\", not a fixed reference.",
            style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginTop': '10px'},
        )

        body = html.Div([
            # Row 1: per-book metrics + capital allocation + suggested splits (5 cards)
            html.Div([
                _metric_card('Beta Book', result['beta'], THEME['accent'], result['pnl_beta_mm']),
                _metric_card('Alpha Book', result['alpha'], THEME['warning'], result['pnl_alpha_mm'],
                              margin_ann_return=result['alpha_margin_metrics']['ann_return']),
                _metric_card('Combined', combined, THEME['success'], result['pnl_combined_mm']),
                alloc_card,
                reco,
            ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap', 'marginBottom': '14px'}),
            # Row 2: diversification frontier (1) : combined-book backtest (3)
            html.Div([
                html.Div([dcc.Graph(figure=frontier, config={'displayModeBar': False})],
                         style={'flex': '1', 'minWidth': '260px'}),
                html.Div([dcc.Graph(figure=combined_chart, config={'displayModeBar': False})],
                         style={'flex': '3', 'minWidth': '400px'}),
            ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap', 'marginBottom': '14px'}),
            # Row 3: rolling correlation diagnostic, full width
            html.Div([rolling_corr_section]),
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

        return strip, body, margin_hint, formula
