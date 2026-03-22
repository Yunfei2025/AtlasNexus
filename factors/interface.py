"""Thin interface for the pipeline layer to call factor analysis.

Every public function follows the signature ``(cfg, store) -> result``
where *cfg* is a :class:`engine.context.RunConfig` and *store* is an
:class:`engine.artifacts.ArtifactStore`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.artifacts import ArtifactStore
    from engine.context import RunConfig

logger = logging.getLogger(__name__)


def calibrate(cfg: RunConfig, store: ArtifactStore) -> dict[str, Any] | None:
    """Run full factor analysis (daily EOD).

    Delegates to :func:`factors.engine.factor_engine.run_analysis` via
    the config manager for dates and tickers.
    """
    logger.info("[factors] Starting factor analysis (asof=%s)", cfg.asof)
    try:
        import importlib
        fe = importlib.import_module("factors.engine.factor_engine")
        cfg_mod = importlib.import_module("factors.config")
        config_manager = cfg_mod.config_manager

        date_config = config_manager.date_config
        model_config = config_manager.model_config

        results = fe.run_analysis(
            start_date=date_config.day_data_start_date,
            end_date=date_config.day_data_end_date,
            ticker=model_config.ticker,
        )
        logger.info("[factors] Factor analysis completed (status=%s)",
                     results.get("status") if results else "none")
        return results
    except Exception:
        logger.exception("[factors] Factor analysis failed")
        raise
