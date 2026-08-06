# -*- coding: utf-8 -*-
"""Shared helpers for Alpha candidate callbacks."""

from __future__ import annotations

import json as _json
from datetime import datetime

import numpy as np
import pandas as pd

from dash import html
import plotly.graph_objects as go

from ..data import (
    THEME,
    SPREAD_CATEGORIES,
    ZSCORE_ENTRY_THRESHOLD,
    _get_input_dir,
    _load_pickle_safe,
    load_spread_data,
    load_spread_timeseries,
    display_key,
    _get_borrow_cost_annual_bp,
    _get_ttm_display,
    _get_current_fr007_bp,
)
from ..scoring import (
    compute_spread_correlation,
    rank_low_correlation_pairs,
    select_diverse_instruments,
    compute_scan_score,
)


_ALPHA_BOOK_POSITIONS_PARQUET = _get_input_dir() / 'alpha_book_positions.parquet'
_REGIME_LOOKUP_CACHE: dict[str, dict[str, str]] = {}

# Custom colorscale matching guide/AlphaCandidates.jsx corrCell():
# navy-blue (rgb(30,80,160)) for positive, brick-red (rgb(200,60,40))
# for negative, fading to a near-transparent center at 0.
_ALPHA_CORR_COLORSCALE = [
    [0.0, 'rgb(200,60,40)'],
    [0.5, 'rgb(20,35,60)'],
    [1.0, 'rgb(30,80,160)'],
]
_REGIME_CACHE_MTIME: float = 0.0  # mtime of Alpha-spreadsrt.pkl when cache was last built


def _load_seasonal_screener() -> dict | None:
    """Load the precomputed monthly seasonal statistics, when available."""
    try:
        import pickle as _pkl

        path = _get_input_dir() / 'seasonal-spds.pkl'
        if path.exists():
            with open(path, 'rb') as file:
                data = _pkl.load(file)
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


def _apply_seasonal_quality_gate(
    candidates: pd.DataFrame,
    seasonal_data: dict | None,
    *,
    min_consistency: float,
    p_value_threshold: float,
    month: int | None = None,
) -> tuple[pd.DataFrame, int, int]:
    """Keep candidates with reliable current-month seasonality."""
    if not isinstance(seasonal_data, dict):
        return candidates, 0, 0
    if not {'spread_type', 'ID'}.issubset(candidates.columns):
        return candidates, 0, 0

    month_key = f'm{month or datetime.now().month}'
    keep_mask = pd.Series(True, index=candidates.index)
    excluded = 0
    evaluated = 0

    def _is_mean_reverting_row(row: pd.Series) -> bool:
        style = str(row.get('style', '') or '').strip().lower()
        regime = str(row.get('regime', '') or '').strip().lower()
        return (
            style in {'meanreversion', 'mean_reverting', 'mean-reverting'}
            or regime in {'meanreversion', 'mean_reverting', 'mean-reverting'}
        )

    for index, row in candidates.iterrows():
        if _is_mean_reverting_row(row):
            continue

        seasonal_frame = seasonal_data.get(str(row['spread_type']))
        instrument = str(row['ID'])
        if (
            not isinstance(seasonal_frame, pd.DataFrame)
            or instrument not in seasonal_frame.index
            or month_key not in seasonal_frame.columns
        ):
            continue

        cell = seasonal_frame.at[instrument, month_key]
        if not isinstance(cell, dict):
            continue
        try:
            p_value = float(cell.get('p_value', 1.0))
            consistency = float(cell.get('consistency', 0.0))
        except (TypeError, ValueError):
            continue

        evaluated += 1
        if p_value >= p_value_threshold or consistency < min_consistency:
            keep_mask.at[index] = False
            excluded += 1

    return candidates.loc[keep_mask].copy(), excluded, evaluated


def _invalidate_regime_cache_if_stale() -> None:
    """Clear _REGIME_LOOKUP_CACHE if the snapshot pickle has been updated since last build."""
    global _REGIME_CACHE_MTIME
    snap_path = _get_input_dir() / 'Alpha-spreadsrt.pkl'
    try:
        current_mtime = snap_path.stat().st_mtime
    except FileNotFoundError:
        return
    if current_mtime != _REGIME_CACHE_MTIME:
        _REGIME_LOOKUP_CACHE.clear()
        _REGIME_CACHE_MTIME = current_mtime


def _style_to_regime(style: object) -> str:
    style_value = str(style or '').strip().lower()
    if style_value in {'meanreversion', 'mean_reverting', 'mean-reverting'}:
        return 'mean-reverting'
    if style_value in {'trend', 'trendfollowing', 'trend_following', 'trending', 'carry', 'mixed', 'momentum', 'eventdriven'}:
        return 'momentum'
    return 'uncertain'


def _get_upstream_regime(spread_type: str, instrument: str) -> str:
    spread_type = str(spread_type or '').strip()
    instrument = str(instrument or '').strip()
    if not spread_type or not instrument:
        return 'uncertain'

    _invalidate_regime_cache_if_stale()
    cache = _REGIME_LOOKUP_CACHE.get(spread_type)
    if cache is None:
        cache = {}
        try:
            snap = load_spread_data(spread_type)
            if isinstance(snap, pd.DataFrame) and not snap.empty and 'style' in snap.columns:
                style_series = snap['style'].astype(str).str.strip().str.lower()
                for idx, style in style_series.items():
                    cache[str(idx)] = _style_to_regime(style)
        except Exception:
            cache = {}
        _REGIME_LOOKUP_CACHE[spread_type] = cache

    return cache.get(instrument, 'uncertain')


def _normalize_curated_entry(entry: dict, *, infer_regime: bool = True) -> dict:
    instrument = str(entry.get('instrument') or entry.get('ID') or '').strip()
    spread_type = str(entry.get('spread_type') or entry.get('type') or '').strip()

    if '|' in instrument:
        maybe_stype, maybe_inst = instrument.split('|', 1)
        _known_spread_types = {
            t for info in SPREAD_CATEGORIES.values() for t in info.get('types', [])
        }
        if maybe_stype in _known_spread_types and maybe_inst:
            if not spread_type or spread_type == 'Unknown':
                spread_type = maybe_stype
            instrument = maybe_inst

    _raw = str(entry.get('regime') or entry.get('style') or '').strip()
    regime = _style_to_regime(_raw) if _raw else 'uncertain'
    direction = str(entry.get('direction') or '').strip().upper()

    if infer_regime and regime == 'uncertain':
        regime = _get_upstream_regime(spread_type, instrument)

    normalized = dict(entry)
    normalized['instrument'] = instrument
    normalized['spread_type'] = spread_type
    normalized['regime'] = regime
    normalized['direction'] = direction if direction in {'BUY', 'SELL'} else ''
    normalized['manual'] = bool(entry.get('manual', False))
    return normalized


def _load_alpha_book_positions() -> list[dict]:
    if not _ALPHA_BOOK_POSITIONS_PARQUET.exists():
        return []
    try:
        df = pd.read_parquet(_ALPHA_BOOK_POSITIONS_PARQUET)
    except Exception:
        return []

    if not isinstance(df, pd.DataFrame) or df.empty:
        return []

    if 'ID' in df.columns and 'spread_type' in df.columns:
        _FUTURES_CODES = ('T', 'TL', 'TF', 'TS')
        _raw_id_map = {f'{c}-CTD': c for c in _FUTURES_CODES}
        _raw_id_map.update({f'{c}-Cal': c for c in _FUTURES_CODES})
        _raw_id_map.update({f'{c}-FtSwp': c for c in _FUTURES_CODES})
        _raw_id_map['TL-Cal'] = 'TL'
        df['ID'] = df['ID'].map(lambda v: _raw_id_map.get(str(v), v))

    _id_cols = [c for c in ('spread_type', 'ID') if c in df.columns]
    if _id_cols:
        df = df.drop_duplicates(subset=_id_cols, keep='first')

    _snap_cache: dict = {}

    _summary_alpha_z: dict[tuple[str, str], float] = {}
    try:
        _summary_alpha_path = _get_input_dir() / 'summary_alpha_portfolio.parquet'
        if _summary_alpha_path.exists():
            _sdf = pd.read_parquet(_summary_alpha_path)
            if isinstance(_sdf, pd.DataFrame) and not _sdf.empty:
                if 'spread_type' in _sdf.columns and 'ID' in _sdf.columns and 'Zscore' in _sdf.columns:
                    _tmp = _sdf[['spread_type', 'ID', 'Zscore']].copy()
                    _tmp['Zscore'] = pd.to_numeric(_tmp['Zscore'], errors='coerce')
                    _tmp = _tmp.dropna(subset=['Zscore'])
                    _tmp = _tmp.drop_duplicates(subset=['spread_type', 'ID'], keep='first')
                    for _, _r in _tmp.iterrows():
                        _summary_alpha_z[(str(_r['spread_type']), str(_r['ID']))] = float(_r['Zscore'])
    except Exception:
        pass
    rows: list[dict] = []
    for _, row in df.iterrows():
        entry = row.to_dict()
        entry.setdefault('instrument', entry.get('ID', ''))
        entry.setdefault('spread_type', entry.get('spread_type', ''))
        entry.setdefault('manual', False)

        inst = str(entry.get('instrument', '') or '').strip()
        stype = str(entry.get('spread_type', '') or '').strip()

        raw_regime = str(entry.get('style', '') or entry.get('regime', '') or '').strip()
        if not raw_regime or raw_regime == 'uncertain':
            if stype not in _snap_cache:
                try:
                    _snap_cache[stype] = load_spread_data(stype)
                except Exception:
                    _snap_cache[stype] = None
            snap = _snap_cache[stype]
            if snap is not None and inst in snap.index and 'style' in snap.columns:
                raw_regime = str(snap.loc[inst, 'style'] or '').strip()
        entry['regime'] = raw_regime or 'uncertain'

        raw_dir = str(entry.get('direction', '') or '').strip().upper()
        if raw_dir not in {'BUY', 'SELL'}:
            if stype not in _snap_cache:
                try:
                    _snap_cache[stype] = load_spread_data(stype)
                except Exception:
                    _snap_cache[stype] = None
            snap = _snap_cache[stype]
            if snap is not None and inst in snap.index and 'direction' in snap.columns:
                raw_dir = str(snap.loc[inst, 'direction'] or '').strip().upper()
        entry['direction'] = raw_dir if raw_dir in {'BUY', 'SELL'} else ''

        zscore_val = pd.to_numeric(entry.get('Zscore', entry.get('zscore', None)), errors='coerce')
        if pd.isna(zscore_val):
            if stype not in _snap_cache:
                try:
                    _snap_cache[stype] = load_spread_data(stype)
                except Exception:
                    _snap_cache[stype] = None
            snap = _snap_cache[stype]
            if snap is not None and inst in snap.index and 'Zscore' in snap.columns:
                zscore_val = pd.to_numeric(snap.loc[inst, 'Zscore'], errors='coerce')

        if pd.isna(zscore_val):
            zscore_val = _summary_alpha_z.get((stype, inst), np.nan)

        if pd.notna(zscore_val):
            entry['Zscore'] = round(float(zscore_val), 4)

        entry = _normalize_curated_entry(entry, infer_regime=True)
        if entry['instrument'] and entry['spread_type']:
            rows.append(entry)
    return rows


def _merge_curated_entries(*groups: list[dict] | None) -> list[dict]:
    merged: list[dict] = []
    index: dict[tuple[str, str], int] = {}

    for group in groups:
        if not group:
            continue
        for raw_entry in group:
            if not isinstance(raw_entry, dict):
                continue
            entry = _normalize_curated_entry(raw_entry, infer_regime=True)
            key = (entry['spread_type'], entry['instrument'])
            if not key[0] or not key[1]:
                continue

            existing_idx = index.get(key)
            if existing_idx is None:
                index[key] = len(merged)
                merged.append(entry)
                continue

            existing = merged[existing_idx]
            for field, value in entry.items():
                if field == 'manual':
                    existing[field] = bool(existing.get(field, False)) or bool(value)
                elif field == 'regime':
                    existing_value = str(existing.get(field, '') or '').strip()
                    new_value = str(value or '').strip()
                    if existing_value in {'', 'uncertain'} and new_value:
                        existing[field] = new_value
                elif field == 'direction':
                    existing_value = str(existing.get(field, '') or '').strip()
                    new_value = str(value or '').strip()
                    if existing_value and not new_value:
                        continue
                    if new_value:
                        existing[field] = new_value
                elif value not in (None, '', [], {}):
                    existing[field] = value

    return merged


def _normalize_corr_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Convert legacy 'spread_type|instrument' labels to display_key labels."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df

    def _norm(label: object) -> str:
        text = str(label)
        if '|' not in text:
            return text
        stype, inst = text.split('|', 1)
        return display_key(stype, inst)

    rows = [_norm(i) for i in df.index]
    cols = [_norm(c) for c in df.columns]
    out = df.copy()
    out.index = rows
    out.columns = cols
    if out.index.duplicated().any() or out.columns.duplicated().any():
        out = out.groupby(level=0).mean()
        out = out.T.groupby(level=0).mean().T
    return out


def _build_heatmap(values, *, title: str, height: int | None = None):
    fig = go.Figure(data=go.Heatmap(
        z=values, colorscale=_ALPHA_CORR_COLORSCALE, zmin=-1, zmax=1,
        hovertemplate='%{y} vs %{x}<br>Corr: %{z:.3f}<extra></extra>',
    ))
    if height is None:
        height = 350
    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=100, r=20, t=40, b=80),
        plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main'], size=10),
        xaxis=dict(tickangle=45),
    )
    return fig
