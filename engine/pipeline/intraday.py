from __future__ import annotations

import logging
from datetime import datetime

from engine.artifacts import ArtifactStore, write_json
from engine.context import RunConfig
from engine.data_update import load_default_retrievers, run_data_update

logger = logging.getLogger(__name__)


def run(cfg: RunConfig, *, update_data: bool = False) -> dict[str, str]:
    """Run the intraday pipeline (single snapshot).

    Steps:
      0. (optional) update intraday tick data via retrieve modules
      1. Refresh curves (rates + IRS — the fast-path subset)
      2. Compute factor signals from latest models

    A scheduler can call this periodically during trading hours.
    """

    logger.info("Intraday run started: run_id=%s asof=%s", cfg.run_id, cfg.asof)
    store = ArtifactStore(cfg.input_dir)

    step_status: dict[str, str] = {}

    # ── 0. Intraday data retrieval ─────────────────────────────────────
    if update_data:
        try:
            load_default_retrievers()
            run_data_update(cfg, names=["futures.intraday.retrieve"])
            step_status["data_update"] = "ok"
        except Exception:
            logger.exception("Intraday data update failed — continuing")
            step_status["data_update"] = "failed"

    # ── 1. Quick curve refresh (rates only) ────────────────────────────
    try:
        from curves.interface import refresh_rates
        refresh_rates(cfg, store)
        step_status["refresh_rates"] = "ok"
    except Exception:
        logger.exception("Intraday rates refresh failed — continuing")
        step_status["refresh_rates"] = "failed"

    # ── 2. Factor signals from existing trained models ─────────────────
    try:
        from engine.pipeline.eod import _compute_factor_signals
        signals = _compute_factor_signals(cfg)
        step_status["factor_signals"] = "ok" if signals else "empty"
    except Exception:
        logger.exception("Intraday factor signal computation failed")
        step_status["factor_signals"] = "failed"

    # ── Write run metadata ─────────────────────────────────────────────
    write_json(
        cfg.output_dir / "run_meta.json",
        {
            "mode": cfg.mode,
            "run_id": cfg.run_id,
            "asof": cfg.asof.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "status": "completed",
            "steps": step_status,
        },
    )

    logger.info("Intraday run finished. Steps: %s  Output: %s", step_status, cfg.output_dir)
    return step_status
