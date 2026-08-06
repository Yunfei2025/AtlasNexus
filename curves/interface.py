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
        from settings.fixed_income import BondConfig

        for bond_type in BondConfig.INCLUDE_FILTERS.keys():
            logger.info("[curves] Refreshing credit spread for %s", bond_type)
            CreditSpreadRefresher.main(other_bond_type=bond_type)
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


# ── OTR/OFR (mature RV + BondNewIssue event strategy) ────────────────────

def calibrate_otr_ofr(cfg: RunConfig, store: ArtifactStore) -> dict:
    """Refresh both OTR/OFR strategies (see docs/dev/tbondcurve-30y-otr-ofr-plan.md).

    Runs independently per sub-step (best-effort): a failure in one asset
    class or artifact never blocks the others.
      1. Live daily universe append (BondRT) for TBond/CBond.
      2. BondNewIssue-spds.pkl aggregation (event strategy StatInfo/Spread).
      3. otr_ofr_rv merge of mature pairs into TBond-spds.pkl/CBond-spds.pkl.
    """
    status: dict[str, str] = {}
    from curves.calibration.otr_ofr_universe import refresh_new_issue_universe

    for asset_class in ("TBond", "CBond"):
        try:
            refresh_new_issue_universe(asset_class, daily=True, update=True)
            status[f"universe_{asset_class}"] = "ok"
        except Exception:
            logger.exception("[curves] OTR/OFR universe refresh failed for %s", asset_class)
            status[f"universe_{asset_class}"] = "failed"

    try:
        from curves.refreshers.newissue_spreads import refresh_new_issue_spreads
        refresh_new_issue_spreads(refresh_universe=False, update=True, daily=True)
        status["newissue_spreads"] = "ok"
    except Exception:
        logger.exception("[curves] BondNewIssue-spds.pkl refresh failed")
        status["newissue_spreads"] = "failed"

    for asset_class in ("TBond", "CBond"):
        try:
            from curves.refreshers.otr_ofr_rv import refresh_otr_ofr_rv_spreads, refresh_otr_ofr_rv_realtime
            refresh_otr_ofr_rv_spreads(asset_class, update=True)
            refresh_otr_ofr_rv_realtime(asset_class, update=True)
            status[f"otr_ofr_rv_{asset_class}"] = "ok"
        except Exception:
            logger.exception("[curves] otr_ofr_rv merge failed for %s", asset_class)
            status[f"otr_ofr_rv_{asset_class}"] = "failed"

    return status
