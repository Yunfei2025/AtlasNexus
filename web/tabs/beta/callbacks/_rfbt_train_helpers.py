# -*- coding: utf-8 -*-
"""Helper functions for the RFBT train/predict callback.

These were extracted from the inner scope of
``train_factor_model_for_factor_tab`` in ``backtest_rfbt.py`` so the
containing function stays concise.  All closures have been converted to
explicit parameters.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc

from settings.paths import DIR_INPUT
from ..data import THEME


# ──────────────────────────────────────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────────────────────────────────────

def _config_matches(saved_cfg, current_cfg) -> bool:
    """Return True if *saved_cfg* covers the same user-exposed settings as *current_cfg*.

    Only compares the three parameters that appear in the UI (train_months,
    ic_threshold, top_n).  Internal params like signal_smooth_days are not
    surfaced in the UI and are not passed during training, so comparing them
    would produce false mismatches.
    """
    if not saved_cfg:
        return False
    try:
        return (
            int(saved_cfg.get('train_months', -1)) == int(current_cfg['train_months']) and
            float(saved_cfg.get('ic_threshold', -1)) == float(current_cfg['ic_threshold']) and
            int(saved_cfg.get('top_n', -1)) == int(current_cfg['top_n'])
        )
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# IC statistics
# ──────────────────────────────────────────────────────────────────────────────

def _compute_factor_stats(results: Dict) -> Dict:
    """Compute per-factor IC / signal statistics from backtest *results*."""
    factor_stats = {}
    for factor, df in results.items():
        pred = df['predicted_return'].dropna()
        sig = df['signal'].dropna()
        last_signal = float(sig.iloc[-1]) if not sig.empty else 0.0
        last_pred_val = float(pred.iloc[-1]) if not pred.empty else 0.0
        pred_hist = pred.tail(252)
        z_score = ((last_pred_val - pred_hist.mean()) / (pred_hist.std() + 1e-8)
                   if len(pred_hist) > 5 else 0.0)
        scalar = max(0.5, min(2.0, abs(z_score)))
        actual_fwd = df['returns'].shift(-1).reindex(df.index)
        ic_rolling = df['predicted_return'].rolling(60).corr(actual_fwd).dropna()
        mean_ic = float(ic_rolling.mean()) if len(ic_rolling) > 0 else 0.0
        ic_std = float(ic_rolling.std()) if len(ic_rolling) > 1 else 1.0
        icir = mean_ic / (ic_std + 1e-8)
        ic_hit = float((ic_rolling > 0).mean()) if len(ic_rolling) > 0 else 0.0
        n_ic = len(ic_rolling)
        ic_tstat = mean_ic / (ic_std / (n_ic ** 0.5) + 1e-8) if n_ic > 1 else 0.0
        factor_stats[factor] = {
            'last_signal': last_signal,
            'z_score': z_score,
            'scalar': scalar,
            'mean_ic': mean_ic,
            'icir': icir,
            'ic_hit': ic_hit,
            'ic_tstat': ic_tstat,
            'ic_rolling': ic_rolling,
        }
    return factor_stats


# ──────────────────────────────────────────────────────────────────────────────
# Signal cards
# ──────────────────────────────────────────────────────────────────────────────

def _render_signal_cards(factor_stats: Dict, artifact=None) -> html.Div:
    """Render a grid of signal-state cards for *factor_stats*.

    Each card embeds its own Top-Drivers chart inside a native
    ``<details>``/``<summary>`` element so it expands in place on click
    (matches the guide's BetaCandidates.jsx interaction) without needing a
    server round-trip or clientside callback.
    """
    _IR_PREFIXES = ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL', 'SPCV')
    _POS = '#34d399'
    _NEG = '#f87171'
    _NEUTRAL = 'var(--text-muted)'

    def _sc(factor, stats):
        ls = stats['last_signal']            # quantised target in [-1,1]; sign = direction
        strong = ls >= 0.8 or ls <= -0.8
        arrow_prefix = '↑↑' if ls >= 0.8 else ('↓↓' if ls <= -0.8 else '')
        prefix = factor.split('.')[0]
        is_yield = prefix in _IR_PREFIXES
        is_slope = prefix == 'IRSL'
        is_curv = prefix == 'IRCV'
        if ls > 0:
            if is_slope:
                arrow, dir_label = '↑', 'Steepener'
            elif is_curv:
                arrow, dir_label = '↑', 'Concave'
            elif is_yield:
                arrow, dir_label = '↑', 'Bullish'
            else:
                arrow, dir_label = '↑', 'Long'
            dir_color = _POS
        elif ls < 0:
            if is_slope:
                arrow, dir_label = '↓', 'Flattener'
            elif is_curv:
                arrow, dir_label = '↓', 'Convex'
            elif is_yield:
                arrow, dir_label = '↓', 'Bearish'
            else:
                arrow, dir_label = '↓', 'Short'
            dir_color = _NEG
        else:
            arrow, dir_label, dir_color = '‖', 'Neutral', _NEUTRAL

        icir_val = stats['icir']
        if abs(icir_val) >= 0.50:
            conf, conf_color = 'HIGH', _POS
        elif abs(icir_val) >= 0.25:
            conf, conf_color = 'MEDIUM', 'var(--accent-amber)'
        else:
            conf, conf_color = 'LOW', _NEG

        driver_chart = _build_single_driver_chart(factor, (artifact or {}).get(factor))

        card_body = html.Div([
            html.Div([
                html.Span(factor, style={'fontSize': '9px', 'color': 'var(--text-muted)',
                                          'textTransform': 'uppercase', 'letterSpacing': '0.04em'}),
            ], style={'display': 'flex', 'justifyContent': 'space-between',
                       'alignItems': 'center', 'marginBottom': '4px'}),
            html.Div(
                f"{(arrow_prefix + ' ') if strong else ''}{arrow} {dir_label}",
                style={'fontSize': '13px', 'fontWeight': '700', 'color': dir_color,
                       'marginBottom': '6px'},
            ),
            html.Div([
                html.Div([
                    html.Span('Signal Z', style={'color': 'var(--text-muted)'}),
                    html.Span(f"{stats['z_score']:+.2f}", style={'color': 'var(--text-secondary)'}),
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'fontSize': '9px'}),
                html.Div([
                    html.Span('Scale', style={'color': 'var(--text-muted)'}),
                    html.Span(f"{stats['scalar']:.1f}×", style={'color': 'var(--text-secondary)'}),
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'fontSize': '9px'}),
                html.Div([
                    html.Span('ICIR', style={'color': 'var(--text-muted)'}),
                    html.Span(f'{icir_val:.2f}', style={'color': 'var(--text-secondary)'}),
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'fontSize': '9px'}),
                html.Div([
                    html.Span('Conf', style={'color': 'var(--text-muted)'}),
                    html.Span(conf, style={'color': conf_color, 'fontWeight': '700'}),
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'fontSize': '9px',
                          'marginTop': '2px'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '2px'}),
        ], style={'padding': '10px 12px'})

        if driver_chart is None:
            return html.Div(card_body, style={
                'border': f'2px solid {dir_color}',
                'borderRadius': '6px',
                'background': 'var(--surface-input)',
                'minWidth': '130px',
                'flex': '1',
            })

        return html.Details([
            html.Summary(card_body, style={
                'listStyle': 'none', 'cursor': 'pointer', 'display': 'block',
            }),
            html.Div(driver_chart, style={
                'borderTop': '1px solid var(--border-strong)',
                'padding': '8px 12px 10px', 'background': 'var(--surface-panel)',
            }),
        ], style={
            'border': f'2px solid {dir_color}',
            'borderRadius': '6px',
            'background': 'var(--surface-input)',
            'minWidth': '130px',
            'flex': '1',
            'overflow': 'hidden',
        })

    return html.Div(
        [_sc(f, s) for f, s in factor_stats.items()],
        style={'display': 'grid', 'gridTemplateColumns': 'repeat(3, 1fr)',
               'gap': '8px', 'marginBottom': '12px', 'alignItems': 'start'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Artifact → results
# ──────────────────────────────────────────────────────────────────────────────

def _build_results_from_saved_artifact(
    artifact,
    smooth_days: int,
    factors: List[str],
    factor_subset: Optional[List[str]] = None,
    sizing_mode: str = 'discrete',
    position_smooth_window: int = 10,
) -> Dict:
    """Build results DataFrames from a saved *artifact*.

    Parameters
    ----------
    artifact:
        Loaded model artifact dict (factor → model dict).
    smooth_days:
        Signal smoothing days (from saved config).
    factors:
        Full list of currently selected factors.
    factor_subset:
        Restrict prediction to this subset of factors.
        ``None`` → use the full *factors* list.
    sizing_mode, position_smooth_window:
        Position sizing applied fresh from the saved predictions (not baked
        into the .joblib), so the discrete 5-level mapping needs no retrain.
    """
    from multiasset.factor_backtest import load_factor_rates
    from multiasset.factor_model import (
        build_features, _compute_target_returns, _predict_ic_model,
        build_position_series, factor_tx_cost_per_unit, FactorModelConfig,
    )

    size_cfg = FactorModelConfig(
        signal_smooth_days=smooth_days,
        sizing_mode=sizing_mode,
        position_smooth_window=position_smooth_window,
    )

    try:
        factor_levels = load_factor_rates(DIR_INPUT)
    except Exception:
        return {}

    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    _factor_iter = factor_subset if factor_subset is not None else factors
    results = {}
    for factor in _factor_iter:
        fa = artifact.get(factor)
        if not fa:
            continue
        trained_model = fa.get('trained_model')
        if not trained_model:
            continue
        try:
            needed_features = list(fa.get('selected_factors') or trained_model.get('feature_names') or [])
            features = build_features(
                factor, factor_levels, DIR_INPUT,
                feature_subset=needed_features or None,
            )
            features = features.ffill().fillna(0)
            preds = _predict_ic_model(features, trained_model)
            if preds.empty:
                continue
            daily_returns = _compute_target_returns(factor, factor_levels)
            result = pd.DataFrame(index=preds.index)
            result['predicted_return'] = preds
            result['n_features'] = len(fa.get('selected_factors', []) or trained_model.get('feature_names', []))
            result['returns'] = daily_returns.reindex(result.index)

            _long_only = factor.split('.')[0] == 'IRDL'
            pos = build_position_series(
                result['predicted_return'], result['returns'], size_cfg,
                long_only=_long_only,
            )
            result['signal'] = pos['signal']
            result['position'] = pos['position']
            result['turnover'] = pos['turnover']

            result['strategy_returns_gross'] = result['position'].shift(1) * result['returns']
            tx_cost = result['turnover'].abs() * factor_tx_cost_per_unit(factor, size_cfg)
            result['strategy_returns'] = result['strategy_returns_gross'] - tx_cost
            result['cumulative_returns'] = (1 + result['strategy_returns'].fillna(0)).cumprod()
            results[factor] = result
        except Exception as e:
            print(f"Warning: prediction failed for {factor}: {e}")
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Top-drivers chart (per-factor, embedded inline inside each signal card)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_driver_feature(fn: str):
    """Classify a feature name into (category label, short code) for display."""
    if '_vs_' in fn:
        return 'Cross-Market', 'XMK'
    if fn.startswith('MACRO_'):
        return 'Macro', 'MACRO'
    for kw in ('_Slope', '_Curv', '_Carry_', '_SlopeMom', '_SlopeZ', '_CurvZ'):
        if kw in fn:
            return 'Carry / Curve', 'CARRY'
    for kw in ('_Vol', '_VolRatio'):
        if kw in fn:
            return 'Volatility', 'VOL'
    for kw in ('_ZScore', '_PctRank', '_ValueMom'):
        if kw in fn:
            return 'Value / Mean-Rev', 'VAL'
    for kw in ('_Mom', '_EMACross'):
        if kw in fn:
            return 'Momentum', 'MOM'
    return 'Other', '?'


def _shorten_driver_feature(fn: str, risk_factor: str) -> str:
    prefix = risk_factor + '_'
    if fn.startswith(prefix):
        fn = fn[len(prefix):]
    return fn[:32]


_DRIVER_LEGEND = html.Div([
    html.Div([
        html.Span("■ Green bar  ", style={'color': '#34d399', 'fontWeight': 'bold'}),
        html.Span("Positive IC — feature rises → factor return ↑  (pro-factor / trend-following)"),
        html.Span("     ■ Red bar  ", style={'color': '#f87171', 'fontWeight': 'bold'}),
        html.Span("Negative IC — feature rises → factor return ↓  (contra-factor / mean-reversion)"),
    ], style={'marginBottom': '5px'}),
    html.Div(
        "Feature categories:  MOM = Momentum  ·  VAL = Value / Mean-Rev  ·  "
        "CARRY = Carry / Curve  ·  XMK = Cross-Market  ·  MACRO = Macro  ·  VOL = Volatility",
    ),
], style={
    'fontSize': '9px', 'color': 'var(--text-muted)', 'lineHeight': '1.5',
})


def _build_single_driver_chart(risk_factor: str, fa) -> Optional[html.Div]:
    """Return a compact Plotly bar chart (+ legend) of ALL drivers for one
    risk factor, for embedding inside that factor's signal card.  Bar length
    = IC-weighted contribution share (sums to 100%). Returns ``None`` if no
    trained-model data is available for *risk_factor*.
    """
    if not fa:
        return None
    tm = fa.get('trained_model', {})
    feats = tm.get('feature_names', [])
    coefs = tm.get('coefficients', [])
    if isinstance(coefs, pd.Series):
        coefs = coefs.tolist()
    if not feats or not coefs or len(feats) != len(coefs):
        return None

    total_abs = sum(abs(c) for c in coefs) or 1.0
    ranked = sorted(zip(feats, coefs), key=lambda x: abs(x[1]), reverse=True)
    feats_all = [x[0] for x in ranked]
    coefs_all = [x[1] for x in ranked]
    contribs = [abs(c) / total_abs * 100 for c in coefs_all]
    cats = [_classify_driver_feature(f) for f in feats_all]

    bar_colors = ['#34d399' if c > 0 else '#f87171' for c in coefs_all]
    hover_texts = [
        (f"<b>{f}</b><br>"
         f"IC (Spearman): {c:+.4f}<br>"
         f"Contribution: {p:.1f}% of total |IC|<br>"
         f"Feature type: {cat[0]}<br>"
         f"{'↑ Pro-factor — feature moves with target' if c > 0 else '↓ Contra-factor — feature moves against target'}")
        for f, c, p, cat in zip(feats_all, coefs_all, contribs, cats)
    ]
    y_labels = [f"{_shorten_driver_feature(f, risk_factor)} [{cats[i][1]}]" for i, f in enumerate(feats_all)]

    n_bars = len(feats_all)
    fig_h = max(120, n_bars * 24 + 40)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=contribs[::-1],
        y=y_labels[::-1],
        orientation='h',
        marker_color=bar_colors[::-1],
        marker_line_width=0,
        text=[f"IC {c:+.3f}" for c in coefs_all[::-1]],
        textposition='outside',
        textfont={'size': 9, 'color': THEME['text_sub']},
        hovertext=hover_texts[::-1],
        hoverinfo='text',
        cliponaxis=False,
    ))
    fig.update_layout(
        title=dict(text='Top Drivers', font={'color': 'var(--accent-blue)', 'size': 11},
                    x=0.01, y=0.98, xanchor='left', yanchor='top'),
        height=fig_h,
        template=THEME['chart_template'],
        paper_bgcolor='#122a4c',
        plot_bgcolor='#122a4c',
        font={'color': '#e9eef8', 'size': 9},
        margin=dict(l=8, r=60, t=24, b=20),
        xaxis=dict(range=[0, 115], gridcolor='#0e1d3a', ticksuffix='%',
                    title=dict(text='Contribution (%)', font={'size': 8})),
        yaxis=dict(gridcolor='rgba(0,0,0,0)', automargin=True, tickfont={'size': 8}),
        showlegend=False,
    )

    return html.Div([
        dcc.Graph(figure=fig, config={'displayModeBar': False}, style={'height': f'{fig_h}px'}),
        _DRIVER_LEGEND,
    ])
