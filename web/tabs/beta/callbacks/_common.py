# -*- coding: utf-8 -*-
"""Shared imports, constants, and helpers used across the Beta callback modules."""

from __future__ import annotations

import pandas as pd
from dash import html

from multiasset.risk_loader import RiskFactorLoader
from settings.paths import DIR_INPUT


_SUMMARY_BETA_PARQUET    = str(DIR_INPUT / 'summary_beta_portfolio.parquet')
_SUMMARY_ALPHA_PARQUET   = str(DIR_INPUT / 'summary_alpha_portfolio.parquet')
_BETA_BOOK_POSITIONS_PARQUET = str(DIR_INPUT / 'beta_book_positions.parquet')
_BETA_BOOK_USER_PARQUET  = str(DIR_INPUT / 'beta_book_user.parquet')
_ALPHA_POSITIONS_PARQUET = str(DIR_INPUT / 'alpha_book_positions.parquet')

# Optional: carry+roll timeseries loader (from alpha data module)
try:
    from web.tabs.alpha.data import load_carry_roll_timeseries as _load_cr_ts
except ImportError:
    try:
        from ...alpha.data import load_carry_roll_timeseries as _load_cr_ts
    except ImportError:
        _load_cr_ts = None

# Map asset-name prefix → primary risk factor (used for close-price lookup)
_ASSET_PREFIX_TO_FACTOR: dict[str, str] = {
    'CN':  'IRDL.CN',  'US':  'IRDL.US',  'EU':  'IRDL.DE',
    'JP':  'IRDL.JP',  'UK':  'IRDL.UK',
    'IRS': 'SPDL.IRS', 'CDB': 'SPDL.CDB', 'ICP': 'SPDL.ICP',
}


def _upsert_snapshot(new_df: pd.DataFrame, parquet_path: str, id_cols: list[str]) -> pd.DataFrame:
    """Insert-or-update by id_cols: keep existing rows, replace matched ones, add new ones.

    Re-running Run Analysis / Run Optimization preserves prior trades that
    are not in the latest run, and refreshes values for trades that are.
    """
    import os
    existing = None
    if os.path.exists(parquet_path):
        try:
            existing = pd.read_parquet(parquet_path)
        except Exception:
            existing = None

    if existing is None or existing.empty:
        new_df.to_parquet(parquet_path, index=False)
        return new_df

    # Align columns: union of both schemas
    all_cols = list(dict.fromkeys(list(existing.columns) + list(new_df.columns)))
    existing = existing.reindex(columns=all_cols)
    new_df = new_df.reindex(columns=all_cols)

    # Drop existing rows whose id_cols match any row in new_df (so we replace)
    if all(c in existing.columns and c in new_df.columns for c in id_cols):
        merge_key = existing[id_cols].astype(str).agg('|'.join, axis=1)
        new_key = set(new_df[id_cols].astype(str).agg('|'.join, axis=1).tolist())
        kept = existing.loc[~merge_key.isin(new_key)].copy()
    else:
        kept = existing.copy()

    merged = pd.concat([kept, new_df], ignore_index=True)

    # After concat, numeric columns may become object dtype due to type
    # mismatches between the existing parquet and the new batch (e.g. Duration
    # stored as string in an old file vs float in the new run).  Cast them back
    # so pyarrow can serialise without ArrowTypeError.
    _NUMERIC_COLS = ('Duration', 'Capital (CNY)', 'DV01 (MM CNY)', 'Weight (%)')
    for _c in _NUMERIC_COLS:
        if _c in merged.columns:
            merged[_c] = pd.to_numeric(merged[_c], errors='coerce')

    merged.to_parquet(parquet_path, index=False)
    return merged


def _allocation_bar(pct: float, color: str, max_pct: float = 25.0) -> html.Div:
    """Capital-allocation mini bar + label, matching guide/SummaryBooks.jsx.

    A thin track with a left-anchored fill proportional to `pct` (scaled
    against `max_pct` so typical weights are readable), plus the numeric
    weight printed alongside — mirrors the Beta Book 'Allocation' column.
    """
    fill_pct = max(0.0, min(100.0, (pct / max_pct) * 100)) if max_pct else 0.0
    return html.Div([
        html.Div(style={
            'flex': '1', 'height': '5px', 'background': 'var(--surface-input)',
            'borderRadius': '3px', 'overflow': 'hidden',
        }, children=[
            html.Div(style={
                'height': '100%', 'width': f'{fill_pct:.1f}%',
                'background': color, 'borderRadius': '3px', 'opacity': '0.7',
            }),
        ]),
        html.Span(f'{pct:.1f}%', style={
            'font': 'var(--type-meta)', 'fontSize': '9px', 'color': 'var(--text-muted)',
            'minWidth': '32px', 'textAlign': 'right',
        }),
    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '6px', 'minWidth': '100px'})


def _price_progress_bar(
    entry: float,
    current: float,
    target: float,
    stop: float,
    direction: str,
    up_color: str = 'rgba(52,211,153,0.5)',
    down_color: str = 'rgba(239,68,68,0.5)',
    current_color: str = 'var(--accent-amber)',
    target_color: str = 'rgba(52,211,153,0.8)',
) -> html.Div:
    """Three-layer price-progress bar, matching guide/SummaryBooks.jsx exactly:

    1. A range-fill from Entry to Current (green if favourable, red if adverse).
    2. A thin amber tick pinned at Current.
    3. A thin green tick pinned at Target.

    All positions are computed against the [min(entry, stop), max(target, entry)]
    span, same as the guide's `mn`/`mx`/`rng` logic.
    """
    lo = min(entry, stop)
    hi = max(target, entry)
    span = (hi - lo) or 1.0
    entry_pct   = (entry - lo) / span * 100
    current_pct = (current - lo) / span * 100
    target_pct  = (target - lo) / span * 100
    gained = (current_pct > entry_pct) if direction == 'BUY' else (current_pct < entry_pct)
    fill_color = up_color if gained else down_color
    fill_left  = min(entry_pct, current_pct)
    fill_width = abs(current_pct - entry_pct)

    return html.Div(style={
        'position': 'relative', 'height': '6px', 'background': 'var(--surface-input)',
        'borderRadius': '3px', 'minWidth': '90px',
    }, children=[
        html.Div(style={
            'position': 'absolute', 'top': '0', 'bottom': '0',
            'left': f'{fill_left:.1f}%', 'width': f'{fill_width:.1f}%',
            'background': fill_color, 'borderRadius': '3px',
        }),
        html.Div(style={
            'position': 'absolute', 'top': '-2px', 'bottom': '-2px', 'left': f'{current_pct:.1f}%',
            'width': '3px', 'background': current_color, 'borderRadius': '1px',
            'transform': 'translateX(-50%)',
        }),
        html.Div(style={
            'position': 'absolute', 'top': '-1px', 'bottom': '-1px', 'left': f'{target_pct:.1f}%',
            'width': '2px', 'background': target_color, 'borderRadius': '1px',
            'transform': 'translateX(-50%)',
        }),
    ])


def _dir_badge(direction: str) -> html.Span:
    """BUY/SELL pill badge, matching guide/SummaryBooks.jsx Dir column."""
    is_buy = str(direction).strip().upper() == 'BUY'
    return html.Span(direction, style={
        'padding': '2px 6px', 'borderRadius': '3px', 'fontSize': '9px', 'fontWeight': '600',
        'background': 'rgba(52,211,153,0.15)' if is_buy else 'rgba(239,68,68,0.15)',
        'color': '#34d399' if is_buy else '#f87171',
    })


_STYLE_REGIME_LABEL = {
    'meanreversion': 'mean-reverting', 'mean_reverting': 'mean-reverting', 'mean-reverting': 'mean-reverting',
    'trend': 'momentum', 'trendfollowing': 'momentum', 'carry': 'momentum', 'mixed': 'momentum', 'momentum': 'momentum',
}

# Same pill shape as _dir_badge, generalised to colour by arbitrary content.
_BADGE_PALETTE = {
    'mean-reverting': ('rgba(52,211,153,0.15)', '#34d399'),
    'momentum':       ('rgba(224,162,60,0.15)', '#e0a23c'),
}
_BADGE_DEFAULT = ('rgba(148,163,184,0.15)', '#94a3b8')


def _style_badge(style: str) -> html.Span:
    """Style pill badge, same shape as _dir_badge, coloured by regime label.

    Raw values (e.g. 'MeanReversion', 'TrendFollowing', 'Carry', 'Mixed') are
    normalised to display labels ('mean-reverting' / 'momentum') the same way
    web/tabs/alpha/callbacks/candidates.py:_style_to_regime_label does, so the
    badge text and colour stay consistent with the rest of the Alpha Book UI.
    """
    raw = str(style).strip()
    label = _STYLE_REGIME_LABEL.get(raw.lower(), raw)
    bg, fg = _BADGE_PALETTE.get(label, _BADGE_DEFAULT)
    return html.Span(label, style={
        'padding': '2px 6px', 'borderRadius': '3px', 'fontSize': '9px', 'fontWeight': '600',
        'background': bg, 'color': fg,
    })


def _signed_value_style(value: float | None) -> dict:
    """Green/red text colour for a signed PnL-like value, per guide convention."""
    if value is None:
        return {}
    return {'color': '#34d399' if value >= 0 else '#f87171', 'fontWeight': '600'}


def _zscore_cell_style(zscore: float | None, max_abs: float = 2.0) -> dict:
    """Z-score cell background tint + text colour, matching guide's zscore column:
    positive = green tint scaling with magnitude, negative = red tint (stronger)."""
    if zscore is None:
        return {}
    mag = min(abs(zscore) / max_abs, 1.0)
    if zscore > 0:
        return {'background': f'rgba(52,211,153,{mag * 0.28:.3f})', 'color': '#34d399', 'fontWeight': '600'}
    return {'background': f'rgba(239,68,68,{mag * 0.38:.3f})', 'color': '#f87171', 'fontWeight': '600'}


def _sortable_header(label: str, col_id: str, header_id_prefix: str, sort_state: dict,
                      align: str = 'right') -> html.Th:
    """Clickable column header for a custom html.Table, with a sort-direction arrow.

    `sort_state` is {'col': <id or None>, 'dir': 'asc'|'desc'}. Clicking fires
    Input({'type': f'{header_id_prefix}-sort-th', 'col': col_id}, 'n_clicks').
    """
    active = sort_state.get('col') == col_id
    arrow = ('▲' if sort_state.get('dir') == 'asc' else '▼') if active else ''
    return html.Th(
        html.Button(
            [label, html.Span(arrow, style={'marginLeft': '4px', 'fontSize': '8px'})],
            id={'type': f'{header_id_prefix}-sort-th', 'col': col_id},
            n_clicks=0,
            style={
                'background': 'none', 'border': 'none', 'cursor': 'pointer', 'padding': '0',
                'font': 'var(--type-label)', 'fontSize': '9px',
                'color': 'var(--accent-cyan)' if active else 'var(--text-muted)',
                'letterSpacing': '0.05em', 'whiteSpace': 'nowrap',
            },
        ),
        style={'padding': '7px 10px', 'textAlign': align},
    )


def _apply_sort(rows: list[dict], sort_state: dict, numeric_cols: set[str]) -> list[dict]:
    """Sort `rows` by sort_state={'col','dir'}. Callers pre-filter out any TOTAL row."""
    col = sort_state.get('col')
    if not col:
        return rows
    reverse = sort_state.get('dir') == 'desc'

    def _key(r):
        raw = str(r.get(col, '') or '').replace('%', '').replace(',', '').strip()
        if col in numeric_cols:
            try:
                return (0, float(raw)) if raw else (1, 0.0)
            except (TypeError, ValueError):
                return (1, 0.0)
        return (0, raw.lower())

    return sorted(rows, key=_key, reverse=reverse)


def _get_beta_close_prices() -> dict[str, float]:
    """Return {asset_name_prefix: last_factor_level} for Beta-Book close prices.

    Uses the most-recent row of the risk-factor level time series as a proxy.
    IR / Spread factors are reported in %; FX / Commodity not yet supported.
    """
    try:
        loader = RiskFactorLoader(DIR_INPUT)
        factor_levels = loader.load_risk_factors(use_cache=True)
        if factor_levels is None or factor_levels.empty:
            return {}
        last_row = factor_levels.iloc[-1]
        return {
            prefix: round(float(last_row[factor]), 4)
            for prefix, factor in _ASSET_PREFIX_TO_FACTOR.items()
            if factor in last_row.index and pd.notna(last_row[factor])
        }
    except Exception:
        return {}
