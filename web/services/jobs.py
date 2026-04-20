from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


# ── Conflict matrix ───────────────────────────────────────────────────────────
# Jobs in the same conflict group share DIR_INPUT / DIR_DATA artifacts and must
# not run concurrently.  The value for each key is the set of job types that
# cannot co-exist with it.
_CONFLICT_MATRIX: dict[str, set[str]] = {
    "curve-backtest": {"eod", "update-data", "intraday", "refresh"},
    "eod":            {"curve-backtest"},
    "update-data":    {"curve-backtest"},
    "intraday":       {"curve-backtest"},
    "refresh":        {"curve-backtest"},
}


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


# ── PID liveness ──────────────────────────────────────────────────────────────

def _is_pid_running(pid: int) -> bool:
    """Return True if the process with *pid* is still alive."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if not handle:
                return False
            ec = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(ec))
            ctypes.windll.kernel32.CloseHandle(handle)
            return ec.value == STILL_ACTIVE
        else:
            os.kill(pid, 0)  # signal 0 = existence check only
            return True
    except Exception:
        return False


def _parse_status_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_process_started_at(pid: int) -> datetime | None:
    try:
        if sys.platform.startswith("win"):
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return None
            try:
                creation_time = ctypes.c_ulonglong(0)
                exit_time = ctypes.c_ulonglong(0)
                kernel_time = ctypes.c_ulonglong(0)
                user_time = ctypes.c_ulonglong(0)
                ok = ctypes.windll.kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation_time),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                )
                if not ok:
                    return None
                windows_epoch = 116444736000000000
                seconds = (creation_time.value - windows_epoch) / 10_000_000
                return datetime.fromtimestamp(seconds, tz=timezone.utc)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return None
    return None


def _matches_recorded_process(status: dict[str, Any], pid: int) -> bool:
    if not _is_pid_running(pid):
        return False

    expected_start = _parse_status_time(
        status.get("pid_started_at") or status.get("started_at") or status.get("created_at")
    )
    actual_start = _get_process_started_at(pid)

    if expected_start is None or actual_start is None:
        return True

    tolerance = timedelta(seconds=10) if status.get("pid_started_at") else timedelta(minutes=1)
    return abs(actual_start - expected_start) <= tolerance


def finalize_job_if_done(job_id: str) -> dict[str, Any] | None:
    """If a job is marked RUNNING but its PID is dead, mark it FINISHED on disk.

    Returns the (possibly updated) status dict, or None if not found.
    """
    status = get_job_status(job_id)
    if status is None:
        return None
    if status.get("state") != "RUNNING":
        return status
    pid = status.get("pid")
    should_finalize = False
    if not pid:
        should_finalize = True
        status["error"] = status.get("error") or "RUNNING job record had no PID; marked stale."
    else:
        try:
            should_finalize = not _matches_recorded_process(status, int(pid))
        except Exception:
            should_finalize = True

    if should_finalize:
        status["state"] = "FINISHED"
        status["ended_at"] = now_iso()
        p = jobs_dir() / job_id / "status.json"
        try:
            p.write_text(json.dumps(status, indent=2), encoding="utf-8")
        except Exception:
            pass
    return status


def list_running_jobs() -> list[dict[str, Any]]:
    """Scan all job directories, auto-finalize stale ones, return only truly running jobs.

    A job is truly running when its status.json says RUNNING *and* its PID is still alive.
    """
    jd = jobs_dir()
    if not jd.exists():
        return []
    running: list[dict[str, Any]] = []
    for job_dir in sorted(jd.iterdir()):
        if not job_dir.is_dir():
            continue
        status_path = job_dir / "status.json"
        if not status_path.exists():
            continue
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status.get("state") == "RUNNING":
            status = finalize_job_if_done(status["job_id"])
            if status and status.get("state") == "RUNNING":
                running.append(status)
    return running


def _cmd_type(cmd: list[str]) -> str | None:
    """Extract the subcommand type from a cmd list like ['python', 'main.py', 'eod', ...]."""
    for i, arg in enumerate(cmd):
        if arg.endswith("main.py") and i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def check_conflict(new_argv: list[str]) -> str | None:
    """Check if starting *new_argv* would conflict with an already-running job.

    Returns a human-readable error string if conflicting, None if safe to start.
    """
    new_type = new_argv[0] if new_argv else None
    conflicts_with = _CONFLICT_MATRIX.get(new_type, set())
    if not conflicts_with and new_type not in _CONFLICT_MATRIX:
        return None  # not a tracked type — always allowed

    running = list_running_jobs()
    for job in running:
        existing_type = _cmd_type(job.get("cmd", []))
        if existing_type in conflicts_with or existing_type == new_type:
            return (
                f"⛔ Cannot start '{new_type}': job {job['job_id']} "
                f"({existing_type}) is already RUNNING and shares data artifacts. "
                f"Wait for it to finish first."
            )
    return None


# ── Job launcher ──────────────────────────────────────────────────────────────

def start_engine_job(*, argv: list[str]) -> JobInfo:
    """Start an engine job as a subprocess and write status/log files.

    The subprocess runs:
        python main.py <argv...>

    Status file is created immediately as RUNNING.
    Raises ``RuntimeError`` if a conflicting job is already running.
    """
    conflict = check_conflict(argv)
    if conflict:
        raise RuntimeError(conflict)

    job_id = uuid.uuid4().hex[:12]
    root = project_root()
    job_folder = jobs_dir() / job_id
    ensure_dir(job_folder)

    status_path = job_folder / "status.json"
    log_path = job_folder / "job.log"

    cmd = [sys.executable, str(root / "main.py"), *argv]

    status = {
        "job_id": job_id,
        "state": "STARTING",
        "created_at": now_iso(),
        "started_at": None,
        "ended_at": None,
        "cmd": cmd,
        "returncode": None,
        "error": None,
    }
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")

    # Start subprocess, redirect stdout/stderr to log file.
    log_f = log_path.open("w", encoding="utf-8")
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0,
        )
    except Exception as exc:
        log_f.write(f"Failed to start job: {exc}\n")
        log_f.flush()
        log_f.close()
        status["state"] = "FAILED"
        status["ended_at"] = now_iso()
        status["error"] = str(exc)
        status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        raise

    # Store PID in status (best effort)
    status["state"] = "RUNNING"
    status["started_at"] = now_iso()
    status["pid"] = p.pid
    proc_started_at = _get_process_started_at(p.pid)
    if proc_started_at is not None:
        status["pid_started_at"] = proc_started_at.isoformat()
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
    """Finalize the job if its PID has exited, then return the latest status."""
    return finalize_job_if_done(job_id)
