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

    # --- Step 3: Compute factor signals for risk exposure control -----------
    signal_snapshot = _compute_factor_signals(cfg)

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


# ── helpers ────────────────────────────────────────────────────────────

def _compute_factor_signals(cfg: RunConfig) -> list:
    """Run factor models for known contracts and produce a signal snapshot.

    The snapshot is written as ``factor_signals.json`` inside the run
    output directory so the web dashboard can pick it up.

    Returns the snapshot rows (list of dicts) or an empty list on failure.
    """
    try:
        import glob, os, joblib
        from settings.paths import PATH
        from factors.processing.risk_factor_mapper import (
            CONTRACT_RISK_PROFILES, decompose_signal_series,
        )
        from factors.processing.exposure_mapper import (
            BucketConfig, compute_signal_snapshot,
        )

        model_dir = os.path.join(str(PATH), 'factors')
        model_files = glob.glob(os.path.join(model_dir, 'trained_model_*.joblib'))
        if not model_files:
            logger.info("No trained factor models found — skipping signal step.")
            return []

        rf_signals: dict = {}
        for mf in model_files:
            basename = os.path.basename(mf)
            parts = basename.replace('trained_model_', '').replace('.joblib', '').split('_')
            contract = parts[0] if parts else None
            if contract not in CONTRACT_RISK_PROFILES:
                continue
            model = joblib.load(mf)
            predictions = model.get('predictions')
            if predictions is None or (hasattr(predictions, 'empty') and predictions.empty):
                continue
            decomposed = decompose_signal_series(predictions, contract)
            for col in decomposed.columns:
                if col in rf_signals:
                    rf_signals[col] = rf_signals[col].add(decomposed[col], fill_value=0)
                else:
                    rf_signals[col] = decomposed[col].copy()

        if not rf_signals:
            logger.info("No signal series produced — skipping signal step.")
            return []

        snapshot = compute_signal_snapshot(rf_signals, BucketConfig())
        if snapshot.empty:
            return []

        rows = snapshot.to_dict(orient='records')
        write_json(cfg.output_dir / "factor_signals.json", rows)
        logger.info("Factor signals written: %d factors", len(rows))
        return rows

    except Exception as exc:
        logger.warning("Factor signal computation failed: %s", exc)
        return []
