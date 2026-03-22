from __future__ import annotations

import json
import logging
import pickle
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _json_default(obj: Any):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=_json_default)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")


# ---------------------------------------------------------------------------
# ArtifactStore – thin read/write layer over the shared ``input/`` directory
# ---------------------------------------------------------------------------

class ArtifactStore:
    """Unified read/write access to the shared ``input/`` directory.

    Every module already reads/writes pickle and JSON files under
    ``DIR_INPUT`` (``../input`` relative to the project root).  This class
    provides a single façade so the pipeline layer can pass a *store*
    object to each module interface instead of hard-coding paths.
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from settings.paths import DIR_INPUT
            root = DIR_INPUT
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- path helpers -------------------------------------------------------

    def path(self, name: str) -> Path:
        """Return the full path for a named artifact."""
        return self.root / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    # -- pickle -------------------------------------------------------------

    def read_pickle(self, name: str) -> Any:
        p = self.path(name)
        with p.open("rb") as f:
            return pickle.load(f)

    def write_pickle(self, name: str, obj: Any) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump(obj, f)
        logger.debug("Wrote pickle artifact: %s", p)
        return p

    # -- JSON ---------------------------------------------------------------

    def read_json(self, name: str) -> Any:
        return read_json(self.path(name))

    def write_json(self, name: str, obj: Any) -> Path:
        p = self.path(name)
        write_json(p, obj)
        logger.debug("Wrote JSON artifact: %s", p)
        return p

    # -- plain text ---------------------------------------------------------

    def write_lines(self, name: str, lines: Iterable[str]) -> Path:
        p = self.path(name)
        write_lines(p, lines)
        return p

    def __repr__(self) -> str:
        return f"ArtifactStore(root={self.root!r})"
