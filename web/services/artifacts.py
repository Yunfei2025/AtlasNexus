from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunMeta:
    run_id: str
    mode: str
    asof: str
    generated_at: str | None = None
    status: str | None = None
    path: Path | None = None


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runs_dir() -> Path:
    return project_root() / "runs"


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def find_latest_run(mode: str | None = None) -> RunMeta | None:
    """Find the latest run folder under runs/ by mtime.

    If mode is provided, read run_meta.json and filter by mode.
    """

    base = runs_dir()
    if not base.exists():
        return None

    candidates: list[Path] = [p for p in base.iterdir() if p.is_dir()]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for folder in candidates:
        meta_file = folder / "run_meta.json"
        if not meta_file.exists():
            continue
        meta = _safe_read_json(meta_file)
        if not meta:
            continue

        if mode and meta.get("mode") != mode:
            continue

        return RunMeta(
            run_id=str(meta.get("run_id", folder.name)),
            mode=str(meta.get("mode", "")),
            asof=str(meta.get("asof", "")),
            generated_at=meta.get("generated_at"),
            status=meta.get("status"),
            path=folder,
        )

    return None


def format_run_meta(meta: RunMeta | None) -> str:
    if not meta:
        return "No runs found under runs/."

    parts = [
        f"run_id={meta.run_id}",
        f"mode={meta.mode}",
        f"asof={meta.asof}",
    ]
    if meta.generated_at:
        parts.append(f"generated_at={meta.generated_at}")
    if meta.status:
        parts.append(f"status={meta.status}")
    return " | ".join(parts)


def load_step_result(step_name: str, mode: str = "eod") -> dict[str, Any] | None:
    """Load the persisted result for a pipeline step from the latest run dir.

    The EOD pipeline writes ``<step>_result.json`` for every calibrate() call
    that returns a JSON-serializable value. This is the reader-side counterpart
    so web callbacks can display pre-computed results instead of recomputing.

    Returns None if no matching run or artifact is found.

    Example::

        result = load_step_result("futures")
        if result:
            best_sharpe = max(
                s["sharpe"] for s in result["strategies"].values()
            )
    """
    run = find_latest_run(mode=mode)
    if run is None or run.path is None:
        return None
    artifact_path = run.path / f"{step_name}_result.json"
    data = _safe_read_json(artifact_path)
    return data  # None if missing or malformed


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.utcnow().isoformat()
