from __future__ import annotations

import json
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from web.services.artifacts import ensure_dir, now_iso, project_root


@dataclass(frozen=True)
class JobInfo:
    job_id: str
    created_at: str
    cmd: list[str]
    cwd: str
    status_path: Path
    log_path: Path


def jobs_dir() -> Path:
    return project_root() / "runs" / "_jobs"


def get_job_status(job_id: str) -> dict[str, Any] | None:
    p = jobs_dir() / job_id / "status.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def tail_log(job_id: str, max_lines: int = 200) -> str:
    p = jobs_dir() / job_id / "job.log"
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def start_engine_job(*, argv: list[str]) -> JobInfo:
    """Start an engine job as a subprocess and write status/log files.

    The subprocess runs:
        python main.py <argv...>

    Status file is created immediately as RUNNING.
    """

    job_id = uuid.uuid4().hex[:12]
    root = project_root()
    job_folder = jobs_dir() / job_id
    ensure_dir(job_folder)

    status_path = job_folder / "status.json"
    log_path = job_folder / "job.log"

    cmd = [sys.executable, str(root / "main.py"), *argv]

    status = {
        "job_id": job_id,
        "state": "RUNNING",
        "created_at": now_iso(),
        "started_at": now_iso(),
        "ended_at": None,
        "cmd": cmd,
        "returncode": None,
        "error": None,
    }
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")

    # Start subprocess, redirect stdout/stderr to log file.
    log_f = log_path.open("w", encoding="utf-8")
    p = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0,
    )

    # Store PID in status (best effort)
    status["pid"] = p.pid
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")

    return JobInfo(
        job_id=job_id,
        created_at=status["created_at"],
        cmd=cmd,
        cwd=str(root),
        status_path=status_path,
        log_path=log_path,
    )


def refresh_job_state(job_id: str) -> dict[str, Any] | None:
    """Refresh RUNNING job to SUCCESS/FAILED if the process ended.

    Note: We don't keep the Popen handle around in Dash, so we can't poll
    return code directly. This function is a placeholder for later integration
    (e.g., writing run status from engine itself).

    For now, it just returns the last known status.json.
    """

    return get_job_status(job_id)
