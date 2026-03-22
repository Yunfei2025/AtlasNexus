from __future__ import annotations

import logging
from datetime import datetime

from engine.artifacts import ArtifactStore, write_json
from engine.context import RunConfig
from engine.data_update import load_default_retrievers, run_data_update

logger = logging.getLogger(__name__)

# Ordered list of (step_name, module_path, function_name).
# Each interface module exposes ``calibrate(cfg, store) -> Any``.
_EOD_STEPS: list[tuple[str, str, str]] = [
    ("curves",      "curves.interface",      "calibrate"),
    ("factors",     "factors.interface",      "calibrate"),
    ("pairs",       "pairs.interface",        "calibrate"),
    ("futures",     "futures.interface",      "calibrate"),
    ("multiasset",  "multiasset.interface",   "calibrate"),
    ("derivatives", "derivatives.interface",  "calibrate"),
]


def run(cfg: RunConfig, *, update_data: bool = False) -> dict[str, str]:
    """Run the daily EOD pipeline.

    Execution order:
      0. (optional) update data via retrieve.py modules
      1. curves   – full calibration chain (Trend → BondCurve → Credit → IRS → Stat → Pairs)
      2. factors  – factor model training + signal generation
      3. pairs    – pair regression analysis
      4. futures  – daily portfolio strategy analysis
      5. multiasset – universe construction + factor optimizer
      6. derivatives – option pricing / vol analysis

    Each step is isolated behind its ``interface.calibrate(cfg, store)``
    entry point.  A failing step is logged and recorded but does **not**
    abort downstream steps (best-effort).
    """

    logger.info("EOD run started: run_id=%s asof=%s", cfg.run_id, cfg.asof)
    store = ArtifactStore(cfg.input_dir)

    # ── 0. Data retrieval ──────────────────────────────────────────────
    if update_data:
        load_default_retrievers()
        run_data_update(cfg)

    # ── 1-6. Module calibration steps ──────────────────────────────────
    step_status: dict[str, str] = {}
    import importlib

    for step_name, module_path, func_name in _EOD_STEPS:
        logger.info("── Step: %s ─────────────────────────────────", step_name)
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            fn(cfg, store)
            step_status[step_name] = "ok"
        except Exception:
            logger.exception("Step '%s' failed — continuing with next step", step_name)
            step_status[step_name] = "failed"

    # ── 7. Factor signals (existing logic kept for backward compat) ────
    signal_snapshot = _compute_factor_signals(cfg)
    if signal_snapshot:
        step_status["factor_signals"] = "ok"

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

    logger.info("EOD run finished. Steps: %s  Output: %s", step_status, cfg.output_dir)
    return step_status


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
