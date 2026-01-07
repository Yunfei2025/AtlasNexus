import sys
import os
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def timed_import(module_name):
    print(f"Importing {module_name}...", end="", flush=True)
    start = time.time()
    try:
        __import__(module_name)
        print(f" Done ({time.time() - start:.2f}s)", flush=True)
    except Exception as e:
        print(f" Failed: {e}")

print("Starting granular import check...")

timed_import("plotly")
# timed_import("web.core.server")
timed_import("web.core.styles")
timed_import("web.core.load")
timed_import("web.core.graphs")
timed_import("web.core.scripts") # This one likely hangs
timed_import("web.core.content")
timed_import("web.apps.fi")

print("Check complete.")
