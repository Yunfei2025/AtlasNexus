import sys
from pathlib import Path
import time

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("Importing curves.utils.loader...")
import curves.utils.loader
print("Importing curves.utils.retrieve...")
import curves.utils.retrieve
print("Importing curves.calibration.irscurves...")
import curves.calibration.irscurves
print("Importing curves.refreshers.irs...")
import curves.refreshers.irs
