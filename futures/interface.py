"""Thin interface for the pipeline layer to call futures analysis.

Every public function follows the signature ``(cfg, store) -> result``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.artifacts import ArtifactStore
    from engine.context import RunConfig

logger = logging.getLogger(__name__)


def calibrate(cfg: RunConfig, store: ArtifactStore) -> dict[str, Any] | None:
    """Run daily futures portfolio strategy analysis.

    Returns a JSON-serializable summary dict so ``engine.pipeline.eod`` can
    persist it as ``futures_result.json`` in the run dir. The web layer can
    then read this artifact via ``web.services.artifacts.load_step_result``
    instead of recomputing.

    Returns None on failure (pipeline continues best-effort).
    """
    logger.info("[futures] Starting daily analysis (asof=%s)", cfg.asof)
    try:
        from futures.daily.main import main as _daily_main, run_with_summary
        _daily_main()
        logger.info("[futures] Daily analysis completed")

        # Build a serializable summary for the run artifact.
        summary = run_with_summary()
        if summary:
            logger.info(
                "[futures] Summary built: symbol=%s period=%s→%s strategies=%s",
                summary.get("symbol"),
                summary.get("period_start"),
                summary.get("period_end"),
                list(summary.get("strategies", {}).keys()),
            )
            return {
                "asof": cfg.asof.isoformat(),
                "symbol": summary["symbol"],
                "period_start": summary["period_start"],
                "period_end": summary["period_end"],
                "strategies": summary["strategies"],
            }
        return None

    except Exception:
        logger.exception("[futures] Daily analysis failed")
        raise
