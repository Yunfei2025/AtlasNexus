"""Thin interface for the pipeline layer to call pair analysis.

Every public function follows the signature ``(cfg, store) -> result``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.artifacts import ArtifactStore
    from engine.context import RunConfig

logger = logging.getLogger(__name__)


def calibrate(cfg: RunConfig, store: ArtifactStore) -> dict:
    """Run pair regression analysis (daily EOD).

    Delegates to :func:`pairs.main.main` in standalone (non-Excel) mode.

    Returns a slim JSON-serializable summary — the full results dict maps
    pair names to ``RegressionResults`` objects (custom dataclass, not
    JSON-serializable), so only pair names and counts are extracted.
    """
    logger.info("[pairs] Starting pair analysis (asof=%s)", cfg.asof)
    try:
        from pairs.main import main as _pairs_main
        results = _pairs_main(excel_mode=False)
        pair_names = sorted(results.keys()) if results else []
        logger.info("[pairs] Pair analysis completed: %d pairs", len(pair_names))
        return {
            "asof": cfg.asof.isoformat(),
            "pair_count": len(pair_names),
            "pairs": pair_names,
        }
    except Exception:
        logger.exception("[pairs] Pair analysis failed")
        raise
