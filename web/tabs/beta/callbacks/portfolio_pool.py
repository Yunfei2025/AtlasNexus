# -*- coding: utf-8 -*-
"""Portfolio (Allocation) tab — asset pool callbacks.

The asset pool is not edited in the Portfolio tab: it is always the assets of the factors
selected in Candidates (SELECTED_FACTOR_POOL), the same pool the backtest trades.

Contains:
  1. Asset pool follows the Candidates factor selection
  2. Use the correlation analysis' recommended factors as the Candidates selection
"""

from __future__ import annotations

import dash
from dash.dependencies import Input, Output

from ..data import DIVERSIFICATION_RECOMMENDATIONS, selected_factors
from ..layouts.portfolio import pool_display_from_factors

# Candidates checklist id -> predicate on a factor code (see layouts/factor.py)
_IR_DOMICILES = ('CN', 'US', 'EU', 'JP', 'UK')
_CR_UNIVERSES = ('CDB', 'LGB', 'MTN', 'NCD')
_FX_CROSS = ('FXDL.EURUSD', 'FXDL.GBPUSD', 'FXDL.JPYUSD')


def _checklist_values(factors):
    """Split a factor list into the values of each Candidates factor checklist, in the
    order of the outputs registered below."""
    fs = list(factors)
    out = [[f for f in fs if f.split('.')[0] in ('IRDL', 'IRSL', 'IRCV') and f.endswith(f'.{d}')]
           for d in _IR_DOMICILES]
    out += [[f for f in fs if f.split('.')[0] in ('CRDL', 'CRSL', 'CRCV') and f.endswith(f'.{u}')]
            for u in _CR_UNIVERSES]
    out.append([f for f in fs if f.startswith('FXDL.') and f not in _FX_CROSS])
    out.append([f for f in fs if f in _FX_CROSS])
    out.append([f for f in fs if f.startswith('EQDL.')])
    out.append([f for f in fs if f.startswith('CMDL.')])
    return out


def register_portfolio_pool_callbacks(app):
    """Register asset-pool callbacks for the Portfolio tab."""

    # 1. The pool follows the Candidates selection. factor-selection-store is written by the
    # Candidates pool counter right after it updates SELECTED_FACTOR_POOL, so read the pool
    # from there (the session store can hold a stale selection on page load).
    @app.callback(
        [Output('asset-pool-store', 'data'),
         Output('asset-pool-display', 'children'),
         Output('pool-count', 'children')],
        Input('factor-selection-store', 'data'),
        prevent_initial_call=True,
    )
    def sync_asset_pool_with_factor_selection(_selection):
        return pool_display_from_factors(selected_factors())

    # 2. Recommended factors from the correlation analysis -> Candidates selection (the pool
    # then follows through callback 1). Uses the global set by the correlation callback since
    # dcc.Store data doesn't persist across tab switches.
    @app.callback(
        [Output('add-diversified-status', 'children')]
        + [Output(f'factor-selection-ir-{d.lower()}', 'value') for d in _IR_DOMICILES]
        + [Output(f'factor-selection-cr-{u.lower()}', 'value') for u in _CR_UNIVERSES]
        + [Output('factor-selection-fx', 'value'),
           Output('factor-selection-fx-cross', 'value'),
           Output('factor-selection-eq', 'value'),
           Output('factor-selection-cmd', 'value')],
        Input('add-diversified-assets-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def use_recommended_factors(n_clicks):
        n_outputs = len(_IR_DOMICILES) + len(_CR_UNIVERSES) + 4
        if not n_clicks:
            return ["", *([dash.no_update] * n_outputs)]
        factors = DIVERSIFICATION_RECOMMENDATIONS.get('factors', [])
        if not factors:
            return ["⚠ No recommended factors available. Please run correlation analysis first.",
                    *([dash.no_update] * n_outputs)]
        values = _checklist_values(factors)
        return [f"✓ {sum(len(v) for v in values)} factors selected; the Portfolio asset pool follows.", *values]
