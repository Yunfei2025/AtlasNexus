"""Thin interface for the pipeline layer to call multiasset modules.

Every public function follows the signature ``(cfg, store) -> result``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from engine.artifacts import ArtifactStore
    from engine.context import RunConfig

logger = logging.getLogger(__name__)


def calibrate(cfg: RunConfig, store: ArtifactStore) -> dict[str, Any] | None:
    """Build bond + spread universes and factor optimizer snapshot.

    The multiasset module does not have a single ``main()``; instead we
    call the universe builders and optionally persist a snapshot.

    Returns a slim JSON-serializable summary — the full universe objects
    (``MultiFactorBondAsset``, ``Asset``) are not JSON-serializable, so
    only names and counts are extracted.
    """
    logger.info("[multiasset] Building universes (asof=%s)", cfg.asof)
    try:
        from multiasset.main import create_bond_universe, create_spread_universe

        bonds = create_bond_universe()
        spreads = create_spread_universe()
        bond_names = [getattr(b, "name", str(b)) for b in bonds]
        spread_names = [getattr(s, "name", str(s)) for s in spreads]
        logger.info("[multiasset] Universe built: %d bonds, %d spreads",
                     len(bonds), len(spreads))
        return {
            "asof": cfg.asof.isoformat(),
            "bond_count": len(bonds),
            "spread_count": len(spreads),
            "bond_names": bond_names,
            "spread_names": spread_names,
        }
    except Exception:
        logger.exception("[multiasset] Universe build failed")
        raise


def calibrate_rolldown(cfg: RunConfig, store: ArtifactStore) -> dict[str, Any] | None:
    """CGB Stage-1 risk parity + roll-down tilt (Approach 1, simple tilt).

    See docs/dev/rates_risk_budget_rolldown_approach1.md §7. Stage 1 solves
    a closed-form factor risk-parity target ``e*`` across Level/Slope/
    Curvature; the roll-down tilt then moves a fraction of DV01 onto the
    tenor with the best risk-adjusted carry + roll-down, funded pro-rata
    from the rest of the book.

    ``cfg.params['cgb_rolldown_tilt_pct']`` overrides the tilt fraction
    (default 0.20) — the one knob to calibrate via backtest.
    """
    from .config import CURVE_CONFIG
    from .pca_analyzer import CN_IR_TENORS
    from .rolldown import cn_loading_matrix, run_rolldown_tilt

    logger.info("[multiasset] Roll-down tilt (asof=%s)", cfg.asof)
    try:
        pkl_file, pkl_key, cols = CURVE_CONFIG['CN']
        data = pd.read_pickle(cfg.input_dir / pkl_file)[pkl_key][cols]
        col_to_tenor = dict(zip(cols, CN_IR_TENORS))
        data = data.rename(columns=col_to_tenor).dropna()
        data.index = pd.to_datetime(data.index)

        tenors = list(CN_IR_TENORS)
        data = data.loc[data.index <= pd.Timestamp(cfg.asof)]
        asof_row = data.iloc[-1]
        lookback = data.loc[data.index >= asof_row.name - pd.DateOffset(years=1), tenors]
        dy = lookback.diff().dropna()

        B = cn_loading_matrix()
        sigma_k = (dy.values @ B).std(axis=0)
        b_k = np.array([1 / 3, 1 / 3, 1 / 3])
        e_star = np.sqrt(b_k) / sigma_k  # sigma_p = 1.0 (arbitrary common scale)

        w_baseline = pd.Series(np.linalg.pinv(B.T) @ e_star, index=tenors)
        tilt_pct = cfg.params.get("cgb_rolldown_tilt_pct", 0.20)

        result = run_rolldown_tilt(
            asof_row[tenors], w_baseline, e_star, level_vol=sigma_k[0], tilt_pct=tilt_pct,
        )
        result["asof"] = cfg.asof.isoformat()
        logger.info("[multiasset] Roll-down T*=%s", result["t_star"])
        return result
    except Exception:
        logger.exception("[multiasset] Roll-down tilt failed")
        raise
