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

    # --- Book toggle pill styling helpers ---
    def book_btn_style(active: bool, accent: str):
        base = {
            'padding': '7px 18px', 'fontSize': '13px', 'fontWeight': '500',
            'cursor': 'pointer', 'border': f'1px solid {THEME["table_header"]}',
            'transition': 'all 100ms',
        }
        if active:
            base.update({'backgroundColor': THEME['bg_input'], 'color': accent, 'borderColor': accent})
        else:
            base.update({'backgroundColor': 'transparent', 'color': THEME['text_sub']})
        return base

    def col_pill_style(active: bool):
        base = {
            'display': 'inline-flex', 'alignItems': 'center', 'gap': '5px',
            'padding': '3px 9px', 'borderRadius': '20px', 'fontSize': '10px',
            'fontWeight': '600', 'letterSpacing': '.05em', 'cursor': 'pointer',
            'border': f'1px solid {THEME["table_header"]}',
        }
        if active:
            base.update({'backgroundColor': 'rgba(61,139,212,0.25)', 'color': THEME['text_main'], 'borderColor': THEME['accent']})
        else:
            base.update({'color': THEME['text_sub']})
        return base

    # --- Assemble Layout ---
    # The Books/Risk/Tickets subtab bar is rendered by the app-level
    # _make_tab_switcher; we only build the content divs here.
    return html.Div([

        # ── Books subtab ─────────────────────────────────────────────────────
        html.Div(id='summary-tab-books', children=[

        # 1. Combination Section — collapsed summary strip, expandable on click
        html.Div([
            html.Div([
                html.Span("Portfolio Combination", style={
                    'fontSize': '11px', 'fontWeight': '600', 'letterSpacing': '.08em',
                    'textTransform': 'uppercase', 'color': THEME['text_sub'],
                    'whiteSpace': 'nowrap', 'marginRight': '16px',
                }),
                html.Div([
                    html.Div([
                        html.Span(f"{total_ret:.1f}%", style={'fontSize': '18px', 'fontWeight': '700', 'color': THEME['accent']}),
                        html.Span("Target Return", style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center', 'padding': '4px 20px', 'borderRight': f'1px solid {THEME["table_header"]}'}),
                    html.Span("=", style={'padding': '0 14px', 'color': THEME['table_header'], 'fontSize': '18px'}),
                    html.Div([
                        html.Span(f"{risk_free_rate:.1f}%", style={'fontSize': '18px', 'fontWeight': '700', 'color': THEME['success']}),
                        html.Span("Risk Free", style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center', 'padding': '4px 20px', 'borderRight': f'1px solid {THEME["table_header"]}'}),
                    html.Span("+", style={'padding': '0 14px', 'color': THEME['table_header'], 'fontSize': '18px'}),
                    html.Div([
                        html.Span(f"{beta_ret:.1f}%", style={'fontSize': '18px', 'fontWeight': '700', 'color': THEME['accent']}),
                        html.Span("Beta Alloc", style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center', 'padding': '4px 20px', 'borderRight': f'1px solid {THEME["table_header"]}'}),
                    html.Span("+", style={'padding': '0 14px', 'color': THEME['table_header'], 'fontSize': '18px'}),
                    html.Div([
                        html.Span(f"{alpha_ret:.1f}%", style={'fontSize': '18px', 'fontWeight': '700', 'color': THEME['warning']}),
                        html.Span("Alpha Overlay", style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center', 'padding': '4px 20px'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'flex': '1', 'overflow': 'hidden'}),
                html.Span("▼ details", id='summary-combo-chevron', style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginLeft': '12px', 'flexShrink': '0'}),
            ], id='summary-combo-toggle', n_clicks=0, style={'display': 'flex', 'alignItems': 'center', 'cursor': 'pointer', 'userSelect': 'none', 'padding': '4px 0'}),

            # Expanded detail — collapsed by default
            html.Div(id='summary-combo-detail', children=[
                html.Hr(style={'borderColor': THEME['table_header'], 'margin': '12px 0'}),
                html.Div([
                    html.Div([
                        html.Div("Risk Free Rate", style=label_style()),
                        html.Div(f"{risk_free_rate:.1f}%", style=value_style(THEME['success'])),
                        html.Div("Cash / Treasury", style={'fontSize': '11px', 'color': THEME['text_sub']}),
                    ], style=card_style()),
                    html.Div([
                        html.Div("Beta Allocation", style=label_style()),
                        html.Div(f"{beta_ret:.1f}%", style=value_style(THEME['accent'])),
                        html.Div([
                            html.Span("Strategic Asset Allocation", style={'display': 'block', 'marginBottom': '5px'}),
                            html.Span(f"{beta_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['accent']}),
                            html.Span(" × "),
                            html.Span(f"{beta_sharpe} Sharpe", style={'fontWeight': 'bold', 'color': THEME['accent']}),
                        ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'}),
                    ], style=card_style()),
                    html.Div([
                        html.Div("Alpha Overlay", style=label_style()),
                        html.Div(f"{alpha_ret:.1f}%", style=value_style(THEME['warning'])),
                        html.Div([
                            html.Span("Tactical Adjustments", style={'display': 'block', 'marginBottom': '5px'}),
                            html.Span(f"{alpha_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                            html.Span(" × "),
                            html.Span(f"{alpha_ir} IR", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                        ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'}),
                    ], style=card_style()),
                ], style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center', 'alignItems': 'stretch'}),
            ], style={'display': 'none', 'overflow': 'hidden'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '14px 20px', 'borderRadius': '5px', 'marginBottom': '20px'}),

        # 2. Portfolio Allocation Snapshot — full-width Beta/Alpha toggle
        html.Div([
            html.Div([
                html.Span("Portfolio Allocation Snapshot",
                          style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '13px'}),
                html.Div([
                    # Book toggle pills
                    html.Div([
                        html.Button("Beta Book", id='summary-book-beta-btn', n_clicks=0,
                                     style=book_btn_style(True, THEME['accent'])),
                        html.Button("Alpha Book", id='summary-book-alpha-btn', n_clicks=0,
                                     style=book_btn_style(False, THEME['warning'])),
                    ], style={'display': 'flex'}),
                    html.Button("Refresh", id='summary-refresh-btn', n_clicks=0,
                                style={'fontSize': '11px', 'padding': '3px 10px',
                                       'backgroundColor': THEME['bg_input'],
                                       'color': THEME['text_main'],
                                       'border': f'1px solid {THEME["accent"]}',
                                       'borderRadius': '4px', 'cursor': 'pointer'}),
                    html.Span(id='summary-refresh-status',
                              style={'fontSize': '11px', 'color': THEME['text_sub'],
                                     'fontStyle': 'italic'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between',
                      'alignItems': 'center', 'marginBottom': '12px', 'flexWrap': 'wrap', 'gap': '10px'}),

            # Column-visibility pills — track via dcc.Store, options depend on active book
            dcc.Store(id='summary-book-active', data='beta'),
            dcc.Store(id='summary-col-visibility', data={'open_date': False, 'volume': False, 'score': False}),
            html.Div([
                html.Span("Columns", style={
                    'fontSize': '10px', 'fontWeight': '600', 'letterSpacing': '.07em',
                    'textTransform': 'uppercase', 'color': THEME['text_sub'], 'marginRight': '4px',
                }),
                html.Button("Open Date", id='summary-col-pill-open_date', n_clicks=0, style=col_pill_style(False)),
                html.Button("Volume", id='summary-col-pill-volume', n_clicks=0, style=col_pill_style(False)),
            ], id='summary-col-pills-row', style={'display': 'flex', 'alignItems': 'center', 'gap': '6px', 'marginBottom': '10px', 'flexWrap': 'wrap'}),

            # Single full-width table container — content swapped by book toggle
            html.Div(id='summary-beta-table-container', style={'minHeight': '60px'}),
            html.Div(id='summary-alpha-table-container', style={'minHeight': '60px', 'display': 'none'}),

        ], style={'backgroundColor': THEME['bg_card'], 'padding': '16px 20px', 'borderRadius': '5px'}),
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

        dcc.Loading(type='circle', color=THEME['accent'], children=[
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

            # ── Net position by instrument (Beta + Alpha legs combined) ───────
            html.Div([
                html.H6("Net Position by Instrument  (Beta + Alpha legs)", style={
                    'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '13px',
                }),
                html.Div(id='risk-netpos-container',
                         children=[html.Div("Click Refresh to load positions.",
                                            style={'color': THEME['text_sub'], 'fontStyle': 'italic',
                                                   'padding': '20px', 'textAlign': 'center'})]),
            ], style={'backgroundColor': THEME['bg_card'], 'padding': '14px 16px',
                      'borderRadius': '5px', 'marginBottom': '16px',
                      'border': f'1px solid {THEME["table_header"]}'}),

            # ── Risk exposure table ───────────────────────────────────────────
            html.Div([
                html.H6("Risk Exposure (Beta + Alpha)", style={
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
