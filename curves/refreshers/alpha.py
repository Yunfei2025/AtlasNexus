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
import re

import numpy as np
import pandas as pd

import sys

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))


from curves.calibration.stat import OU_calibrate
from curves.utils.file import updatePKL
from settings.paths import DIR_INPUT


ALPHA_SNAPSHOT_FILENAME = "Alpha-spreadsrt.pkl"
ALPHA_CANDIDATES_FILENAME = "Alpha-candidates.pkl"

# ──────────────── Candidate scoring parameters ────────────────
_HORIZON_DAYS: int = 30              # 1-month expected-return horizon (calendar-day approximation)
_REG_LOOKBACK_DAYS: int = 30         # regression window for slope & z-score (~1 month of trading days)
_RISK_VOL_WINDOW: int = 90           # 3-month risk normalisation window (calendar-day approximation)
_CARRY_BASIS_DAYS: float = 90.0      # carry_roll is stored as a ~3-month quantity
_ANNUAL_CARRY_BASIS_DAYS: float = 360.0
_BOND_CURVE_BORROW_COST_BP_ANNUAL: float = 30.0
_SWAP_SPREAD_BUTTERFLY_PATTERN = re.compile(r"^(?:Repo|Shi3M)-(?:\d+[my]){3,}$", re.IGNORECASE)


def _exclude_swapspread_butterflies(labels: pd.Index | pd.Series):
	"""Return mask that excludes IRS butterfly IDs such as Repo-1y2y5y or Shi3M-3m6m9m."""
	text = labels.astype(str)
	return ~text.str.match(_SWAP_SPREAD_BUTTERFLY_PATTERN)


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


def _append_snapshot_spread_to_series(
	s: pd.Series,
	spread_value: float | int | None,
	*,
	asof: pd.Timestamp | None = None,
) -> pd.Series:
	"""Return historical spread series updated with the latest snapshot spread.

	This keeps regression-based z-scores aligned with the realtime snapshot used
	by the UI when the historical spread pickle has not yet been updated for the
	latest session.
	"""
	s_clean = pd.to_numeric(s, errors="coerce").dropna()
	if s_clean.empty:
		idx = pd.DatetimeIndex([])
	else:
		idx = pd.to_datetime(pd.Index(s_clean.index))
	s_clean = pd.Series(s_clean.to_numpy(dtype=float), index=idx, name=s.name, dtype=float).sort_index()
	spread_num = pd.to_numeric(pd.Series([spread_value]), errors="coerce").iloc[0]
	if pd.isna(spread_num):
		return s_clean

	if s_clean.empty:
		stamp = pd.Timestamp(asof).normalize() if asof is not None else pd.Timestamp.now().normalize()
		return pd.Series([float(spread_num)], index=pd.DatetimeIndex([stamp]), name=s.name, dtype=float)

	last_idx = pd.Timestamp(s_clean.index[-1])
	stamp = pd.Timestamp(asof).normalize() if asof is not None else pd.Timestamp.now().normalize()
	if stamp <= last_idx:
		stamp = last_idx
	elif last_idx.normalize() < stamp:
		stamp = stamp
	else:
		stamp = last_idx + pd.Timedelta(days=1)

	new_point = pd.Series([float(spread_num)], index=pd.DatetimeIndex([stamp]), name=s.name, dtype=float)
	out = pd.concat([s_clean, new_point], axis=0)
	out = out[~out.index.duplicated(keep="last")]
	return out.sort_index()


def _build_tenor_spread_timeseries(cnbd_data: object) -> dict[str, pd.Series]:
	"""Build tenor spread time series from CNBD key-rate history."""
	if not isinstance(cnbd_data, dict) or "CGB" not in cnbd_data or "CDB" not in cnbd_data:
		return {}
	try:
		return {
			"CGB-5s10s": cnbd_data["CGB"]["中债国债到期收益率:10年"] - cnbd_data["CGB"]["中债国债到期收益率:5年"],
			"CGB-10s30s": cnbd_data["CGB"]["中债国债到期收益率:30年"] - cnbd_data["CGB"]["中债国债到期收益率:10年"],
			"CDB-5s10s": cnbd_data["CDB"]["中债国开债到期收益率:10年"] - cnbd_data["CDB"]["中债国开债到期收益率:5年"],
			"CDB-10s30s": cnbd_data["CDB"]["中债国开债到期收益率:30年"] - cnbd_data["CDB"]["中债国开债到期收益率:10年"],
			"CDBCGB-5y": cnbd_data["CDB"]["中债国开债到期收益率:5年"] - cnbd_data["CGB"]["中债国债到期收益率:5年"],
			"CDBCGB-10y": cnbd_data["CDB"]["中债国开债到期收益率:10年"] - cnbd_data["CGB"]["中债国债到期收益率:10年"],
			"CDBCGB-30y": cnbd_data["CDB"]["中债国开债到期收益率:30年"] - cnbd_data["CGB"]["中债国债到期收益率:30年"],
		}
	except Exception:
		return {}


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
	try:
		tenor_spd = _build_tenor_spread_timeseries(cnbd_data)
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
			df_bc["Zscore"] = (
				pd.to_numeric(df_bc.get("spread", pd.Series(np.nan, index=df_bc.index)), errors="coerce") -
				pd.to_numeric(df_bc.get("mean", pd.Series(0.0, index=df_bc.index)), errors="coerce")
			) / pd.to_numeric(df_bc.get("vol", pd.Series(np.nan, index=df_bc.index)), errors="coerce").replace(0, np.nan)
			spread_bp = pd.to_numeric(df_bc.get("spread", pd.Series(np.nan, index=df_bc.index)), errors="coerce") * 100.0
			borrow_cost_bp = pd.Series(
				_BOND_CURVE_BORROW_COST_BP_ANNUAL * (_CARRY_BASIS_DAYS / _ANNUAL_CARRY_BASIS_DAYS),
				index=df_bc.index,
				dtype=float,
			)
			df_bc["carry_bp"] = spread_bp
			df_bc["roll_bp"] = 0.0
			df_bc["borrow_cost_bp"] = -borrow_cost_bp
			df_bc["carry_roll"] = df_bc["carry_bp"] + df_bc["roll_bp"] + df_bc["borrow_cost_bp"]
			df_bc["carry_basis_days"] = _CARRY_BASIS_DAYS
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
			df_rt["carry_3m_bp"] = carry_latest.reindex(df_rt.index)
			df_rt["roll_3m_bp"] = 0.0

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
		df_irs = df_irs[_exclude_swapspread_butterflies(df_irs.index)].copy()
		df_irs = _ensure_numeric(df_irs, ["Zscore", "spread", "mean", "vol", "Carry(3m,bp)", "Roll(3m,bp)"])
		if "Carry(3m,bp)" in df_irs.columns:
			df_irs["carry_3m_bp"] = pd.to_numeric(df_irs["Carry(3m,bp)"], errors="coerce")
		if "Roll(3m,bp)" in df_irs.columns:
			df_irs["roll_3m_bp"] = pd.to_numeric(df_irs["Roll(3m,bp)"], errors="coerce")
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
		# Use the recent 252 trading days (~1y), consistent with candidate lookback.
		N = 252
		df_hist = df_ts.tail(N)
		stat_info = OU_calibrate(df_hist)
		latest = df_hist.ffill().iloc[-1].rename("spread")

		df_tenor = stat_info.join(latest, how="right")
		for col in ["mean", "vol", "halflife"]:
			if col not in df_tenor.columns:
				df_tenor[col] = np.nan
		if "stationary" not in df_tenor.columns:
			df_tenor["stationary"] = "NO"

		df_tenor["spread"] = pd.to_numeric(df_tenor["spread"], errors="coerce")
		df_tenor["mean"] = pd.to_numeric(df_tenor["mean"], errors="coerce")
		df_tenor["vol"] = pd.to_numeric(df_tenor["vol"], errors="coerce")
		df_tenor["Zscore"] = (
			(df_tenor["spread"] - df_tenor["mean"]) /
			df_tenor["vol"].replace(0, np.nan)
		)
		# Use the tenor spread level itself as annual BUY-side carry+roll proxy.
		# Spread is stored in yield %, so convert to annual bp.
		# Use 30/360 scaling so a 1-month horizon is exactly annual_carry / 12.
		df_tenor["carry_roll"] = df_tenor["spread"] * 100.0
		df_tenor["carry_basis_days"] = _ANNUAL_CARRY_BASIS_DAYS
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
	snapshot: Dict[str, object] = dict(build_alpha_spreads_snapshot(dir_input=paths.dir_input))
	
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
			spread_now = row.get("spread", np.nan)
			s_enriched = _append_snapshot_spread_to_series(s, spread_now)
			slope, rvol, rmean, rvolresid = _compute_trend_metrics(s_enriched)
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
	# risk_spd is σ(daily yield-spread changes), computed from the spread series.
	# Multiply by effective duration so numerator and denominator are both returns.
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
	# BondCurve/BondSwap carry is a running carry return and is not duration-scaled.
	# IRS carry/roll are already return terms in source bp.  BondCurve roll is also
	# already a duration-based return term.  /100 converts bp → %.
	carry_bp = carry_bp.where(carry_bp.notna(), carry_roll.where(roll_bp.isna(), np.nan))
	roll_bp = roll_bp.fillna(0.0)
	carry_H = (carry_bp / 100.0) * (H / cd)
	roll_H = (roll_bp / 100.0) * (H / cd)
	out["carry_H"] = carry_H
	out["roll_H"] = roll_H

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

	# ── Expected P&L for canonical BUY position — return space ────────────────
	# BUY profits when spread FALLS:
	#   P&L_BUY = D_eff × (−E[Δs_H]) + carry_H + roll_H
	#
	# Duration scales only the MTM from expected spread changes.
	# carry_H stays as running carry return; roll_H stays as source roll return.
	# risk_return is the matching return-vol denominator.
	#
	# Example (IRS 1y5y flattener, TTM=5, E[Δs]=6bp, carry=20bp/3m, σ=5bp):
	#   pnl_buy = 5×0.06 + (20/3)/100 = 0.30 + 0.0667 = 0.3667 %
	#   risk    = 5×0.05 = 0.25 %
	#   score   = 0.3667 / 0.25 = 1.47
	#
	#   −D_eff×E[Δs_H]: spread expected to fall → BUY gains in MTM terms ✓
	#   carry_H       : running carry on financed notional ✓
	#   roll_H        : roll-down return from aging the position ✓
	mtm_buy = duration_eff * (-e_spread)
	out["mtm_H"] = mtm_buy
	pnl_buy = mtm_buy + carry_H.fillna(0.0) + roll_H.fillna(0.0)

	# ── Direction: sign of P&L_BUY ─────────────────────────────────────────────
	# BUY  if pnl_buy > 0  (spread expected to fall, or carry dominates)
	# SELL if pnl_buy < 0  (spread expected to rise, better to short)
	direction = pd.Series("SELL", index=out.index, dtype=str)
	direction.loc[pnl_buy.gt(0)] = "BUY"
	out["direction"] = direction
	dir_sign = pd.Series(-1.0, index=out.index, dtype=float)
	dir_sign.loc[direction.eq("BUY")] = 1.0
	out["dir_sign_score"] = dir_sign

	# ── Score: return / return-vol — dimensionless ratio ──────────────────────
	# score = |P&L_BUY| / risk_spd
	# Numerator: carry + roll + duration-scaled MTM, all in return %
	# Denominator: duration-scaled spread-vol, also in return %
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
		df = df.loc[:, _exclude_swapspread_butterflies(pd.Index(df.columns))].copy()
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
		tenor_ts = _build_tenor_spread_timeseries(obj)
		if not tenor_ts:
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

	# Style mapping: explicit carry categories stay Carry; mixed categories are ADF-driven.
	cat_to_style = {
		"Bond-Curve": "MeanReversion",
		#"Swap-Spread": "MeanReversion", # HANDLED DYNAMICALLY BELOW
		"Bond-Swap": "Carry",
	}
	if "style" not in df_all.columns:
		df_all["style"] = df_all["category"].map(cat_to_style)
		
		# Dynamic style for mixed categories: MR if stationary, else Carry.
		for dynamic_category in ["Swap-Spread", "Tenor-Spread"]:
			mask_dynamic = df_all["category"] == dynamic_category
			if mask_dynamic.any():
				df_all.loc[mask_dynamic, "style"] = "Carry"
				if "stationary" in df_all.columns:
					stat_mask = mask_dynamic & _stationary_yes_mask(df_all["stationary"])
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

	# ── BondSwap direction override + score recomputation ────────────────────────
	# Convention: spread = bond yield − swap rate.
	# z > 0 (spread above mean, bond cheap vs swap) → BUY; z < 0 → SELL.
	# The stored carry (BondCarry) is the BUY-side carry (buy bond, sell swap).
	# Pin direction to z-score sign, then recompute score with carry correctly
	# attributed: +carry for BUY, −carry for SELL.
	if not trend.empty and "category" in trend.columns and "Zscore" in trend.columns:
		bs_mask = trend["category"].astype(str).eq("Bond-Swap")
		if bs_mask.any():
			bs_idx = trend.index[bs_mask]
			z_bs = pd.to_numeric(trend.loc[bs_idx, "Zscore"], errors="coerce")
			bs_dir = pd.Series(
				["BUY" if (pd.notna(z) and float(z) > 0) else "SELL" for z in z_bs],
				index=bs_idx,
			)
			trend.loc[bs_idx, "direction"] = bs_dir
			# Recompute score with carry sign aligned to the pinned direction.
			# carry_H / roll_H / mtm_H were computed as BUY-side quantities by
			# _add_unified_score_preview; negate all three when direction is SELL.
			if {"mtm_H", "carry_H", "roll_H", "risk"}.issubset(trend.columns):
				bs_dir_sign = bs_dir.map({"BUY": 1.0, "SELL": -1.0}).fillna(1.0)
				pnl_bs = (
					trend.loc[bs_idx, "mtm_H"].fillna(0.0)
					+ trend.loc[bs_idx, "carry_H"].fillna(0.0)
					+ trend.loc[bs_idx, "roll_H"].fillna(0.0)
				)
				risk_bs = trend.loc[bs_idx, "risk"].replace(0, np.nan).fillna(1.0)
				exp_ret = (bs_dir_sign * pnl_bs).clip(lower=0.0)
				trend.loc[bs_idx, "expected_return_H"] = exp_ret
				trend.loc[bs_idx, "score"] = (exp_ret / risk_bs).fillna(0.0)

	# ── Execution-feasibility filters ──────────────────────────────────────────
	# Bond-Swap (TBondSwap / CBondSwap): borrowing the bond to short is not
	# feasible in practice, so only BUY-side candidates are kept.
	# Bond-Curve (TBondCurve / CBondCurve): shorting off-the-run bonds is
	# similarly not feasible, so only BUY-side candidates are kept.
	_SELL_RESTRICTED_CATEGORIES = {"Bond-Swap", "Bond-Curve"}
	if "category" in mr.columns and "direction" in mr.columns:
		sell_restricted = mr["category"].isin(_SELL_RESTRICTED_CATEGORIES)
		mr = mr[~(sell_restricted & mr["direction"].eq("SELL"))].copy()
	if "category" in trend.columns and "direction" in trend.columns:
		sell_restricted = trend["category"].isin(_SELL_RESTRICTED_CATEGORIES)
		trend = trend[~(sell_restricted & trend["direction"].eq("SELL"))].copy()

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
