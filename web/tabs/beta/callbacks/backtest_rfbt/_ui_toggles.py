# -*- coding: utf-8 -*-
"""Small cascading/toggle callbacks for the RFBT parameter panel: factor
dropdown cascade, strategy/tilt param visibility, and per-factor sizing
defaults. Split out of backtest_rfbt.py so the run/save/train callbacks
aren't buried alongside this UI plumbing."""

from __future__ import annotations

from dash.dependencies import Input, Output, State

# Factor options grouped by asset class (mirrors the Factor History sidebar)
RFBT_FACTOR_OPTIONS = {
    'Rates': [
        {'label': 'IRDL.CN — China Level',       'value': 'IRDL.CN'},
        {'label': 'IRSL.CN — China Slope',        'value': 'IRSL.CN'},
        {'label': 'IRCV.CN — China Curvature',    'value': 'IRCV.CN'},
        {'label': 'IRDL.US — US Level',           'value': 'IRDL.US'},
        {'label': 'IRSL.US — US Slope',           'value': 'IRSL.US'},
        {'label': 'IRDL.DE — Europe Level',       'value': 'IRDL.DE'},
        {'label': 'IRDL.JP — Japan Level',        'value': 'IRDL.JP'},
        {'label': 'IRDL.UK — UK Level',           'value': 'IRDL.UK'},
    ],
    'Credit': [
        {'label': 'CRDL.CDB — CDB Level',         'value': 'CRDL.CDB'},
        {'label': 'CRSL.CDB — CDB Slope',         'value': 'CRSL.CDB'},
        {'label': 'CRCV.CDB — CDB Curvature',     'value': 'CRCV.CDB'},
        {'label': 'CRDL.LGB — LGB Level',         'value': 'CRDL.LGB'},
        {'label': 'CRSL.LGB — LGB Slope',         'value': 'CRSL.LGB'},
        {'label': 'CRCV.LGB — LGB Curvature',     'value': 'CRCV.LGB'},
        {'label': 'CRDL.MTN — MTN Level',         'value': 'CRDL.MTN'},
        {'label': 'CRSL.MTN — MTN Slope',         'value': 'CRSL.MTN'},
        {'label': 'CRCV.MTN — MTN Curvature',     'value': 'CRCV.MTN'},
        {'label': 'CRDL.NCD — NCD Level',         'value': 'CRDL.NCD'},
        {'label': 'CRSL.NCD — NCD Slope',         'value': 'CRSL.NCD'},
    ],
    'FX': [
        {'label': 'FXDL.USDCNY',                 'value': 'FXDL.USDCNY'},
        {'label': 'FXDL.EURCNY',                 'value': 'FXDL.EURCNY'},
        {'label': 'FXDL.JPYCNY',                 'value': 'FXDL.JPYCNY'},
        {'label': 'FXDL.GBPCNY',                 'value': 'FXDL.GBPCNY'},
    ],
    'Commodities': [
        {'label': 'CMDL.AU — Gold',              'value': 'CMDL.AU'},
        {'label': 'CMDL.CU — Copper',            'value': 'CMDL.CU'},
        {'label': 'CMDL.AL — Aluminium',         'value': 'CMDL.AL'},
        {'label': 'CMDL.SC — Crude Oil',         'value': 'CMDL.SC'},
    ],
}


def register_ui_toggle_callbacks(app):
    """Register the RFBT parameter-panel cascade/toggle callbacks onto *app*."""

    @app.callback(
        [Output('rfbt-factor', 'options'),
         Output('rfbt-factor', 'value')],
        Input('rfbt-asset-class', 'value'),
    )
    def update_rfbt_factor_options(asset_class):
        """Cascade: populate the Factor dropdown when Asset Class changes."""
        opts = RFBT_FACTOR_OPTIONS.get(asset_class, [])
        default = opts[0]['value'] if opts else None
        return opts, default

    @app.callback(
        [Output('rfbt-ma-params', 'style'),
         Output('rfbt-boll-params', 'style'),
         Output('rfbt-mom-params', 'style'),
         Output('rfbt-zscore-params', 'style'),
         Output('rfbt-fm-params', 'style')],
        Input('rfbt-strategy-selector', 'data'),
    )
    def toggle_rfbt_strategy_params(strategy):
        """Show/hide strategy-specific parameter inputs."""
        flex = {'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '8px'}
        hide = {'display': 'none'}
        return (hide, hide, hide, hide, flex)

    @app.callback(
        Output('rfbt-fm-tilt-params', 'style'),
        Input('rfbt-fm-sizing', 'value'),
    )
    def toggle_rfbt_tilt_params(sizing_mode):
        """Reveal the tilt baseline/amplitude inputs only in 'tilt' mode."""
        return {'display': 'block'} if sizing_mode == 'tilt' else {'display': 'none'}

    @app.callback(
        [Output('rfbt-fm-sizing', 'value'),
         Output('rfbt-fm-tiltbase', 'value'),
         Output('rfbt-fm-tiltamp', 'value')],
        Input('rfbt-factor', 'value'),
    )
    def apply_factor_sizing_default(factor_val):
        """Pre-select the sizing mode this factor is configured for.

        Mirrors ``multiasset.factor_model._FACTOR_SIZING_OVERRIDES`` so the
        panel opens on the same mode the engine would use by default (e.g.
        IRDL.CN → tilt). The user can still change it; an explicit choice is
        always passed through to the backtest.
        """
        from multiasset.factor_model import factor_sizing_override, FactorModelConfig
        defaults = FactorModelConfig()
        ov = factor_sizing_override(factor_val) if factor_val else {}
        return (
            ov.get('sizing_mode', defaults.sizing_mode),
            ov.get('tilt_base', defaults.tilt_base),
            ov.get('tilt_amp', defaults.tilt_amp),
        )
