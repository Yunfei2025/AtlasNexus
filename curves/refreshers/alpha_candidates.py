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

import re
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
	_add_momentum_ma_zscore,
    _add_unified_score_preview,
    _stationary_yes_mask,
)
from web.tabs.alpha.data.saved_state import load_instrument_params

# Category default (entry_z, carry_z_weight) when an instrument has no saved
# state -- mirrors web/tabs/alpha/callbacks/backtest_tab.py's
# preset_backtest_params, so an un-reviewed instrument's candidate gate uses
# the same threshold the individual-spread backtest panel would default to.
_DEFAULT_ENTRY_PARAMS = {
	"TenorSpread": {"entry_z": 2.5, "carry_z_weight": 0.5},
}
_FALLBACK_ENTRY_PARAMS = {"entry_z": 2.0, "carry_z_weight": 0.5}

# Momentum Zscore-magnitude entry gate (Momentum bucket only -- Carry and
# EventDriven rows are split out into their own buckets and do not use this
# gate, see build_alpha_candidates). Checks |trend_momentum| (the pullback
# z-score against the established trend -- this is what a Momentum row's
# 'Zscore' column actually holds, since _add_momentum_ma_zscore overwrites
# it with this value): 1.0 means the pullback itself is at least one
# standard deviation, the same dimensionally-meaningful cutoff MR's
# composite_z >= entry_z gate enforces in its own (z-score) units. Combines
# with the pullback-direction/stretch_cap window in build_alpha_candidates's
# momentum-direction block into MOMENTUM_CARRY_MIN_SCORE <= |trend_momentum|
# < stretch_cap.
# NOTE: name kept for backward compatibility (tests/saved params may
# reference it); it covers neither "Carry" (see CARRY_MIN_SIGMA) nor the
# separate 'score' (expected-edge/risk) column -- corrected 2026-09-22 per
# user, this gate is on the Zscore/trend_momentum pullback magnitude.
MOMENTUM_CARRY_MIN_SCORE = 1.0

# Carry bucket entry gate: |carry_sigma| (see _carry_sigma) must clear this
# many vol-normalized sigma units of carry-roll before a row is shown as a
# Carry candidate. Applies uniformly to genuine Bond-Futures carry rows and
# to Swap-Spread/Tenor-Spread rows that fell back to style="Carry" after
# failing the MeanReversion stationarity test -- a non-stationary MR spread
# only appears in Carry if its carry-roll is actually large enough relative
# to vol to be a real carry trade, not merely because it lost MR eligibility
# for the day. carry_sigma is clipped to [-1.5, 1.5], so 1.0 is already a
# fairly tight bar relative to that ceiling -- revisit if it empties the
# bucket most days.
CARRY_MIN_SIGMA = 1.0

# Carry bucket entry gate #2: |carry_roll| (bp, 3m) must ALSO clear this
# absolute floor -- catches a row that only clears CARRY_MIN_SIGMA because
# its vol is small, not because the carry itself is economically worth
# trading. Both gates (vol-relative AND absolute) must pass. 5bp chosen per
# user 2026-09-21: live book's Carry-bucket carry_roll ranged ~4.6bp-228bp
# that day, so 5bp excludes only the thinnest-edge row without being overly
# aggressive -- revisit if it starts excluding most of the bucket.
CARRY_MIN_ROLL_BP = 5.0

# Carry bucket entry gate #3: vol (risk_vol_63d, falling back to the OU vol
# column) must be <= this quantile of the pre-gate Carry pool's own vol
# distribution. A carry trade is meant to be HELD for the running yield, not
# traded for P&L on the spread moving -- so it should be a comparatively
# quiet spread relative to that day's other carry candidates, not just one
# with big carry relative to ITS OWN vol (which CARRY_MIN_SIGMA already
# checks). Relative/self-calibrating rather than an absolute vol number,
# since vol scale varies a lot across spread types (Repo7d, TBondSwap,
# TenorSpread, ...) and across days. 0.5 (median) chosen per user
# 2026-09-21: "low vol" should mean quieter than a typical carry candidate
# that day, not an arbitrary fixed cutoff -- revisit if this proves too
# tight/loose in practice (e.g. 0.6-0.75 to keep more of the bucket).
CARRY_VOL_PCTILE = 0.5


def _entry_params_for(spread_type: str, instrument: str) -> tuple[float, float]:
	"""Return (entry_z, carry_z_weight) for one instrument: saved params if
	the instrument has been reviewed (Save Parameters on the individual
	backtest panel), else the same category default the backtest panel
	itself would preset for an un-reviewed instrument."""
	saved = None
	try:
		saved = load_instrument_params(spread_type, instrument)
	except Exception:
		saved = None
	default = _DEFAULT_ENTRY_PARAMS.get(spread_type, _FALLBACK_ENTRY_PARAMS)
	entry_z = default["entry_z"]
	carry_z_weight = default["carry_z_weight"]
	if saved:
		if saved.get("entry_z") is not None:
			entry_z = float(saved["entry_z"])
		if saved.get("carry_z_weight") is not None:
			carry_z_weight = float(saved["carry_z_weight"])
	return entry_z, carry_z_weight


# SwapSpread liquidity gate: FR007 anchor tenors quoted/traded with reliable
# two-way markets. Mirrors settings.futures.FuturesConfig.IRS_TERMS (the same
# anchor set the curve-interpolation layer already trusts), plus Shi3M's own
# narrower liquid set (1y/5y only -- Shi3M has materially thinner two-way
# markets than FR007 even at matching tenors, per user 2026-09-19).
# Repo7d-4y5y, Repo7d-2y3y, and any other combination touching a non-anchor
# leg (4y, 3y as a Shi3M leg, etc.) are suitable for rebalance-driven
# position rolls (e.g. a 5y position aging into 4y5y to hold duration) but
# not for allocating significant size in a standalone RV trade -- see
# alpha-single-spread-sharpe-ceiling: a thin instrument can't absorb size
# even if its z-score signal looks clean.
# 7y/10y added 2026-09-22: now tradable and liquid on the FR007 curve (user
# confirmed). Shi3M's 7y/10y stay out of its own liquid set -- not yet liquid
# there.
_REPO7D_LIQUID_TENORS = {"3m", "6m", "9m", "1y", "2y", "5y", "7y", "10y"}
_SHI3M_LIQUID_TENORS = {"1y", "5y"}
_BASIS_LIQUID_TENORS = {"1y", "5y"}

_TENOR_TOKEN_RE = re.compile(r"(\d+[a-z])")
_BASIS_SINGLE_RE = re.compile(r"^basis-(\d+y)$")


def _swapspread_tenor_legs(instrument_id: str) -> tuple[Optional[str], list[str]]:
	"""Parse a SwapSpread ID into (prefix, [tenor_tokens]).

	Mirrors web/tabs/alpha/data/legs.py's _parse_repo_spread_legs /
	_parse_repo_spread_fly_legs tenor tokenization (2-leg slope, 3-leg fly,
	or single-tenor Basis-Xy) so the liquidity gate agrees with how legs are
	actually resolved for trading. Returns (None, []) if the ID doesn't match
	any known SwapSpread naming convention.
	"""
	lowered = str(instrument_id).strip().lower()
	m = _BASIS_SINGLE_RE.match(lowered)
	if m:
		return "basis", [m.group(1)]
	for prefix in ("repo7d", "shi3m"):
		m = re.match(rf"{prefix}-(.+)", lowered)
		if m:
			return prefix, _TENOR_TOKEN_RE.findall(m.group(1))
	return None, []


def is_swapspread_liquid(instrument_id: str) -> bool:
	"""True only if EVERY leg of a SwapSpread instrument is an anchor tenor

	with a reliable two-way market -- see the liquid-tenor sets above. A
	spread with any illiquid leg (e.g. Repo7d-4y5y, Shi3M-2y3y) still trades
	fine for rebalancing an existing position's duration, but should not be
	sized as a standalone RV candidate in the scanner.
	"""
	prefix, tenors = _swapspread_tenor_legs(instrument_id)
	if prefix is None or not tenors:
		return False
	liquid_set = {
		"repo7d": _REPO7D_LIQUID_TENORS,
		"shi3m": _SHI3M_LIQUID_TENORS,
		"basis": _BASIS_LIQUID_TENORS,
	}[prefix]
	return all(t in liquid_set for t in tenors)


def _carry_sigma(df: pd.DataFrame) -> pd.Series:
	"""carry_roll, expressed in vol-normalized sigma units.

	  carry_sigma = clip(carry_roll_bp/100 * 30/90 / ewm_vol, -1.5, 1.5)

	Shared by MR's composite_z (_add_composite_score, below) and the Carry
	bucket's own entry gate in build_alpha_candidates -- same "carry relative
	to current risk" measure either way, just used as a tilt on MR's z-score
	there vs. a standalone signal here.
	"""
	if df.empty:
		return pd.Series(dtype=float)
	ewm_vol = pd.to_numeric(df.get("ewm_vol"), errors="coerce")
	ewm_vol = ewm_vol.where(ewm_vol.notna() & ewm_vol.gt(0), pd.to_numeric(df.get("vol"), errors="coerce"))
	carry_roll_bp = pd.to_numeric(df.get("carry_roll"), errors="coerce").fillna(0.0)
	return ((carry_roll_bp / 100.0) * (30.0 / 90.0) / ewm_vol.replace(0, np.nan)).clip(-1.5, 1.5).fillna(0.0)


def _add_composite_score(df: pd.DataFrame) -> pd.DataFrame:
	"""Add 'entry_z_used', 'carry_z_weight_used', and 'composite_z' columns.

	Mirrors the backtest engines' composite score (engine_monthly.py):
	  composite_z = zscore - carry_z_weight * carry_sigma
	using each row's own saved (or category-default) entry_z/carry_z_weight,
	and the snapshot's own Zscore/ewm_vol/carry_roll -- a same-day check
	against the backtest's own entry rule, not a multi-day position replay.
	"""
	if df.empty:
		out = df.copy()
		out["entry_z_used"] = pd.Series(dtype=float)
		out["carry_z_weight_used"] = pd.Series(dtype=float)
		out["composite_z"] = pd.Series(dtype=float)
		return out

	out = df.copy()
	entry_z_vals = []
	carry_zw_vals = []
	for stype, inst in zip(out["spread_type"].astype(str), out["ID"].astype(str)):
		ez, czw = _entry_params_for(stype, inst)
		entry_z_vals.append(ez)
		carry_zw_vals.append(czw)
	out["entry_z_used"] = entry_z_vals
	out["carry_z_weight_used"] = carry_zw_vals

	zscore = pd.to_numeric(out.get("Zscore"), errors="coerce")
	out["composite_z"] = zscore - out["carry_z_weight_used"] * _carry_sigma(out)
	return out


def _corr_display_key(spread_type: str, inst: str) -> str:
	"""Correlation matrix label used across Alpha pipeline and web tab.

	Keep instrument codes human-readable while disambiguating known overlaps.
	"""
	stype = str(spread_type or "")
	instrument = str(inst or "")
	if stype in {"TBondCurve", "CBondCurve"}:
		return f"{instrument}-OTR"
	if stype in {"TBondSwap", "CBondSwap"}:
		return f"{instrument}-Swp"
	if stype == "NetBasis":
		return f"{instrument}-Basis"
	if stype == "TermBasis":
		return f"{instrument}-Cal"
	if stype == "FuturesSwap":
		return f"{instrument}-FtSwp"
	return instrument


def load_historical_spread_series(
	spread_type: str,
	candidates: Iterable[str],
	*,
	dir_input: str | Path = DIR_INPUT,
	lookback_days: int = 252,
) -> Dict[str, pd.Series]:
	"""Load historical spread time series for a set of IDs.

	Returns mapping key -> Series, where key is the display correlation label.
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
					s.name = _corr_display_key(spread_type, str(cid))
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
					s.name = _corr_display_key(spread_type, str(cid))
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
					s.name = _corr_display_key(spread_type, str(cid))
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
					s.name = _corr_display_key(spread_type, str(cid))
					key_to_series[s.name] = s

	elif spread_type in {"NetBasis", "FuturesSwap"}:
		obj = _read_pickle(paths.futures_spds)
		if not isinstance(obj, dict):
			return {}
		cat_data = obj.get("NetBasis" if spread_type == "NetBasis" else "FuturesSwap", {})
		if not isinstance(cat_data, dict):
			return {}
		for cid in candidates:
			ctype_data = cat_data.get(cid, {})
			sp = ctype_data.get("Spread") if isinstance(ctype_data, dict) else None
			if not isinstance(sp, pd.DataFrame) or sp.empty:
				continue
			col = cid if cid in sp.columns else sp.columns[0]
			s = pd.to_numeric(sp[col], errors="coerce").dropna().sort_index().tail(int(lookback_days))
			if not s.empty:
				s.name = _corr_display_key(spread_type, str(cid))
				key_to_series[s.name] = s

	elif spread_type == "TermBasis":
		obj = _read_pickle(paths.futures_spds)
		if not isinstance(obj, dict):
			return {}
		sp = obj.get("TermBasis", {}).get("Spread")
		if not isinstance(sp, pd.DataFrame) or sp.empty:
			return {}
		sp = sp.sort_index().tail(int(lookback_days))
		for cid in candidates:
			if cid in sp.columns:
				s = pd.to_numeric(sp[cid], errors="coerce").dropna()
				if not s.empty:
					s.name = _corr_display_key(spread_type, str(cid))
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

	# Normalise all series indices to pd.Timestamp so mixed datetime.date /
	# Timestamp indices (e.g. Bond-Curve vs Bond-Futures) don't crash sort_index.
	normalised = {k: s.copy() for k, s in series_map.items()}
	for k, s in normalised.items():
		if not isinstance(s.index, pd.DatetimeIndex):
			normalised[k] = s.set_axis(pd.to_datetime(s.index))
	df = pd.DataFrame(normalised).sort_index()
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
		work["corr_key"] = [
			_corr_display_key(stype, cid)
			for stype, cid in zip(work["spread_type"].astype(str), work["ID"].astype(str))
		]

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
	momentum_stretch_mult: float = 1.5,
	max_per_style: int = 20,
	lookback_days: int = 252,
	max_abs_corr: float = 0.6,
	top_n_low_corr: int = 10,
) -> Dict[str, object]:
	"""Select candidates and compute low-correlation basket.

	- Limits to max ``max_per_style`` rows per style bucket (MeanReversion,
	  Momentum, Carry, EventDriven), each bucket scored/ranked independently.
	- MeanReversion requires stationary == "YES" (hard requirement)
	- Uses historical spread time series to compute correlation (diff-based)
	- Priority order within the Carry-eligible pool (Swap-Spread,
	  Tenor-Spread, Bond-Futures, Futures-Swap, Bond-Swap -- Futures-Term is
	  NOT included, see EventDriven note below), per user 2026-09-22:
	    1. Momentum: evaluated on the FULL pool first -- z_t opposite in
	       sign to trend_state (a mild pullback against the established
	       trend) AND MOMENTUM_CARRY_MIN_SCORE <= |z_t| <
	       ``zscore_threshold * momentum_stretch_mult`` (the pullback must
	       be at least 1 sigma, but not so large it reads as an incipient
	       reversal rather than a retracement).
	    2. Carry: whatever did NOT qualify for Momentum (including
	       trend_state != 0 rows that failed the pullback/Zscore gate) is
	       then evaluated against |carry_sigma| >= CARRY_MIN_SIGMA
	       (carry-roll magnitude relative to vol) AND |carry_roll| >=
	       CARRY_MIN_ROLL_BP (absolute bp floor) AND vol <=
	       CARRY_VOL_PCTILE quantile of that day's Carry pool (held for the
	       running yield, so it should be a comparatively quiet spread).
	  A row can therefore land in Momentum OR Carry, never both.
	- EventDriven is scoped to exactly New-Issue (OTR/OFR roll-pressure),
	  Futures-Term-Event (calendar-spread roll event), and Futures-Term
	  (TermBasis calendar spread) -- see _EVENT_DRIVEN_CATEGORIES. New-Issue
	  rows additionally require data_ready == True (alpha_snapshot.py's own
	  quote-freshness/lag-existence check -- added 2026-09-22 per user, since
	  unfiltered New-Issue rows were mostly backfilled/not-yet-clean data).
	  Other EventDriven categories have no upstream data_ready gate.
	"""
	# Force rebuild so each scan uses the latest spread snapshot, avoiding
	# stale candidate rows when upstream realtime pickles were refreshed.
	snap = load_alpha_spreads_snapshot(dir_input=dir_input, refresh=True)

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
		"New-Issue": "EventDriven",
		# Futures-Term (TermBasis, displayed as *-Cal) is a calendar/roll
		# spread -- always EventDriven, per user 2026-09-22, same family as
		# Futures-Term-Event/TermBasisEvent (its roll-progress-gated
		# sibling on the same underlying spread; see
		# SPREAD_CATEGORIES['Futures-Term-Event']). NOT dynamic/stationary-
		# gated like Swap-Spread/Tenor-Spread/Futures-Swap below -- a
		# calendar spread's economics are event-driven (contract roll)
		# regardless of whether its z-score happens to be stationary today.
		"Futures-Term": "EventDriven",
	}
	if "style" not in df_all.columns:
		df_all["style"] = df_all["category"].map(cat_to_style)
	else:
		style_existing = df_all["style"].astype(str).str.strip()
		style_missing = df_all["style"].isna() | style_existing.eq("") | style_existing.str.lower().isin({"nan", "none", "unknown"})
		if style_missing.any():
			df_all.loc[style_missing, "style"] = df_all.loc[style_missing, "category"].map(cat_to_style)

	# Dynamic style for mixed categories: MR if stationary, else Carry.
	# Bond-Futures is always Carry (defined as carry trade in SPREAD_CATEGORIES).
	# Futures-Term is NOT included here -- it's a static EventDriven category
	# via cat_to_style above (calendar spread, not MR/Carry-eligible).
	_MR_ELIGIBLE_DYNAMIC = {"Swap-Spread", "Tenor-Spread", "Futures-Swap"}
	for dynamic_category in ["Swap-Spread", "Tenor-Spread", "Bond-Futures", "Futures-Swap"]:
		mask_dynamic = df_all["category"] == dynamic_category
		if mask_dynamic.any():
			df_all.loc[mask_dynamic, "style"] = "Carry"
			if dynamic_category in _MR_ELIGIBLE_DYNAMIC and "stationary" in df_all.columns:
				stat_mask = mask_dynamic & _stationary_yes_mask(df_all["stationary"])
				if stat_mask.any():
					df_all.loc[stat_mask, "style"] = "MeanReversion"

	df_all["style"] = df_all["style"].fillna("Unknown")

	# Extract ID from index
	if df_all.index.name != "ID":
		df_all = df_all.copy()
		df_all.index.name = "ID"
	work = df_all.reset_index()

	# Basic validity -- EventDriven rows (New-Issue) are exempt: their Zscore
	# is frequently NaN (see alpha_snapshot.py's BondNewIssue block), since
	# they're gated by roll-pressure/event mechanics, not a z-score.
	style_lower_all = work["style"].str.lower()
	is_event_all = style_lower_all.eq("eventdriven")
	work = work[is_event_all | pd.to_numeric(work["Zscore"], errors="coerce").notna()].copy()
	work["abs_zscore"] = pd.to_numeric(work["Zscore"], errors="coerce").abs()

	# Split MR / Momentum / Carry / EventDriven. Each bucket gets its own
	# entry logic below: MR gates on composite_z vs entry_z, Momentum on a
	# trend-pullback + score>=MOMENTUM_CARRY_MIN_SCORE, Carry on
	# |carry_sigma|>=CARRY_MIN_SIGMA, EventDriven ungated (its own upstream
	# roll-pressure/event gating already applies before this point).
	style_lower = work["style"].str.lower()
	mr = work[style_lower.eq("meanreversion")].copy()
	# hard requirement
	if "stationary" in mr.columns:
		mr = mr[_stationary_yes_mask(mr["stationary"])].copy()
	else:
		mr = mr.iloc[0:0].copy()

	# NOTE: no style mapping anywhere in this pipeline ever assigns
	# style="Trend"/"TrendFollowing" (cat_to_style/dynamic-style above only
	# ever produce MeanReversion/Carry/EventDriven) -- so Momentum is not a
	# style-based bucket at all. Per user 2026-09-22: Momentum is evaluated
	# on the FULL Carry-eligible pool below (pullback-direction + score
	# gate), and Carry is whatever's left over that did NOT qualify for
	# Momentum -- see the priority-order block further down (needs
	# series_map, built after this point, so the split happens later).
	carry = work[style_lower.eq("carry")].copy()

	# Event-Driven is scoped to exactly the event-mechanics categories
	# SPREAD_CATEGORIES declares as EventDriven -- New-Issue (OTR/OFR
	# roll-pressure), Futures-Term-Event (calendar-spread roll event), and
	# Futures-Term (TermBasis, the calendar spread itself -- added
	# 2026-09-22 per user: TS-Cal/T-Cal/TF-Cal/TL-Cal are calendar spreads
	# and belong in Event-Driven, not Mean-Reversion, regardless of their
	# z-score's stationarity). Futures-Term-Event has no snapshot pipe yet
	# (load_alpha_spreads_snapshot() has no TermBasisEvent block -- it has
	# its own separate backtest pathway, see engine_termbasis_event.py), so
	# only New-Issue and Futures-Term rows actually reach this point today.
	# The explicit category allowlist below guards against silent scope
	# creep if EITHER (a) TermBasisEvent is ever wired into the snapshot, or
	# (b) some other category's style is ever set/defaulted to
	# "EventDriven" -- only these named categories should ever populate
	# this bucket, not "whatever style ended up EventDriven".
	_EVENT_DRIVEN_CATEGORIES = {"New-Issue", "Futures-Term-Event", "Futures-Term"}
	event = work[style_lower.eq("eventdriven") & work["category"].isin(_EVENT_DRIVEN_CATEGORIES)].copy()

	# Data-quality gate for New-Issue (BondNewIssue) rows: alpha_snapshot.py
	# already computes 'data_ready' per row (quote-freshness / lag-existence
	# checks -- see docs/dev/tbondcurve-30y-otr-ofr-plan.md's gate list;
	# False rows carry a 'rejection_reason' like
	# 'backfilled_close_yield_only'/'backfilled_with_turnover'). Previously
	# unfiltered here, so every open New-Issue event showed as a candidate
	# regardless of data quality. Per user 2026-09-22: require data_ready ==
	# True. Other EventDriven categories (Futures-Term/TermBasis today) have
	# no such column and are left as-is.
	if "data_ready" in event.columns:
		_ni_mask = event["category"].eq("New-Issue")
		_data_ready = event["data_ready"].astype(object).map(lambda v: bool(v) if isinstance(v, (bool, int)) else str(v).strip().lower() == "true")
		event = event[~_ni_mask | _data_ready].copy()

	# Apply z-score threshold
	try:
		z_thd = float(zscore_threshold)
	except Exception:
		z_thd = 2.0

	# Mean-reversion entries governed by the SAME composite z-score and
	# per-instrument entry_z the individual-spread backtest panel would use
	# (saved params when the instrument has been reviewed, else the category
	# default preset) -- not the flat zscore_threshold/raw Zscore used
	# elsewhere. This is a same-day check against the backtest's own entry
	# rule ("would the backtest open a position on this spread today"), not a
	# multi-day open-position replay. See _add_composite_score.
	mr = _add_composite_score(mr)
	_FUTURES_CATS = {"Bond-Futures", "Futures-Term", "Futures-Swap"}
	if "category" in mr.columns and not mr.empty:
		mr_futures = mr[mr["category"].isin(_FUTURES_CATS)].copy()
		mr_other   = mr[~mr["category"].isin(_FUTURES_CATS)].copy()
		mr_other   = mr_other[mr_other["composite_z"].abs() >= mr_other["entry_z_used"]].copy()
		mr = pd.concat([mr_futures, mr_other], axis=0, ignore_index=True)
	else:
		mr = mr[mr["composite_z"].abs() >= mr["entry_z_used"]].copy()

	# Load historical series for all pre-filtered candidates before scoring.
	# 'carry' here is still the FULL pre-trend-state-split pool (Momentum is
	# carved out of it below, after this series_map is built), so this
	# already covers every instrument Momentum will end up needing too.
	all_pre = pd.concat([mr, carry, event], axis=0, ignore_index=True)
	series_map: Dict[str, pd.Series] = {}
	if not all_pre.empty and "spread_type" in all_pre.columns and "ID" in all_pre.columns:
		for stype in all_pre["spread_type"].unique().tolist():
			ids = all_pre.loc[all_pre["spread_type"].eq(stype), "ID"].astype(str).unique().tolist()
			series_map.update(
				load_historical_spread_series(stype, ids, dir_input=dir_input, lookback_days=lookback_days)
			)

	# Correlation uses human-readable display keys, whereas scoring looks up a
	# series by ``spread_type|ID``. Keep the correlation map unchanged and add
	# qualified aliases only for the scoring functions.
	scoring_series_map = series_map.copy()
	if not all_pre.empty:
		for stype, cid in zip(all_pre["spread_type"].astype(str), all_pre["ID"].astype(str)):
			display_key = _corr_display_key(stype, cid)
			if display_key in series_map:
				scoring_series_map[f"{stype}|{cid}"] = series_map[display_key]

	# Enrich with regression slope + 3m rolling vol, then score + rank.
	mr = _enrich_candidates_with_regression(mr, scoring_series_map)
	event = _enrich_candidates_with_regression(event, scoring_series_map)

	# Priority order for the Carry-eligible pool, per user 2026-09-22:
	#   1. MR already removed above (separate pool from the start).
	#   2. Momentum: STRONG trend only -- trend_state != 0 AND passes the
	#      pullback-direction gate AND |trend_momentum| >=
	#      MOMENTUM_CARRY_MIN_SCORE (the pullback z-score itself, NOT the
	#      separate 'score' expected-edge/risk column -- corrected
	#      2026-09-22 per user). Evaluated on the FULL Carry-eligible pool
	#      (not pre-split by trend_state), so a row only leaves the
	#      Carry-eligible pool if it actually clears the full momentum bar
	#      -- not merely because it has SOME historical trend direction.
	#   3. Carry: everything that did NOT qualify for Momentum (including
	#      trend_state != 0 rows that failed the pullback/Zscore gate) is
	#      then evaluated against Carry's own sigma/bp/vol gates. A weakly-
	#      trending but well-compensated carry spread can still surface here.
	carry_pool = _enrich_candidates_with_regression(carry, scoring_series_map)
	momentum_candidates = _add_momentum_ma_zscore(carry_pool.copy(), scoring_series_map)
	if not momentum_candidates.empty:
		momentum_candidates["style"] = "Momentum"

	mr = _add_unified_score_preview(mr)
	momentum_candidates = _add_unified_score_preview(momentum_candidates)
	event = _add_unified_score_preview(event)

	# Mean-reversion direction follows the platform's economic convention:
	# BUY profits when the spread falls, so an extreme high composite z-score
	# is a BUY; SELL profits when the spread rises, so an extreme low
	# composite z-score is a SELL. Uses composite_z (carry-adjusted, per-
	# instrument entry_z) rather than raw Zscore/zscore_threshold, so the
	# side shown here is the actual side the backtest's own entry rule would
	# take today, not just today's raw deviation.
	# Momentum direction: trend_state sets the established direction
	# (BUY=downtrend/expect fall, SELL=uptrend/expect rise); z_t must be the
	# OPPOSITE sign — a mild pullback against that trend — so there is still
	# room left to continue. z_t agreeing in sign with trend_state means the
	# move already ran recently (chase risk, limited margin/low odds) and is
	# excluded; a pullback beyond the stretch cap is excluded too (that size
	# of countertrend move risks being a reversal, not a retracement).
	if not mr.empty:
		mr_composite_z = pd.to_numeric(mr["composite_z"], errors="coerce")
		mr.loc[mr_composite_z.ge(mr["entry_z_used"]), "direction"] = "BUY"
		mr.loc[mr_composite_z.le(-mr["entry_z_used"]), "direction"] = "SELL"

	if not momentum_candidates.empty:
		trend_state = pd.to_numeric(momentum_candidates.get("trend_state", pd.Series(np.nan, index=momentum_candidates.index)), errors="coerce")
		trend_zt = pd.to_numeric(momentum_candidates.get("trend_momentum", momentum_candidates.get("Zscore", pd.Series(np.nan, index=momentum_candidates.index))), errors="coerce")
		stretch_cap = abs(z_thd * float(momentum_stretch_mult))
		trend_dir = pd.Series("", index=momentum_candidates.index, dtype=str)
		trend_dir.loc[trend_state.lt(0) & trend_zt.gt(0) & trend_zt.lt(stretch_cap)] = "BUY"
		trend_dir.loc[trend_state.gt(0) & trend_zt.lt(0) & trend_zt.gt(-stretch_cap)] = "SELL"
		momentum_candidates["direction"] = trend_dir
		momentum_candidates = momentum_candidates[momentum_candidates["direction"].isin(["BUY", "SELL"])].copy()

		# Zscore-magnitude gate: |trend_momentum| (the SAME pullback z-score
		# used for direction just above, i.e. the row's 'Zscore' column,
		# since _add_momentum_ma_zscore overwrites Zscore with this value)
		# must clear MOMENTUM_CARRY_MIN_SCORE sigma units -- a pullback that
		# is too small isn't a meaningfully sized retracement, even though
		# it's the right sign and under the stretch_cap ceiling. Combines
		# with the pullback-direction window above into
		# MOMENTUM_CARRY_MIN_SCORE <= |trend_momentum| < stretch_cap.
		# Corrected 2026-09-22 per user: this gate checks the Zscore/
		# trend_momentum pullback magnitude, NOT the separate 'score'
		# (expected-edge/risk) column -- score remains a ranking/display
		# field only for Momentum rows, not an entry gate.
		if not momentum_candidates.empty:
			trend_zt_gate = pd.to_numeric(
				momentum_candidates.get("trend_momentum", momentum_candidates.get("Zscore")),
				errors="coerce",
			)
			momentum_candidates = momentum_candidates[trend_zt_gate.abs().ge(MOMENTUM_CARRY_MIN_SCORE)].copy()

	momentum = momentum_candidates

	# Carry is everything from the Carry-eligible pool that did NOT qualify
	# for Momentum above (per user 2026-09-22: MR removed first, then
	# STRONG trend rows are pulled out as Momentum, then the remainder --
	# including trend_state!=0 rows that failed the pullback/score gate --
	# is evaluated as Carry). Match on (spread_type, ID) since momentum was
	# scored/enriched as its own copy of the pool.
	if "spread_type" in carry_pool.columns and "ID" in carry_pool.columns:
		momentum_keys = set(
			zip(momentum["spread_type"].astype(str), momentum["ID"].astype(str))
		) if not momentum.empty and "spread_type" in momentum.columns else set()
		carry_keys = list(zip(carry_pool["spread_type"].astype(str), carry_pool["ID"].astype(str)))
		not_in_momentum = [k not in momentum_keys for k in carry_keys]
		carry = carry_pool[pd.Series(not_in_momentum, index=carry_pool.index)].copy()
	else:
		carry = carry_pool.copy()
	carry = _add_unified_score_preview(carry)

	# Carry direction/gate: sign of carry_sigma sets the side (positive
	# carry_sigma -> BUY the carry). Entry requires ALL THREE:
	#   1. |carry_sigma| >= CARRY_MIN_SIGMA (vol-relative magnitude)
	#   2. |carry_roll| >= CARRY_MIN_ROLL_BP (absolute bp floor -- catches a
	#      row that only clears gate 1 because its vol is tiny, not because
	#      carry itself is economically worth trading)
	#   3. vol <= CARRY_VOL_PCTILE quantile of the pre-gate Carry pool's own
	#      vol (relative low-vol filter -- a carry trade is held for the
	#      running yield, not traded for P&L on the spread moving, so it
	#      should be a comparatively QUIET spread; self-calibrating across
	#      spread types/days rather than a fixed absolute vol number, since
	#      Repo7d/TBondSwap/TenorSpread vol scales differ a lot -- see
	#      CARRY_VOL_PCTILE docstring). Quantile taken over this bucket
	#      BEFORE gates 1-2 shrink it, so it reflects "quieter than a
	#      typical carry candidate today", not the post-gate survivors.
	# All three independent of any trend/momentum signal. Applies uniformly
	# whether the row is a genuine Bond-Futures carry trade or a
	# Swap-Spread/Tenor-Spread row that fell back to style="Carry" after
	# failing the MR stationarity test (see CARRY_MIN_SIGMA docstring above).
	if not carry.empty:
		carry_sigma = _carry_sigma(carry)
		carry["carry_sigma"] = carry_sigma
		carry_roll_bp_abs = pd.to_numeric(carry.get("carry_roll"), errors="coerce").abs()
		clears_roll_floor = carry_roll_bp_abs.ge(CARRY_MIN_ROLL_BP)

		carry_vol = pd.to_numeric(carry.get("risk_vol_63d"), errors="coerce").abs()
		carry_vol = carry_vol.where(carry_vol.gt(0) & carry_vol.notna(), pd.to_numeric(carry.get("vol"), errors="coerce").abs())
		vol_cap = carry_vol.quantile(CARRY_VOL_PCTILE) if carry_vol.notna().any() else np.nan
		clears_vol_gate = carry_vol.le(vol_cap) if pd.notna(vol_cap) else pd.Series(True, index=carry.index)

		carry_dir = pd.Series("", index=carry.index, dtype=str)
		_carry_passes = clears_roll_floor & clears_vol_gate
		carry_dir.loc[carry_sigma.ge(CARRY_MIN_SIGMA) & _carry_passes] = "BUY"
		carry_dir.loc[carry_sigma.le(-CARRY_MIN_SIGMA) & _carry_passes] = "SELL"
		carry["direction"] = carry_dir
		carry = carry[carry["direction"].isin(["BUY", "SELL"])].copy()

	# EventDriven (New-Issue): no trend/momentum or score gate -- these rows
	# are event-mechanics driven (roll pressure), not price-signal driven,
	# and already carry their own direction from alpha_snapshot.py's
	# BondNewIssue block (defaults to "BUY" if not otherwise set).
	if not event.empty and "direction" not in event.columns:
		event["direction"] = "BUY"

	# ── Execution-feasibility filters ──────────────────────────────────────────
	_SELL_RESTRICTED_CATEGORIES = {"Bond-Swap", "Bond-Curve"}
	_style_buckets = [mr, momentum, carry, event]
	_style_buckets = [
		b[~(b["category"].isin(_SELL_RESTRICTED_CATEGORIES) & b["direction"].eq("SELL"))].copy()
		if "category" in b.columns and "direction" in b.columns else b
		for b in _style_buckets
	]
	mr, momentum, carry, event = _style_buckets

	# SwapSpread liquidity gate: only anchor-tenor-both-legs instruments (see
	# is_swapspread_liquid) are eligible as standalone RV candidates here.
	# Off-anchor combinations (Repo7d-4y5y, Shi3M-2y3y, ...) are real
	# instruments used for rebalancing an existing position's duration as it
	# ages (e.g. a 5y position rolling into 4y5y to hold the 5y point), not
	# for sizing new RV positions -- excluded from the scanner, not from the
	# underlying data (SwapSpread-spds.pkl / TenorSpread's carried-over
	# subset are unaffected; risk/portfolio reporting on an existing
	# rebalance-driven position still resolves normally).
	def _drop_illiquid_swapspread(b: pd.DataFrame) -> pd.DataFrame:
		if "spread_type" not in b.columns or "ID" not in b.columns:
			return b
		swap_mask = b["spread_type"].eq("SwapSpread")
		if not swap_mask.any():
			return b
		illiquid = swap_mask & ~b["ID"].astype(str).map(is_swapspread_liquid)
		return b[~illiquid].copy()

	mr = _drop_illiquid_swapspread(mr)
	momentum = _drop_illiquid_swapspread(momentum)
	carry = _drop_illiquid_swapspread(carry)
	event = _drop_illiquid_swapspread(event)

	mr = mr.sort_values(["score"], ascending=False).head(int(max_per_style)).copy()
	momentum = momentum.sort_values(["score"], ascending=False).head(int(max_per_style)).copy()
	carry = carry.sort_values(["score"], ascending=False).head(int(max_per_style)).copy()
	event = event.sort_values(["score"], ascending=False).head(int(max_per_style)).copy()

	candidates = pd.concat([mr, momentum, carry, event], axis=0, ignore_index=True)
	if candidates.empty:
		return {"asof": pd.Timestamp.now(), "candidates": candidates, "selected_lowcorr": pd.DataFrame(), "corr": None}

	corr, _ = compute_candidate_correlation(series_map)
	# Add correlation key to candidates (even if corr is None)
	candidates["corr_key"] = [
		_corr_display_key(stype, cid)
		for stype, cid in zip(candidates["spread_type"].astype(str), candidates["ID"].astype(str))
	]

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
			"momentum_stretch_mult": float(momentum_stretch_mult),
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
	momentum_stretch_mult: float = 1.5,
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
		momentum_stretch_mult=momentum_stretch_mult,
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
	momentum_stretch_mult: float = 1.5,
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
		momentum_stretch_mult=momentum_stretch_mult,
		max_per_style=max_per_style,
		lookback_days=lookback_days,
		max_abs_corr=max_abs_corr,
		top_n_low_corr=top_n_low_corr,
		rewrite=True,
	)
	obj = pd.read_pickle(paths.out_candidates)
	return obj if isinstance(obj, dict) else {}
