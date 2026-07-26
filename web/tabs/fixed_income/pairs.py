"""Pairs tab (Alpha Book > Pairs subtab).

Provides `build_pairs_layout()` and `register_pairs_callbacks(app)` for the
legacy "Pairs Analysis" dashboard content, migrated from `web.core.content`
onto the AtlasNexus Dash app instance.
"""

from __future__ import annotations

from dash import dcc, html
from dash.dependencies import Input, Output

from .common import _fi_card_header


def build_pairs_layout():
    """Build the optimized 'Pairs' tab layout with smart cards and live stats."""
    from web.core.styles import app_color
    from web.tabs.alpha.data import THEME

    _label_style = {
        'color': THEME['text_sub'], 'fontSize': '9px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '4px', 'display': 'block',
    }
    _pair_input_style = {
        "width": "100%", "padding": "4px", "fontSize": "11px",
        "backgroundColor": THEME["bg_input"], "color": THEME["text_main"],
        "border": f"1px solid {THEME['border']}", "borderRadius": "2px", "boxSizing": "border-box",
    }

    def _pair_config_cell(title, leg1_id, leg1_val, leg2_id, leg2_val, hint):
        return html.Div([
            html.Div(title, style={"fontSize": "10px", "fontWeight": "600", "color": THEME["text_sub"], "marginBottom": "4px"}),
            html.Div([
                dcc.Input(id=leg1_id, type='text', value=leg1_val, style=_pair_input_style),
                dcc.Input(id=leg2_id, type='text', value=leg2_val, style={**_pair_input_style, "marginTop": "3px"}),
                html.Div(hint, style={"fontSize": "10px", "color": THEME["text_sub"], "marginTop": "4px", "fontStyle": "italic"}),
            ]),
        ], style={
            "padding": "8px",
            "backgroundColor": "var(--surface-panel)",
            "border": f"1px solid {THEME['border_sub']}",
            "borderRadius": "4px",
        })

    return html.Div([
        html.Div([
            html.H1("Pairs Analysis", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "Relative value spreads with OLS trends and confidence bands",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Main layout: Controls (left) + Charts (right) ──────────────────────
        html.Div([
            # Controls card — narrow, fixed width
            html.Div([
                _fi_card_header("Controls"),
                html.Div([
                    html.Div([
                        html.Label("Lookback Days", style=_label_style),
                        dcc.Input(
                            id='pairs-days-input', type='number', value=90, min=1,
                            style={"width": "100%", "padding": "6px 8px", "boxSizing": "border-box",
                                   "backgroundColor": THEME["bg_input"], "color": THEME["text_main"],
                                   "border": f"1px solid {THEME['border']}", "borderRadius": "4px",
                                   "fontSize": "11px", "textAlign": "right"},
                        ),
                    ]),

                    html.Details([
                        html.Summary("⚙ Configure", style={
                            'padding': '6px 12px', 'background': 'var(--surface-panel)',
                            'color': 'var(--text-secondary)', 'border': '1px solid var(--border-default)',
                            'borderRadius': '4px', 'fontSize': '10px', 'cursor': 'pointer', 'listStyle': 'none',
                        }),
                        html.Div([
                            _pair_config_cell("Pair 1", 'pairs-leg1-1', '260010.IB', 'pairs-leg2-1', '260008.IB', "CGB-5s10s"),
                            _pair_config_cell("Pair 2", 'pairs-leg1-2', '2600002.IB', 'pairs-leg2-2', '260010.IB', "CGB-10s20s"),
                            _pair_config_cell("Pair 3", 'pairs-leg1-3', '260205.IB', 'pairs-leg2-3', '260010.IB', "CDBCGB-10y"),
                            _pair_config_cell("Pair 4", 'pairs-leg1-4', '260008.IB', 'pairs-leg2-4', 'FR007S5Y.IR', "CGBRepo7d-5y"),
                        ], style={"display": "grid", "gridTemplateColumns": "minmax(0, 1fr)", "gap": "10px",
                                  "padding": "10px", "marginTop": "6px",
                                  "maxHeight": "360px", "overflowY": "auto",
                                  "backgroundColor": THEME["bg_input"], "borderRadius": "4px",
                                  "border": f"1px solid {THEME['border']}"}),
                    ]),

                    html.Button(
                        "↻ Refresh", id="pairs-refresh-btn", n_clicks=0,
                        style={'padding': '6px 12px', 'background': THEME['accent'], 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': '700',
                               'cursor': 'pointer', 'width': '100%'},
                    ),
                    html.Span(
                        id="pairs-last-updated", children="—",
                        style={"color": THEME["text_sub"], "fontSize": "8px", "fontFamily": "monospace"},
                    ),

                    # ── Z-Score Thresholds (moved to bottom, vertically stacked) ──
                    html.Div([
                        html.Div("Z-Score Thresholds", style={'fontSize': '10px', 'fontWeight': '600', 'color': THEME['text_sub'], 'marginBottom': '8px'}),
                        html.Div([
                            html.Div([
                                html.Span(style={'width': '8px', 'height': '8px', 'borderRadius': '50%',
                                                 'background': color, 'display': 'inline-block', 'flexShrink': '0'}),
                                html.Span([
                                    html.Span(label, style={'color': 'var(--text-secondary)', 'fontWeight': '600', 'display': 'block', 'fontSize': '9px'}),
                                    html.Span(rng, style={'color': 'var(--text-muted)', 'fontSize': '8px'}),
                                ], style={'minWidth': '0', 'flex': '1'}),
                            ], style={'display': 'flex', 'alignItems': 'flex-start', 'gap': '6px'})
                            for color, rng, label in [
                                ('#a4b6d2', '|z| < 1.5', 'Neutral'),
                                (THEME['accent'], '1.5 ≤ |z| < 2.0', 'Watch'),
                                ('#e06060', '|z| ≥ 2.0', 'Signal'),
                            ]
                        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '6px', 'fontSize': '9px'}),
                    ], style={'padding': '10px', 'background': THEME['bg_input'], 'borderRadius': '4px',
                              'border': f"1px solid {THEME['border_sub']}"}),
                ], style={'padding': '12px 14px', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
            ], style={'width': '280px', 'minWidth': '280px', 'flexShrink': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'visible'}),

            # ── Results panel: 2x2 grid for pair cards (right side) ──────────
            html.Div(
                id="pairs-plots-container",
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "10px", "flex": "1", "minWidth": "0"},
                children=[
                    html.Div([
                        html.Div(
                            "Click Refresh to generate pair analysis",
                            style={"textAlign": "center", "color": THEME["text_sub"],
                                   "padding": "40px 20px", "fontSize": "12px"}
                        )
                    ])
                ],
            ),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-start'}),

        # ── Hidden loader for triggering updates ────────────────────────────
        html.Div(id="pairs-content-loader", style={"display": "none"}),
    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})


def _z_score_color(z):
    """Return hex color for a z-score value based on statistical thresholds.

    Color thresholds:
    - |z| ≥ 2.0:       Red (#e06060)      — Signal: statistically extreme
    - 1.5 ≤ |z| < 2.0: Amber (#e8a13f)   — Watch: elevated deviation
    - |z| < 1.5:       Muted (#a4b6d2)   — Neutral: within noise

    Args:
        z: Z-score value (float)

    Returns:
        str: Hex color code
    """
    az = abs(z)
    if az >= 2.0:
        return '#e06060'  # red — signal
    elif az >= 1.5:
        return '#e8a13f'  # amber — watch
    else:
        return '#a4b6d2'  # muted — neutral


def _build_pair_card(leg1, leg2, stats, figure=None):
    """Build a pair card with smart header showing live stats.

    Header displays:
    - Pair names: bold instrument codes
    - last: current spread in basis points
    - β (beta): slope (change per day)
    - z (z-score): deviation from mean, color-coded by _z_score_color()

    Args:
        leg1, leg2: Instrument names (strings)
        stats: Dict with keys: last_bp, slope (beta), last_z (z-score)
        figure: Plotly figure object (optional)

    Returns:
        html.Div: Card component with header and chart
    """
    from web.tabs.alpha.data import THEME

    z = stats.get('last_z', 0.0)
    slope = stats.get('slope', 0.0)
    last_bp = stats.get('last_bp', 0.0)

    # Determine z-score color based on thresholds (see _z_score_color docs)
    z_color = _z_score_color(z)

    sign_z = '+' if z >= 0 else ''
    sign_slope = '+' if slope >= 0 else ''

    # Build header with stats
    header = html.Div(
        [
            html.Div([
                html.B(leg1, style={'color': '#e9eef8'}),
                html.Span(' vs ', style={'color': '#4a5d7c'}),
                html.B(leg2, style={'color': '#e9eef8'}),
            ], style={
                'fontSize': '11px',
                'fontWeight': '700',
                'letterSpacing': '0.09em',
                'textTransform': 'uppercase',
                'color': '#6f83a3',
            }),
            html.Div([
                html.Span(['last ', html.B(f'{last_bp:.1f} bp')]),
                html.Span(['β ', html.B(f'{sign_slope}{slope:.3f}/d')]),
                html.Span([
                    'z ',
                    html.Span(f'{sign_z}{z:.1f}σ', style={'color': z_color, 'fontWeight': '700'}),
                ]),
            ], style={
                'display': 'flex',
                'gap': '16px',
                'fontSize': '12px',
                'color': '#6f83a3',
            }),
        ],
        style={
            'padding': '13px 18px',
            'borderBottom': '1px solid rgba(255,255,255,0.06)',
            'display': 'flex',
            'alignItems': 'baseline',
            'justifyContent': 'space-between',
            'gap': '12px',
            'background': '#17345c',
        },
        className='pair-card__header',
    )

    # Build chart section
    if figure:
        chart = dcc.Graph(
            figure=figure,
            config={'displayModeBar': 'hover', 'displaylogo': False, 'responsive': True},
            style={'height': '430px'},
        )
    else:
        chart = html.Div(
            'Loading chart...',
            style={'height': '430px', 'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center', 'color': THEME['text_sub']},
        )

    # Build card
    return html.Div(
        [header, chart],
        className='pair-card',
        style={
            'background': '#0e1d3a',
            'border': '1px solid #1e3a5f',
            'borderRadius': '7px',
            'overflow': 'hidden',
        },
    )


def register_pairs_callbacks(app) -> None:
    """Register the callbacks required by `build_pairs_layout()` onto `app`."""
    from dash import callback_context
    import datetime
    import pandas as pd

    try:
        import plotly.graph_objs as go
        PLOTTING_AVAILABLE = True
    except Exception as e:
        print(f"Warning: Plotting dependencies not available: {e}")
        PLOTTING_AVAILABLE = False
        go = None

    @app.callback(
        [Output("pairs-plots-container", "children"), Output("pairs-last-updated", "children")],
        [Input("pairs-content-loader", "children"), Input("pairs-refresh-btn", "n_clicks"),
         Input("pairs-leg1-1", "value"), Input("pairs-leg2-1", "value"),
         Input("pairs-leg1-2", "value"), Input("pairs-leg2-2", "value"),
         Input("pairs-leg1-3", "value"), Input("pairs-leg2-3", "value"),
         Input("pairs-leg1-4", "value"), Input("pairs-leg2-4", "value"),
         Input("pairs-days-input", "value")],
    )
    def _load_pairs_content(_, n_clicks, leg1_1, leg2_1, leg1_2, leg2_2, leg1_3, leg2_3, leg1_4, leg2_4, window_days):
        """Build pair cards with Plotly figures and smart headers showing live stats."""
        from web.tabs.alpha.data import THEME
        import numpy as np

        # Determine if we should recompute pairs analysis
        trigger_id = None
        cards = []
        last_updated = "Last updated: Loading..."

        if callback_context.triggered:
            trigger_id = callback_context.triggered[0]["prop_id"].split(".")[0]
            if trigger_id == "pairs-refresh-btn" and n_clicks and n_clicks > 0:
                try:
                    from pairs.manager import PairManager

                    # Validate window_days
                    if not window_days or window_days < 1:
                        window_days = 90

                    # Create PairManager and add pairs based on user inputs
                    manager = PairManager()

                    # Add pairs if both legs are provided
                    pairs_config = [
                        ("Pair 1", leg1_1, leg2_1),
                        ("Pair 2", leg1_2, leg2_2),
                        ("Pair 3", leg1_3, leg2_3),
                        ("Pair 4", leg1_4, leg2_4),
                    ]

                    for name, leg1, leg2 in pairs_config:
                        if leg1 and leg2 and leg1.strip() and leg2.strip():
                            manager.add_pair(name, leg1.strip(), leg2.strip(), window=int(window_days))

                    if len(manager) == 0:
                        raise ValueError("No valid pairs configured. Please provide at least one pair.")

                    # Prepare analysis for all pairs
                    analyses = manager.prepare_analysis()

                    # Build cards with Plotly figures
                    for pair_name, pair in manager.pairs.items():
                        if pair_name not in analyses:
                            continue

                        analysis = analyses[pair_name]
                        spread_df = analysis.get('spread_df')
                        reg_result = analysis.get('regression_result')

                        if spread_df is None or len(spread_df) == 0:
                            continue

                        # Extract numeric spread values properly
                        if isinstance(spread_df, pd.DataFrame):
                            # Try to get 'spread' column first, fallback to first numeric column
                            if 'spread' in spread_df.columns:
                                spread = pd.to_numeric(spread_df['spread'], errors='coerce').values
                            else:
                                # Find first numeric column
                                for col in spread_df.columns:
                                    try:
                                        spread = pd.to_numeric(spread_df[col], errors='coerce').values
                                        if not np.all(np.isnan(spread)):
                                            break
                                    except:
                                        continue

                            # Extract dates: try 'date' column or use index
                            if 'date' in spread_df.columns:
                                dates = pd.to_datetime(spread_df['date']).values
                            else:
                                dates = spread_df.index
                        else:
                            # If it's a Series
                            spread = pd.to_numeric(spread_df, errors='coerce').values
                            dates = spread_df.index

                        # Remove NaN values
                        valid_idx = ~np.isnan(spread)
                        spread = spread[valid_idx]
                        if isinstance(dates, np.ndarray):
                            dates = dates[valid_idx]
                        else:
                            dates = dates[valid_idx] if hasattr(dates, '__getitem__') else dates

                        if len(spread) < 2:
                            continue

                        # OLS fit
                        xs = np.arange(len(spread), dtype=float)
                        slope, intercept = np.polyfit(xs, spread, 1)
                        trend = intercept + slope * xs
                        resid = spread - trend
                        sigma = resid.std()
                        last_z = resid[-1] / sigma if sigma > 0 else 0.0

                        stats = {
                            'last_bp': float(spread[-1]),
                            'slope': float(slope),
                            'last_z': float(last_z),
                        }

                        # Build Plotly figure
                        fig = go.Figure()

                        # Upper and lower bands (±1σ)
                        upper = trend + sigma
                        lower = trend - sigma

                        fig.add_trace(go.Scatter(
                            x=dates, y=upper,
                            mode='lines',
                            line=dict(width=0),
                            showlegend=False,
                            hoverinfo='skip',
                        ))
                        fig.add_trace(go.Scatter(
                            x=dates, y=lower,
                            mode='lines',
                            line=dict(width=0),
                            fill='tonexty',
                            fillcolor='rgba(69,182,230,0.10)',
                            name='±1σ confidence',
                            hoverinfo='skip',
                        ))

                        # Spread points
                        fig.add_trace(go.Scatter(
                            x=dates, y=spread,
                            mode='markers',
                            name='Spread',
                            marker=dict(color='#7fd1c0', size=5, opacity=0.85),
                        ))

                        # Trend line (cyan hero)
                        fig.add_trace(go.Scatter(
                            x=dates, y=trend,
                            mode='lines',
                            name='Trend (OLS)',
                            line=dict(color='#45b6e6', width=2.5),
                        ))

                        # Update layout with AtlasNexus theme
                        fig.update_layout(
                            paper_bgcolor='#0e1d3a',
                            plot_bgcolor='#0e1d3a',
                            font=dict(family='-apple-system,system-ui,sans-serif', color='#6f83a3', size=12),
                            margin=dict(l=48, r=16, t=30, b=36),
                            hovermode='x unified',
                            xaxis=dict(
                                gridcolor='rgba(255,255,255,0.06)',
                                zeroline=False,
                                linecolor='rgba(255,255,255,0.18)',
                                ticks='outside',
                                tickcolor='rgba(255,255,255,0.18)',
                                tickfont=dict(size=11, color='#6f83a3'),
                                nticks=7,
                            ),
                            yaxis=dict(
                                title=dict(text='Spread (bp)', font=dict(size=11, color='#6f83a3')),
                                gridcolor='rgba(255,255,255,0.06)',
                                zeroline=False,
                                linecolor='rgba(255,255,255,0.18)',
                                ticks='outside',
                                tickcolor='rgba(255,255,255,0.18)',
                                tickfont=dict(size=11, color='#6f83a3'),
                            ),
                            legend=dict(
                                orientation='h', x=0, y=1.06,
                                xanchor='left', yanchor='bottom',
                                bgcolor='rgba(0,0,0,0)', borderwidth=0,
                                font=dict(size=11, color='#6f83a3'),
                            ),
                            showlegend=True,
                        )

                        # Build card
                        card = _build_pair_card(pair.leg1, pair.leg2, stats, fig)
                        cards.append(card)

                    last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

                except Exception as e:
                    import traceback
                    print(f"Pairs analysis error: {str(e)}")
                    traceback.print_exc()
                    last_updated = f"Error: {str(e)[:100]} at {datetime.datetime.now().strftime('%H:%M:%S')}"
                    cards = [html.Div(f"Error: {str(e)[:120]}", style={'color': THEME['text_sub']})]

            elif trigger_id in {
                "pairs-leg1-1", "pairs-leg2-1",
                "pairs-leg1-2", "pairs-leg2-2",
                "pairs-leg1-3", "pairs-leg2-3",
                "pairs-leg1-4", "pairs-leg2-4",
                "pairs-days-input",
            }:
                last_updated = "Pending changes - click Refresh Plots"
                cards = [html.Div("Waiting for refresh...", style={'color': THEME['text_sub'], 'padding': '40px', 'textAlign': 'center'})]
            else:
                last_updated = f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            last_updated = "Last updated: Loading..."

        # Return cards or placeholder. NOTE: pairs-plots-container is a CSS
        # grid (2 columns); the children list must be the cards themselves,
        # not a single wrapper html.Div, otherwise spacing/scroll behavior is
        # harder to control from CSS.
        if not cards:
            content = [html.Div(
                "Click 'Refresh' to generate pair analysis",
                style={'color': THEME['text_sub'], 'padding': '40px', 'textAlign': 'center', 'gridColumn': '1 / -1'},
            )]
        else:
            content = cards

        return content, last_updated
