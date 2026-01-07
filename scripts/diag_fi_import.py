"""Diagnostic: import and validate FIEngine Dash app deps.

Usage:
    conda run --name dev --no-capture-output python scripts/diag_fi_import.py

This avoids complex quoting/newlines in `python -c` on Windows.
"""

from __future__ import annotations

import importlib
import sys
import time
import traceback


def _check(mod: str) -> None:
    t0 = time.time()
    try:
        m = importlib.import_module(mod)
        dt = time.time() - t0
        ver = getattr(m, "__version__", None)
        extra = f" v{ver}" if ver else ""
        print(f"OK   {mod}{extra} ({dt:.2f}s)")
    except Exception:
        dt = time.time() - t0
        print(f"FAIL {mod} ({dt:.2f}s)")
        traceback.print_exc()


def main() -> int:
    print("Python:", sys.executable)

    # Core web deps
    _check("dash")
    _check("dash_bootstrap_components")
    _check("diskcache")

    print("\nImporting FI app module web.apps.fi ...")
    t0 = time.time()
    try:
        importlib.import_module("web.apps.fi")
        print(f"OK   web.apps.fi ({time.time()-t0:.2f}s)")
    except Exception:
        print(f"FAIL web.apps.fi ({time.time()-t0:.2f}s)")
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
