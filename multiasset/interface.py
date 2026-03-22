"""Thin interface for the pipeline layer to call multiasset modules.

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
    """Build bond + spread universes and factor optimizer snapshot.

    The multiasset module does not have a single ``main()``; instead we
    call the universe builders and optionally persist a snapshot.
    """
    logger.info("[multiasset] Building universes (asof=%s)", cfg.asof)
    try:
        from multiasset.main import create_bond_universe, create_spread_universe

        bonds = create_bond_universe()
        spreads = create_spread_universe()
        logger.info("[multiasset] Universe built: %d bonds, %d spreads",
                     len(bonds), len(spreads))
        return {"bonds": bonds, "spreads": spreads}
    except Exception:
        logger.exception("[multiasset] Universe build failed")
        raise
