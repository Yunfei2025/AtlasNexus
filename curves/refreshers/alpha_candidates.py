"""Alpha candidate pipeline: historical series loading, correlation, and selection.

Provides:
- load_historical_spread_series
- compute_candidate_correlation
- select_low_corr_basket
- build_alpha_candidates
- save_alpha_candidates
- load_alpha_candidates
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Iterable, Tuple

import numpy as np
import pandas as pd

from curves.utils.file import updatePKL
from settings.paths import DIR_INPUT
from curves.refreshers.alpha_snapshot import (
    AlphaSnapshotPaths,
    _read_pickle,
    _exclude_swapspread_butterflies,
    _build_tenor_spread_timeseries,
    load_alpha_spreads_snapshot,
    ALPHA_CANDIDATES_FILENAME,
)
from curves.refreshers.alpha_scoring import (
    _enrich_candidates_with_regression,
    _add_unified_score_preview,
    _stationary_yes_mask,
)


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
		work["corr_key"] = work["spread_type"].astype(str) + "|" + work["ID"].astype(str)

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

	# If we couldn't fill to top_n under the strict threshold, fill remaining by "least max corr"
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

	# Apply z-score threshold to both buckets
	try:
		z_thd = float(zscore_threshold)
	except Exception:
		z_thd = 2.0

	# Mean-reversion entries are governed by z-score threshold.
	mr = mr[mr["abs_zscore"] >= z_thd].copy()

	# Trend/Carry: Swap-Spread and Tenor-Spread carry do NOT gate by z-score.
	if not trend.empty and "category" in trend.columns:
		trend_free = trend[trend["category"].astype(str).isin({"Swap-Spread", "Tenor-Spread"})].copy()
		trend_other = trend[~trend["category"].astype(str).isin({"Swap-Spread", "Tenor-Spread"})].copy()
		trend_other = trend_other[trend_other["abs_zscore"] >= z_thd].copy()
		trend = pd.concat([trend_free, trend_other], axis=0, ignore_index=True)
	else:
		trend = trend[trend["abs_zscore"] >= z_thd].copy()

	# Load historical series for all pre-filtered candidates before scoring.
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

	corr, _ = compute_candidate_correlation(series_map)
	# Add correlation key to candidates (even if corr is None)
	candidates["corr_key"] = candidates["spread_type"].astype(str) + "|" + candidates["ID"].astype(str)

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
