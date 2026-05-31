"""Alpha scoring engine: trend metrics, regression enrichment, and unified score.

Provides:
- _stationary_yes_mask
- _compute_trend_metrics
- _enrich_candidates_with_regression
- _rank_score  (deprecated, kept for backward compatibility)
- _add_unified_score_preview
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from curves.calibration.regime import SpreadRegimeClassifier
from curves.calibration.trend import compute_trend_signal
from curves.refreshers.alpha_snapshot import (
    _append_snapshot_spread_to_series,
    _HORIZON_DAYS,
    _REG_LOOKBACK_DAYS,
    _RISK_VOL_WINDOW,
    _CARRY_BASIS_DAYS,
)


def _stationary_yes_mask(s: pd.Series) -> pd.Series:
	"""Case-insensitive YES check; non-strings become False."""
	return s.astype(str).str.upper().eq("YES")


def _compute_trend_metrics(
	s: pd.Series,
	*,
	reg_lookback: int = _REG_LOOKBACK_DAYS,
	vol_window: int = _RISK_VOL_WINDOW,
) -> Tuple[float, float, float, float]:
	"""Compute (reg_slope_per_day, risk_vol, reg_mean, reg_vol_resid) from a historical spread series.

	reg_slope_per_day: OLS linear-regression slope on spread levels (series units / day).
	    Positive = spread trending upward over the lookback window.
	risk_vol: rolling std of daily first-differences over the last vol_window obs.
	    Used as the risk denominator in the expected-return score.
	reg_mean: regression-fitted value at the last observation (trendline level today).
	reg_vol_resid: std of regression residuals; used as the z-score denominator so that
	    Zscore = (spread − reg_mean) / reg_vol_resid.
	Returns (nan, nan, nan, nan) when series has fewer than 5 non-null observations.
	"""
	s_clean = pd.to_numeric(s, errors="coerce").dropna()
	n_all = len(s_clean)
	if n_all < 5:
		return np.nan, np.nan, np.nan, np.nan

	# OLS on the most recent reg_lookback observations: y = a + b*x
	s_reg = s_clean.iloc[-min(int(reg_lookback), n_all):]
	n = len(s_reg)
	y = s_reg.to_numpy(dtype=float)
	x = np.arange(n, dtype=float)
	x_mean = x.mean()
	y_mean = y.mean()
	xx = float(np.dot(x - x_mean, x - x_mean))
	if xx <= 0.0:
		return np.nan, np.nan, np.nan, np.nan
	b = float(np.dot(x - x_mean, y - y_mean)) / xx
	a = y_mean - b * x_mean
	y_hat = a + b * x
	residuals = y - y_hat
	reg_slope_per_day = b
	reg_mean = float(y_hat[-1])  # fitted trendline level at last observation
	reg_vol_resid = float(residuals.std(ddof=1)) if n >= 5 else np.nan

	# 3-month rolling vol of first differences for risk normalisation
	daily_chg = s_clean.diff().dropna()
	w = min(int(vol_window), len(daily_chg))
	risk_vol = float(daily_chg.iloc[-w:].std(ddof=1)) if w >= 5 else np.nan
	return reg_slope_per_day, risk_vol, reg_mean, reg_vol_resid


def _enrich_candidates_with_regression(
	df: pd.DataFrame,
	series_map: Dict[str, pd.Series],
) -> pd.DataFrame:
	"""Add reg_slope_per_day, risk_vol_63d, reg_mean, reg_vol_resid columns.

	Called before _add_unified_score_preview so that the scorer can use the
	regression slope as the directional signal and regression residual vol for
	z-score computation and risk normalisation.
	"""
	if df.empty or "ID" not in df.columns or "spread_type" not in df.columns:
		out = df.copy()
		out["reg_slope_per_day"] = np.nan
		out["risk_vol_63d"] = np.nan
		out["reg_mean"] = np.nan
		out["reg_vol_resid"] = np.nan
		out["regime"] = "unknown"
		out["regime_confidence"] = np.nan
		out["efficiency_ratio"] = np.nan
		out["hurst"] = np.nan
		out["trend_state"] = 0.0
		out["trend_momentum"] = np.nan
		return out
	out = df.copy()
	reg_slopes: list[float] = []
	risk_vols: list[float] = []
	reg_means: list[float] = []
	reg_vols_resid: list[float] = []
	regimes: list[str] = []
	regime_confs: list[float] = []
	eff_ratios: list[float] = []
	hursts: list[float] = []
	trend_states: list[float] = []
	trend_moms: list[float] = []
	regime_clf = SpreadRegimeClassifier()
	# Pre-extract row data once to avoid per-row pandas Series construction.
	keys = (out["spread_type"].astype(str) + "|" + out["ID"].astype(str)).to_numpy()
	spreads = (
		out["spread"].to_numpy()
		if "spread" in out.columns
		else np.full(len(out), np.nan)
	)
	for i in range(len(out)):
		key = keys[i]
		s = series_map.get(key)
		if isinstance(s, pd.Series) and len(s.dropna()) >= 10:
			spread_now = spreads[i]
			s_enriched = _append_snapshot_spread_to_series(s, spread_now)
			slope, rvol, rmean, rvolresid = _compute_trend_metrics(s_enriched)
			# ── Regime classification ──
			try:
				reg_result = regime_clf.classify(s_enriched)
				regimes.append(reg_result.get("regime", "unknown"))
				regime_confs.append(reg_result.get("regime_score", np.nan))
				eff_ratios.append(reg_result.get("efficiency_ratio", np.nan))
				hursts.append(reg_result.get("hurst", np.nan))
			except Exception:
				regimes.append("unknown")
				regime_confs.append(np.nan)
				eff_ratios.append(np.nan)
				hursts.append(np.nan)
			# ── Trend signal ──
			try:
				ts = compute_trend_signal(s_enriched)
				trend_states.append(ts.get("state", 0.0))
				trend_moms.append(ts.get("momentum_20d", np.nan))
			except Exception:
				trend_states.append(0.0)
				trend_moms.append(np.nan)
		else:
			slope, rvol, rmean, rvolresid = np.nan, np.nan, np.nan, np.nan
			regimes.append("unknown")
			regime_confs.append(np.nan)
			eff_ratios.append(np.nan)
			hursts.append(np.nan)
			trend_states.append(0.0)
			trend_moms.append(np.nan)
		reg_slopes.append(slope)
		risk_vols.append(rvol)
		reg_means.append(rmean)
		reg_vols_resid.append(rvolresid)
	out["reg_slope_per_day"] = reg_slopes
	out["risk_vol_63d"] = risk_vols
	out["reg_mean"] = reg_means
	out["reg_vol_resid"] = reg_vols_resid
	out["regime"] = regimes
	out["regime_confidence"] = regime_confs
	out["efficiency_ratio"] = eff_ratios
	out["hurst"] = hursts
	out["trend_state"] = trend_states
	out["trend_momentum"] = trend_moms
	return out


def _rank_score(df: pd.DataFrame, style: str) -> pd.Series:
	"""Deprecated: use unified edge/risk scoring.

	Kept for backward compatibility if other modules import it.
	"""
	# Fall back to previous behavior.
	z_raw = df["Zscore"] if "Zscore" in df.columns else pd.Series(index=df.index, dtype=float)
	z = pd.to_numeric(z_raw, errors="coerce")
	abs_z = z.abs()
	if style.lower() in {"carry", "trend", "trendfollowing"}:
		cr_raw = df["carry_roll"] if "carry_roll" in df.columns else pd.Series(index=df.index, dtype=float)
		vol_raw = df["vol"] if "vol" in df.columns else pd.Series(index=df.index, dtype=float)
		cr = pd.to_numeric(cr_raw, errors="coerce")
		vol = pd.to_numeric(vol_raw, errors="coerce")
		with pd.option_context("mode.use_inf_as_na", True):
			carry_risk = cr.abs() / vol.replace(0, pd.NA)
		if carry_risk.notna().any():
			return carry_risk.fillna(-1e9)
	return abs_z.fillna(-1e9)


def _add_unified_score_preview(
	df: pd.DataFrame,
	*,
	horizon_days: int = _HORIZON_DAYS,
	carry_basis_days: float = _CARRY_BASIS_DAYS,
) -> pd.DataFrame:
	"""Unified candidate score for spread trades in return space.

	Spread = YTM_A − YTM_B.  "BUY the spread" means buy bond A, sell bond B.
	Since bond prices move INVERSELY to yields, BUY profits when spread FALLS.

	The raw spread signal and raw risk volatility are both in yield space.
	To make the score dimensionally consistent, only the mark-to-market term
	from spread changes is duration-scaled.  Running carry is kept as a return
	on financed notional; roll is used in whatever return units the source
	already reports.  Risk is converted to return-vol with the same duration.

	  score = |carry_H + roll_H − D_eff × E[Δs_H]| / (D_eff × σ(Δs))

	── Expected spread change (unified for MR and Trend/Carry) ────────────────
	  E[Δs_H] = slope × H + (reg_mean − spread)

	  • slope × H        — linear trend drift extrapolated H days forward
	  • (reg_mean−spread) — today's deviation from the regression trendline,
	                        expected to revert toward zero

	  For MeanReversion candidates the regression slope ≈ 0, so the formula
	  collapses to full reversion-to-trendline.  For Trend/Carry candidates
	  the slope term dominates.  No separate MR vs TC branches needed.

	── Expected P&L for the BUY side (return space) ──────────────────────────
	  P&L_BUY = carry_H + roll_H + D_eff × (−E[Δs_H])
	  where:
	    carry_H = carry_3m_bp / 100 × (H / carry_basis_days)     [return %]
	    roll_H  = roll_3m_bp  / 100 × (H / carry_basis_days)     [return %]
	    D_eff × (−E[Δs_H])                                      [return %]

	  BondCurve carry is running carry (yield-like return, no duration scaling).
	  BondCurve roll and IRS carry/roll are already return terms in the source.

	── Direction & score ──────────────────────────────────────────────────────
	  direction = BUY  if P&L_BUY > 0     (spread expected to fall net of carry)
	            = SELL if P&L_BUY < 0     (spread expected to rise, short is better)

	  score = |P&L_BUY| / (D_eff × risk_spd)   ≥ 0
	         (dimensionless return / return-vol ratio; direction encodes side)

	── Z-score ────────────────────────────────────────────────────────────────
	  Zscore = (spread − reg_mean) / reg_vol_resid  when regression available
	         = Zscore from snapshot                  otherwise
	  Positive z → spread above trendline.  For MR: positive z → BUY (expect fall).
	"""
	if df is None:
		return df
	if df.empty:
		out = df.copy()
		out["score"] = pd.Series(dtype=float)
		if "direction" not in out.columns:
			out["direction"] = pd.Series(dtype=str)
		return out

	out = df.copy()
	H = float(max(1, int(horizon_days)))
	carry_basis_series = pd.to_numeric(
		out["carry_basis_days"] if "carry_basis_days" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	cd_default = float(carry_basis_days) if carry_basis_days and np.isfinite(float(carry_basis_days)) and float(carry_basis_days) > 0 else 90.0
	cd = carry_basis_series.where(carry_basis_series.gt(0) & carry_basis_series.notna(), cd_default)

	spread = pd.to_numeric(
		out["spread"] if "spread" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	mean_ = pd.to_numeric(
		out["mean"] if "mean" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	carry_roll = pd.to_numeric(
		out["carry_roll"] if "carry_roll" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	carry_bp = pd.to_numeric(
		out["carry_bp"]
		if "carry_bp" in out.columns
		else out["carry_3m_bp"] if "carry_3m_bp" in out.columns else out.get("Carry(3m,bp)", pd.Series(np.nan, index=out.index)),
		errors="coerce",
	)
	roll_bp = pd.to_numeric(
		out["roll_bp"]
		if "roll_bp" in out.columns
		else out["roll_3m_bp"] if "roll_3m_bp" in out.columns else out.get("Roll(3m,bp)", pd.Series(np.nan, index=out.index)),
		errors="coerce",
	)
	vol = pd.to_numeric(
		out["vol"] if "vol" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	).abs()
	reg_slope = pd.to_numeric(
		out["reg_slope_per_day"] if "reg_slope_per_day" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	reg_mean_col = pd.to_numeric(
		out["reg_mean"] if "reg_mean" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	reg_vol_resid = pd.to_numeric(
		out["reg_vol_resid"] if "reg_vol_resid" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	).abs()
	risk_vol_series = pd.to_numeric(
		out["risk_vol_63d"] if "risk_vol_63d" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	).abs()
	trade_duration = pd.to_numeric(
		out["Duration"] if "Duration" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	).abs()

	# ── Effective duration: contract duration when available, else TTM proxy ─────
	ttm = pd.to_numeric(
		out["ttm"] if "ttm" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	).abs()
	duration_eff = trade_duration.where(trade_duration.gt(0) & trade_duration.notna(), ttm)
	duration_eff = duration_eff.fillna(1.0).clip(lower=0.25)
	out["ttm_used"] = duration_eff

	# ── Spread-vol risk converted to return-vol via duration ───────────────────
	risk_spd = risk_vol_series.where(risk_vol_series.gt(0) & risk_vol_series.notna(), vol)
	risk_spd = risk_spd.replace(0, np.nan)
	fallback_risk = float(risk_spd.median(skipna=True)) if not risk_spd.dropna().empty else 1.0
	if not np.isfinite(fallback_risk) or fallback_risk <= 0:
		fallback_risk = 1.0
	risk_spd = risk_spd.fillna(fallback_risk)
	risk_return = (duration_eff * risk_spd).replace(0, np.nan)
	out["risk_spd_yield"] = risk_spd
	out["risk"] = risk_return

	# ── Carry and roll over horizon, kept as return terms ─────────────────────
	carry_bp = carry_bp.where(carry_bp.notna(), carry_roll.where(roll_bp.isna(), np.nan))
	roll_bp = roll_bp.fillna(0.0)
	carry_H = (carry_bp / 100.0) * (H / cd)
	roll_H = (roll_bp / 100.0) * (H / cd)
	out["carry_H"] = carry_H
	out["roll_H"] = roll_H

	# ── Z-score: regression-based (spread − reg_mean) / reg_vol_resid ──────────
	z_snap = pd.to_numeric(
		out["Zscore"] if "Zscore" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	reg_z = (spread - reg_mean_col) / reg_vol_resid.replace(0, np.nan)
	out["snapshot_zscore"] = z_snap
	out["reg_zscore"] = reg_z
	out["Zscore"] = z_snap.where(z_snap.notna(), reg_z)

	# ── Unified expected spread change E[Δs_H] ─────────────────────────────────
	trendline_gap = (reg_mean_col - spread)
	trendline_gap_used = trendline_gap.where(
		reg_mean_col.notna(), (mean_ - spread)
	).fillna(0.0)
	e_spread = reg_slope.fillna(0.0) * H + trendline_gap_used

	# ── Expected P&L for canonical BUY position — return space ────────────────
	mtm_buy = duration_eff * (-e_spread)
	out["mtm_H"] = mtm_buy
	pnl_buy = mtm_buy + carry_H.fillna(0.0) + roll_H.fillna(0.0)

	# ── Direction: sign of P&L_BUY ─────────────────────────────────────────────
	direction = pd.Series("SELL", index=out.index, dtype=str)
	direction.loc[pnl_buy.gt(0)] = "BUY"
	out["direction"] = direction
	dir_sign = pd.Series(-1.0, index=out.index, dtype=float)
	dir_sign.loc[direction.eq("BUY")] = 1.0
	out["dir_sign_score"] = dir_sign

	# ── Score: return / return-vol — dimensionless ratio ──────────────────────
	expected_return_H = dir_sign * pnl_buy
	out["expected_return_H"] = expected_return_H
	score = (expected_return_H / risk_return).replace([np.inf, -np.inf], np.nan).fillna(0.0)

	# ── Regime-conditional score adjustment ────────────────────────────────────
	regime_col = out["regime"] if "regime" in out.columns else pd.Series("unknown", index=out.index)
	trend_st = pd.to_numeric(
		out["trend_state"] if "trend_state" in out.columns else pd.Series(0.0, index=out.index),
		errors="coerce",
	).fillna(0.0)

	is_trending = regime_col.eq("trending")
	is_uncertain = regime_col.eq("uncertain")
	trend_agrees = (trend_st * dir_sign) < 0
	trend_boost = pd.Series(1.0, index=out.index)
	trend_boost.loc[is_trending & trend_agrees] = 1.3
	trend_boost.loc[is_trending & ~trend_agrees & trend_st.ne(0)] = 0.6
	trend_boost.loc[is_uncertain] = 0.5

	score = score * trend_boost
	out["regime_boost"] = trend_boost
	out["score"] = score
	return out
