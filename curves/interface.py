"""Thin interface for the pipeline layer to call curves calibration and refresh.

Every public function follows the signature ``(cfg, store) -> None``
where *cfg* is a :class:`engine.context.RunConfig` and *store* is an
:class:`engine.artifacts.ArtifactStore`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.artifacts import ArtifactStore
    from engine.context import RunConfig
     

logger = logging.getLogger(__name__)


# ── EOD (full calibration) ────────────────────────────────────────────────

def calibrate(cfg: RunConfig, store: ArtifactStore) -> dict:
    """Run the full curve generation chain (daily EOD).

    Delegates to :func:`curves.initialise.main` which runs
    Trend → BondCurve(TBond/CBond) → CreditSpread → IRS → Stat → Pairs
    generators sequentially, writing artifacts to ``DIR_INPUT``.

    Returns a slim JSON-serializable summary persisted by the engine as
    ``curves_result.json`` in the run dir.

    Note: Requires data retrieval (Wind, Bloomberg, etc.) to have been run first.
    If data is unavailable, calibration is skipped and logged as a warning.
    """
    logger.info("[curves] Starting full calibration (asof=%s)", cfg.asof)
    try:
        from curves.initialise import main as _calibrate_main
        status = _calibrate_main(asof=cfg.asof.date() if hasattr(cfg.asof, 'date') else cfg.asof)
        logger.info("[curves] Full calibration completed: %s", status)
        return {"asof": cfg.asof.isoformat(), "status": status or "completed"}
    except Exception as e:
        error_msg = str(e).lower()
        # If data hasn't been retrieved (Wind/Bloomberg unavailable), skip gracefully
        if any(keyword in error_msg for keyword in ["wind", "outside trading hours", "quota"]):
            logger.warning(
                "[curves] Calibration skipped (data retrieval required): %s. "
                "Run with data_update=True to fetch Wind/Bloomberg data first.",
                e
            )
            return {
                "asof": cfg.asof.isoformat(),
                "status": "skipped",
                "reason": "data_retrieval_required"
            }
        logger.exception("[curves] Full calibration failed")
        raise


# ── Refresh (intraday hot-path) ──────────────────────────────────────────

def refresh_rates(cfg: RunConfig, store: ArtifactStore) -> None:
    """Refresh bond curve pricing (TBond + CBond)."""
    logger.info("[curves] Refreshing rates curves")
    try:
        from curves.refreshers.rates import BondCurveRefresher
        for bond_type in ("TBond", "CBond"):
            BondCurveRefresher.main(bond_type=bond_type)
        logger.info("[curves] Rates refresh done")
    except Exception:
        logger.exception("[curves] Rates refresh failed")
        raise


def refresh_credit(cfg: RunConfig, store: ArtifactStore) -> None:
    """Refresh credit spread curves."""
    logger.info("[curves] Refreshing credit spreads")
    try:
        from curves.refreshers.credit import CreditSpreadRefresher
        CreditSpreadRefresher.main()
        logger.info("[curves] Credit refresh done")
    except Exception:
        logger.exception("[curves] Credit refresh failed")
        raise


def refresh_irs(cfg: RunConfig, store: ArtifactStore) -> None:
    """Refresh IRS curves."""
    logger.info("[curves] Refreshing IRS curves")
    try:
        from curves.refreshers.irs import IRSRefresher
        IRSRefresher.main()
        logger.info("[curves] IRS refresh done")
    except Exception:
        logger.exception("[curves] IRS refresh failed")
        raise


def refresh_stat(cfg: RunConfig, store: ArtifactStore) -> None:
    """Refresh spread statistics (bonds, swaps, alpha)."""
    logger.info("[curves] Refreshing spread statistics")
    try:
        from curves.refreshers.stat import StatRefresher
        StatRefresher.main()
        logger.info("[curves] Stat refresh done")
    except Exception:
        logger.exception("[curves] Stat refresh failed")
        raise


def refresh_all(cfg: RunConfig, store: ArtifactStore) -> None:
    """Run the full refresh chain: rates → credit → IRS → stat."""
    refresh_rates(cfg, store)
    refresh_credit(cfg, store)
    refresh_irs(cfg, store)
    refresh_stat(cfg, store)
