"""Periodic refresh pipeline — the intraday hot-path.

Runs the curve refreshers (rates → credit → IRS → stat/alpha) to update
``DIR_INPUT`` artifacts without a full recalibration.  Designed to be
called every N minutes during trading hours by the scheduler.
"""
from __future__ import annotations

import logging
from datetime import datetime

from engine.artifacts import ArtifactStore, write_json
from engine.context import RunConfig

logger = logging.getLogger(__name__)

# Ordered refresh steps.  Each tuple is (step_name, module_path, function_name).
_REFRESH_STEPS: list[tuple[str, str, str]] = [
    ("rates",  "curves.interface", "refresh_rates"),
    ("credit", "curves.interface", "refresh_credit"),
    ("irs",    "curves.interface", "refresh_irs"),
    ("stat",   "curves.interface", "refresh_stat"),
]


def run(cfg: RunConfig, *, steps: list[str] | None = None) -> dict[str, str]:
    """Run the refresh pipeline.

    Parameters
    ----------
    cfg : RunConfig
        Execution context (asof, mode, output_dir, input_dir).
    steps : list[str] | None
        If given, only run these step names (e.g. ``["rates", "irs"]``).
        Defaults to all steps.

    Returns
    -------
    dict[str, str]
        Mapping of step_name → ``"ok"`` | ``"failed"`` | ``"skipped"``.
    """
    logger.info("Refresh run started: run_id=%s asof=%s", cfg.run_id, cfg.asof)
    store = ArtifactStore(cfg.input_dir)

    import importlib

    step_status: dict[str, str] = {}
    for step_name, module_path, func_name in _REFRESH_STEPS:
        if steps and step_name not in steps:
            step_status[step_name] = "skipped"
            continue

        logger.info("── Refresh step: %s ───────────────────────────", step_name)
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            fn(cfg, store)
            step_status[step_name] = "ok"
        except Exception:
            logger.exception("Refresh step '%s' failed — continuing", step_name)
            step_status[step_name] = "failed"

    # Write run metadata
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

    logger.info("Refresh run finished. Steps: %s  Output: %s", step_status, cfg.output_dir)
    return step_status
