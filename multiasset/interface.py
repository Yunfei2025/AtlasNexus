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
