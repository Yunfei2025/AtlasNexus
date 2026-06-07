from __future__ import annotations

import logging
from datetime import datetime

from engine.artifacts import ArtifactStore, write_json
from engine.context import RunConfig
from engine.data_update import load_default_retrievers, run_data_update
from engine.schema import RunManifest

logger = logging.getLogger(__name__)

# Ordered list of (step_name, module_path, function_name).
# Each interface module exposes ``calibrate(cfg, store) -> Any``.
_EOD_STEPS: list[tuple[str, str, str]] = [
    ("curves",      "curves.interface",      "calibrate"),
    ("factors",     "factors.interface",      "calibrate"),
    ("futures",     "futures.interface",      "calibrate"),
    ("multiasset",  "multiasset.interface",   "calibrate"),
    # pairs step runs on-demand only, not in EOD pipeline
    # derivatives step runs on-demand only, not in EOD pipeline
]


def run(cfg: RunConfig, *, update_data: bool = False) -> dict[str, str]:
    """Run the daily EOD pipeline.

    Execution order:
      0. (optional) update data via retrieve.py modules
      1. curves   – full calibration chain (Trend → BondCurve → Credit → IRS → Stat)
      2. factors  – factor model training + signal generation
      3. futures  – daily portfolio strategy analysis
      4. multiasset – universe construction + factor optimizer

    Each step is isolated behind its ``interface.calibrate(cfg, store)``
    entry point.  A failing step is logged and recorded but does **not**
    abort downstream steps (best-effort).

    Note: pairs (pair regression analysis) and derivatives (option pricing)
    run on-demand only, not in EOD.
    """

    logger.info("EOD run started: run_id=%s asof=%s", cfg.run_id, cfg.asof)
    store = ArtifactStore(cfg.input_dir)

    # ── 0. Data retrieval ──────────────────────────────────────────────
    if update_data:
        load_default_retrievers()
        run_data_update(cfg)

    # ── 1-6. Module calibration steps ──────────────────────────────────
    step_status: dict[str, str] = {}
    artifacts: list[str] = []
    import importlib

    for step_name, module_path, func_name in _EOD_STEPS:
        logger.info("── Step: %s ─────────────────────────────────", step_name)
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            result = fn(cfg, store)
            step_status[step_name] = "ok"
            # Capture the step's return value as a run artifact. Previously
            # discarded; persisted now (best-effort) so the run dir is a
            # reproducible record and the UI can read it instead of recomputing.
            saved = _persist_step_result(cfg, step_name, result)
            if saved:
                artifacts.append(saved)
        except Exception:
            logger.exception("Step '%s' failed — continuing with next step", step_name)
            step_status[step_name] = "failed"

    # ── 7. Factor signals (existing logic kept for backward compat) ────
    signal_snapshot = _compute_factor_signals(cfg)
    if signal_snapshot:
        step_status["factor_signals"] = "ok"
        artifacts.append("factor_signals.json")

    # ── Write run manifest (backward-compatible run_meta.json) ─────────
    RunManifest(
        run_id=cfg.run_id,
        mode=cfg.mode,
        asof=cfg.asof.isoformat(),
        generated_at=datetime.utcnow().isoformat(),
        status="completed",
        steps=step_status,
        artifacts=artifacts,
    ).write(cfg.output_dir / "run_meta.json")

    logger.info("EOD run finished. Steps: %s  Output: %s", step_status, cfg.output_dir)
    return step_status


def _persist_step_result(cfg: RunConfig, step_name: str, result: object) -> str | None:
    """Best-effort persistence of a calibrate() return value to the run dir.

    Only JSON-serializable results are written (as ``<step>_result.json``);
    non-serializable returns (DataFrames, custom objects) are skipped without
    failing the run. Returns the artifact filename if written, else ``None``.
    """
    if result is None:
        return None
    name = f"{step_name}_result.json"
    try:
        write_json(cfg.output_dir / name, result)
        return name
    except TypeError:
        logger.debug("Step '%s' result not JSON-serializable — skipping persist", step_name)
        return None
    except Exception:
        logger.warning("Failed to persist result for step '%s'", step_name, exc_info=True)
        return None


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
