"""
Migrate legacy *-cvobj.pkl files that reference old module paths (e.g., 'affine.curve')
so they can be loaded without alias shims. This loads with shims and re-saves using
current module names (curves.affine.*). Optionally, it can also convert to a plain
"data-only" dict format to avoid any future import-path coupling.

Usage (run from project root):
  python -m utils.migrate_cvobj --in d:/.../CBond-cvobj.pkl --out d:/.../CBond-cvobj.v2.pkl
  # optional: also dump JSON/NPZ data-only form
  python -m utils.migrate_cvobj --in d:/.../CBond-cvobj.pkl --json d:/.../CBond-cvobj.json
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import pickle
from pathlib import Path
import importlib

# Ensure project on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Legacy alias shims
try:
    affine_pkg = importlib.import_module('curves.affine')
    sys.modules.setdefault('affine', affine_pkg)
    for _sub in ('affine', 'curve', 'bootstrap', 'pricingYield'):
        try:
            sys.modules.setdefault(f'affine.{_sub}', importlib.import_module(f'curves.affine.{_sub}'))
        except Exception:
            pass
except Exception:
    pass
try:
    import numpy.core as _np_core  # type: ignore
    sys.modules.setdefault('numpy._core', _np_core)  # type: ignore[attr-defined]
except Exception:
    pass


def load_pickle(path: str):
    with open(path, 'rb') as f:
        return pickle.load(f)


def save_pickle(obj, path: str, protocol: int = pickle.HIGHEST_PROTOCOL):
    with open(path, 'wb') as f:
        pickle.dump(obj, f, protocol=protocol)


def to_data_only(obj):
    """Best-effort conversion of known curve objects to plain dicts.
    Extend this as needed for your project types.
    """
    try:
        # curves.affine.curve.Curve
        from curves.affine.curve import Curve, IRSCurve  # type: ignore
        import pandas as pd
        import numpy as np
    except Exception:
        Curve = IRSCurve = None  # type: ignore
        pd = np = None  # type: ignore

    # simple passthrough for dict/df/series
    try:
        import pandas as pd  # noqa: F401
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            return {"type": "pandas", "data": obj.to_dict(orient='split'), "kind": obj.__class__.__name__}
    except Exception:
        pass

    if isinstance(obj, dict):
        return {k: to_data_only(v) for k, v in obj.items()}

    if Curve is not None and isinstance(obj, Curve):  # type: ignore[arg-type]
        d = {
            "format_version": 1,
            "type": "Curve",
            "day": getattr(obj, 'day', None).strftime('%Y-%m-%d') if getattr(obj, 'day', None) else None,
            "gamma": getattr(obj, 'gamma', None),
            "mtype": getattr(obj, 'mtype', None),
            "caltype": getattr(obj, 'caltype', None),
        }
        # numpy/pandas fields if present
        for attr in ('S2', 'factors', 'reference'):
            val = getattr(obj, attr, None)
            if val is None:
                continue
            try:
                import numpy as np
                if hasattr(val, 'tolist'):
                    d[attr] = val.tolist()
                else:
                    d[attr] = val
            except Exception:
                d[attr] = str(type(val))
        return d

    if IRSCurve is not None and isinstance(obj, IRSCurve):  # type: ignore[arg-type]
        d = {
            "format_version": 1,
            "type": "IRSCurve",
            "day": getattr(obj, 'day', None).strftime('%Y-%m-%d') if getattr(obj, 'day', None) else None,
            "curve_type": getattr(obj, 'type', None),
            "gamma": getattr(obj, 'gamma', None),
            "mtype": getattr(obj, 'mtype', None),
            "caltype": getattr(obj, 'caltype', None),
        }
        for attr in ('S2', 'factors'):
            val = getattr(obj, attr, None)
            if val is None:
                continue
            try:
                if hasattr(val, 'tolist'):
                    d[attr] = val.tolist()
                else:
                    d[attr] = val
            except Exception:
                d[attr] = str(type(val))
        # If anchor/key_rate exist and are DataFrames, convert
        try:
            import pandas as pd
            for attr in ('anchor', 'key_rate', 'curves'):
                val = getattr(obj, attr, None)
                if val is not None and hasattr(val, 'to_dict'):
                    d[attr] = val.to_dict(orient='split')
        except Exception:
            pass
        return d

    # Fallback: try to serialize via repr
    try:
        return {"type": type(obj).__name__, "repr": repr(obj)[:200]}
    except Exception:
        return {"type": type(obj).__name__}


def main():
    p = argparse.ArgumentParser()
    # p.add_argument('--in', dest='src', required=True, help='Input legacy cvobj pickle')
    # p.add_argument('--out', dest='dst', help='Output re-pickled file (module paths updated)')
    p.add_argument('--json', dest='json_out', help='Optional data-only JSON dump')
    args = p.parse_args()
    from settings.paths import DIR_DATA, DIR_INPUT
    src = os.path.join(DIR_INPUT, 'TBond-cvrtold.obj')#args.src
    dst = os.path.join(DIR_INPUT, 'TBond-cvrt.obj')#args.dst or os.path.splitext(src)[0] + '.v2.pkl'

    obj = load_pickle(src)
    print(f"Loaded: {src} -> type: {type(obj)}")

    # Re-pickle using current module names
    save_pickle(obj, dst)
    print(f"Re-saved with updated module paths: {dst}")

    if args.json_out:
        data_only = to_data_only(obj)
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump(data_only, f, ensure_ascii=False)
        print(f"Also wrote data-only JSON: {args.json_out}")


if __name__ == '__main__':
    main()
