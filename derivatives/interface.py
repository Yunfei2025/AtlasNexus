"""Thin interface for the pipeline layer to call derivatives modules.

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
    """Run derivative pricing / vol analysis (daily EOD).

    This step is optional and only runs if the pricer module is available.

    Returns a JSON-serializable dict of option greeks (price, delta, gamma,
    vega, theta, rho) enriched with the run asof date.
    """
    logger.info("[derivatives] Starting pricing (asof=%s)", cfg.asof)
    try:
        from derivatives.pricer.main import main as _pricer_main
        results = _pricer_main(option_type_choice="bond")
        logger.info("[derivatives] Pricing completed")
        if isinstance(results, dict):
            return {"asof": cfg.asof.isoformat(), **results}
        return {"asof": cfg.asof.isoformat()}
    except ImportError:
        logger.info("[derivatives] Pricer module not available — skipping")
        return None
    except Exception:
        logger.exception("[derivatives] Pricing failed")
        raise
