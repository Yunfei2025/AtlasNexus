# -*- coding: utf-8 -*-
"""
Factor-model predictor for risk-factor returns.

Unlike the technical-indicator approach (MA, Bollinger, …), this module
generates *predictive features* (carry, value, momentum, macro, yield-curve
shape) for each risk factor and trains an IC-weighted model to forecast the
next-period factor return.  The pipeline mirrors ``factors/`` but is adapted
for yield/price series that lack OHLCV data.

Pipeline per risk factor:
  1. build_features()    – generate carry / value / momentum / macro features
  2. calculate_metrics() – IC / IR of each feature vs future factor return
  3. select_factors()    – filter by IC ≥ threshold, diversification, top-N
  4. train_model()       – IC-weighted (or ridge) coefficients on train window
  5. predict()           – out-of-sample predicted return → sign = signal

Reuses:
  - ``factors.analysis.metrics.calculate_metrics`` (IC / IR)
  - ``factors.engine.selector.FactorSelector``     (IC + VIF filtering)
  - ``factors.engine.predictor.train_model``        (IC-weighted / ridge)
  - ``factors.engine.predictor.predict_returns``    (OOS prediction)
  - ``factors.generator.macro.MacroFactors``        (macro feature set)
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

from settings.paths import DIR_INPUT, DIR_DATA, DIR_MODELS

# ── Reused components from factors/ ─────────────────────────────────────────
from factors.engine.selector import FactorSelector
from scipy.stats import spearmanr

from multiasset.factor_backtest import (
    load_factor_rates,
    _yield_to_return,
    _price_to_return,
    _is_yield_factor,
    get_factor_duration,
    compute_metrics,
)


# ═══════════════════════════════════════════════════════════════════════════
#  1. Configuration (light-weight dataclass, no OOP hierarchy)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FactorModelConfig:
    """Minimal config consumed by FactorSelector and train_model."""
    # Selection
    ic_threshold: float = 0.05
    ir_threshold: float = 0.4
    filtering_method: str = 'significance'  # use t-test on IC
    top_n: int = 8
    use_vif_filtering: bool = True
    vif_threshold: float = 5.0
    vif_fallback_threshold: float = 10.0
    use_factor_diversification: bool = True
    max_factor_correlation: float = 0.7
    use_significance_test: bool = True      # require p < 0.05
    min_observations: int = 60
    confidence_level: float = 0.05
    # Training
    weighting_method: str = 'ic_weighted'
    model_type: str = 'ic_weighted'
    ic_weighting_method: str = 'ic_signed'   # signed preserves direction of IC
    scale_ic_predictions: bool = True
    # Walk-forward
    train_months: int = 12
    test_months: int = 1
    # Signal smoothing
    signal_smooth_days: int = 1              # no pre-smoothing: keep signal path-independent
    # Target horizon
    target_horizon: int = 1                  # predict N-day forward return
    # ── Position sizing ──────────────────────────────────────────────────────
    # 'discrete' mode: z-score → 5 discrete levels via ICIR-scaled z.
    # ICIR acts as a confidence multiplier on the z-score (not a gate) so
    # the warm-up transition is smooth rather than abrupt.
    # No SMA smoothing and no turnover filter → fully path-independent.
    sizing_mode: str = 'discrete'            # 'binary' (legacy) | 'continuous' | 'discrete'
    target_vol: float = 0.10                 # annualised vol target (continuous mode only)
    vol_scale_window: int = 60               # realised-vol lookback (continuous mode only)
    icir_window: int = 60                    # rolling OOS-IC window for ICIR confidence
    icir_saturation: float = 0.25            # tanh saturation: ICIR at which confidence=0.76
    max_leverage: float = 2.0                # cap |position| (continuous mode only)
    # ── Discrete sizing ─────────────────────────────────────────────────────
    position_smooth_window: int = 1          # no SMA smoothing → path-independent
    discrete_tick: float = 0.2               # quantisation step of the target
    discrete_max_z: float = 1.5              # |z| at which the target saturates to ±1
    discrete_deadzone_z: float = 0.5         # |z| below which target is exactly 0
    # ── Turnover & costs (doc §3.3 / §5.1) ──────────────────────────────────
    turnover_threshold: float = 0.10         # used only in continuous mode
    # tx cost is read from settings.fixed_income.FACTOR_TX_COST_BP (flat notional bp)
    # ── Walk-forward purge / embargo (doc §4.2) ─────────────────────────────
    purge_days: int = 5                      # purge around train/test boundary
    embargo_days: int = 10                   # embargo at start of test set
    # ── Fix 1: Multi-horizon ensemble ───────────────────────────────────────
    # Train separate models for each prediction horizon and blend by IC weight.
    # H=20 strongly upweights momentum features, capturing sustained trends.
    target_horizons: List[int] = field(default_factory=lambda: [1, 5, 20])
    # ── Fix 2: Trend-regime veto on mean-reversion features ─────────────────
    # During a confirmed directional trend, zero out z-score / value features
    # so they cannot force the model to fade a running bull/bear market.
    trend_veto_zscore: bool = True
    trend_veto_ema_windows: tuple = (10, 30, 60)  # fast / mid / slow EMA spans
    trend_veto_mom_sigma: float = 0.5             # threshold: |mom| > σ × this
    # ── Fix 3: EWMA observation weighting in IC calculation ─────────────────
    # Recent months dominate IC estimates; half-life ≈ 3 months (63 trading days).
    # Set to 0 to disable (uniform weighting).
    ewma_obs_halflife: int = 63
    # ── Fix 4: Longer momentum features + long-only position floor ──────────
    # Mom120 / Mom252 added in _momentum_features; floor enforced here.
    long_floor: float = 0.30                      # min position during confirmed trend
    long_floor_confirm_window: int = 120          # medium-term momentum window (days)


# ═══════════════════════════════════════════════════════════════════════════
#  2. Feature generators (yield-adapted, no OHLCV needed)
# ═══════════════════════════════════════════════════════════════════════════

def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    mu = s.rolling(window, min_periods=max(window // 2, 20)).mean()
    sigma = s.rolling(window, min_periods=max(window // 2, 20)).std()
    return ((s - mu) / sigma.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def _rolling_percentile(s: pd.Series, window: int) -> pd.Series:
    rmin = s.rolling(window, min_periods=max(window // 2, 20)).min()
    rmax = s.rolling(window, min_periods=max(window // 2, 20)).max()
    rng = rmax - rmin
    mid = (rmax + rmin) / 2.0
    return ((s - mid) / rng.replace(0, np.nan) * 2.0).clip(-1, 1)


# ── Momentum features ───────────────────────────────────────────────────
def _momentum_features(level: pd.Series, name: str) -> Dict[str, pd.Series]:
    """Rate-of-change at multiple horizons + trend strength.

    Fix 4: adds Mom120 (6M) and Mom252 (12M) which carry much higher IC vs
    20-day forward returns during sustained trends, plus a long-horizon EMA
    crossover that flags multi-month directional regimes.
    """
    feats: Dict[str, pd.Series] = {}
    for w in [5, 10, 20, 60, 120, 252]:
        feats[f'{name}_Mom{w}'] = level.diff(w)
    # Short EMA crossover (10d vs 30d) — captures intra-month momentum
    ema_fast = level.ewm(span=10, adjust=False).mean()
    ema_slow = level.ewm(span=30, adjust=False).mean()
    feats[f'{name}_EMACross'] = ema_fast - ema_slow
    # Long EMA crossover (60d vs 200d) — captures multi-month trend regime
    ema_mid  = level.ewm(span=60,  adjust=False).mean()
    ema_vlong = level.ewm(span=200, adjust=False).mean()
    feats[f'{name}_EMACrossLong'] = ema_mid - ema_vlong
    return feats


# ── Value / mean-reversion features ─────────────────────────────────────
def _value_features(level: pd.Series, name: str) -> Dict[str, pd.Series]:
    feats: Dict[str, pd.Series] = {}
    for w in [60, 120, 252]:
        feats[f'{name}_ZScore{w}'] = _rolling_zscore(level, w)
    feats[f'{name}_PctRank252'] = _rolling_percentile(level, 252)
    # Short z − long z  (contrarian distance)
    z20 = _rolling_zscore(level, 20)
    z252 = _rolling_zscore(level, 252)
    feats[f'{name}_ValueMom'] = z20 - z252
    return feats


# ── Volatility features (realised vol of changes) ──────────────────────
def _volatility_features(level: pd.Series, name: str) -> Dict[str, pd.Series]:
    chg = level.diff()
    feats: Dict[str, pd.Series] = {}
    for w in [10, 20, 60]:
        feats[f'{name}_Vol{w}'] = chg.rolling(w).std()
    # Vol ratio (short / long)
    feats[f'{name}_VolRatio'] = (
        chg.rolling(10).std() / chg.rolling(60).std().replace(0, np.nan)
    )
    return feats


# ── Carry features (for yield factors only) ─────────────────────────────
def _carry_features(
    factor_code: str,
    curve_data: Optional[pd.DataFrame],
) -> Dict[str, pd.Series]:
    """Build carry / roll-down features from the underlying curve data.

    Works only for IR and SP factors where we can access the raw tenor yields.
    """
    if curve_data is None or curve_data.empty:
        return {}

    feats: Dict[str, pd.Series] = {}
    cols = list(curve_data.columns)
    prefix = factor_code.split('.')[0]

    if len(cols) >= 2:
        # Slope = longest − shortest tenor
        slope = curve_data.iloc[:, -1] - curve_data.iloc[:, 0]
        feats[f'{factor_code}_Slope'] = slope
        feats[f'{factor_code}_SlopeMom20'] = slope.diff(20)
        feats[f'{factor_code}_SlopeZ60'] = _rolling_zscore(slope, 60)

    if len(cols) >= 3:
        # Curvature = mid − average(short, long)
        mid_idx = len(cols) // 2
        curv = curve_data.iloc[:, mid_idx] - (curve_data.iloc[:, 0] + curve_data.iloc[:, -1]) / 2
        feats[f'{factor_code}_Curv'] = curv
        feats[f'{factor_code}_CurvZ60'] = _rolling_zscore(curv, 60)

    # Roll-down proxy: adjacent tenor spread ≈ carry for level factor
    if prefix in ('IRDL', 'SPDL') and len(cols) >= 2:
        for i in range(len(cols) - 1):
            spread = curve_data.iloc[:, i + 1] - curve_data.iloc[:, i]
            feats[f'{factor_code}_Carry_{i}'] = spread

    return feats


# ── Cross-factor features ──────────────────────────────────────────────
def _cross_factor_features(
    factor_code: str,
    all_factor_levels: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """Relative momentum / correlation features from other factors."""
    feats: Dict[str, pd.Series] = {}
    if factor_code not in all_factor_levels.columns:
        return feats

    own = all_factor_levels[factor_code]
    prefix = factor_code.split('.')[0]

    # Diff vs related factors
    for col in all_factor_levels.columns:
        if col == factor_code:
            continue
        other_prefix = col.split('.')[0]
        # Only include factors from same asset class
        same_class = (
            (prefix in ('IRDL', 'IRSL', 'IRCV') and other_prefix in ('IRDL', 'IRSL', 'IRCV'))
            or (prefix in ('SPDL', 'SPSL') and other_prefix in ('SPDL', 'SPSL'))
            or (prefix == 'FXDL' and other_prefix == 'FXDL')
            or (prefix == 'CMDL' and other_prefix == 'CMDL')
        )
        if same_class:
            diff = own - all_factor_levels[col]
            feats[f'{factor_code}_vs_{col}_20'] = diff.rolling(20).mean()

    return feats


# ── Macro features (shared, loaded once) ────────────────────────────────
_MACRO_CACHE: Optional[pd.DataFrame] = None


def _load_macro_features() -> pd.DataFrame:
    global _MACRO_CACHE
    if _MACRO_CACHE is not None:
        return _MACRO_CACHE

    try:
        from factors.generator.macro import MacroFactors
        macro = MacroFactors()
        _MACRO_CACHE = macro.calculate_all()
    except Exception as e:
        print(f"Warning: macro features unavailable: {e}")
        _MACRO_CACHE = pd.DataFrame()
    return _MACRO_CACHE


# ── Load raw curve data for a factor ────────────────────────────────────
def _load_curve_data(factor_code: str, input_dir: str) -> Optional[pd.DataFrame]:
    """Load raw tenor yield data for the factor's underlying curve."""
    from multiasset.config import CURVE_CONFIG, SPREAD_CONFIG

    prefix = factor_code.split('.')[0]
    suffix = factor_code.split('.')[1] if '.' in factor_code else ''

    try:
        if prefix in ('IRDL', 'IRSL', 'IRCV'):
            cfg = CURVE_CONFIG.get(suffix)
            if cfg is None:
                # Foreign curves from fxcurve_ts.pkl
                fxcurve_path = os.path.join(input_dir, 'fxcurve_ts.pkl')
                if os.path.exists(fxcurve_path):
                    fxcurve = pd.read_pickle(fxcurve_path)
                    if suffix in fxcurve:
                        return fxcurve[suffix]
                return None
            pkl_file, pkl_key, columns = cfg
            data = pd.read_pickle(os.path.join(input_dir, pkl_file))
            if pkl_key and isinstance(data, dict):
                data = data[pkl_key]
            if columns:
                data = data[[c for c in columns if c in data.columns]]
            return data

        elif prefix in ('SPDL', 'SPSL'):
            cfg = SPREAD_CONFIG.get(suffix)
            if cfg is None:
                return None
            pkl_file, pkl_key, columns = cfg
            data = pd.read_pickle(os.path.join(input_dir, pkl_file))
            if pkl_key and isinstance(data, dict):
                data = data[pkl_key]
            if columns:
                data = data[[c for c in columns if c in data.columns]]
            return data

    except Exception as e:
        print(f"Warning: could not load curve data for {factor_code}: {e}")

    return None


# ── Master feature builder ──────────────────────────────────────────────

def build_features(
    factor_code: str,
    factor_levels: pd.DataFrame,
    input_dir: Union[str, Path] = DIR_INPUT,
    include_macro: bool = True,
    include_cross: bool = True,
) -> pd.DataFrame:
    """Build all predictive features for a single risk factor.

    Returns a DataFrame (index = date) of named features.
    """
    if factor_code not in factor_levels.columns:
        raise ValueError(f"{factor_code} not in factor_levels")

    level = factor_levels[factor_code].dropna()
    feats: Dict[str, pd.Series] = {}

    # Self-based features
    feats.update(_momentum_features(level, factor_code))
    feats.update(_value_features(level, factor_code))
    feats.update(_volatility_features(level, factor_code))

    # Carry features from raw curve data
    is_yield = _is_yield_factor(factor_code)
    if is_yield:
        curve_data = _load_curve_data(factor_code, str(input_dir))
        feats.update(_carry_features(factor_code, curve_data))

    # Cross-factor features
    if include_cross:
        feats.update(_cross_factor_features(factor_code, factor_levels))

    # Macro features (shared across all factors)
    if include_macro:
        macro_df = _load_macro_features()
        if not macro_df.empty:
            for col in macro_df.columns:
                feats[f'MACRO_{col}'] = macro_df[col]

    # Assemble and clean
    result = pd.DataFrame(feats)
    # Drop columns with >50% NaN
    nan_pct = result.isnull().sum() / len(result)
    result = result.loc[:, nan_pct < 0.5]

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  3. Self-contained IC model (avoids shift issues in shared functions)
# ═══════════════════════════════════════════════════════════════════════════

# ── Fix 3 helper: weighted Spearman IC ──────────────────────────────────
def _weighted_spearman_ic(
    x: pd.Series,
    y: pd.Series,
    weights: pd.Series,
) -> float:
    """Weighted Spearman rank correlation.

    Implements fractional weighted ranks so that observations with higher
    weight contribute more to the IC estimate.  Used when ``ewma_obs_halflife``
    is set so that recent training data is emphasised over older data.
    """
    idx = x.notna() & y.notna() & weights.notna() & (weights > 0)
    xv = x[idx].values.astype(float)
    yv = y[idx].values.astype(float)
    wv = weights[idx].values.astype(float)
    if len(xv) < 10:
        return float('nan')
    wv = wv / wv.sum()

    def _wrank(v: np.ndarray, wt: np.ndarray) -> np.ndarray:
        order = np.argsort(v)
        rv = np.empty(len(v))
        cw = 0.0
        for k in order:
            rv[k] = cw + wt[k] / 2.0
            cw += float(wt[k])
        return rv

    rx = _wrank(xv, wv)
    ry = _wrank(yv, wv)
    mx = float((rx * wv).sum())
    my = float((ry * wv).sum())
    num  = float(((rx - mx) * (ry - my) * wv).sum())
    var_x = float(((rx - mx) ** 2 * wv).sum())
    var_y = float(((ry - my) ** 2 * wv).sum())
    denom = np.sqrt(var_x * var_y)
    return float(num / denom) if denom > 1e-12 else 0.0


# ── Fix 2 helper: trend-regime flag ─────────────────────────────────────
def _trend_regime_flag(
    level: pd.Series,
    ema_windows: tuple = (10, 30, 60),
    mom_sigma_mult: float = 0.5,
) -> pd.Series:
    """Boolean Series: True where a sustained directional trend is confirmed.

    Confirmation requires both:
    * EMA alignment — the three EMAs cascade in one direction
      (EMA_fast < EMA_mid < EMA_slow for a downtrend; reverse for uptrend)
    * Strong momentum — |mom_slow_window| > ``mom_sigma_mult × rolling σ``

    For yield factors (IRDL) a *downtrend* in the yield level equals a bond
    bull market.  The flag catches both downtrends and uptrends so it works
    for all factor types.
    """
    e1 = level.ewm(span=ema_windows[0], adjust=False).mean()
    e2 = level.ewm(span=ema_windows[1], adjust=False).mean()
    e3 = level.ewm(span=ema_windows[2], adjust=False).mean()
    mom = level.diff(ema_windows[2])
    mom_std = mom.rolling(252, min_periods=60).std()
    ema_downtrend = (e1 < e2) & (e2 < e3)
    ema_uptrend   = (e1 > e2) & (e2 > e3)
    strong_mom = mom.abs() > mom_sigma_mult * mom_std.replace(0, np.nan)
    return ((ema_downtrend | ema_uptrend) & strong_mom.fillna(False))


def _compute_ic_metrics(
    features: pd.DataFrame,
    forward_returns: pd.Series,
    min_obs: int = 60,
    ewma_halflife: int = 0,
) -> pd.DataFrame:
    """Compute Spearman IC of each feature vs already-aligned forward returns.

    Unlike ``factors.analysis.metrics.calculate_metrics`` this does **not**
    shift returns internally — caller must supply properly aligned fwd returns.

    Fix 3: when ``ewma_halflife > 0`` the IC is computed as a weighted
    Spearman correlation where each observation is weighted by
    ``exp(-log(2)/halflife × (T-t))`` so that recent training data dominates.
    The regular (unweighted) ``spearmanr`` p-value is still used as a
    conservative significance gate.
    """
    common = features.index.intersection(forward_returns.dropna().index)
    if len(common) < min_obs:
        return pd.DataFrame()

    feat = features.loc[common]
    ret  = forward_returns.loc[common]

    # EWMA sample weights (Fix 3) — computed once for all features
    n = len(common)
    if ewma_halflife > 0 and n > ewma_halflife:
        decay = np.exp(-np.log(2) / ewma_halflife * np.arange(n - 1, -1, -1))
        sample_weights = pd.Series(decay / decay.sum(), index=common)
    else:
        sample_weights = None

    rows = []
    for col in feat.columns:
        valid = feat[col].notna() & ret.notna()
        if valid.sum() < min_obs:
            continue
        x_col = feat[col].loc[valid]
        y_col = ret.loc[valid]

        if sample_weights is not None:
            w_col = sample_weights.reindex(x_col.index).fillna(0)
            w_col = w_col / w_col.sum() if w_col.sum() > 1e-12 else w_col
            ic = _weighted_spearman_ic(x_col, y_col, w_col)
            # conservative p-value: use unweighted Spearman
            _, p = spearmanr(x_col, y_col)
        else:
            ic, p = spearmanr(x_col, y_col)

        if np.isnan(ic):
            continue
        rows.append({
            'factor': col,
            'IC': ic,
            'IC_abs': abs(ic),
            'IR': 0.0,          # rolling IR not needed for selection
            'count': int(valid.sum()),
            'p_value': p,
            'is_significant': p < 0.05,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index('factor')


def _train_ic_model(
    features: pd.DataFrame,
    forward_returns: pd.Series,
    selected_features: List[str],
) -> Dict:
    """Train IC-weighted model: weight_i = signed Spearman IC(feature_i, fwd_ret)."""
    from sklearn.preprocessing import StandardScaler

    avail = [f for f in selected_features if f in features.columns]
    if not avail:
        return {'error': 'No available features'}

    X = features[avail].ffill().fillna(0)
    y = forward_returns.reindex(X.index)

    valid = y.notna() & X.notna().all(axis=1)
    X, y = X.loc[valid], y.loc[valid]
    if len(X) < 30:
        return {'error': 'Insufficient data'}

    scaler = StandardScaler()
    Xs = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)

    weights = pd.Series(0.0, index=avail)
    for col in avail:
        ic, _ = spearmanr(Xs[col], y)
        weights[col] = ic if not np.isnan(ic) else 0.0

    preds = (Xs * weights).sum(axis=1)
    mean_abs_a = abs(y).mean()
    mean_abs_p = abs(preds).mean()
    scale = mean_abs_a / mean_abs_p if mean_abs_p > 1e-10 else 1.0

    return {
        'coefficients': weights,
        'scaling_factor': scale,
        'scaler': scaler,
        'feature_names': avail,
    }


def _predict_ic_model(
    features: pd.DataFrame,
    model: Dict,
) -> pd.Series:
    """Apply IC-weighted model to (test) features."""
    avail = [f for f in model['feature_names'] if f in features.columns]
    if not avail:
        return pd.Series(dtype=float)

    X = features[avail].ffill().fillna(0)
    Xs = pd.DataFrame(
        model['scaler'].transform(X), index=X.index, columns=X.columns,
    )
    w = model['coefficients'].reindex(avail, fill_value=0)
    return (Xs * w).sum(axis=1) * model.get('scaling_factor', 1.0)


# ═══════════════════════════════════════════════════════════════════════════
#  3b. Position sizing  (shared by backtest + live-predict paths)
# ═══════════════════════════════════════════════════════════════════════════

def rolling_icir(
    predicted_return: pd.Series,
    daily_returns: pd.Series,
    window: int = 60,
) -> pd.Series:
    """Rolling information-coefficient information-ratio.

    IC_t   = window-corr(predicted_return, next-day actual return)
    ICIR_t = rolling mean(IC) / rolling std(IC)   over the same window.

    The series is **not** shifted here — callers that use it for sizing must
    ``.shift(1)`` so that only past information drives today's position.
    Mirrors the dashboard IC block (backtest_rfbt.py) so both paths agree.
    """
    actual_fwd = daily_returns.shift(-1).reindex(predicted_return.index)
    ic = predicted_return.rolling(window).corr(actual_fwd)
    ic_mean = ic.rolling(window, min_periods=max(window // 2, 10)).mean()
    ic_std = ic.rolling(window, min_periods=max(window // 2, 10)).std()
    return (ic_mean / ic_std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def factor_tx_cost_per_unit(factor_code: str, cfg: FactorModelConfig) -> float:
    """Transaction cost per unit of position turnover, in **return space**.

    Uses a flat notional-based cost (``FACTOR_TX_COST_BP`` from
    ``settings.fixed_income``) applied uniformly across all factor types.
    0.3 bp notional = 3e-5 per unit of position.
    """
    from settings.fixed_income import FACTOR_TX_COST_BP
    return FACTOR_TX_COST_BP / 1e4


def discrete_target_level(
    z: float,
    tick: float = 0.2,
    max_z: float = 1.5,
    deadzone_z: float = 0.5,
    long_only: bool = False,
) -> float:
    """Map a z-score to a quantised target position in ``[-1, 1]``.

    Dead-zone: ``|z| <= deadzone_z`` → returns exactly 0 ("no conviction").

    Above the dead-zone, scales the remaining range ``(deadzone_z, max_z]``
    linearly to ``(0, 1]``, then rounds to the nearest tick (minimum 1 tick so
    the first non-zero level is always ``±tick``).  With ``tick=0.2``,
    ``deadzone_z=0.5``, ``max_z=1.5``:

        |z| ≤ 0.5                → 0
        0.5 < |z| ≤ 0.7  → ±0.2
        0.7 < |z| ≤ 0.9  → ±0.4
        0.9 < |z| ≤ 1.1  → ±0.6
        1.1 < |z| ≤ 1.3  → ±0.8
        |z| > 1.3         → ±1.0

    Long-only clips negatives to 0 (e.g. IRDL).

    Shared by the engine's ``discrete`` sizing mode, the predict-from-saved
    path and the live signal snapshot so the level is identical everywhere.
    """
    if z is None or not np.isfinite(z):
        return 0.0
    if abs(z) <= deadzone_z:
        return 0.0
    sign = 1.0 if z > 0 else -1.0
    span = max(max_z - deadzone_z, 1e-9)
    raw = min((abs(z) - deadzone_z) / span, 1.0)   # in (0, 1]
    # round to nearest tick; enforce minimum of 1 tick (already past dead-zone)
    n_ticks = max(1, int(round(raw / tick)))
    level = sign * min(n_ticks * tick, 1.0)
    if long_only and level < 0:
        level = 0.0
    return round(level, 10)


def bucket_position(
    position: Union[float, pd.Series],
    num_levels: int = 5,
    long_only: bool = False,
) -> Union[int, float, pd.Series]:
    """Bucket continuous position into discrete levels to avoid overfitting.

    Pass ``long_only=True`` for factors that are restricted to [0, 1] (e.g. IRDL).
    The regime is determined by the *caller* — never inferred from the sign of the
    value — so a small positive position on a long-short factor is not misclassified.

    Long-only [0, 1]:    maps to levels 0, 0.5, 1, 1.5, 2 (spread across [0, 1])
    Long-short [-1, 1]:  maps to levels -2, -1, 0, 1, 2 (symmetric around zero)

    For long-only assets, levels represent quintiles of [0, 1]:
      Level 0:    position ∈ [0.0, 0.2)
      Level 0.5:  position ∈ [0.2, 0.4)
      Level 1:    position ∈ [0.4, 0.6)
      Level 1.5:  position ∈ [0.6, 0.8)
      Level 2:    position ∈ [0.8, 1.0]

    For long-short assets, levels are:
      Level -2 (strong short): position ≤ -0.6
      Level -1 (weak short):   -0.6 < position ≤ -0.2
      Level  0 (neutral):      -0.2 < position ≤ 0.2
      Level +1 (weak long):     0.2 < position ≤ 0.6
      Level +2 (strong long):   position > 0.6

    Args:
        position: Continuous position value or Series
        num_levels: Number of discrete levels (currently only 5 supported)
        long_only: Whether the factor is restricted to non-negative positions

    Returns:
        Bucketed level(s) as int/float or Series
    """
    if isinstance(position, pd.Series):
        return position.apply(
            lambda x: bucket_position(x, num_levels, long_only) if pd.notna(x) else np.nan
        )

    if num_levels != 5:
        raise ValueError(f"Only 5-level bucketing is currently supported")

    if pd.isna(position):
        return np.nan

    if long_only:
        # Long-only: spread 5 levels across [0, 1]
        p = max(0.0, min(1.0, float(position)))
        if p >= 0.8:
            return 2
        elif p >= 0.6:
            return 1.5
        elif p >= 0.4:
            return 1
        elif p >= 0.2:
            return 0.5
        else:
            return 0
    else:
        # Long-short: symmetric levels around 0
        if position > 0.6:
            return 2
        elif position > 0.2:
            return 1
        elif position > -0.2:
            return 0
        elif position > -0.6:
            return -1
        else:
            return -2


def build_position_series(
    predicted_return: pd.Series,
    daily_returns: pd.Series,
    cfg: FactorModelConfig,
    long_only: bool = False,
) -> pd.DataFrame:
    """Convert predicted returns into a tradable position series.

    Returns a DataFrame with columns ``signal`` (-1/0/+1), ``position``
    (continuous target, leverage-capped) and ``turnover`` (|Δposition|).

    ``sizing_mode='binary'`` reproduces the legacy ``sign(smoothed pred)``
    behaviour exactly (turnover = |Δsign|).  ``'continuous'`` applies the
    doc §3.1 recipe: ``z(pred) × tanh(ICIR/κ) × vol_scale``, turnover-filtered
    and leverage-capped.  ``'discrete'`` bins the z-scored prediction into
    integer levels {-2..2} (``signal``) and takes an N-day moving average of
    that target to obtain a feasible, gradually-ramping ``position`` — a
    stateless filter whose daily move is bounded by
    ``2*discrete_max_level / position_smooth_window`` (no path dependence on
    the held position).  All inputs are causal (shifted) to avoid look-ahead.

    ``long_only=True`` clips the final position to ``[0, max_leverage]`` so
    the factor can never go short — appropriate for IRDL (duration level)
    which represents the core long-only bond exposure.
    """
    pred = predicted_return.astype(float)

    # Smoothed prediction (shared by all modes)
    if cfg.signal_smooth_days > 1:
        smoothed = pred.rolling(cfg.signal_smooth_days, min_periods=1).mean()
    else:
        smoothed = pred

    if cfg.sizing_mode == 'discrete':
        # 1. Standardise so the level is regime-relative (causal rolling z).
        pred_z = _rolling_zscore(smoothed, cfg.icir_window).fillna(0.0)

        # 2. ICIR confidence scaler — multiplies the z-score so warm-up is
        #    gradual rather than abrupt.  During the first icir_window days
        #    the ICIR ≈ 0 → confidence ≈ 0 → z_scaled ≈ 0 → neutral levels.
        #    As the rolling IC history builds, confidence smoothly ramps to 1
        #    and z_scaled converges to pred_z.  This is NOT path-dependent:
        #    ICIR depends only on market data (pred vs actual), not positions.
        icir = rolling_icir(smoothed, daily_returns, cfg.icir_window).shift(1)
        icir_confidence = np.tanh(icir.clip(lower=0) / cfg.icir_saturation).fillna(0.0)
        pred_z_scaled = pred_z * icir_confidence

        # 3. Map scaled z directly to 5 discrete levels — no SMA, no turnover
        #    filter, fully path-independent.
        target = pred_z_scaled.map(lambda v: discrete_target_level(
            v, cfg.discrete_tick, cfg.discrete_max_z, cfg.discrete_deadzone_z, long_only,
        )).astype(float)

        out = pd.DataFrame({'signal': target, 'position': target})
        out['turnover'] = out['position'].diff().abs().fillna(out['position'].abs())
        return out[['signal', 'position', 'turnover']]

    if cfg.sizing_mode == 'binary':
        raw_sig = np.sign(smoothed).fillna(0).astype(float)
        if long_only:
            raw_sig = raw_sig.clip(lower=0)   # 0 or +1 only
        signal = raw_sig.astype(int)
        out = pd.DataFrame({'signal': signal, 'position': raw_sig})
        out['turnover'] = out['position'].diff().abs().fillna(out['position'].abs())
        return out

    # ── Continuous sizing (doc §3.1) ─────────────────────────────────────
    # 1. Standardise the predicted return so size is regime-relative.
    pred_z = _rolling_zscore(smoothed, cfg.icir_window).fillna(0.0)

    # 2. ICIR weight — smooth saturating confidence gate (past info only).
    icir = rolling_icir(pred, daily_returns, cfg.icir_window).shift(1)
    icir_weight = np.tanh(icir / cfg.icir_saturation).fillna(0.0)

    # 3. Risk-parity vol scale — target_vol / realised annualised vol (lagged).
    realised_vol = (
        daily_returns.rolling(cfg.vol_scale_window).std().shift(1) * np.sqrt(252)
    )
    realised_vol = realised_vol.reindex(pred.index)
    vol_scale = (cfg.target_vol / realised_vol.replace(0, np.nan)).clip(upper=cfg.max_leverage)
    vol_scale = vol_scale.fillna(0.0)

    lo, hi = (0.0, cfg.max_leverage) if long_only else (-cfg.max_leverage, cfg.max_leverage)
    raw_position = (pred_z * icir_weight * vol_scale).clip(lo, hi).fillna(0.0)

    # 4. Turnover filter — only move when the change clears the threshold.
    held = 0.0
    positions = []
    thr = cfg.turnover_threshold
    for val in raw_position.values:
        if abs(val - held) > thr:
            held = float(val)
        positions.append(held)

    position = pd.Series(positions, index=raw_position.index)
    out = pd.DataFrame({'position': position})
    out['signal'] = np.sign(position).fillna(0).astype(int)
    out['turnover'] = position.diff().abs().fillna(position.abs())
    return out[['signal', 'position', 'turnover']]


# ═══════════════════════════════════════════════════════════════════════════
#  4. Walk-forward factor model engine
# ═══════════════════════════════════════════════════════════════════════════

def _compute_target_returns(
    factor_code: str,
    factor_levels: pd.DataFrame,
) -> pd.Series:
    """Compute daily returns for a factor (duration-adjusted for yields)."""
    level = factor_levels[factor_code].dropna()
    is_yield = _is_yield_factor(factor_code)
    mod_dur = get_factor_duration(factor_code)

    if is_yield:
        return _yield_to_return(level, mod_dur)
    else:
        return _price_to_return(level)


def run_factor_model_backtest(
    factor_code: str,
    factor_levels: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    input_dir: Union[str, Path] = DIR_INPUT,
    config: Optional[FactorModelConfig] = None,
    models_by_month: Optional[Dict] = None,
) -> pd.DataFrame:
    """Run walk-forward factor model backtest for a single risk factor.

    Parameters
    ----------
    factor_code : str
        Risk factor code (e.g. ``'IRDL.CN'``).
    factor_levels : pd.DataFrame
        Full factor-rates DataFrame (all factors, full history).
    start_date, end_date : str or None
        Backtest date range (YYYY-MM-DD).
    input_dir : path
        Data directory.
    config : FactorModelConfig or None
        Model parameters; uses defaults if None.

    Returns
    -------
    pd.DataFrame
        Columns: signal, returns, strategy_returns, cumulative_returns,
                 predicted_return, n_features
    """
    cfg = config or FactorModelConfig()

    # Ensure DatetimeIndex
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    # Date filter
    if start_date:
        ts = pd.Timestamp(start_date)
    else:
        ts = factor_levels.index.min()
    if end_date:
        te = pd.Timestamp(end_date)
    else:
        te = factor_levels.index.max()

    # ── Build features once (full history) ─────────────────────────────────
    # Fix 1: use a list of horizons; ensemble predictions across H=1, 5, 20.
    horizons = list(cfg.target_horizons) if cfg.target_horizons else [max(cfg.target_horizon, 1)]
    print(f"  [{factor_code}] Building features (horizons={horizons}d) ...")
    all_features = build_features(factor_code, factor_levels, input_dir)

    # Daily returns; forward returns are computed PER horizon inside the loop.
    daily_returns = _compute_target_returns(factor_code, factor_levels)
    all_fwd_by_H: Dict[int, pd.Series] = {
        H: daily_returns.rolling(H).sum().shift(-H)
        for H in horizons
    }
    # Trim features to where the shortest-horizon forward return is defined
    # (guarantees we have at least some training data for all horizons).
    H_min = min(horizons)
    all_features = all_features.loc[
        all_features.index.intersection(all_fwd_by_H[H_min].dropna().index)
    ]
    # Raw level series — used for trend veto (Fix 2) and position floor (Fix 4)
    level = factor_levels[factor_code].dropna()

    # Walk-forward periods
    from dateutil.relativedelta import relativedelta

    # First train window must end before start_date
    train_months = cfg.train_months
    test_months = cfg.test_months

    # Generate test windows.  Purge the last (H + purge_days) calendar days
    # before each test set so the forward-return window of the final training
    # sample cannot overlap the test period (doc §4.2 — Lopéz de Prado purging).
    purge_gap = pd.Timedelta(days=1 + cfg.purge_days + H_min)
    periods = []
    cursor = ts
    while cursor <= te:
        period_end = min(cursor + relativedelta(months=test_months) - pd.Timedelta(days=1), te)
        train_start = cursor - relativedelta(months=train_months)
        train_end = cursor - purge_gap
        periods.append((train_start, train_end, cursor, period_end))
        cursor = period_end + pd.Timedelta(days=1)

    if not periods:
        print(f"  [{factor_code}] No valid walk-forward periods")
        return pd.DataFrame()

    # Walk-forward loop
    all_predictions = []
    selector = FactorSelector(cfg)

    for train_start, train_end, test_start, test_end in periods:
        # ── Slice train / test ──────────────────────────────────────────────
        train_mask = (all_features.index >= train_start) & (all_features.index <= train_end)
        test_mask  = (all_features.index >= test_start)  & (all_features.index <= test_end)

        train_feat = all_features.loc[train_mask].copy()
        test_feat  = all_features.loc[test_mask].copy()

        # Embargo: drop the first ``embargo_days`` rows of the test set so that
        # samples immediately after the train boundary do not bleed train info
        # through the forward-return window (doc §4.2).
        if cfg.embargo_days > 0 and len(test_feat) > cfg.embargo_days:
            test_feat = test_feat.iloc[cfg.embargo_days:]

        if len(train_feat) < cfg.min_observations or len(test_feat) == 0:
            continue

        # Forward-fill then zero-fill NaN in features
        train_feat = train_feat.ffill().fillna(0)
        test_feat  = test_feat.ffill().fillna(0)

        # ── Fix 2: Trend-regime flag at the end of the training window ──────
        # We check whether the factor was in a confirmed directional trend at
        # train_end. If so, mean-reversion features (z-scores, value) are vetoed
        # so they cannot force the model to fade a running bull/bear market.
        trend_confirmed = False
        if cfg.trend_veto_zscore:
            lvl_train = level.reindex(train_feat.index)
            if len(lvl_train.dropna()) > cfg.trend_veto_ema_windows[2]:
                tf = _trend_regime_flag(
                    lvl_train,
                    ema_windows=cfg.trend_veto_ema_windows,
                    mom_sigma_mult=cfg.trend_veto_mom_sigma,
                )
                trend_confirmed = bool(tf.iloc[-1]) if len(tf) > 0 else False

        # ── Fix 1: Multi-horizon ensemble ────────────────────────────────────
        # Train one IC-weighted model per horizon; blend predictions by mean
        # |IC| of the selected features — longer horizons win during trends.
        preds_list:    List[pd.Series] = []
        weights_list:  List[float]     = []
        best_selected: List[str]       = []

        for H in horizons:
            # Align training forward returns to the training feature window
            train_fwd_H = all_fwd_by_H[H].reindex(train_feat.index)
            common_H    = train_fwd_H.dropna().index
            if len(common_H) < cfg.min_observations:
                continue

            tf_H = train_feat.loc[common_H]
            fr_H = train_fwd_H.loc[common_H]

            # Fix 3: IC metrics with EWMA weighting
            metrics_H = _compute_ic_metrics(
                tf_H, fr_H, cfg.min_observations,
                ewma_halflife=cfg.ewma_obs_halflife,
            )
            if metrics_H.empty:
                continue

            # Fix 2: Zero out mean-reversion features when trend confirmed
            if trend_confirmed:
                veto = [f for f in metrics_H.index
                        if any(k in f for k in ('_ZScore', '_PctRank', '_ValueMom'))]
                if veto:
                    metrics_H.loc[veto, 'IC']             = 0.0
                    metrics_H.loc[veto, 'IC_abs']         = 0.0
                    metrics_H.loc[veto, 'is_significant'] = False

            # Feature selection
            selected_H = selector.select_factors(metrics_H, tf_H)
            if not selected_H:
                selected_H = metrics_H.nlargest(min(3, len(metrics_H)), 'IC_abs').index.tolist()
            if not selected_H:
                continue

            # Train model for this horizon
            trained_H = _train_ic_model(tf_H, fr_H, selected_H)
            if 'error' in trained_H:
                continue

            # Persist artifact keyed to the first (shortest) horizon
            if H == horizons[0] and models_by_month is not None:
                month_key = train_end.strftime('%Y%m%d')
                if month_key not in models_by_month:
                    models_by_month[month_key] = {}
                models_by_month[month_key][factor_code] = {
                    'trained_model': {
                        'coefficients': trained_H['coefficients'],
                        'scaling_factor': trained_H['scaling_factor'],
                        'scaler': trained_H['scaler'],
                        'feature_names': trained_H['feature_names'],
                    },
                    'selected_factors': selected_H,
                }

            preds_H = _predict_ic_model(test_feat, trained_H)
            if preds_H.empty:
                continue

            mean_ic_H = float(
                metrics_H.loc[[f for f in selected_H if f in metrics_H.index], 'IC_abs'].mean()
            ) if selected_H else 0.01
            preds_list.append(preds_H)
            weights_list.append(max(mean_ic_H if not np.isnan(mean_ic_H) else 0.0, 0.01))
            if len(selected_H) > len(best_selected):
                best_selected = selected_H

        if not preds_list:
            continue

        # IC-weighted blend of horizon predictions
        total_w = sum(weights_list)
        preds   = sum(p * (w / total_w) for p, w in zip(preds_list, weights_list))

        pred_df = pd.DataFrame({
            'predicted_return': preds,
            'n_features':       len(best_selected),
        })
        all_predictions.append(pred_df)

    if not all_predictions:
        print(f"  [{factor_code}] No predictions generated")
        return pd.DataFrame()

    # Concatenate predictions
    pred_full = pd.concat(all_predictions).sort_index()
    # Remove duplicate indices (overlapping windows)
    pred_full = pred_full[~pred_full.index.duplicated(keep='first')]

    # Build result DataFrame
    level = factor_levels[factor_code].dropna()
    if not isinstance(level.index, pd.DatetimeIndex):
        level.index = pd.to_datetime(level.index)

    result = pd.DataFrame({'level': level})
    result = result.loc[result.index.intersection(pred_full.index)]

    result['predicted_return'] = pred_full['predicted_return']
    result['n_features'] = pred_full['n_features']

    # Actual daily returns (for PnL, always use 1-day returns)
    result['returns'] = daily_returns.reindex(result.index)

    # IRDL (rate level) factors represent core long-only duration exposure.
    _long_only = factor_code.split('.')[0] == 'IRDL'
    pos = build_position_series(result['predicted_return'], result['returns'], cfg,
                                long_only=_long_only)

    # Fix 4: Position floor during confirmed bond-bull trend (IRDL only).
    # When both short-term (60d) and medium-term (cfg.long_floor_confirm_window)
    # yield momentum are negative — i.e. yields are falling on both horizons —
    # the model must hold at least cfg.long_floor units of duration exposure.
    # This prevents a full exit during a running bull market caused by noisy
    # daily predictions or residual mean-reversion signal.
    if _long_only and cfg.long_floor > 0:
        lvl_chg_short  = factor_levels[factor_code].diff(60).reindex(result.index)
        lvl_chg_medium = factor_levels[factor_code].diff(
            cfg.long_floor_confirm_window
        ).reindex(result.index)
        # For yield factors: falling level = bond rally → enforce the floor
        floor_mask = (lvl_chg_short < 0) & (lvl_chg_medium < 0)
        pos.loc[floor_mask, 'position'] = (
            pos.loc[floor_mask, 'position'].clip(lower=cfg.long_floor)
        )

    result['signal'] = pos['signal']
    result['position'] = bucket_position(pos['position'], long_only=_long_only)
    result['turnover'] = pos['turnover']

    # Gross PnL, then net of transaction costs (doc §5.1, DV01-aware)
    # Use continuous position for returns calculation before bucketing
    result['strategy_returns_gross'] = pos['position'].shift(1) * result['returns']
    cost_per_unit = factor_tx_cost_per_unit(factor_code, cfg)
    tx_cost = result['turnover'].abs() * cost_per_unit
    result['strategy_returns'] = result['strategy_returns_gross'] - tx_cost
    result['cumulative_returns'] = (1 + result['strategy_returns'].fillna(0)).cumprod()

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  5. Batch runner (mirrors run_factor_backtest in factor_backtest.py)
# ═══════════════════════════════════════════════════════════════════════════

def run_factor_model_batch(
    factors: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    input_dir: Union[str, Path] = DIR_INPUT,
    config: Optional[FactorModelConfig] = None,
    save: bool = True,
    save_latest_only: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], Optional[Dict]]:
    """Run factor-model backtest across multiple risk factors.

    Saves results to ``factor-backtest.pkl`` under the key ``'FactorModel'``.
    When ``save_latest_only=True`` only the most-recent monthly model is
    persisted (useful for the Factor-tab daily train action).

    Returns
    -------
    (results, latest_artifact)
        results         : {factor_code: DataFrame}
        latest_artifact : the artifact dict saved/updated for the latest month,
                          or None when save=False or nothing was produced.
    """
    factor_levels = load_factor_rates(input_dir)
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    results: Dict[str, pd.DataFrame] = {}
    models_by_month: Dict[str, Dict] = {}  # month_key -> {factor: model_artifact}

    for factor in factors:
        if factor not in factor_levels.columns:
            print(f"Skipping {factor}: not in factor-rates")
            continue

        series = factor_levels[factor].dropna()
        if len(series) < 120:
            print(f"Skipping {factor}: insufficient data ({len(series)} days)")
            continue

        try:
            df = run_factor_model_backtest(
                factor_code=factor,
                factor_levels=factor_levels,
                start_date=start_date,
                end_date=end_date,
                input_dir=input_dir,
                config=config,
                models_by_month=models_by_month,
            )
            if not df.empty:
                results[factor] = df
        except Exception as e:
            print(f"Error backtesting {factor}: {e}")
            import traceback
            traceback.print_exc()

    if save and results:
        # ── Accumulative save to factor-backtest.pkl ──────────────────────
        pkl_path = os.path.join(str(input_dir), 'factor-backtest.pkl')
        existing: Dict = {}
        if os.path.exists(pkl_path):
            try:
                existing = pd.read_pickle(pkl_path)
            except Exception:
                existing = {}

        # Merge new factor results into existing (accumulative, not replace)
        if 'FactorModel' not in existing:
            existing['FactorModel'] = {}

        for factor_code, new_df in results.items():
            prev_df = existing['FactorModel'].get(factor_code)
            if prev_df is not None and not prev_df.empty:
                # Concat and keep latest rows for overlapping dates
                merged = pd.concat([prev_df, new_df])
                merged = merged[~merged.index.duplicated(keep='last')]
                existing['FactorModel'][factor_code] = merged.sort_index()
            else:
                existing['FactorModel'][factor_code] = new_df

        pd.to_pickle(existing, pkl_path)
        print(f"Saved factor-backtest.pkl  (strategy=FactorModel, "
              f"{len(existing['FactorModel'])} total factors, "
              f"{len(results)} updated)")

        # ── Save monthly trained-model .joblib files ──────────────────────
        cfg = config or FactorModelConfig()
        models_dir = os.path.join(str(input_dir), 'models')
        os.makedirs(models_dir, exist_ok=True)

        # When save_latest_only=True we only persist the most-recent month,
        # keeping the models/ folder lean for daily-signal use.
        if save_latest_only and models_by_month:
            latest_key = max(models_by_month)
            months_to_save = {latest_key: models_by_month[latest_key]}
        else:
            months_to_save = models_by_month

        n_saved = 0
        last_saved_artifact: Optional[Dict] = None
        for month_key, factor_models in months_to_save.items():
            joblib_path = os.path.join(
                models_dir, f'factor_model_{month_key}.joblib'
            )
            # Incremental merge: load existing file, overlay new factors only.
            # Factors not in this run are preserved unchanged.
            existing_artifact: Dict = {}
            n_retained = 0
            if os.path.exists(joblib_path):
                try:
                    existing_artifact = joblib.load(joblib_path)
                    n_retained = len([k for k in existing_artifact
                                      if k != 'metadata' and k not in factor_models])
                except Exception:
                    existing_artifact = {}
            existing_artifact.update(factor_models)  # new factors override by key
            print(f"  joblib merge: {len(factor_models)} updated, "
                  f"{n_retained} retained from previous → "
                  f"{len([k for k in existing_artifact if k != 'metadata'])} total")
            existing_artifact['metadata'] = {
                'train_end_date': month_key,
                'created_date': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                'config': {
                    'train_months': cfg.train_months,
                    'ic_threshold': cfg.ic_threshold,
                    'top_n': cfg.top_n,
                    'target_horizon': cfg.target_horizon,
                    'signal_smooth_days': cfg.signal_smooth_days,
                    'weighting_method': cfg.weighting_method,
                },
                'factors': [k for k in existing_artifact if k != 'metadata'],
            }
            joblib.dump(existing_artifact, joblib_path)
            last_saved_artifact = existing_artifact
            n_saved += 1

        label = 'latest-only' if save_latest_only else 'all'
        print(f"Saved {n_saved} monthly factor_model_*.joblib files ({label}) "
              f"({len(months_to_save)} months, factors per latest: "
              f"{len(months_to_save.get(max(months_to_save) if months_to_save else '', {}))}")

        return results, last_saved_artifact

    return results, None


# ═══════════════════════════════════════════════════════════════════════════
#  6. Prediction from saved model (for PORTFOLIO subtab integration)
# ═══════════════════════════════════════════════════════════════════════════

def load_latest_factor_model(
    models_dir: Union[str, Path] = DIR_MODELS,
) -> Tuple[Optional[Dict], Optional[str]]:
    """Load the most recent ``factor_model_*.joblib`` from ``input/models/``.

    Returns (artifact_dict, month_key) or (None, None) if no files found.
    """
    pattern = os.path.join(str(models_dir), 'factor_model_*.joblib')
    files = sorted(glob.glob(pattern))
    if not files:
        return None, None
    latest = files[-1]
    month_key = os.path.basename(latest).replace('factor_model_', '').replace('.joblib', '')
    return joblib.load(latest), month_key


def predict_factor_signals(
    input_dir: Union[str, Path] = DIR_INPUT,
    models_dir: Union[str, Path] = DIR_MODELS,
) -> Dict[str, pd.Series]:
    """Generate live risk-factor signal series from the latest saved model.

    For each risk factor in the model, builds features from current data
    and applies the trained IC-weighted model to produce a predicted-return
    time series.  The PORTFOLIO subtab can feed these into
    ``compute_signal_snapshot()`` to obtain scalars for risk budgets.

    Returns
    -------
    dict  {risk_factor: pd.Series of predicted returns}
    """
    artifact, month_key = load_latest_factor_model(models_dir)
    if artifact is None:
        return {}

    factor_levels = load_factor_rates(input_dir)
    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    signals: Dict[str, pd.Series] = {}

    for factor_code, entry in artifact.items():
        if factor_code == 'metadata':
            continue
        trained_model = entry.get('trained_model')
        if not trained_model:
            continue

        try:
            features = build_features(factor_code, factor_levels, input_dir)
            features = features.ffill().fillna(0)
            preds = _predict_ic_model(features, trained_model)
            if not preds.empty:
                signals[factor_code] = preds
        except Exception as e:
            print(f"Warning: prediction failed for {factor_code}: {e}")
            continue

    return signals
