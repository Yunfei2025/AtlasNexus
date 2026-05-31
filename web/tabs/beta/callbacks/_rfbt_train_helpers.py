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
    """Return True if *saved_cfg* covers the same settings as *current_cfg*."""
    if not saved_cfg:
        return False
    try:
        return (
            int(saved_cfg.get('train_months', -1)) == int(current_cfg['train_months']) and
            float(saved_cfg.get('ic_threshold', -1)) == float(current_cfg['ic_threshold']) and
            int(saved_cfg.get('top_n', -1)) == int(current_cfg['top_n']) and
            int(saved_cfg.get('signal_smooth_days', current_cfg['signal_smooth_days'])) == int(current_cfg['signal_smooth_days'])
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
        last_signal = int(sig.iloc[-1]) if not sig.empty else 0
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

def _render_signal_cards(factor_stats: Dict) -> html.Div:
    """Render a row of signal-state cards for *factor_stats*."""
    _IR_PREFIXES = ('IRDL', 'IRSL', 'IRCV', 'SPDL', 'SPSL', 'SPCV')

    def _sc(factor, stats):
        ls = stats['last_signal']
        prefix = factor.split('.')[0]
        is_yield = prefix in _IR_PREFIXES
        is_slope = prefix == 'IRSL'
        is_curv = prefix == 'IRCV'
        if ls == 1:
            if is_slope:
                dir_label, sub_label = '⬆ Flattener', 'curve expected to flatten'
            elif is_curv:
                dir_label, sub_label = '⬆ Concave', 'curvature expected ↓'
            elif is_yield:
                dir_label, sub_label = '⬆ Bullish', 'rate expected ↓'
            else:
                dir_label, sub_label = '⬆ LONG', ''
            dir_color = THEME['success']
        elif ls == -1:
            if is_slope:
                dir_label, sub_label = '⬇ Steepener', 'curve expected to steepen'
            elif is_curv:
                dir_label, sub_label = '⬇ Convex', 'curvature expected ↑'
            elif is_yield:
                dir_label, sub_label = '⬇ Bearish', 'rate expected ↑'
            else:
                dir_label, sub_label = '⬇ SHORT', ''
            dir_color = THEME['danger']
        else:
            dir_label, sub_label, dir_color = '⏸ NEUTRAL', '', THEME['text_sub']
        icir_val = stats['icir']
        if abs(icir_val) >= 0.50:
            conf, conf_color = 'HIGH', THEME['success']
        elif abs(icir_val) >= 0.25:
            conf, conf_color = 'MEDIUM', THEME['warning']
        else:
            conf, conf_color = 'LOW', THEME['danger']
        return html.Div([
            html.Div(factor, style={'fontSize': '11px', 'color': THEME['text_sub'],
                                    'marginBottom': '4px'}),
            html.Div(dir_label, style={'fontSize': '15px', 'fontWeight': 'bold',
                                       'color': dir_color, 'marginBottom': '2px'}),
            *([html.Div(sub_label, style={'fontSize': '10px', 'color': dir_color,
                                          'marginBottom': '4px', 'fontStyle': 'italic'})]
              if sub_label else [html.Div(style={'marginBottom': '4px'})]),
            html.Div([
                html.Span('Signal Z ', style={'color': THEME['text_sub']}),
                html.Span(f"{stats['z_score']:+.2f}", style={'color': THEME['text_main']}),
            ], style={'fontSize': '12px'}),
            html.Div([
                html.Span('Scale ', style={'color': THEME['text_sub']}),
                html.Span(f"{stats['scalar']:.1f}×", style={'color': THEME['accent']}),
            ], style={'fontSize': '12px'}),
            html.Div([
                html.Span('ICIR ', style={'color': THEME['text_sub']}),
                html.Span(f'{icir_val:.2f}', style={'color': conf_color}),
            ], style={'fontSize': '12px'}),
            html.Div(f'Conf: {conf}',
                     style={'fontSize': '10px', 'color': conf_color,
                            'fontWeight': 'bold', 'marginTop': '4px'}),
        ], style={
            'backgroundColor': THEME['bg_card'],
            'border': f'2px solid {dir_color}',
            'borderRadius': '6px',
            'padding': '12px 14px',
            'minWidth': '115px',
            'textAlign': 'center',
        })

    return html.Div(
        [_sc(f, s) for f, s in factor_stats.items()],
        style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '12px',
               'marginBottom': '20px'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Artifact → results
# ──────────────────────────────────────────────────────────────────────────────

def _build_results_from_saved_artifact(
    artifact,
    smooth_days: int,
    factors: List[str],
    factor_subset: Optional[List[str]] = None,
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
    """
    from multiasset.factor_backtest import load_factor_rates
    from multiasset.factor_model import (
        build_features, _compute_target_returns, _predict_ic_model,
        build_position_series, factor_tx_cost_per_unit, FactorModelConfig,
    )

    size_cfg = FactorModelConfig(signal_smooth_days=smooth_days)

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
            features = build_features(factor, factor_levels, DIR_INPUT)
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
# Top-drivers chart
# ──────────────────────────────────────────────────────────────────────────────

def _build_top_drivers(artifact, factors: List[str]) -> html.Div:
    """Return a horizontal bar-chart panel showing ALL selected drivers per
    risk factor.  Bar length = IC-weighted contribution share (sums to 100 %).
    Green = positive IC (pro-factor); Red = negative IC (contra-factor).
    Feature category codes are shown in the y-axis labels.

    Parameters
    ----------
    artifact:
        Loaded model artifact dict.
    factors:
        Currently selected list of risk factors.
    """

    # ── feature classifier ─────────────────────────────────────────────────
    def _classify(fn: str):
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

    def _shorten(fn: str, risk_factor: str) -> str:
        prefix = risk_factor + '_'
        if fn.startswith(prefix):
            fn = fn[len(prefix):]
        return fn[:32]

    # ── collect per-factor data ────────────────────────────────────────────
    rows_data = []
    for risk_factor in factors:
        fa = (artifact or {}).get(risk_factor)
        if not fa:
            continue
        tm = fa.get('trained_model', {})
        feats = tm.get('feature_names', [])
        coefs = tm.get('coefficients', [])
        if isinstance(coefs, pd.Series):
            coefs = coefs.tolist()
        if not feats or not coefs or len(feats) != len(coefs):
            continue
        total_abs = sum(abs(c) for c in coefs) or 1.0
        ranked = sorted(zip(feats, coefs), key=lambda x: abs(x[1]), reverse=True)
        rows_data.append({
            'factor': risk_factor,
            'ranked': ranked,
            'total_abs': total_abs,
        })

    if not rows_data:
        if artifact:
            akeys = [k for k in artifact if k != 'metadata']
            msg = (f"⚠️ Artifact has keys {akeys} but none matched selected "
                   f"factors {factors}, or all coefficients were zero.")
        else:
            msg = "⚠️ No model artifact available. Click Train Model first."
        return html.Div(
            msg,
            style={'color': THEME['warning'], 'fontSize': '11px',
                   'fontStyle': 'italic', 'padding': '10px 14px',
                   'backgroundColor': THEME['bg_input'],
                   'border': f'1px dashed {THEME["table_header"]}',
                   'borderRadius': '6px', 'marginTop': '16px'},
        )

    # ── build one compact Plotly bar chart per risk factor ─────────────────
    charts = []
    for rd in rows_data:
        rf = rd['factor']
        ranked = rd['ranked']
        total_abs = rd['total_abs']

        feats_all = [x[0] for x in ranked]
        coefs_all = [x[1] for x in ranked]
        contribs = [abs(c) / total_abs * 100 for c in coefs_all]
        cats = [_classify(f) for f in feats_all]

        bar_colors = [
            THEME['success'] if c > 0 else THEME['danger']
            for c in coefs_all
        ]
        hover_texts = [
            (f"<b>{f}</b><br>"
             f"IC (Spearman): {c:+.4f}<br>"
             f"Contribution: {p:.1f}% of total |IC|<br>"
             f"Feature type: {cat[0]}<br>"
             f"{'↑ Pro-factor — feature moves with target' if c > 0 else '↓ Contra-factor — feature moves against target'}")
            for f, c, p, cat in zip(feats_all, coefs_all, contribs, cats)
        ]
        y_labels = [
            f"{_shorten(f, rf)} [{cats[i][1]}]"
            for i, f in enumerate(feats_all)
        ]

        n_bars = len(feats_all)
        fig_h = max(140, n_bars * 26 + 55)

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
            title=dict(
                text=rf,
                font={'color': THEME['accent'], 'size': 12},
                x=0.01, y=0.99, xanchor='left', yanchor='top',
            ),
            height=fig_h,
            template=THEME['chart_template'],
            paper_bgcolor=THEME['bg_card'],
            plot_bgcolor=THEME['bg_card'],
            font={'color': THEME['text_main'], 'size': 10},
            margin=dict(l=8, r=70, t=28, b=22),
            xaxis=dict(
                range=[0, 115],
                gridcolor=THEME['table_header'],
                ticksuffix='%',
                title=dict(text='Contribution (%)', font={'size': 9}),
            ),
            yaxis=dict(
                gridcolor='rgba(0,0,0,0)',
                automargin=True,
                tickfont={'size': 9},
            ),
            showlegend=False,
        )
        charts.append(
            html.Div(
                dcc.Graph(
                    figure=fig,
                    config={'displayModeBar': False},
                    style={'height': f'{fig_h}px'},
                ),
                style={'flex': '1', 'minWidth': '360px'},
            )
        )

    # ── legend ────────────────────────────────────────────────────────────
    legend = html.Div([
        html.Div([
            html.Span("■ Green bar  ",
                      style={'color': THEME['success'], 'fontWeight': 'bold'}),
            html.Span("Positive IC — feature rises → factor return ↑  "
                      "(pro-factor / trend-following)"),
            html.Span("     ■ Red bar  ",
                      style={'color': THEME['danger'], 'fontWeight': 'bold'}),
            html.Span("Negative IC — feature rises → factor return ↓  "
                      "(contra-factor / mean-reversion)"),
        ], style={'marginBottom': '5px'}),
        html.Div(
            "Feature categories in labels:  "
            "MOM = Momentum (trend)  ·  "
            "VAL = Value / Mean-Rev (z-score, percentile)  ·  "
            "CARRY = Carry / Curve structure  ·  "
            "XMK = Cross-Market spillover  ·  "
            "MACRO = Macro indicator  ·  "
            "VOL = Volatility",
        ),
    ], style={
        'fontSize': '11px', 'color': THEME['text_sub'],
        'lineHeight': '1.6', 'marginBottom': '10px',
        'padding': '7px 10px',
        'backgroundColor': THEME['bg_input'],
        'borderRadius': '4px',
        'border': f'1px solid {THEME["table_header"]}',
    })

    return html.Div([
        html.H6("Top Drivers per Risk Factor",
                style={'color': THEME['accent'], 'marginBottom': '4px'}),
        html.P(
            "Bar length = contribution share = |IC_i| / Σ|IC| across ALL selected features. "
            "If top 3 bars fill ~100% the remaining features have near-zero IC — "
            "they were selected but contribute little to the model.",
            style={'color': THEME['text_sub'], 'fontSize': '11px',
                   'marginBottom': '8px', 'fontStyle': 'italic'},
        ),
        legend,
        html.Div(charts,
                 style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '12px'}),
    ], style={
        'backgroundColor': THEME['bg_card'],
        'border': f'1px solid {THEME["table_header"]}',
        'borderRadius': '8px',
        'padding': '14px 16px',
        'marginTop': '16px',
    })
