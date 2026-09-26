# -*- coding: utf-8 -*-
"""Pure UI callbacks for the Backtest tab: date-mode toggle, factor-pool chip
grid, lookback-preset date range, and min-date info. None of these touch the
historical-allocation backtest itself (see orchestrator.py) — moved verbatim
from backtest_hist.py:36-201, no behaviour change."""

from __future__ import annotations

import pandas as pd
from dash import html
from dash.dependencies import Input, Output, State
from dateutil.relativedelta import relativedelta

from multiasset.risk_loader import RiskFactorLoader
from settings.paths import DIR_INPUT

from ...data import THEME, SELECTED_FACTOR_POOL


def _all_selected_factors() -> list:
    all_factors = []
    all_factors.extend(SELECTED_FACTOR_POOL.get('ir_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('sp_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('cr_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('fx_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('cmd_factors', []))
    all_factors.extend(SELECTED_FACTOR_POOL.get('eq_factors', []))
    return all_factors


def register_ui_callbacks(app):
    """Register the pure-UI (no backtest logic) callbacks for the Backtest tab."""

    # 4.3 Toggle visibility between Preset Lookback and Custom Period
    @app.callback(
        [Output('backtest-lookback-container', 'style'),
         Output('backtest-period-container', 'style')],
        [Input('backtest-date-mode', 'value')],
        prevent_initial_call=False
    )
    def toggle_date_mode_visibility(date_mode):
        """Show/hide lookback dropdown or date range picker based on date mode."""
        print(f"[Backtest Date Mode] Switched to: {date_mode}")
        if date_mode == 'preset':
            print("  → Showing Preset Lookback dropdown, hiding Custom Period picker")
            return (
                {'marginRight': '25px', 'display': 'block'},  # lookback container visible
                {'marginRight': '25px', 'display': 'none'},   # period container hidden
            )
        else:  # custom
            print("  → Showing Custom Period picker, hiding Preset Lookback dropdown")
            return (
                {'marginRight': '25px', 'display': 'none'},   # lookback container hidden
                {'marginRight': '25px', 'display': 'block'},  # period container visible
            )

    # 4.3b Populate Strategy card's Factor Pool chip grid from the live factor pool.
    # backtest-date-mode is just a convenient existing Input to fire this once on page load;
    # its value isn't used since the chip grid doesn't depend on date mode.
    @app.callback(
        Output('backtest-strategy-factor-pool', 'children'),
        [Input('backtest-date-mode', 'value'),
         Input('factor-selection-store', 'data')],
        prevent_initial_call=False
    )
    def update_strategy_factor_pool_chips(_date_mode, _factor_store):
        """Render the current SELECTED_FACTOR_POOL (from the Factor tab) as small chip cards."""
        _CATEGORY_COLOR = {
            'IR':  THEME['accent'],
            'SP':  '#9b6dd6',
            'CR':  '#d6708f',
            'FX':  '#45b6e6',
            'CMD': '#e0a23c',
            'EQ':  '#2f9d6b',
        }
        _PREFIX_CATEGORY = {
            'IRDL': 'IR', 'IRSL': 'IR', 'IRCV': 'IR',
            'SPDL': 'SP', 'SPSL': 'SP',
            'CRDL': 'CR', 'CRSL': 'CR', 'CRCV': 'CR',
            'FXDL': 'FX',
            'CMDL': 'CMD',
            'EQDL': 'EQ',
        }

        all_factors = _all_selected_factors()

        if not all_factors:
            return html.Div("No factors selected", style={'fontSize': '11px', 'color': THEME['text_sub'],
                                                            'gridColumn': '1 / -1'})

        chips = []
        for factor in all_factors:
            prefix = factor.split('.')[0]
            color = _CATEGORY_COLOR.get(_PREFIX_CATEGORY.get(prefix), THEME['text_sub'])
            chips.append(html.Div(
                factor,
                title=factor,
                style={
                    'fontSize': '10px', 'fontWeight': '600', 'color': color,
                    'background': 'var(--surface-input)', 'border': f'1px solid {color}',
                    'borderRadius': '4px', 'padding': '3px 5px', 'textAlign': 'center',
                    'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap',
                },
            ))
        return chips

    # 4.4 Update date range based on lookback preset dropdown
    @app.callback(
        [Output('history-date-range', 'start_date'),
         Output('history-date-range', 'end_date')],
        [Input('backtest-lookback-preset', 'value')],
        prevent_initial_call=True
    )
    def update_date_range_from_lookback(lookback_preset):
        """Update the date range based on the selected lookback period."""
        from datetime import datetime

        end_date = datetime.now().date()

        if lookback_preset == '1Y':
            start_date = end_date - relativedelta(years=1)
        elif lookback_preset == '2Y':
            start_date = end_date - relativedelta(years=2)
        elif lookback_preset == '5Y':
            start_date = end_date - relativedelta(years=5)
        elif lookback_preset == '10Y':
            start_date = end_date - relativedelta(years=10)
        else:
            start_date = end_date - relativedelta(years=2)  # default to 2Y

        return start_date, end_date

    # 4.5 Backtest Min Date Info (earliest valid custom-period start date for the selected factor pool)
    @app.callback(
        Output('backtest-min-date-info', 'children'),
        [Input('run-history-button', 'n_clicks'),
         Input('backtest-date-mode', 'value')],
        [State('backtest-corr-lookback', 'value')],
        prevent_initial_call=False
    )
    def update_backtest_min_date_info(n_clicks, date_mode, corr_lookback):
        """Calculate and display the minimum supported backtest start date for the selected factor pool."""
        all_factors = _all_selected_factors()

        if not all_factors:
            return "ℹ️ Select factors in the Factor tab first to see minimum supported date."

        # Calculate minimum supported date based on selected factors
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            risk_factors = loader.load_risk_factors(use_cache=True)
            risk_factors.index = pd.to_datetime(risk_factors.index)

            available_factors = [f for f in all_factors if f in risk_factors.columns]
            if len(available_factors) >= 2:
                # Find the latest start date among selected factors
                factor_data = risk_factors[available_factors].dropna(how='any')
                factor_data_start = factor_data.index.min()
                factor_data_end = factor_data.index.max()

                # Determine lookback period
                if corr_lookback == '6M':
                    lookback_delta = relativedelta(months=6)
                elif corr_lookback == '1Y':
                    lookback_delta = relativedelta(years=1)
                else:
                    lookback_delta = relativedelta(months=3)

                earliest_valid_date = factor_data_start + lookback_delta

                # Find the limiting factor (the one with latest start date)
                latest_factor = None
                latest_start = None
                for f in available_factors:
                    f_start = risk_factors[f].dropna().index.min()
                    if latest_start is None or f_start > latest_start:
                        latest_start = f_start
                        latest_factor = f

                min_date_info = (f"ℹ️ Min supported date: {earliest_valid_date.strftime('%Y-%m-%d')} "
                               f"(Data: {factor_data_start.strftime('%Y-%m-%d')} ~ {factor_data_end.strftime('%Y-%m-%d')}, "
                               f"limited by {latest_factor})")
            else:
                min_date_info = "⚠️ Not enough factors available in data."
        except Exception as e:
            min_date_info = f"⚠️ Error calculating date range: {str(e)}"

        return min_date_info
