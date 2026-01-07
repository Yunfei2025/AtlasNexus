from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunConfig:
    """Configuration for a single engine run."""

    asof: date
    mode: str  # eod | intraday
    run_id: str
    output_dir: Path
    cache_dir: Path | None = None
    params: dict[str, Any] = field(default_factory=dict)


def default_run_id(asof: date, mode: str) -> str:
    # Example: 20260104-eod-153012
    ts = datetime.now().strftime("%H%M%S")
    return f"{asof.strftime('%Y%m%d')}-{mode}-{ts}"


def resolve_output_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "runs" / run_id


def resolve_cache_dir(project_root: Path) -> Path:
    return project_root / "cache"


def build_run_config(
    *,
    project_root: Path,
    mode: str,
    asof: date | None = None,
    run_id: str | None = None,
    output_dir: Path | None = None,
    cache_dir: Path | None = None,
    params: dict[str, Any] | None = None,
) -> RunConfig:
    asof = asof or date.today()
    run_id = run_id or default_run_id(asof, mode)
    out_dir = output_dir or resolve_output_dir(project_root, run_id)
    cache_dir = cache_dir or resolve_cache_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    return RunConfig(
        asof=asof,
        mode=mode,
        run_id=run_id,
        output_dir=out_dir,
        cache_dir=cache_dir,
        params=params or {},
    )
