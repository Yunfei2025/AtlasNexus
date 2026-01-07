from __future__ import annotations

import importlib
import logging
from typing import Iterable

from engine.context import RunConfig
from engine.registry import get_retrievers, register_retriever

logger = logging.getLogger(__name__)


DEFAULT_RETRIEVER_MODULES: list[str] = [
    # Central provider-style
    "data.providers.retrieve",
    # Curves / surfaces
    "curves.utils.retrieve",
    # NOTE: `surface` package imports Dash app at import time; keep it opt-in via `--modules surface.retrieve`.
    # Multiasset
    "multiasset.retrieve",
    # Futures intraday
    "futures.intraday.retrieve",
    # Factors helper
    "factors.utils.retrieve",
    # Derivatives vol
    "derivatives.vol.retrieve",
]


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
    for attr in dir(mod):
        if not attr.startswith("retrieve"):
            continue
        if attr in ("retrieve",):
            continue
        fn = getattr(mod, attr, None)
        if callable(fn):
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


def run_data_update(cfg: RunConfig, *, names: list[str] | None = None) -> None:
    """Run 0..N data retrieval/update routines.

    If names is None: run all registered.
    If names provided: run only those.

    Note: Many existing retrieve.py scripts likely have custom signatures.
    The goal here is to start with a best-effort wrapper. If a module needs
    arguments, we can adapt it by adding a tiny adapter in engine/data_update.py.
    """

    retrievers = get_retrievers()
    selected = names or sorted(retrievers.keys())

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
                fn(cfg)
            except TypeError:
                fn()
        except Exception as e:
            logger.exception("Retriever failed: %s (%s)", name, e)
