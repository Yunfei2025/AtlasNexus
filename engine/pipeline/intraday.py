from __future__ import annotations

import logging
from datetime import datetime

from engine.artifacts import write_json
from engine.context import RunConfig
from engine.data_update import load_default_retrievers, run_data_update

logger = logging.getLogger(__name__)


def run(cfg: RunConfig, *, update_data: bool = False) -> None:
    """Run intraday pipeline (single snapshot).

    Later, a loop/scheduler can call this periodically during trading hours.
    """

    logger.info("Intraday run started: run_id=%s asof=%s", cfg.run_id, cfg.asof)

    if update_data:
        load_default_retrievers()
        run_data_update(cfg, names=["futures.intraday.retrieve"])

    write_json(
        cfg.output_dir / "run_meta.json",
        {
            "mode": cfg.mode,
            "run_id": cfg.run_id,
            "asof": cfg.asof.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "status": "stub",
        },
    )

    logger.info("Intraday run finished (stub). Output: %s", cfg.output_dir)
