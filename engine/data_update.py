from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from engine.context import RunConfig
from engine.registry import get_retrievers, register_retriever

logger = logging.getLogger(__name__)


DEFAULT_RETRIEVER_MODULES: list[str] = [
    # Central provider-style
    "data.providers.retrieve",
    # Curves / surfaces
    "curves.utils.retrieve",
    # Multiasset
    "multiasset.retrieve",
    # Futures intraday
    "futures.intraday.retrieve",
    # Factors helper
    "factors.utils.retrieve",
    # Derivatives vol
    "derivatives.vol.retrieve",
]

DAILY_REQUIRED_RETRIEVERS: dict[str, str] = {
    "factors.utils.retrieve:retrieveMarcoPx": "macro-px.pkl",
    "futures.intraday.retrieve:retrieveFuturesDailyK": "futures-dailyK_con.pkl",
    "derivatives.vol.retrieve:retrieveFuturesVol": "futures-volpx.pkl",
}


def _file_mtime_date(path: Path) -> date | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except FileNotFoundError:
        return None


def get_stale_daily_retrievers(cfg: RunConfig) -> list[str]:
    stale: list[str] = []
    for retriever_name, artifact_name in DAILY_REQUIRED_RETRIEVERS.items():
        artifact_path = cfg.input_dir / artifact_name
        if _file_mtime_date(artifact_path) != cfg.asof:
            stale.append(retriever_name)
    return stale


def ensure_daily_required_updates(cfg: RunConfig) -> list[str]:
    load_default_retrievers()
    stale = get_stale_daily_retrievers(cfg)
    if not stale:
        logger.info("Daily required data already up to date for %s", cfg.asof)
        return []

    logger.info("Refreshing stale daily data retrievers: %s", ", ".join(stale))
    run_data_update(cfg, names=stale)
    return stale


def _try_register_module(module_name: str) -> None:
    """Import a retrieve module and register a retriever if it exposes common patterns."""

    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        # Some packages (e.g. surface) import Dash-heavy app modules at package import time.
        # For data update discovery we should be resilient and simply skip those.
        logger.debug("Retriever module import failed: %s (%s)", module_name, e)
        return

    registered_any = False

    # Convention 1: module exposes a single entrypoint function.
    for entry in ("run", "main", "retrieve"):
        if hasattr(mod, entry) and callable(getattr(mod, entry)):
            register_retriever(module_name, getattr(mod, entry))
            registered_any = True

    # Convention 2: legacy codebase often uses retrieveXxx() functions.
    # Register each callable that starts with 'retrieve' (excluding the plain 'retrieve' which is already handled above).
    # Skip functions with required positional arguments — those are helpers, not standalone retrievers.
    for attr in dir(mod):
        if not attr.startswith("retrieve"):
            continue
        if attr in ("retrieve",):
            continue
        fn = getattr(mod, attr, None)
        if not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
            required = [
                p for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            if required:
                logger.debug("Skipping retriever with required args: %s:%s%s", module_name, attr, sig)
                continue
        except (ValueError, TypeError):
            pass
        register_retriever(f"{module_name}:{attr}", fn)
        registered_any = True

    if registered_any:
        return

    # Otherwise: ignore.


def load_default_retrievers(extra_modules: Iterable[str] | None = None) -> None:
    for m in DEFAULT_RETRIEVER_MODULES:
        _try_register_module(m)
    if extra_modules:
        for m in extra_modules:
            _try_register_module(m)


def run_data_update(cfg: RunConfig, *, names: list[str] | None = None, force: bool = False) -> None:
    """Run 0..N data retrieval/update routines.

    If names is None: run all registered.
    If names provided: run only those.

    Note: Many existing retrieve.py scripts likely have custom signatures.
    The goal here is to start with a best-effort wrapper. If a module needs
    arguments, we can adapt it by adding a tiny adapter in engine/data_update.py.
    """

    retrievers = get_retrievers()
    selected = names or sorted(retrievers.keys())
    effective_cfg = replace(cfg, params={**cfg.params, "force_update": force}) if force else cfg

    if not selected:
        logger.warning(
            "No retrievers selected/registered. "
            "This usually means no retrieve modules were successfully imported. "
            "Try `python main.py update-data --modules <module.path.retrieve>` or run without --retrievers to run all registered."
        )
        return

    if not retrievers:
        logger.warning(
            "No retrievers registered. Selected=%s. "
            "To debug: check module imports in engine.data_update.DEFAULT_RETRIEVER_MODULES or pass --modules.",
            selected,
        )
    else:
        logger.info("Available retrievers: %s", ", ".join(sorted(retrievers.keys())))

    for name in selected:
        fn = retrievers.get(name)
        if fn is None:
            logger.warning("Retriever not found: %s", name)
            continue

        logger.info("Running data retriever: %s", name)
        try:
            # Try calling with cfg first; if it fails, fall back to no-arg.
            try:
                fn(effective_cfg)
            except TypeError:
                fn()
        except Exception as e:
            logger.exception("Retriever failed: %s (%s)", name, e)
