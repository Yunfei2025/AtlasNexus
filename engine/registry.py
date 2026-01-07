"""Simple registries for data-updaters and strategy runners.

The goal is to integrate your existing per-module retrieve.py scripts
(curves/utils/retrieve.py, futures/intraday/retrieve.py, etc.) behind a single
interface, without forcing a rewrite.

Each retriever is registered as a callable with signature:
    retriever(run_config: RunConfig) -> None

You can expand this later into entrypoint discovery, config-driven enabling,
and richer return objects.
"""

from __future__ import annotations

from typing import Callable

from engine.context import RunConfig

Retriever = Callable[[RunConfig], None]


_RETRIEVERS: dict[str, Retriever] = {}


def register_retriever(name: str, fn: Retriever) -> None:
    _RETRIEVERS[name] = fn


def get_retrievers() -> dict[str, Retriever]:
    return dict(_RETRIEVERS)
