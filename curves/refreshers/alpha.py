"""Alpha generator: normalize spread signals for UI scanning.

This module builds a single consistent snapshot for candidate scanning:

- BondCurve (mean-reverting): z-score + stationarity from *-spdsrt.pkl
  - zscore: tbond_spdrt['BondCurve']['Zscore'] (and CBond equivalent)
  - stationary: tbond_spdrt['BondCurve']['stationary']

- BondSwap (trend/carry):
  - stationarity from *-spdsrt.pkl (BondSwap)
  - carry+roll: stored in *BondSwap* history pickle as tbondswap['BondCarry']

- IRS swap spreads (mixed):
  - zscore + stationarity from irs_spdrt['spreads']
  - carry+roll: Carry(3m,bp) + Roll(3m,bp)

The output is a dict of DataFrames saved to DIR_INPUT/Alpha-spreadsrt.pkl.
Other modules (e.g. web UI) can import and call `get_alpha_spread_table()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Iterable, Tuple

import numpy as np
import pandas as pd

import sys

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))


from curves.utils.file import updatePKL
from settings.paths import DIR_INPUT


ALPHA_SNAPSHOT_FILENAME = "Alpha-spreadsrt.pkl"
ALPHA_CANDIDATES_FILENAME = "Alpha-candidates.pkl"

# ──────────────── Candidate scoring parameters ────────────────
_HORIZON_DAYS: int = 30              # 1-month expected-return horizon (calendar-day approximation)
_REG_LOOKBACK_DAYS: int = 30         # regression window for slope & z-score (~1 month of trading days)
_RISK_VOL_WINDOW: int = 90           # 3-month risk normalisation window (calendar-day approximation)
_CARRY_BASIS_DAYS: float = 90.0      # carry_roll is stored as a ~3-month quantity


@dataclass(frozen=True)
class AlphaSnapshotPaths:
	dir_input: Path

	@property
	def out_snapshot(self) -> Path:
		return self.dir_input / ALPHA_SNAPSHOT_FILENAME

	@property
	def out_candidates(self) -> Path:
		return self.dir_input / ALPHA_CANDIDATES_FILENAME

	@property
	def tbond_spds(self) -> Path:
		return self.dir_input / "TBond-spds.pkl"

	@property
	def cbond_spds(self) -> Path:
		return self.dir_input / "CBond-spds.pkl"

	@property
	def irs_pxspds(self) -> Path:
		return self.dir_input / "IRS-pxspds.pkl"

	@property
	def tbond_spdsrt(self) -> Path:
		return self.dir_input / "TBond-spdsrt.pkl"

	@property
	def cbond_spdsrt(self) -> Path:
		return self.dir_input / "CBond-spdsrt.pkl"

	@property
	def irs_spdsrt(self) -> Path:
		return self.dir_input / "IRS-spdsrt.pkl"
	
	@property
	def cnbd_data(self) -> Path:
		return self.dir_input / "database-px.pkl"


def _read_pickle(path: Path) -> object:
	if not path.exists():
		raise FileNotFoundError(str(path))
	return pd.read_pickle(path)


def _last_values(df: pd.DataFrame) -> pd.Series:
	"""Return last available value per column, robust to trailing NaNs."""
	if df.empty:
		return pd.Series(dtype=float)
	df2 = df.sort_index().copy()
	# ffill over time then take last row
	return df2.ffill().iloc[-1]


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
	out = df.copy()
	out.index.name = "ID"
	return out


def _ensure_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
	out = df.copy()
	for c in cols:
		if c in out.columns:
			out[c] = pd.to_numeric(out[c], errors="coerce")
	return out


def build_alpha_spreads_snapshot(dir_input: str | Path = DIR_INPUT) -> Dict[str, pd.DataFrame]:
	"""Build normalized snapshot tables keyed by spread type.

	Keys returned (when available):
	- TBondCurve, CBondCurve
	- TBondSwap, CBondSwap
	- SwapSpread
	"""
	paths = AlphaSnapshotPaths(Path(dir_input))

	tbond_spd = _read_pickle(paths.tbond_spds)
	cbond_spd = _read_pickle(paths.cbond_spds)
	irs_pxspd = _read_pickle(paths.irs_pxspds)
	tbond_spdrt = _read_pickle(paths.tbond_spdsrt)
	cbond_spdrt = _read_pickle(paths.cbond_spdsrt)
	irs_spdrt = _read_pickle(paths.irs_spdsrt)
	cnbd_data = _read_pickle(paths.cnbd_data)

	tenor_spd: dict[str, pd.Series] = {}
	# Only build if CNBD data looks like expected dict-of-DataFrames
	try:
		if isinstance(cnbd_data, dict) and "CGB" in cnbd_data and "CDB" in cnbd_data:
			tenor_spd["CGB-5s10s"] = cnbd_data["CGB"]["中债国债到期收益率:10年"] - cnbd_data["CGB"]["中债国债到期收益率:5年"]
			tenor_spd["CGB-10s30s"] = cnbd_data["CGB"]["中债国债到期收益率:30年"] - cnbd_data["CGB"]["中债国债到期收益率:10年"]
			tenor_spd["CDB-5s10s"] = cnbd_data["CDB"]["中债国开债到期收益率:10年"] - cnbd_data["CDB"]["中债国开债到期收益率:5年"]
			tenor_spd["CDB-10s30s"] = cnbd_data["CDB"]["中债国开债到期收益率:30年"] - cnbd_data["CDB"]["中债国开债到期收益率:10年"]
			tenor_spd["CDBCGB-5y"] = cnbd_data["CDB"]["中债国开债到期收益率:5年"] - cnbd_data["CGB"]["中债国债到期收益率:5年"]
			tenor_spd["CDBCGB-10y"] = cnbd_data["CDB"]["中债国开债到期收益率:10年"] - cnbd_data["CGB"]["中债国债到期收益率:10年"]
			tenor_spd["CDBCGB-30y"] = cnbd_data["CDB"]["中债国开债到期收益率:30年"] - cnbd_data["CGB"]["中债国债到期收益率:30年"]
	except Exception:
		tenor_spd = {}

	if not isinstance(tbond_spd, dict) or not isinstance(cbond_spd, dict):
		raise TypeError("Bond spread pickles are not dicts")
	if not isinstance(tbond_spdrt, dict) or not isinstance(cbond_spdrt, dict):
		raise TypeError("Bond realtime spread pickles are not dicts")
	if not isinstance(irs_spdrt, dict):
		raise TypeError("IRS realtime spread pickle is not a dict")

	out: Dict[str, pd.DataFrame] = {}

	# -----------------------
	# BondCurve (mean reversion)
	# -----------------------
	for prefix, spdrt in [("TBond", tbond_spdrt), ("CBond", cbond_spdrt)]:
		df_bc = spdrt.get("BondCurve")
		if isinstance(df_bc, pd.DataFrame) and not df_bc.empty:
			df_bc = _normalize_index(df_bc)
			df_bc = _ensure_numeric(df_bc, ["Zscore", "spread", "mean", "vol", "Carry(3m,bp)", "Roll(3m,bp)"])
			if "Carry(3m,bp)" in df_bc.columns and "Roll(3m,bp)" in df_bc.columns:
				df_bc["carry_roll"] = df_bc["Carry(3m,bp)"] + df_bc["Roll(3m,bp)"]
			df_bc["spread_type"] = f"{prefix}Curve"
			df_bc["category"] = "Bond-Curve"
			out[f"{prefix}Curve"] = df_bc

	# -----------------------
	# BondSwap (trend/carry)
	# -----------------------
	def _bondswap_with_carry(prefix: str, spd: dict, spdrt: dict) -> Optional[pd.DataFrame]:
		df_rt = spdrt.get("BondSwap")
		if not isinstance(df_rt, pd.DataFrame) or df_rt.empty:
			return None
		df_rt = _normalize_index(df_rt)
		df_rt = _ensure_numeric(df_rt, ["Zscore", "spread", "mean", "vol"])

		carry_hist = None
		bs = spd.get("BondSwap")
		if isinstance(bs, dict):
			carry_hist = bs.get("BondCarry")
		if isinstance(carry_hist, pd.DataFrame) and not carry_hist.empty:
			carry_latest = _last_values(carry_hist)
			df_rt["carry_roll"] = carry_latest.reindex(df_rt.index)

		df_rt["spread_type"] = f"{prefix}Swap"
		df_rt["category"] = "Bond-Swap"
		return df_rt

	df_tbs = _bondswap_with_carry("TBond", tbond_spd, tbond_spdrt)
	if df_tbs is not None:
		out["TBondSwap"] = df_tbs
	df_cbs = _bondswap_with_carry("CBond", cbond_spd, cbond_spdrt)
	if df_cbs is not None:
		out["CBondSwap"] = df_cbs

	# -----------------------
	# IRS swap spreads (mixed)
	# -----------------------
	df_irs = irs_spdrt.get("spreads")
	if isinstance(df_irs, pd.DataFrame) and not df_irs.empty:
		df_irs = _normalize_index(df_irs)
		# Exclude IDs ending with ".IR"
		df_irs = df_irs[~df_irs.index.astype(str).str.endswith(".IR")].copy()
		df_irs = _ensure_numeric(df_irs, ["Zscore", "spread", "mean", "vol", "Carry(3m,bp)", "Roll(3m,bp)"])
		if "Carry(3m,bp)" in df_irs.columns and "Roll(3m,bp)" in df_irs.columns:
			df_irs["carry_roll"] = df_irs["Carry(3m,bp)"] + df_irs["Roll(3m,bp)"]
		df_irs["spread_type"] = "SwapSpread"
		df_irs["category"] = "Swap-Spread"
		if not df_irs.empty:
			out["SwapSpread"] = df_irs

	# Keep reference to IRS historical structure if callers need it later
	if isinstance(irs_pxspd, dict) and "CarryRoll3m" in irs_pxspd and "SwapSpread" not in out:
		pass

	# -----------------------
	# Tenor spreads (curve slope / cross-curve)
	# -----------------------
	if tenor_spd:
		df_ts = pd.DataFrame(tenor_spd).sort_index()
		# Basic stats over recent window
		# lookback 252 trading days (~1 year)
		N = 252
		df_hist = df_ts.tail(N)
		latest = df_hist.ffill().iloc[-1]
		mu = df_hist.mean(skipna=True)
		sig = df_hist.std(skipna=True).replace(0, np.nan)
		z = (latest - mu) / sig

		df_tenor = pd.DataFrame(
			{
				"spread": latest,
				"mean": mu,
				"vol": sig,
				"Zscore": z,
				"halflife": np.nan,
				"stationary": "YES",
			}
		)
		df_tenor.index.name = "ID"
		df_tenor["spread_type"] = "TenorSpread"
		df_tenor["category"] = "Tenor-Spread"
		out["TenorSpread"] = df_tenor

	return out


def build_alpha_timeseries(dir_input: str | Path = DIR_INPUT) -> Dict[str, pd.DataFrame]:
	"""Extract historical time series for correlation analysis.
	
	Returns dict with keys like 'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'
	Each value is a DataFrame with time series columns (bonds/spreads) and datetime index.
	"""
	paths = AlphaSnapshotPaths(Path(dir_input))
	
	out: Dict[str, pd.DataFrame] = {}
	
	try:
		# TBond-spds.pkl structure: dict with 'BondCurve' and 'BondSwap' keys
		tbond_spd = _read_pickle(paths.tbond_spds)
		if isinstance(tbond_spd, dict):
			bc = tbond_spd.get("BondCurve", {})
			if isinstance(bc, dict):
				spread_ts = bc.get("Spread")
				if isinstance(spread_ts, pd.DataFrame):
					out["TBondCurve"] = spread_ts
			
			bs = tbond_spd.get("BondSwap", {})
			if isinstance(bs, dict):
				spread_ts = bs.get("Spread")
				if isinstance(spread_ts, pd.DataFrame):
					out["TBondSwap"] = spread_ts
	except Exception as e:
		print(f"Warning: Could not load TBond time series: {e}")
	
	try:
		# CBond-spds.pkl structure: dict with 'BondCurve' and 'BondSwap' keys
		cbond_spd = _read_pickle(paths.cbond_spds)
		if isinstance(cbond_spd, dict):
			bc = cbond_spd.get("BondCurve", {})
			if isinstance(bc, dict):
				spread_ts = bc.get("Spread")
				if isinstance(spread_ts, pd.DataFrame):
					out["CBondCurve"] = spread_ts
			
			bs = cbond_spd.get("BondSwap", {})
			if isinstance(bs, dict):
				spread_ts = bs.get("Spread")
				if isinstance(spread_ts, pd.DataFrame):
					out["CBondSwap"] = spread_ts
	except Exception as e:
		print(f"Warning: Could not load CBond time series: {e}")
	
	return out


def save_alpha_spreads_snapshot(
	dir_input: str | Path = DIR_INPUT,
	*,
	rewrite: bool = True,
) -> Path:
	"""Build and save snapshot to DIR_INPUT/Alpha-spreadsrt.pkl."""
	paths = AlphaSnapshotPaths(Path(dir_input))
	snapshot = build_alpha_spreads_snapshot(dir_input=paths.dir_input)
	
	# Add time series data under '_timeseries' key
	timeseries = build_alpha_timeseries(dir_input=paths.dir_input)
	if timeseries:
		snapshot["_timeseries"] = timeseries
	
	updatePKL(snapshot, str(paths.out_snapshot), rewrite=rewrite)
	return paths.out_snapshot


def load_alpha_spreads_snapshot(
	dir_input: str | Path = DIR_INPUT,
	*,
	refresh: bool = False,
) -> Dict[str, pd.DataFrame]:
	"""Load snapshot; optionally rebuild if missing/stale."""
	paths = AlphaSnapshotPaths(Path(dir_input))
	if not refresh and paths.out_snapshot.exists():
		obj = pd.read_pickle(paths.out_snapshot)
		if isinstance(obj, dict):
			return obj
	save_alpha_spreads_snapshot(dir_input=paths.dir_input, rewrite=True)
	obj = pd.read_pickle(paths.out_snapshot)
	return obj if isinstance(obj, dict) else {}


def get_alpha_spread_table(
	spread_type: str,
	dir_input: str | Path = DIR_INPUT,
	*,
	refresh: bool = False,
) -> Optional[pd.DataFrame]:
	"""Convenience accessor used by UI / other modules."""
	snap = load_alpha_spreads_snapshot(dir_input=dir_input, refresh=refresh)
	df = snap.get(spread_type)
	if isinstance(df, pd.DataFrame):
		return df
	return None


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
		return out
	out = df.copy()
	reg_slopes: list[float] = []
	risk_vols: list[float] = []
	reg_means: list[float] = []
	reg_vols_resid: list[float] = []
	for _, row in out.iterrows():
		key = f"{row['spread_type']}|{row['ID']}"
		s = series_map.get(key)
		if isinstance(s, pd.Series) and len(s.dropna()) >= 10:
			slope, rvol, rmean, rvolresid = _compute_trend_metrics(s)
		else:
			slope, rvol, rmean, rvolresid = np.nan, np.nan, np.nan, np.nan
		reg_slopes.append(slope)
		risk_vols.append(rvol)
		reg_means.append(rmean)
		reg_vols_resid.append(rvolresid)
	out["reg_slope_per_day"] = reg_slopes
	out["risk_vol_63d"] = risk_vols
	out["reg_mean"] = reg_means
	out["reg_vol_resid"] = reg_vols_resid
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
	"""Unified candidate score for YTM-spread trades.

	Spread = YTM_A − YTM_B.  "BUY the spread" means buy bond A, sell bond B.
	Since bond prices move INVERSELY to yields, BUY profits when spread FALLS.

	── Expected spread change (unified for MR and Trend/Carry) ────────────────
	  E[Δs_H] = slope × H + (reg_mean − spread)

	  • slope × H        — linear trend drift extrapolated H days forward
	  • (reg_mean−spread) — today's deviation from the regression trendline,
	                        expected to revert toward zero

	  For MeanReversion candidates the regression slope ≈ 0, so the formula
	  collapses to full reversion-to-trendline.  For Trend/Carry candidates
	  the slope term dominates.  No separate MR vs TC branches needed.

	── Expected P&L for the BUY side (canonical direction) ───────────────────
	  P&L_BUY = −TTM × E[Δs_H]  +  carry_H
	  where:
	    TTM       ≈ modified duration of the long leg (term-to-maturity proxy)
	    carry_H   = carry_roll(bp) / 100 × (H / carry_basis_days)
	              (carry already expressed as a P&L return, not a yield change)
	    −TTM × E[Δs_H]: when spread falls (E[Δs_H] < 0), long bond A gains
	                     price × TTM bp per bp of spread narrowing.

	  For SwapSpread/TenorSpread where TTM is unavailable, TTM defaults to 1.

	── Direction & score ──────────────────────────────────────────────────────
	  direction = BUY  if P&L_BUY > 0     (spread expected to fall net of carry)
	            = SELL if P&L_BUY < 0     (spread expected to rise, short is better)

	  score = dir_sign × P&L_BUY / (TTM × risk_vol_63d)   ≥ 0
	         (always positive; direction encodes which side to trade)

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
	cd = float(carry_basis_days) if carry_basis_days and np.isfinite(float(carry_basis_days)) and float(carry_basis_days) > 0 else 90.0

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

	# ── TTM: duration proxy for the long leg (fallback 1.0 for non-bond spreads) ──
	ttm = pd.to_numeric(
		out["ttm"] if "ttm" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	).abs()
	ttm = ttm.fillna(1.0).clip(lower=0.25)  # minimum 3-month floor; 1.0 for IRS/tenor
	out["ttm_used"] = ttm

	# ── Spread-vol risk (in spread units): prefer 3m rolling, fall back to snapshot vol ──
	risk_spd = risk_vol_series.where(risk_vol_series.gt(0) & risk_vol_series.notna(), vol)
	risk_spd = risk_spd.replace(0, np.nan)
	fallback_risk = float(risk_spd.median(skipna=True)) if not risk_spd.dropna().empty else 1.0
	if not np.isfinite(fallback_risk) or fallback_risk <= 0:
		fallback_risk = 1.0
	risk_spd = risk_spd.fillna(fallback_risk)
	out["risk"] = risk_spd

	# ── Carry: convert bp → % return, scaled to H-day horizon ─────────────────
	# carry_roll is already a P&L return (bp), not a yield spread change.
	carry_H = (carry_roll / 100.0) * (H / cd)
	out["carry_H"] = carry_H

	# ── Z-score: regression-based (spread − reg_mean) / reg_vol_resid ──────────
	# Positive z → spread above trendline.
	# Falls back to snapshot z when regression data are unavailable.
	z_snap = pd.to_numeric(
		out["Zscore"] if "Zscore" in out.columns else pd.Series(np.nan, index=out.index),
		errors="coerce",
	)
	reg_z = (spread - reg_mean_col) / reg_vol_resid.replace(0, np.nan)
	z = reg_z.where(reg_z.notna(), z_snap)
	out["Zscore"] = z

	# ── Unified expected spread change E[Δs_H] ─────────────────────────────────
	# E[Δs_H] = slope × H + (reg_mean − spread)
	# Fallback when regression unavailable: full reversion to OU mean (mean_ − spread).
	trendline_gap = (reg_mean_col - spread)          # positive when spread is BELOW trendline
	trendline_gap_used = trendline_gap.where(
		reg_mean_col.notna(), (mean_ - spread)        # fallback: OU mean reversion
	).fillna(0.0)
	e_spread = reg_slope.fillna(0.0) * H + trendline_gap_used   # in yield-spread units (%)

	# ── Expected P&L for canonical BUY position ────────────────────────────────
	# BUY profits when spread FALLS: P&L_BUY = −TTM × E[Δs_H] + carry_H
	# • −TTM × E[Δs_H]: converts expected yield-spread move to price-return via duration
	#   Negative E[Δs_H] (falling spread) → positive price return for long bond A ✓
	# • carry_H: carry/roll P&L for holding the BUY side
	pnl_buy = -ttm * e_spread + carry_H.fillna(0.0)

	# ── Direction: sign of P&L_BUY ─────────────────────────────────────────────
	# BUY  if pnl_buy > 0  (spread expected to fall, or carry dominates)
	# SELL if pnl_buy < 0  (spread expected to rise, better to short)
	direction = pd.Series("SELL", index=out.index, dtype=str)
	direction.loc[pnl_buy.gt(0)] = "BUY"
	out["direction"] = direction
	dir_sign = pd.Series(-1.0, index=out.index, dtype=float)
	dir_sign.loc[direction.eq("BUY")] = 1.0
	out["dir_sign_score"] = dir_sign

	# ── Score: expected return / risk (always ≥ 0, direction captured above) ────
	# Numerator:   dir_sign × pnl_buy = |pnl_buy|   (% return for the recommended side)
	# Denominator: TTM × risk_spd                    (% return vol, duration-scaled)
	risk_return = (ttm * risk_spd).replace(0, np.nan)
	expected_return_H = dir_sign * pnl_buy          # always ≥ 0
	out["expected_return_H"] = expected_return_H
	score = (expected_return_H / risk_return).replace([np.inf, -np.inf], np.nan).fillna(0.0)
	out["score"] = score
	return out


def load_historical_spread_series(
	spread_type: str,
	candidates: Iterable[str],
	*,
	dir_input: str | Path = DIR_INPUT,
	lookback_days: int = 252,
) -> Dict[str, pd.Series]:
	"""Load historical spread time series for a set of IDs.

	Returns mapping key -> Series, where key is f"{spread_type}|{ID}".
	"""
	paths = AlphaSnapshotPaths(Path(dir_input))
	candidates = list(candidates)
	if not candidates:
		return {}

	key_to_series: Dict[str, pd.Series] = {}

	if spread_type in {"TBondCurve", "TBondSwap"}:
		obj = _read_pickle(paths.tbond_spds)
		if not isinstance(obj, dict):
			return {}
		root = obj.get("BondCurve" if spread_type == "TBondCurve" else "BondSwap")
		if not isinstance(root, dict):
			return {}
		df = root.get("Spread")
		if not isinstance(df, pd.DataFrame) or df.empty:
			return {}
		df = df.sort_index().tail(int(lookback_days))
		for cid in candidates:
			if cid in df.columns:
				s = pd.to_numeric(df[cid], errors="coerce").dropna()
				if not s.empty:
					s.name = f"{spread_type}|{cid}"
					key_to_series[s.name] = s

	elif spread_type in {"CBondCurve", "CBondSwap"}:
		obj = _read_pickle(paths.cbond_spds)
		if not isinstance(obj, dict):
			return {}
		root = obj.get("BondCurve" if spread_type == "CBondCurve" else "BondSwap")
		if not isinstance(root, dict):
			return {}
		df = root.get("Spread")
		if not isinstance(df, pd.DataFrame) or df.empty:
			return {}
		df = df.sort_index().tail(int(lookback_days))
		for cid in candidates:
			if cid in df.columns:
				s = pd.to_numeric(df[cid], errors="coerce").dropna()
				if not s.empty:
					s.name = f"{spread_type}|{cid}"
					key_to_series[s.name] = s

	elif spread_type == "SwapSpread":
		obj = _read_pickle(paths.irs_pxspds)
		if not isinstance(obj, dict):
			return {} 
		df = obj.get("Spread")
		if not isinstance(df, pd.DataFrame) or df.empty:
			return {}
		# Exclude ".IR" columns to align with candidates
		df = df.loc[:, ~pd.Index(df.columns.astype(str)).str.endswith(".IR")].copy()
		df = df.sort_index().tail(int(lookback_days))

		for cid in candidates:
			if cid in df.columns:
				s = pd.to_numeric(df[cid], errors="coerce").dropna()
				if not s.empty:
					s.name = f"{spread_type}|{cid}"
					key_to_series[s.name] = s

	elif spread_type == "TenorSpread":
		obj = _read_pickle(paths.cnbd_data)
		if not isinstance(obj, dict):
			return {}
		try:
			tenor_ts = {
				"CGB-5s10s": obj["CGB"]["中债国债到期收益率:10年"] - obj["CGB"]["中债国债到期收益率:5年"],
				"CGB-10s30s": obj["CGB"]["中债国债到期收益率:30年"] - obj["CGB"]["中债国债到期收益率:10年"],
				"CDB-5s10s": obj["CDB"]["中债国开债到期收益率:10年"] - obj["CDB"]["中债国开债到期收益率:5年"],
				"CDB-10s30s": obj["CDB"]["中债国开债到期收益率:30年"] - obj["CDB"]["中债国开债到期收益率:10年"],
				"CDBCGB-5y": obj["CDB"]["中债国开债到期收益率:5年"] - obj["CGB"]["中债国债到期收益率:5年"],
				"CDBCGB-10y": obj["CDB"]["中债国开债到期收益率:10年"] - obj["CGB"]["中债国债到期收益率:10年"],
				"CDBCGB-30y": obj["CDB"]["中债国开债到期收益率:30年"] - obj["CGB"]["中债国债到期收益率:30年"],
			}
		except Exception:
			return {}

		df = pd.DataFrame(tenor_ts).sort_index().tail(int(lookback_days))
		for cid in candidates:
			if cid in df.columns:
				s = pd.to_numeric(df[cid], errors="coerce").dropna()
				if not s.empty:
					s.name = f"{spread_type}|{cid}"
					key_to_series[s.name] = s

	return key_to_series


def compute_candidate_correlation(
	series_map: Dict[str, pd.Series],
	*,
	min_obs: int = 40,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
	"""Compute correlation matrix of daily changes across series_map."""
	if len(series_map) < 2:
		return None, None

	df = pd.DataFrame(series_map).sort_index()
	# use differences for bp spreads
	df_chg = df.diff().dropna(how="all")
	if df_chg.shape[0] < min_obs:
		return None, None

	corr = df_chg.corr()
	return corr, df_chg


def select_low_corr_basket(
	candidates: pd.DataFrame,
	corr: pd.DataFrame,
	*,
	top_n: int = 10,
	max_abs_corr: float = 0.6,
) -> pd.DataFrame:
	"""Greedy selection: maximize score while keeping correlations low.

	Tie-breaks: higher score wins.
	"""
	if candidates.empty or corr is None or corr.empty:
		return candidates.head(0)

	# Build key column mapping to corr matrix columns
	work = candidates.copy()
	if "corr_key" not in work.columns:
		work["corr_key"] = work.apply(lambda r: f"{r['spread_type']}|{r['ID']}", axis=1)

	work = work[work["corr_key"].isin(corr.columns)].copy()
	if work.empty:
		return work

	work = work.sort_values(["score"], ascending=False).reset_index(drop=True)
	selected_keys: list[str] = []
	selected_rows: list[int] = []

	for i in range(int(work.shape[0])):
		row = work.iloc[i]
		key = str(row["corr_key"])
		if not selected_keys:
			selected_keys.append(key)
			selected_rows.append(i)
			if len(selected_keys) >= top_n:
				break
			continue

		# correlation constraint vs already selected
		try:
			arr = corr.loc[key, selected_keys].abs().to_numpy(dtype=float, copy=False)  # type: ignore[index]
			mx = float(np.nanmax(arr)) if arr.size else 1.0
		except Exception:
			mx = 1.0
		if mx <= float(max_abs_corr):
			selected_keys.append(key)
			selected_rows.append(i)
			if len(selected_keys) >= top_n:
				break

	# If we couldn't fill to top_n under the strict threshold, fill remaining by “least max corr”
	if len(selected_keys) < top_n:
		remaining = work.drop(index=selected_rows)
		while len(selected_keys) < top_n and not remaining.empty:
			best_pos = None
			best_tuple = None
			for pos in range(int(remaining.shape[0])):
				row = remaining.iloc[pos]
				key = str(row["corr_key"])
				try:
					arr = corr.loc[key, selected_keys].abs().to_numpy(dtype=float, copy=False)  # type: ignore[index]
					mx = float(np.nanmax(arr)) if arr.size else 1.0
				except Exception:
					mx = 1.0
				# minimize max corr, then maximize score
				score = float(row["score"]) if pd.notna(row.get("score")) else -1e9
				tup = (mx, -score)
				if best_tuple is None or tup < best_tuple:
					best_tuple = tup
					best_pos = pos
			if best_pos is None:
				break
			best_row = remaining.iloc[int(best_pos)]
			selected_keys.append(str(best_row["corr_key"]))
			selected_rows.append(int(remaining.index[int(best_pos)]))
			remaining = remaining.drop(index=int(remaining.index[int(best_pos)]))

	selected = work.iloc[selected_rows].copy()
	selected["basket_rank"] = range(1, len(selected) + 1)
	return selected


def build_alpha_candidates(
	*,
	dir_input: str | Path = DIR_INPUT,
	allowed_categories: Optional[list[str]] = None,
	zscore_threshold: float = 2.0,
	max_per_style: int = 20,
	lookback_days: int = 252,
	max_abs_corr: float = 0.6,
	top_n_low_corr: int = 10,
) -> Dict[str, object]:
	"""Select candidates and compute low-correlation basket.

	- Limits to max 40 total (20 MR + 20 Trend/Carry)
	- MeanReversion requires stationary == "YES" (hard requirement)
	- Uses historical spread time series to compute correlation (diff-based)
	"""
	snap = load_alpha_spreads_snapshot(dir_input=dir_input, refresh=False)

	# Build unified table
	frames = []
	for stype, df in snap.items():
		if isinstance(df, pd.DataFrame) and not df.empty:
			frames.append(df.copy())
	if not frames:
		return {"asof": pd.Timestamp.now(), "candidates": pd.DataFrame(), "selected_lowcorr": pd.DataFrame(), "corr": None}

	df_all = pd.concat(frames, axis=0, ignore_index=False)
	if "spread_type" not in df_all.columns:
		# should not happen for our snapshot
		df_all["spread_type"] = "Unknown"
	if "category" not in df_all.columns:
		df_all["category"] = "Unknown"

	# Allowed categories filter
	if allowed_categories:
		allowed = set(allowed_categories)
		df_all = df_all[df_all["category"].isin(allowed)].copy()
	if df_all.empty:
		return {"asof": pd.Timestamp.now(), "candidates": pd.DataFrame(), "selected_lowcorr": pd.DataFrame(), "corr": None}

	# Ensure required columns
	for c in ["Zscore", "spread", "mean", "vol", "halflife", "carry_roll"]:
		if c in df_all.columns:
			df_all[c] = pd.to_numeric(df_all[c], errors="coerce")

	# Style mapping: treat Bond-Swap as Trend/Carry, Bond-Curve and Swap-Spread as MeanReversion
	cat_to_style = {
		"Bond-Curve": "MeanReversion",
		#"Swap-Spread": "MeanReversion", # HANDLED DYNAMICALLY BELOW
		"Bond-Swap": "Carry",
		"Tenor-Spread": "MeanReversion",
	}
	if "style" not in df_all.columns:
		df_all["style"] = df_all["category"].map(cat_to_style)
		
		# Dynamic style for Swap-Spread: MR if stationary, else Carry
		mask_ss = df_all["category"] == "Swap-Spread"
		if mask_ss.any():
			# Initialize with Carry
			df_all.loc[mask_ss, "style"] = "Carry"
			# Upgrade stationary ones to MeanReversion
			if "stationary" in df_all.columns:
				stat_mask = mask_ss & _stationary_yes_mask(df_all["stationary"])
				if stat_mask.any():
					df_all.loc[stat_mask, "style"] = "MeanReversion"
		
		df_all["style"] = df_all["style"].fillna("Unknown")

	# Extract ID from index
	if df_all.index.name != "ID":
		df_all = df_all.copy()
		df_all.index.name = "ID"
	work = df_all.reset_index()

	# Basic validity
	work = work[pd.to_numeric(work["Zscore"], errors="coerce").notna()].copy()
	work["abs_zscore"] = work["Zscore"].abs()

	# Split MR vs Trend/Carry
	mr = work[work["style"].str.lower().eq("meanreversion")].copy()
	# hard requirement
	if "stationary" in mr.columns:
		mr = mr[_stationary_yes_mask(mr["stationary"])].copy()
	else:
		mr = mr.iloc[0:0].copy()

	trend = work[work["style"].str.lower().isin({"carry", "trend", "trendfollowing"})].copy()

	# Apply z-score threshold to both buckets (keeps behavior aligned with UI slider)
	try:
		z_thd = float(zscore_threshold)
	except Exception:
		z_thd = 2.0

	# Mean-reversion entries are governed by z-score threshold.
	mr = mr[mr["abs_zscore"] >= z_thd].copy()

	# Trend/Carry:
	# - For Bond-Swap (and other non Swap-Spread carry), keep z-score threshold.
	# - For Swap-Spread carry (non-stationary), do NOT gate by z-score; rank by carry_roll/vol.
	if not trend.empty and "category" in trend.columns:
		trend_ss = trend[trend["category"].astype(str).eq("Swap-Spread")].copy()
		trend_other = trend[~trend["category"].astype(str).eq("Swap-Spread")].copy()
		trend_other = trend_other[trend_other["abs_zscore"] >= z_thd].copy()
		trend = pd.concat([trend_ss, trend_other], axis=0, ignore_index=True)
	else:
		trend = trend[trend["abs_zscore"] >= z_thd].copy()

	# Load historical series for all pre-filtered candidates before scoring.
	# The same series_map is reused for correlation below — no duplicate IO.
	all_pre = pd.concat([mr, trend], axis=0, ignore_index=True)
	series_map: Dict[str, pd.Series] = {}
	if not all_pre.empty and "spread_type" in all_pre.columns and "ID" in all_pre.columns:
		for stype in all_pre["spread_type"].unique().tolist():
			ids = all_pre.loc[all_pre["spread_type"].eq(stype), "ID"].astype(str).unique().tolist()
			series_map.update(
				load_historical_spread_series(stype, ids, dir_input=dir_input, lookback_days=lookback_days)
			)

	# Enrich with regression slope + 3m rolling vol, then score + rank
	mr = _enrich_candidates_with_regression(mr, series_map)
	trend = _enrich_candidates_with_regression(trend, series_map)

	mr = _add_unified_score_preview(mr)
	trend = _add_unified_score_preview(trend)

	mr = mr.sort_values(["score"], ascending=False).head(int(max_per_style)).copy()
	trend = trend.sort_values(["score"], ascending=False).head(int(max_per_style)).copy()

	candidates = pd.concat([mr, trend], axis=0, ignore_index=True)
	if candidates.empty:
		return {"asof": pd.Timestamp.now(), "candidates": candidates, "selected_lowcorr": pd.DataFrame(), "corr": None}

	# series_map already loaded above; use directly for correlation

	corr, _ = compute_candidate_correlation(series_map)
	# Add correlation key to candidates (even if corr is None)
	candidates["corr_key"] = candidates.apply(lambda r: f"{r['spread_type']}|{r['ID']}", axis=1)

	selected_lowcorr = pd.DataFrame()
	if corr is not None and not corr.empty:
		selected_lowcorr = select_low_corr_basket(
			candidates,
			corr,
			top_n=int(top_n_low_corr),
			max_abs_corr=float(max_abs_corr),
		)

	# Mark selected
	selected_set = set(selected_lowcorr["corr_key"].tolist()) if not selected_lowcorr.empty else set()
	candidates["selected_lowcorr"] = candidates["corr_key"].isin(selected_set)

	return {
		"asof": pd.Timestamp.now(),
		"params": {
			"allowed_categories": allowed_categories,
			"zscore_threshold": z_thd,
			"max_per_style": int(max_per_style),
			"lookback_days": int(lookback_days),
			"max_abs_corr": float(max_abs_corr),
			"top_n_low_corr": int(top_n_low_corr),
		},
		"candidates": candidates,
		"selected_lowcorr": selected_lowcorr,
		"corr": corr,
	}


def save_alpha_candidates(
	*,
	dir_input: str | Path = DIR_INPUT,
	allowed_categories: Optional[list[str]] = None,
	zscore_threshold: float = 2.0,
	max_per_style: int = 20,
	lookback_days: int = 252,
	max_abs_corr: float = 0.6,
	top_n_low_corr: int = 10,
	rewrite: bool = True,
) -> Path:
	"""Build and persist candidate selection to DIR_INPUT/Alpha-candidates.pkl."""
	paths = AlphaSnapshotPaths(Path(dir_input))
	obj = build_alpha_candidates(
		dir_input=paths.dir_input,
		allowed_categories=allowed_categories,
		zscore_threshold=zscore_threshold,
		max_per_style=max_per_style,
		lookback_days=lookback_days,
		max_abs_corr=max_abs_corr,
		top_n_low_corr=top_n_low_corr,
	)
	updatePKL(obj, str(paths.out_candidates), rewrite=rewrite)
	return paths.out_candidates


def load_alpha_candidates(
	*,
	dir_input: str | Path = DIR_INPUT,
	refresh: bool = False,
	allowed_categories: Optional[list[str]] = None,
	zscore_threshold: float = 2.0,
	max_per_style: int = 20,
	lookback_days: int = 252,
	max_abs_corr: float = 0.6,
	top_n_low_corr: int = 10,
) -> Dict[str, object]:
	"""Load persisted candidates; optionally rebuild."""
	paths = AlphaSnapshotPaths(Path(dir_input))
	if not refresh and paths.out_candidates.exists():
		obj = pd.read_pickle(paths.out_candidates)
		if isinstance(obj, dict) and "candidates" in obj:
			return obj

	save_alpha_candidates(
		dir_input=paths.dir_input,
		allowed_categories=allowed_categories,
		zscore_threshold=zscore_threshold,
		max_per_style=max_per_style,
		lookback_days=lookback_days,
		max_abs_corr=max_abs_corr,
		top_n_low_corr=top_n_low_corr,
		rewrite=True,
	)
	obj = pd.read_pickle(paths.out_candidates)
	return obj if isinstance(obj, dict) else {}


if __name__ == "__main__":
	out_path = save_alpha_spreads_snapshot(DIR_INPUT, rewrite=True)
	print(f"Saved alpha snapshot: {out_path}")

	from pathlib import Path
	from curves.refreshers.alpha import AlphaSnapshotPaths, _read_pickle

	paths = AlphaSnapshotPaths(Path(DIR_INPUT))
