# -*- coding: utf-8 -*-
"""Risk / Summary tab layout."""

from __future__ import annotations

from dash import dcc, html, dash_table
import plotly.graph_objects as go

from ..data import THEME, ALLOCATION_RESULTS


def build_multiasset_risk_layout():
    """Build the layout for the Risk/Summary tab.

    Structure:
    1. Combination: Beta/Alpha composition (Total = Rf + Beta + Alpha)
    2. Exposure: Risk Factor sensitivities (Heatmap)
    3. Ticket: Detailed allocation/trade list
    """

    # --- 1. Combination Data (Placeholders as requested) ---
    risk_free_rate = 1.5

    # Beta (Strategic Asset Allocation)
    beta_vol = 15.0
    beta_sharpe = 0.4
    beta_ret = beta_vol * beta_sharpe  # 6.0%

    # Alpha (Tactical Adjustments)
    alpha_vol = 5.0
    alpha_ir = 0.5
    alpha_ret = alpha_vol * alpha_ir   # 2.5%

    total_ret = risk_free_rate + beta_ret + alpha_ret

    # Styling helpers
    def card_style(bg_color=THEME['bg_card']):
        return {
            'backgroundColor': bg_color,
            'padding': '15px',
            'borderRadius': '6px',
            'textAlign': 'center',
            'border': f'1px solid {THEME["table_header"]}',
            'flex': '1',
            'margin': '0 5px',
            'minWidth': '150px'
        }

    def value_style(color=THEME['success']):
        return {'fontSize': '24px', 'fontWeight': 'bold', 'color': color, 'margin': '5px 0'}

    def label_style():
        return {'color': THEME['text_sub'], 'fontSize': '12px', 'textTransform': 'uppercase', 'letterSpacing': '1px'}

    # --- Prepare Data for Exposure ---
    heatmap_fig = go.Figure()
    vol_table = None

    if ALLOCATION_RESULTS['portfolio'] is not None and ALLOCATION_RESULTS['factor_exposures'] is not None:
        try:
            summary = ALLOCATION_RESULTS['summary']
            factor_exp = ALLOCATION_RESULTS['factor_exposures']
            factor_risk = ALLOCATION_RESULTS['factor_risk']
            portfolio = ALLOCATION_RESULTS['portfolio']

            # --- Heatmap Logic ---
            assets_with_allocation = summary[summary['Allocation (CNY)'] >= 1000].nlargest(15, 'Allocation (CNY)')
            factor_names = sorted([f for f in factor_exp['Risk Factor'].unique() if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL', 'SPDL', 'SPSL'))])
            asset_names = assets_with_allocation['Asset'].tolist()

            sensitivity_matrix = []
            for asset_name in asset_names:
                if asset_name in portfolio.assets:
                    asset = portfolio.assets[asset_name]
                    row = [asset.factors.get(factor, 0.0) for factor in factor_names]
                    sensitivity_matrix.append(row)
                else:
                    sensitivity_matrix.append([0.0] * len(factor_names))

            if asset_names and factor_names:
                heatmap_fig = go.Figure(data=go.Heatmap(
                    z=sensitivity_matrix, x=factor_names, y=asset_names,
                    colorscale='RdBu', zmid=0, text=sensitivity_matrix,
                    texttemplate="%{text:.2f}", textfont={"size": 10}
                ))
                heatmap_fig.update_layout(
                    title=None, height=400, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis_title="Risk Factor", yaxis_title="Asset",
                    template=THEME['chart_template'], paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'], font={'color': THEME['text_main']}
                )

            # --- Volatility Table Logic ---
            factor_vol_df = factor_risk[factor_risk['Risk Factor'].isin(factor_names)].copy()
            display_cols = ['Risk Factor', 'Volatility (% ann.)']
            if 'Net Exposure' in factor_vol_df.columns:
                display_cols.append('Net Exposure')
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                display_cols.append('Risk Contribution (%)')
            factor_vol_df = factor_vol_df[display_cols].copy()
            factor_vol_df['Volatility (% ann.)'] = factor_vol_df['Volatility (% ann.)'].apply(lambda x: f"{x:.2f}%")
            if 'Net Exposure' in factor_vol_df.columns:
                factor_vol_df['Net Exposure'] = factor_vol_df['Net Exposure'].apply(
                    lambda x: f"{x:+.3f}"
                )
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                factor_vol_df['Risk Contribution (%)'] = factor_vol_df['Risk Contribution (%)'].apply(lambda x: f"{x:.1f}%")
            factor_vol_df = factor_vol_df.sort_values('Risk Factor')

            tbl_columns = [
                {'name': 'Risk Factor', 'id': 'Risk Factor'},
                {'name': 'Vol', 'id': 'Volatility (% ann.)'},
            ]
            if 'Net Exposure' in factor_vol_df.columns:
                tbl_columns.append({'name': 'Net Exp', 'id': 'Net Exposure'})
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                tbl_columns.append({'name': 'RC %', 'id': 'Risk Contribution (%)'})

            vol_table = dash_table.DataTable(
                data=factor_vol_df.to_dict('records'),
                columns=tbl_columns,
                style_cell={'textAlign': 'center', 'padding': '8px', 'fontSize': '12px',
                          'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold', 'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    {'if': {'filter_query': '{Net Exposure} contains "-"', 'column_id': 'Net Exposure'},
                     'color': THEME.get('danger', '#e74c3c')},
                    {'if': {'filter_query': '{Net Exposure} contains "+"', 'column_id': 'Net Exposure'},
                     'color': THEME.get('success', '#27ae60')},
                ],
                style_table={'overflowY': 'auto', 'maxHeight': '400px'}
            )

        except Exception as e:
            print(f"Error generating Risk Layout: {e}")
            heatmap_fig.update_layout(title=f"Error: {e}")
            vol_table = html.Div(f"Error generating table: {str(e)}", style={'color': THEME['danger'], 'padding': '10px'})

    _tab_style = {
        'backgroundColor': THEME['bg_input'],
        'color': THEME['text_sub'],
        'fontSize': '12px',
        'padding': '6px 20px',
        'border': 'none',
    }
    _tab_sel = lambda col: {
        'backgroundColor': THEME['bg_card'],
        'color': col,
        'fontSize': '12px',
        'padding': '6px 20px',
        'borderTop': f'2px solid {col}',
        'borderBottom': 'none',
    }

    # --- Assemble Layout ---
    return html.Div([

        dcc.Tabs(
            id='summary-main-tabs',
            value='books',
            children=[
                dcc.Tab(label='Books', value='books',
                        style=_tab_style,
                        selected_style=_tab_sel(THEME['accent'])),
                dcc.Tab(label='Risk', value='risk',
                        style=_tab_style,
                        selected_style=_tab_sel(THEME['warning'])),
                dcc.Tab(label='Tickets', value='tickets',
                        style=_tab_style,
                        selected_style=_tab_sel(THEME['success'])),
            ],
            colors={'border': THEME['table_header'],
                    'primary': THEME['accent'],
                    'background': THEME['bg_input']},
            style={'marginBottom': '16px'},
        ),

        # ── Books subtab ─────────────────────────────────────────────────────
        html.Div(id='summary-tab-books', children=[

        # 1. Combination Section
        html.H4("Portfolio Combination", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            # Equation Row
            html.Div([
                 # Target Return
                 html.Div([
                     html.Div("Target Return", style=label_style()),
                     html.Div(f"{total_ret:.1f}%", style=value_style(THEME['accent'])),
                     html.Div("Total Portfolio Target", style={'fontSize': '11px', 'color': THEME['text_sub']})
                 ], style=card_style()),

                 html.Div("=", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),

                 # Risk Free
                 html.Div([
                     html.Div("Risk Free Rate", style=label_style()),
                     html.Div(f"{risk_free_rate:.1f}%", style=value_style(THEME['success'])),
                     html.Div("Cash / Treasury", style={'fontSize': '11px', 'color': THEME['text_sub']})
                 ], style=card_style()),

                 html.Div("+", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),

                 # Beta
                 html.Div([
                     html.Div("Beta Allocation", style=label_style()),
                     html.Div(f"{beta_ret:.1f}%", style=value_style(THEME['warning'])),
                     html.Div([
                         html.Span("Strategic Asset Allocation", style={'display': 'block', 'marginBottom': '5px'}),
                         html.Span(f"{beta_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                         html.Span(" × "),
                         html.Span(f"{beta_sharpe} Sharpe", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                     ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'})
                 ], style=card_style()),

                 html.Div("+", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),

                 # Alpha
                 html.Div([
                     html.Div("Alpha Overlay", style=label_style()),
                     html.Div(f"{alpha_ret:.1f}%", style=value_style(THEME['danger'])),
                     html.Div([
                         html.Span("Tactical Adjustments", style={'display': 'block', 'marginBottom': '5px'}),
                         html.Span(f"{alpha_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['danger']}),
                         html.Span(" × "),
                         html.Span(f"{alpha_ir} IR", style={'fontWeight': 'bold', 'color': THEME['danger']}),
                     ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'})
                 ], style=card_style()),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center', 'alignItems': 'stretch'}),

            html.Hr(style={'borderColor': THEME['table_header'], 'margin': '18px 0 12px 0'}),

            # Portfolio Allocation Snapshot tabs
            html.Div([
                html.Div([
                    html.Span("Portfolio Allocation Snapshot",
                              style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '13px'}),
                    html.Div([
                        html.Button("Refresh", id='summary-refresh-btn', n_clicks=0,
                                    style={'fontSize': '11px', 'padding': '3px 10px',
                                           'backgroundColor': THEME['bg_input'],
                                           'color': THEME['text_main'],
                                           'border': f'1px solid {THEME["accent"]}',
                                           'borderRadius': '4px', 'cursor': 'pointer'}),
                        html.Span(id='summary-refresh-status',
                                  style={'fontSize': '11px', 'color': THEME['text_sub'],
                                         'fontStyle': 'italic'}),
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),
                ], style={'display': 'flex', 'justifyContent': 'space-between',
                          'alignItems': 'center', 'marginBottom': '8px'}),

                dcc.Tabs(
                    id='summary-book-tabs',
                    value='beta',
                    children=[
                        dcc.Tab(label='Beta Book', value='beta',
                                style={'backgroundColor': THEME['bg_input'],
                                       'color': THEME['text_sub'], 'fontSize': '12px',
                                       'padding': '6px 16px', 'border': 'none'},
                                selected_style={'backgroundColor': THEME['bg_card'],
                                                'color': THEME['accent'], 'fontSize': '12px',
                                                'padding': '6px 16px',
                                                'borderTop': f'2px solid {THEME["accent"]}',
                                                'borderBottom': 'none'}),
                        dcc.Tab(label='Alpha Book', value='alpha',
                                style={'backgroundColor': THEME['bg_input'],
                                       'color': THEME['text_sub'], 'fontSize': '12px',
                                       'padding': '6px 16px', 'border': 'none'},
                                selected_style={'backgroundColor': THEME['bg_card'],
                                                'color': THEME['danger'], 'fontSize': '12px',
                                                'padding': '6px 16px',
                                                'borderTop': f'2px solid {THEME["danger"]}',
                                                'borderBottom': 'none'}),
                    ],
                    colors={'border': THEME['table_header'],
                            'primary': THEME['accent'],
                            'background': THEME['bg_input']},
                    style={'marginBottom': '0'},
                ),

                html.Div(id='summary-book-table-container',
                         style={'minHeight': '60px', 'paddingTop': '10px'}),

            ], style={'backgroundColor': THEME['bg_main'], 'padding': '12px',
                      'borderRadius': '4px', 'marginTop': '4px'}),

        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px', 'marginBottom': '20px'}),

        ]),  # end summary-tab-books

        # ── Risk subtab ──────────────────────────────────────────────────────
        html.Div(id='summary-tab-risk', children=[

        # Header row
        html.Div([
            html.H4("Combined Book Risk", style={
                'color': THEME['text_main'], 'margin': '0',
                'borderBottom': f'2px solid {THEME["warning"]}', 'paddingBottom': '5px', 'flex': '1',
            }),
            html.Div([
                html.Button("Refresh", id='risk-refresh-btn', n_clicks=0, style={
                    'fontSize': '11px', 'padding': '3px 10px',
                    'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'],
                    'border': f'1px solid {THEME["warning"]}', 'borderRadius': '4px', 'cursor': 'pointer',
                }),
                html.Span(id='risk-refresh-status', style={
                    'fontSize': '11px', 'color': THEME['text_sub'], 'fontStyle': 'italic',
                }),
            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),
        ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                  'marginBottom': '16px'}),

        dcc.Loading(type='default', children=[
            # ── Inventory table ───────────────────────────────────────────────
            html.Div([
                html.H6("Position Inventory  (Beta + Alpha)", style={
                    'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '13px',
                }),
                html.Div(id='risk-inventory-container',
                         children=[html.Div("Click Refresh to load positions.",
                                            style={'color': THEME['text_sub'], 'fontStyle': 'italic',
                                                   'padding': '20px', 'textAlign': 'center'})]),
            ], style={'backgroundColor': THEME['bg_card'], 'padding': '14px 16px',
                      'borderRadius': '5px', 'marginBottom': '16px',
                      'border': f'1px solid {THEME["table_header"]}'}),

            # ── Risk exposure table ───────────────────────────────────────────
            html.Div([
                html.H6("Factor Risk Exposure  (Beta + Alpha combined)", style={
                    'color': THEME['warning'], 'marginBottom': '8px', 'fontSize': '13px',
                }),
                html.Div(id='risk-exposure-container',
                         children=[html.Div("Click Refresh to load exposures.",
                                            style={'color': THEME['text_sub'], 'fontStyle': 'italic',
                                                   'padding': '20px', 'textAlign': 'center'})]),
            ], style={'backgroundColor': THEME['bg_card'], 'padding': '14px 16px',
                      'borderRadius': '5px',
                      'border': f'1px solid {THEME["table_header"]}'}),
        ]),

        ], style={'display': 'none'}),

        # ── Tickets subtab ───────────────────────────────────────────────────
        html.Div(id='summary-tab-tickets', children=[

        html.H4("Trade Tickets", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["success"]}', 'paddingBottom': '5px'}),
        html.Div([
            html.Div("Ticket implementation pending...", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'textAlign': 'center', 'padding': '30px'})
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px'}),

        ], style={'display': 'none'}),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})
