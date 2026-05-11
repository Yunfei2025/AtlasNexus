"""
Migrate pickle files saved by old pandas versions to be compatible with pandas 2+/3+.

Usage:
    python utils/migrate_pkl.py /path/to/file.pkl
    python utils/migrate_pkl.py /path/to/file.pkl --dry-run   # preview only
"""
from __future__ import annotations

import argparse
import io
import os
import pickle
import sys
from pathlib import Path


import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Patched unpickler — bypasses the block-manager integrity check that pandas
# 2.x/3.x added. The underlying data is valid; only the internal bookkeeping
# was inconsistent in older serialisation formats.
# ---------------------------------------------------------------------------

class _PermissiveBlockManager:
    """Thin wrapper: reconstructs a clean DataFrame from old block data."""

    def __new__(cls, blocks, axes, *args, **kwargs):
        try:
            # Try the real constructor first (may work for slightly mismatched files)
            from pandas.core.internals.managers import BlockManager
            return BlockManager(blocks, axes, *args, **kwargs)
        except (AssertionError, ValueError):
            pass

        # Fallback: reassemble from numpy arrays in the blocks
        index = axes[-1]   # row index
        columns = axes[0]  # column labels (MultiIndex or Index)
        try:
            arrays = {}
            for blk in blocks:
                for i, col in enumerate(blk.mgr_locs):
                    col_label = columns[col]
                    arrays[col_label] = blk.values[i] if blk.values.ndim == 2 else blk.values
            df = pd.DataFrame(arrays, index=index)
            df = df[columns]  # restore original column order
            return df._mgr
        except Exception as exc:
            raise RuntimeError(
                f"Could not reconstruct BlockManager from old pickle data: {exc}"
            ) from exc


class _LegacyUnpickler(pickle.Unpickler):
    _BM_MODULES = {
        "pandas.core.internals.managers",
        "pandas.core.internals",
        "pandas.core.internals.blocks",
    }

    def find_class(self, module, name):
        if module in self._BM_MODULES and name == "BlockManager":
            return _PermissiveBlockManager
        return super().find_class(module, name)


def _load_legacy(file_path: str):
    with open(file_path, "rb") as fh:
        return _LegacyUnpickler(fh).load()


# ---------------------------------------------------------------------------
# Normaliser: walk the loaded object and rebuild every DataFrame cleanly
# so internal state is consistent with the current pandas version.
# ---------------------------------------------------------------------------

def _rebuild(obj):
    if isinstance(obj, pd.DataFrame):
        # Force a full copy through numpy — discards all legacy internal state
        return pd.DataFrame(
            obj.to_numpy(), index=obj.index, columns=obj.columns, dtype=None
        ).infer_objects()
    if isinstance(obj, pd.Series):
        return obj.copy()
    if isinstance(obj, dict):
        return {k: _rebuild(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rebuild(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def migrate(file_path: str, dry_run: bool = False) -> bool:
    """
    Load *file_path* with the legacy-compatible unpickler, rebuild all
    DataFrames, and overwrite the file with the current pandas serialisation.

    Returns True on success.
    """
    path = Path(file_path)
    if not path.exists():
        print(f"ERROR: file not found: {file_path}")
        return False

    print(f"Loading (legacy mode): {file_path}")
    try:
        obj = _load_legacy(file_path)
    except Exception as exc:
        print(f"ERROR: could not load with legacy unpickler: {exc}")
        return False

    print("Rebuilding data structures...")
    try:
        migrated = _rebuild(obj)
    except Exception as exc:
        print(f"ERROR: rebuild failed: {exc}")
        return False

    # Quick summary of what was loaded
    if isinstance(migrated, dict):
        for k, v in migrated.items():
            if isinstance(v, pd.DataFrame):
                print(f"  [{k}]  DataFrame  {v.shape}  dtypes: {set(v.dtypes.astype(str))}")
            elif isinstance(v, dict):
                print(f"  [{k}]  dict with {len(v)} keys")
            else:
                print(f"  [{k}]  {type(v).__name__}")

    if dry_run:
        print("Dry-run — file NOT modified.")
        return True

    # Back up original before overwriting
    backup = str(path) + ".bak"
    path.rename(backup)
    print(f"Backup saved: {backup}")

    try:
        with open(file_path, "wb") as fh:
            pickle.dump(migrated, fh, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"Migrated file saved: {file_path}")
    except Exception as exc:
        # Restore backup on failure
        Path(backup).rename(file_path)
        print(f"ERROR: could not save migrated file (backup restored): {exc}")
        return False

    # Verify the new file loads cleanly
    try:
        pd.read_pickle(file_path)
        print("Verification passed — file loads cleanly with pd.read_pickle.")
    except Exception as exc:
        print(f"WARNING: verification failed: {exc}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate pandas legacy pickle files")
    parser.add_argument("file", help="Path to the .pkl file to migrate")
    parser.add_argument("--dry-run", action="store_true", help="Load and preview without saving")
    args = parser.parse_args()

    ok = migrate(args.file, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)
