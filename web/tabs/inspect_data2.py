import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


try:
    from settings.paths import DIR_INPUT
    import pandas as pd

    # --- TBond-cvref.pkl ---
    ref = pd.read_pickle(str(DIR_INPUT / "TBond-cvref.pkl"))
    print("TBond-cvref type:", type(ref))
    if isinstance(ref, dict):
        print("  keys:", list(ref.keys()))
        rb = ref.get("RefBond")
        if rb is not None:
            print("  RefBond cols:", rb.columns.tolist())
            print(rb.tail(2).to_string())

    # --- CBond-cvref.pkl ---
    ref2 = pd.read_pickle(str(DIR_INPUT / "CBond-cvref.pkl"))
    print("\nCBond-cvref type:", type(ref2))
    if isinstance(ref2, dict):
        print("  keys:", list(ref2.keys()))
        rb2 = ref2.get("RefBond")
        if rb2 is not None:
            print("  RefBond cols:", rb2.columns.tolist())
            print(rb2.tail(2).to_string())

    # --- IRS-pxspds.pkl ---
    irs = pd.read_pickle(str(DIR_INPUT / "IRS-pxspds.pkl"))
    print("\nIRS-pxspds type:", type(irs))
    if isinstance(irs, dict):
        print("  keys:", list(irs.keys()))
        si = irs.get("StatInfo")
        if si is not None:
            print("  StatInfo cols:", si.columns.tolist())
            print(si.head(10).to_string())

    # --- IRS-spdsrt.pkl ---
    irs_rt = pd.read_pickle(str(DIR_INPUT / "IRS-spdsrt.pkl"))
    print("\nIRS-spdsrt type:", type(irs_rt))
    if isinstance(irs_rt, dict):
        print("  keys:", list(irs_rt.keys()))
        sw = irs_rt.get("swaps")
        if sw is not None and hasattr(sw, "columns"):
            print("  swaps cols:", sw.columns.tolist())
            print(sw.head(5).to_string())
        sp = irs_rt.get("spreads")
        if sp is not None and hasattr(sp, "columns"):
            print("  spreads cols:", sp.columns.tolist())
            print(sp.head(5).to_string())

except Exception:
    traceback.print_exc()