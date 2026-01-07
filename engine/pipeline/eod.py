from __future__ import annotations

import logging
from datetime import datetime

from engine.artifacts import write_json
from engine.context import RunConfig
from engine.data_update import load_default_retrievers, run_data_update

logger = logging.getLogger(__name__)


def run(cfg: RunConfig, *, update_data: bool = False) -> None:
    """Run daily EOD pipeline.

    This is a thin orchestrator. It should:
    1) (optional) update data via retrieve.py modules
    2) build universe (portfolio)
    3) compute regime/factors
    4) compute RV/curves metrics (for FI selection)
    5) generate strategy signals (pairs/futures/derivatives)
    6) aggregate targets + risk (multiasset)
    7) produce manual tickets
    8) write artifacts for web monitoring

    The wiring is intentionally incremental.
    """

    logger.info("EOD run started: run_id=%s asof=%s", cfg.run_id, cfg.asof)

    if update_data:
        load_default_retrievers()
        run_data_update(cfg)

    # Stub artifact so web can show the run exists
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

    logger.info("EOD run finished (stub). Output: %s", cfg.output_dir)
