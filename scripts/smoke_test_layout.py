import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    print("Importing web.apps.fi...")
    from web.apps import fi
    print("Import successful.")
    
    print("Creating layout...")
    layout = fi.create_layout()
    print("Layout created successfully.")
    
    print("Checking callbacks...")
    # Callbacks are registered on import of web.core.content
    print(f"Registered callbacks: {len(fi.app.callback_map)}")
    
    print("Smoke test passed!")
except Exception as e:
    print(f"Smoke test failed: {e}")
    import traceback
    traceback.print_exc()
