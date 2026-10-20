"""Guard: WindPy must only be imported by the Wind worker process
(data/providers/wind_worker.py). A native fault in the Wind DLL kills the host
process, so the web server must never load it."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {ROOT / "data" / "providers" / "wind_worker.py"}
SKIP_DIRS = {"tests", "runs", "docs", ".git", "__pycache__"}
PATTERN = re.compile(r"^\s*(from\s+WindPy\s+import|import\s+WindPy)", re.M)


def test_windpy_not_imported_outside_provider():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if SKIP_DIRS & set(path.relative_to(ROOT).parts) or path in ALLOWED:
            continue
        if PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"in-process WindPy import: {offenders}"
