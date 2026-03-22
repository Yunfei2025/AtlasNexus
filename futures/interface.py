"""Thin interface for the pipeline layer to call futures analysis.

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
    """Run daily futures portfolio strategy analysis."""
    logger.info("[futures] Starting daily analysis (asof=%s)", cfg.asof)
    try:
        from futures.daily.main import main as _daily_main
        _daily_main()
        logger.info("[futures] Daily analysis completed")
    except Exception:
        logger.exception("[futures] Daily analysis failed")
        raise
