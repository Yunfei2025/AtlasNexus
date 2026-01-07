# -*- coding: utf-8 -*-
"""
Web package initializer. Ensures the project root is on sys.path so
internal imports (e.g. `curves`, `settings`) work when `web` modules
are imported directly.

This file is intentionally small and safe to import.
"""

import sys
from pathlib import Path

# Insert project root (two levels up from this file) so `import curves` and
# `import settings` resolve when `web` is imported as a package.
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
	sys.path.insert(0, str(project_root))

