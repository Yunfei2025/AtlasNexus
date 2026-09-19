# -*- coding: utf-8 -*-
"""Sector PCA rich/cheap pair screen callbacks (Candidates subtab).

Renders the output of web.tabs.alpha.sector_pca_screen.screen_sector_pca_pairs
as pair cards with an "Add pair" button. Adding a pair appends BOTH legs
(oversold -> BUY, overbought -> SELL) to the same `alpha-selected-candidates`
store the main MR/momentum scan populates, so they flow through the existing
correlation-check and portfolio-sizing workflow unchanged -- no special-
casing needed downstream since that store is consumed generically via
ID/spread_type/direction/Zscore (see correlation_callbacks.py,
portfolio.py).

SectorPCASpread candidates are NOT run through curves.refreshers.
alpha_candidates.build_alpha_candidates (the main scan's source): that
pipeline's row schema is built around carry_roll/borrow-cost/saved
backtest params, none of which apply to a PCA residual pair. Kept as a
separate, additive screen instead of forcing this schema.
"""

from __future__ import annotations

import json as _json

from dash import html, callback_context
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from ..data import THEME, display_key
from ..sector_pca_screen import screen_sector_pca_pairs, SPREAD_TYPE
from .helpers import _merge_curated_entries, _normalize_curated_entry


def _pair_id(cheap_ticker: str, rich_ticker: str) -> str:
    return f"{cheap_ticker}||{rich_ticker}"


def _leg_pill(direction: str) -> html.Span:
    is_buy = direction == 'BUY'
    return html.Span(direction, style={
        'backgroundColor': THEME['success'] if is_buy else THEME['danger'],
        'color': '#000' if is_buy else '#fff',
        'fontWeight': 'bold', 'fontSize': '10px', 'padding': '2px 8px',
        'borderRadius': '3px', 'minWidth': '36px', 'textAlign': 'center',
        'display': 'inline-block',
    })


def _leg_row(ticker: str, direction: str, z: float, r2, halflife, stationary: str | None) -> html.Div:
    r2_txt = f"{r2:.2f}" if r2 is not None else "n/a"
    hl_txt = f"{halflife:.1f}d" if halflife is not None else "n/a"
    return html.Div([
        _leg_pill(direction),
        html.Span(display_key(SPREAD_TYPE, ticker), style={
            'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '500', 'marginLeft': '8px',
        }),
        html.Span(f"Z={z:+.2f}  R²={r2_txt}  t½={hl_txt}  stationary={stationary or 'n/a'}", style={
            'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '10px',
        }),
    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '3px'})


def _pair_card(cand) -> html.Div:
    cheap, rich = cand.cheap, cand.rich
    passes = cand.passes
    border_color = THEME['success'] if passes else THEME['warning']

    header = html.Div([
        html.Span('✓ Passes screen' if passes else '⚠ Flagged', style={
            'color': border_color, 'fontSize': '11px', 'fontWeight': '700',
        }),
        html.Span(
            f"  spread Z={cand.spread_zscore:+.2f}" if cand.spread_zscore is not None else "",
            style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '6px'},
        ),
        html.Span(
            f"  leg corr={cand.leg_corr:+.2f}" if cand.leg_corr is not None else "",
            style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '6px'},
        ),
    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '6px'})

    legs = html.Div([
        _leg_row(cheap.ticker, 'BUY', cheap.zscore, cheap.r2, cheap.halflife, cheap.stationary),
        _leg_row(rich.ticker, 'SELL', rich.zscore, rich.r2, rich.halflife, rich.stationary),
    ])

    reasons_div = None
    if cand.reasons:
        reasons_div = html.Ul(
            [html.Li(r, style={'fontSize': '9px', 'color': THEME['warning']}) for r in cand.reasons],
            style={'margin': '6px 0 0', 'paddingLeft': '16px'},
        )

    add_btn = html.Button(
        'Add pair to candidates',
        id={'type': 'alpha-pca-pair-add', 'pair': _pair_id(cheap.ticker, rich.ticker)},
        n_clicks=0,
        title=(
            'Adds both legs to the candidate list below (BUY the oversold leg, '
            'SELL the overbought leg).' if passes else
            'This pair failed one or more reversion checks -- adding it is a '
            'deliberate override, not a recommendation.'
        ),
        style={
            'marginTop': '8px', 'padding': '4px 12px',
            'background': 'transparent', 'color': border_color,
            'border': f'1px solid {border_color}', 'borderRadius': '3px',
            'fontSize': '10px', 'fontWeight': '700', 'cursor': 'pointer',
        },
    )

    return html.Div([header, legs, reasons_div, add_btn], style={
        'padding': '10px 12px', 'borderRadius': '4px',
        'backgroundColor': THEME['bg_card'], 'borderLeft': f'3px solid {border_color}',
        'marginBottom': '8px',
    })


def register_pca_pairs_callbacks(app) -> None:
    @app.callback(
        Output('alpha-pca-pairs-container', 'children'),
        Input('alpha-pca-scan-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def scan_pca_pairs(n_clicks):
        if not n_clicks:
            raise PreventUpdate

        candidates = screen_sector_pca_pairs(top_n=3)
        if not candidates:
            return html.Div(
                "No Sector PCA data available, or fewer than 2 instruments have a "
                "computed residual. Run the EOD job to (re)generate Misc-spds.pkl.",
                style={'color': THEME['text_sub'], 'fontSize': '12px', 'fontStyle': 'italic'},
            )

        cards = [_pair_card(c) for c in candidates]
        n_pass = sum(1 for c in candidates if c.passes)
        summary = html.Div(
            f"{n_pass} of {len(candidates)} candidate pair(s) pass the reversion screen "
            "(gap-to-field, residual turned, R² fit, OU stationarity/halflife on the "
            "constructed spread).",
            style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginBottom': '8px'},
        )
        return html.Div([summary] + cards)

    @app.callback(
        [Output('alpha-selected-candidates', 'data', allow_duplicate=True),
         Output('alpha-scan-status', 'children', allow_duplicate=True)],
        Input({'type': 'alpha-pca-pair-add', 'pair': ALL}, 'n_clicks'),
        State('alpha-selected-candidates', 'data'),
        prevent_initial_call=True,
    )
    def add_pca_pair(_, existing):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trig = ctx.triggered[0]
        if not trig.get('value'):
            # Fires once on initial pattern registration with n_clicks=0/None; ignore.
            raise PreventUpdate

        raw_id = trig.get('prop_id', '').split('.n_clicks')[0]
        try:
            btn_id = _json.loads(raw_id)
        except Exception:
            raise PreventUpdate

        pair_key = str(btn_id.get('pair', '') or '')
        if '||' not in pair_key:
            raise PreventUpdate
        cheap_ticker, rich_ticker = pair_key.split('||', 1)

        # Re-screen rather than trust stale button state, so the added rows
        # reflect current data even if the pickle refreshed since the scan
        # rendered these cards.
        candidates = screen_sector_pca_pairs(top_n=10)
        match = next(
            (c for c in candidates
             if c.cheap.ticker == cheap_ticker and c.rich.ticker == rich_ticker),
            None,
        )
        if match is None:
            raise PreventUpdate

        new_entries = [
            _normalize_curated_entry({
                'ID': match.cheap.ticker,
                'spread_type': SPREAD_TYPE,
                'direction': 'BUY',
                'style': 'meanreversion',
                'Zscore': round(match.cheap.zscore, 4),
                'halflife': match.cheap.halflife,
                'manual': True,
            }, infer_regime=False),
            _normalize_curated_entry({
                'ID': match.rich.ticker,
                'spread_type': SPREAD_TYPE,
                'direction': 'SELL',
                'style': 'meanreversion',
                'Zscore': round(match.rich.zscore, 4),
                'halflife': match.rich.halflife,
                'manual': True,
            }, infer_regime=False),
        ]

        merged = _merge_curated_entries(existing or [], new_entries)
        status = (
            f"Added Sector PCA pair: BUY {display_key(SPREAD_TYPE, match.cheap.ticker)} / "
            f"SELL {display_key(SPREAD_TYPE, match.rich.ticker)}"
        )
        return merged, status
