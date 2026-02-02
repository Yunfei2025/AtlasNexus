#!/usr/bin/env python
# Test import of atlasnexus_daily
import sys
import traceback

try:
    import web.apps.atlasnexus_daily as app
    print("✓ Import successful")
    print(f"✓ App object exists: {app.app}")
    print(f"✓ App layout exists: {app.app.layout is not None}")
except Exception as e:
    print(f"✗ Import failed: {e}")
    traceback.print_exc()
