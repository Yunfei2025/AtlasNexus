"""Thin interface for the pipeline layer to call factor analysis.

Every public function follows the signature ``(cfg, store) -> result``
where *cfg* is a :class:`engine.context.RunConfig` and *store* is an
:class:`engine.artifacts.ArtifactStore`.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.artifacts import ArtifactStore
    from engine.context import RunConfig

logger = logging.getLogger(__name__)


def calibrate(cfg: RunConfig, store: ArtifactStore) -> dict[str, Any] | None:
    """Run full factor analysis (daily EOD).

    Delegates to :func:`factors.engine.factor_engine.run_analysis` via
    the config manager for dates and tickers.

    Returns a slim JSON-serializable summary — the full ``FactorAnalysisResults``
    object contains DataFrames and trained models that cannot be JSON-serialized,
    so only scalar metrics and factor names are extracted.
    """
    logger.info("[factors] Starting factor analysis (asof=%s)", cfg.asof)
    try:
        import importlib
        fe = importlib.import_module("factors.engine.factor_engine")
        cfg_mod = importlib.import_module("factors.config")
        config_manager = cfg_mod.config_manager

        date_config = config_manager.date_config
        model_config = config_manager.model_config

        results = fe.run_analysis(
            start_date=date_config.day_data_start_date,
            end_date=date_config.day_data_end_date,
            ticker=model_config.ticker,
        )

        summary = _extract_factors_summary(cfg.asof.isoformat(), results, model_config)
        logger.info("[factors] Factor analysis completed (status=%s)", summary.get("status"))
        return summary

    except Exception:
        logger.exception("[factors] Factor analysis failed")
        raise


def _extract_factors_summary(asof: str, results: Any, model_config: Any) -> dict[str, Any]:
    """Extract a JSON-serializable summary from a FactorAnalysisResults object.

    The full results object contains DataFrames, Series, and trained sklearn
    models — none of which are JSON-serializable. This function pulls out only
    the scalar fields that are useful for the run artifact and the web UI.
    """
    base: dict[str, Any] = {
        "asof": asof,
        "ticker": getattr(model_config, "ticker", None),
        "status": "failed",
    }
    if results is None:
        return base

    base["status"] = getattr(results, "status", "unknown")

    # AnalysisStats — all scalars
    stats = getattr(results, "stats", None)
    if stats is not None:
        base["stats"] = {
            "total_periods": int(getattr(stats, "total_periods", 0)),
            "successful_periods": int(getattr(stats, "successful_periods", 0)),
            "success_rate": float(getattr(stats, "success_rate", 0.0)),
        }

    # BacktestMetrics — all scalars
    bm = getattr(results, "backtest_metrics", None)
    if bm is not None:
        base["backtest_metrics"] = {
            "total_return": float(getattr(bm, "total_return", 0.0)),
            "annual_return": float(getattr(bm, "annual_return", 0.0)),
            "volatility": float(getattr(bm, "volatility", 0.0)),
            "sharpe_ratio": float(getattr(bm, "sharpe_ratio", 0.0)),
            "max_drawdown": float(getattr(bm, "max_drawdown", 0.0)),
            "win_rate": float(getattr(bm, "win_rate", 0.0)),
        }

    # Selected factors — list of strings from first successful period
    selected: list[str] = []
    for pr in getattr(results, "period_results", []):
        factors = getattr(pr, "selected_factors", None)
        if factors:
            selected = [str(f) for f in factors]
            break
    base["selected_factors"] = selected

    return base
