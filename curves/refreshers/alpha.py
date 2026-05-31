"""Alpha generator: normalize spread signals for UI scanning.

This module is a re-export shim that delegates to three focused submodules:

- alpha_snapshot  — file paths, data helpers, snapshot build/save/load
- alpha_scoring   — scoring engine (trend metrics, unified score)
- alpha_candidates — candidate pipeline (correlation, basket selection)

All public symbols are re-exported here so existing imports continue to work.
"""

from __future__ import annotations

# ── Re-export everything from the three submodules ───────────────────────────
from curves.refreshers.alpha_snapshot import (  # noqa: F401
    ALPHA_SNAPSHOT_FILENAME,
    ALPHA_CANDIDATES_FILENAME,
    _HORIZON_DAYS,
    _REG_LOOKBACK_DAYS,
    _RISK_VOL_WINDOW,
    _CARRY_BASIS_DAYS,
    _ANNUAL_CARRY_BASIS_DAYS,
    _BOND_CURVE_BORROW_COST_BP_ANNUAL,
    AlphaSnapshotPaths,
    _read_pickle,
    _snapshot_is_stale,
    _last_values,
    _normalize_index,
    _ensure_numeric,
    _append_snapshot_spread_to_series,
    _build_tenor_spread_timeseries,
    _exclude_swapspread_butterflies,
    build_alpha_spreads_snapshot,
    build_alpha_timeseries,
    save_alpha_spreads_snapshot,
    load_alpha_spreads_snapshot,
    get_alpha_spread_table,
)

from curves.refreshers.alpha_scoring import (  # noqa: F401
    _stationary_yes_mask,
    _compute_trend_metrics,
    _enrich_candidates_with_regression,
    _rank_score,
    _add_unified_score_preview,
)

from curves.refreshers.alpha_candidates import (  # noqa: F401
    load_historical_spread_series,
    compute_candidate_correlation,
    select_low_corr_basket,
    build_alpha_candidates,
    save_alpha_candidates,
    load_alpha_candidates,
)

from settings.paths import DIR_INPUT  # noqa: F401


if __name__ == "__main__":
	out_path = save_alpha_spreads_snapshot(DIR_INPUT, rewrite=True)
	print(f"Saved alpha snapshot: {out_path}")
