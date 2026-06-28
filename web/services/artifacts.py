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


def get_data_generation_date(bond_type: str = "CBond") -> str | None:
    """Get the last date from `<bond_type>-cvpx.pkl` as the calibration date.

    This reflects the actual as-of date of the calibrated curve data baked
    into the pickle (the last index of ``ytm_act``), which can lag behind
    the EOD run's nominal as-of date if a calibration step used stale data.

    Returns ISO format date string (YYYY-MM-DD) or None if file not found.
    """
    try:
        import pandas as pd
        from settings.paths import DIR_INPUT

        cvpx_file = Path(DIR_INPUT) / f"{bond_type}-cvpx.pkl"

        if not cvpx_file.exists():
            return None

        data = pd.read_pickle(cvpx_file)

        # Extract the index (dates) from ytm_act if it's a dict
        if isinstance(data, dict) and 'ytm_act' in data:
            ytm_data = data['ytm_act']
            if hasattr(ytm_data, 'index') and len(ytm_data.index) > 0:
                last_date = ytm_data.index[-1]
                # Convert to datetime if needed and format as YYYY-MM-DD
                if hasattr(last_date, 'strftime'):
                    return last_date.strftime('%Y-%m-%d')
                else:
                    return str(last_date)[:10]  # Extract date part from string

        return None
    except Exception:
        return None


def format_run_meta(meta: RunMeta | None) -> str:
    """Format run metadata into human-readable text.

    Shows asof date and data generation date (from pickle file) in readable format.
    Falls back to generated_at if data date cannot be determined.
    """
    if not meta:
        return "No recent runs found"

    # Parse asof date to readable format (YYYY-MM-DD → Jun 17, 2026)
    asof_readable = "Unknown"
    if meta.asof:
        try:
            # Handle both YYYY-MM-DD and ISO format
            asof_date = datetime.fromisoformat(meta.asof.split('T')[0])
            asof_readable = asof_date.strftime('%b %d, %Y')
        except Exception:
            asof_readable = meta.asof

    # Try to get data generation date from pickle file
    data_date = get_data_generation_date()

    if data_date:
        try:
            data_date_obj = datetime.fromisoformat(data_date)
            data_readable = data_date_obj.strftime('%b %d, %Y')
        except Exception:
            data_readable = data_date

        return f"Run: {asof_readable} | Data: {data_readable}"
    else:
        # Fallback if we can't read pickle file
        return f"Run: {asof_readable}"


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
