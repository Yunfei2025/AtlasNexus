"""Alpha snapshot I/O: paths, data helpers, and snapshot build/save/load.

Provides:
- AlphaSnapshotPaths   — file path helper dataclass
- build_alpha_spreads_snapshot / build_alpha_timeseries
- save_alpha_spreads_snapshot / load_alpha_spreads_snapshot / get_alpha_spread_table
- Private helpers reused by alpha_scoring and alpha_candidates
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
from utils.io import load_frame as _io_load_frame
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
_SWAP_SPREAD_BUTTERFLY_PATTERN = re.compile(r"^(?:Repo7d|Shi3M)-(?:\d+[my]){3,}$", re.IGNORECASE)
_LEGACY_REPO_PREFIX = re.compile(r"^Repo-", re.IGNORECASE)


def _exclude_swapspread_butterflies(labels: pd.Index | pd.Series):
	"""Return mask that excludes IRS butterfly IDs such as Repo7d-1y2y5y or Shi3M-3m6m9m."""
	text = labels.astype(str)
	return ~text.str.match(_SWAP_SPREAD_BUTTERFLY_PATTERN)


def _normalize_legacy_repo_label(value: object) -> object:
	if isinstance(value, str):
		return _LEGACY_REPO_PREFIX.sub("Repo7d-", value)
	return value


def _normalize_legacy_repo_obj(obj: object) -> object:
	if isinstance(obj, pd.DataFrame):
		out = obj.copy()
		if out.index.dtype == object:
			out.index = out.index.map(_normalize_legacy_repo_label)
		if out.columns.dtype == object:
			out.columns = out.columns.map(_normalize_legacy_repo_label)
		return out
	if isinstance(obj, pd.Series):
		out = obj.copy()
		if out.index.dtype == object:
			out.index = out.index.map(_normalize_legacy_repo_label)
		out.name = _normalize_legacy_repo_label(out.name)
		return out
	if isinstance(obj, dict):
		return {
			_normalize_legacy_repo_label(key): _normalize_legacy_repo_obj(value)
			for key, value in obj.items()
		}
	if isinstance(obj, list):
		return [_normalize_legacy_repo_obj(value) for value in obj]
	if isinstance(obj, tuple):
		return tuple(_normalize_legacy_repo_obj(value) for value in obj)
	return obj


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

	@property
	def futures_spds(self) -> Path:
		return self.dir_input / "futures-spds.pkl"

	@property
	def source_pickles(self) -> tuple[Path, ...]:
		return (
			self.tbond_spds,
			self.cbond_spds,
			self.irs_pxspds,
			self.tbond_spdsrt,
			self.cbond_spdsrt,
			self.irs_spdsrt,
			self.cnbd_data,
		)


def _read_pickle(path: Path) -> object:
	if not path.exists():
		raise FileNotFoundError(str(path))
	return _normalize_legacy_repo_obj(_io_load_frame(str(path)))


def _snapshot_is_stale(paths: AlphaSnapshotPaths) -> bool:
	if not paths.out_snapshot.exists():
		return True
	try:
		snapshot_mtime = paths.out_snapshot.stat().st_mtime
	except OSError:
		return True
	for src in paths.source_pickles:
		try:
			if src.exists() and src.stat().st_mtime > snapshot_mtime:
				return True
		except OSError:
			continue
	return False


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


from web.tabs.alpha.data.constants import _build_tenor_spread_timeseries


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
		if {"spread", "mean", "vol"}.issubset(df_rt.columns):
			_df_spread = pd.to_numeric(df_rt["spread"], errors="coerce")
			_df_mean = pd.to_numeric(df_rt["mean"], errors="coerce")
			_df_vol = pd.to_numeric(df_rt["vol"], errors="coerce").replace(0, np.nan)
			_df_z = (_df_spread - _df_mean) / _df_vol
			df_rt["Zscore"] = _df_z.where(_df_z.notna(), df_rt["Zscore"])

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
		# Merge stationary from historical StatInfo (not present in real-time spreads)
		if "stationary" not in df_irs.columns and isinstance(irs_pxspd, dict):
			_stat_info = irs_pxspd.get("StatInfo")
			if isinstance(_stat_info, pd.DataFrame) and "stationary" in _stat_info.columns:
				df_irs["stationary"] = _stat_info["stationary"].reindex(df_irs.index)
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
		df_hist = df_hist.dropna(how="all")
		if df_hist.empty:
			return out
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

	# -----------------------
	# Futures spreads: NetBasis, TermBasis, FuturesSwap
	# -----------------------
	try:
		futures_spd = _read_pickle(paths.futures_spds)
		if isinstance(futures_spd, dict):
			# NetBasis — flattened across seasons; one row per ctype-season key
			nb_raw = futures_spd.get("NetBasis", {})
			if isinstance(nb_raw, dict) and nb_raw:
				frames = []
				for season, sdata in nb_raw.items():
					if not isinstance(sdata, dict):
						continue
					si = sdata.get("StatInfo")
					sp = sdata.get("Spread")
					if not isinstance(si, pd.DataFrame) or si.empty:
						continue
					df_nb = si.copy()
					df_nb["contract"] = season
					if isinstance(sp, pd.DataFrame) and not sp.empty:
						latest = sp.ffill().iloc[-1]
						df_nb["spread"] = latest.reindex(df_nb.index)
					frames.append(df_nb)
				if frames:
					df_netbasis = pd.concat(frames)
					df_netbasis = _normalize_index(df_netbasis)
					for col in ["mean", "vol", "spread"]:
						if col not in df_netbasis.columns:
							df_netbasis[col] = np.nan
					df_netbasis["mean"]  = pd.to_numeric(df_netbasis["mean"],  errors="coerce")
					df_netbasis["vol"]   = pd.to_numeric(df_netbasis["vol"],   errors="coerce").replace(0, np.nan)
					df_netbasis["spread"] = pd.to_numeric(df_netbasis["spread"], errors="coerce")
					df_netbasis["Zscore"] = (
						(df_netbasis["spread"] - df_netbasis["mean"]) /
						df_netbasis["vol"]
					)
					# Carry: annualised (price terms basis, ~3m)
					if "carry_3m_bp" in df_netbasis.columns:
						df_netbasis["carry_roll"] = pd.to_numeric(df_netbasis["carry_3m_bp"], errors="coerce")
					df_netbasis["spread_type"] = "NetBasis"
					df_netbasis["category"]    = "Bond-Futures"
					out["NetBasis"] = df_netbasis

			# TermBasis — flat StatInfo
			tb_raw = futures_spd.get("TermBasis", {})
			if isinstance(tb_raw, dict):
				si_tb = tb_raw.get("StatInfo")
				sp_tb = tb_raw.get("Spread")
				if isinstance(si_tb, pd.DataFrame) and not si_tb.empty:
					df_tb = si_tb.copy()
					df_tb = _normalize_index(df_tb)
					if isinstance(sp_tb, pd.DataFrame) and not sp_tb.empty:
						latest_tb = sp_tb.ffill().iloc[-1]
						df_tb["spread"] = latest_tb.reindex(df_tb.index)
					for col in ["mean", "vol", "spread"]:
						if col not in df_tb.columns:
							df_tb[col] = np.nan
					df_tb["mean"]   = pd.to_numeric(df_tb["mean"],   errors="coerce")
					df_tb["vol"]    = pd.to_numeric(df_tb["vol"],    errors="coerce").replace(0, np.nan)
					df_tb["spread"] = pd.to_numeric(df_tb["spread"], errors="coerce")
					df_tb["Zscore"] = (df_tb["spread"] - df_tb["mean"]) / df_tb["vol"]
					df_tb["spread_type"] = "TermBasis"
					df_tb["category"]    = "Futures-Term"
					out["TermBasis"] = df_tb

			# FuturesSwap — one row per contract type (T / TF / TS / TL)
			fs_raw = futures_spd.get("FuturesSwap", {})
			if isinstance(fs_raw, dict) and fs_raw:
				fs_frames = []
				for ctype, cdata in fs_raw.items():
					if not isinstance(cdata, dict):
						continue
					si_fs = cdata.get("StatInfo")
					sp_fs = cdata.get("Spread")
					cr_fs = cdata.get("CarryRoll3m")
					if not isinstance(si_fs, pd.DataFrame) or si_fs.empty:
						continue
					df_fs = si_fs.copy()
					if isinstance(sp_fs, pd.DataFrame) and not sp_fs.empty:
						df_fs["spread"] = float(pd.to_numeric(sp_fs.ffill().iloc[-1].iloc[0], errors="coerce"))
					if isinstance(cr_fs, pd.Series) and len(cr_fs):
						df_fs["carry_roll"] = float(pd.to_numeric(cr_fs.dropna().iloc[-1], errors="coerce"))
					fs_frames.append(df_fs)
				if fs_frames:
					df_fswap = pd.concat(fs_frames)
					df_fswap = _normalize_index(df_fswap)
					for col in ["mean", "vol", "spread"]:
						if col not in df_fswap.columns:
							df_fswap[col] = np.nan
					df_fswap["mean"]   = pd.to_numeric(df_fswap["mean"],   errors="coerce")
					df_fswap["vol"]    = pd.to_numeric(df_fswap["vol"],    errors="coerce").replace(0, np.nan)
					df_fswap["spread"] = pd.to_numeric(df_fswap["spread"], errors="coerce")
					df_fswap["Zscore"] = (df_fswap["spread"] - df_fswap["mean"]) / df_fswap["vol"]
					df_fswap["spread_type"] = "FuturesSwap"
					df_fswap["category"]    = "Futures-Swap"
					out["FuturesSwap"] = df_fswap
	except Exception:
		pass  # futures data optional; never abort other spread types

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
	if not refresh and not _snapshot_is_stale(paths):
		obj = _normalize_legacy_repo_obj(pd.read_pickle(paths.out_snapshot))
		if isinstance(obj, dict):
			return obj
	save_alpha_spreads_snapshot(dir_input=paths.dir_input, rewrite=True)
	obj = _normalize_legacy_repo_obj(pd.read_pickle(paths.out_snapshot))
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
