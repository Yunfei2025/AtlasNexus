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


def calibrate(cfg: RunConfig, store: ArtifactStore) -> None:
    """Run pair regression analysis (daily EOD).

    Delegates to :func:`pairs.main.main` in standalone (non-Excel) mode.
    """
    logger.info("[pairs] Starting pair analysis (asof=%s)", cfg.asof)
    try:
        from pairs.main import main as _pairs_main
        _pairs_main(excel_mode=False)
        logger.info("[pairs] Pair analysis completed")
    except Exception:
        logger.exception("[pairs] Pair analysis failed")
        raise
