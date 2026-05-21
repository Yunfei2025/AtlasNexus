#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Curve generation initialisation module.

This module runs the complete curve generation workflow independently.
It orchestrates various generators for financial curve processing.

Author: Yunfei Ma
"""

import datetime
import json
import pathlib
import sys
import traceback

# Minimal bootstrap for direct execution: add project root so absolute
# package imports work when running `python curves\initialise.py`.
if __name__ == "__main__":
    _PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))

# Clean imports - all absolute paths
from curves.utils.generator_utils import get_mtime_date
from curves.utils.retrieve import updateInstrumentDef, retrieveCNBDTS, retrieveFuturesTS
from settings.fixed_income import BondConfig
from settings.paths import DIR_INPUT

# Import generators dynamically to avoid dependency issues at module load time
import importlib


_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
_INITIALISE_STATE_DIR = _PROJECT_ROOT / "cache" / "curve_initialise"
_COMPLETION_ARTIFACT = DIR_INPUT / "MNote-spds.pkl"
_REQUIRED_DAILY_INPUTS = {
    "instrument_definitions": DIR_INPUT / "futures-InstrumentInfo.pkl",
    "bond_database": DIR_INPUT / "database-px.pkl",
    "futures_database": DIR_INPUT / "futures-px.pkl",
}


def _initialise_marker_path(asof: datetime.date) -> pathlib.Path:
    return _INITIALISE_STATE_DIR / f"{asof:%Y%m%d}.json"


def _daily_inputs_ready(asof: datetime.date) -> tuple[bool, list[str]]:
    pending: list[str] = []
    for label, path in _REQUIRED_DAILY_INPUTS.items():
        mtime = get_mtime_date(path)
        if mtime != asof:
            state = "missing" if mtime is None else f"dated {mtime.isoformat()}"
            pending.append(f"{label} ({path.name}: {state})")
    return (len(pending) == 0, pending)


def _load_marker(asof: datetime.date) -> dict | None:
    marker_path = _initialise_marker_path(asof)
    if not marker_path.exists():
        return None
    try:
        with marker_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _generation_completed_today(asof: datetime.date) -> bool:
    if not _completion_artifact_ready(asof):
        return False
    marker = _load_marker(asof)
    if not marker:
        return True
    return marker.get("status") == "completed"


def _completion_artifact_ready(asof: datetime.date) -> bool:
    return get_mtime_date(_COMPLETION_ARTIFACT) == asof


def _write_completion_marker(
    asof: datetime.date,
    *,
    generators: list[str],
    pairs_generated: bool,
) -> None:
    _INITIALISE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker = {
        "date": asof.isoformat(),
        "status": "completed",
        "completed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "generators": generators,
        "pairs_generated": pairs_generated,
        "completion_artifact": str(_COMPLETION_ARTIFACT),
        "required_inputs": {
            label: str(path) for label, path in _REQUIRED_DAILY_INPUTS.items()
        },
    }
    marker_path = _initialise_marker_path(asof)
    with marker_path.open("w", encoding="utf-8") as handle:
        json.dump(marker, handle, indent=2)


def run_data_updates() -> None:
    """Run database updates if needed (INFO/WARNING logging only)."""
    try:
        t = datetime.datetime.today()

        print("INFO: Checking data updates...")

        # Update instrument definitions if needed
        futures_file = DIR_INPUT / "futures-InstrumentInfo.pkl"
        if t.date() != get_mtime_date(futures_file):
            print("INFO: Updating instrument definitions...")
            updateInstrumentDef()

        # Update bond database if needed
        bond_file = DIR_INPUT / "database-px.pkl"
        if t.date() != get_mtime_date(bond_file):
            print("INFO: Updating bond database...")
            retrieveCNBDTS()

        # Update futures database if needed
        futures_px_file = DIR_INPUT / "futures-px.pkl"
        if t.date() != get_mtime_date(futures_px_file):
            print("INFO: Updating futures database...")
            retrieveFuturesTS()

    except Exception as e:
        print(f"WARNING: Data updates failed: {e}")

def main() -> str:
    """Main curve generation workflow (INFO/WARNING only)."""
    print("INFO: Starting curve generation...")
    print(f"INFO: curves package path: {pathlib.Path(__file__).resolve().parent}")
    asof = datetime.datetime.today().date()
    
    try:
        if _generation_completed_today(asof):
            print(
                f"INFO: Curve generation already completed for {asof.isoformat()} "
                f"({_COMPLETION_ARTIFACT.name} updated today) — skipping rerun."
            )
            return "Skipped: MNote-spds.pkl already updated today"

        # Step 1: Update databases
        run_data_updates()

        ready, pending_inputs = _daily_inputs_ready(asof)
        if not ready:
            print("INFO: Skipping curve generation until today's prerequisite files are ready:")
            for item in pending_inputs:
                print(f"INFO:   - {item}")
            return "Skipped: prerequisite inputs not ready"

        # Step 2: Run generators in order
        generators = [
            ("TrendGenerator", "trend"),
            ("BondCurveGenerator", "rates"), 
            ("CreditSpreadGenerator", "credit"),
            ("IRSGenerator", "irs"),
            ("StatGenerator", "stat"),
        ]
        
        success_count = 0
        completed_generators: list[str] = []
        for generator_name, module_name in generators:
            try:
                print(f"INFO: Running {generator_name}...")
                
                # Import generator dynamically to avoid dependency issues
                spec = importlib.import_module(f"curves.generators.{module_name}")
                generator_class = getattr(spec, generator_name)

                if generator_name == "BondCurveGenerator":
                    for bond_type in ['TBond', 'CBond']:
                        print(f"INFO: Generating {bond_type} curve...")
                        generator_class.main(bond_type=bond_type)
                elif generator_name == "CreditSpreadGenerator":
                    for bond_type in BondConfig.INCLUDE_FILTERS.keys():
                        print(f"INFO: Generating {bond_type} curve...")
                        generator_class.main(bond_type=bond_type)
                else:
                    generator_class.main()
                
                print(f"INFO: {generator_name} completed successfully")
                success_count += 1
                completed_generators.append(generator_name)

            except ImportError as e:
                print(f"WARNING: Could not import {generator_name}: {e}")
            except Exception as e:
                print(f"ERROR: Error running {generator_name}: {e}")
                
        print(f"INFO: Summary: {success_count}/{len(generators)} generators completed successfully")

        pairs_generated = False
        if success_count == len(generators):
            from curves.generators.pairs import main
            main(min_cr=30.0, lookback_days=60, write_to_excel=False)
            pairs_generated = True
            print("INFO: Top CR pairs generated.")

        if success_count == len(generators) and pairs_generated and _completion_artifact_ready(asof):
            _write_completion_marker(
                asof,
                generators=completed_generators,
                pairs_generated=pairs_generated,
            )
            print("INFO: All curve generation tasks completed!")
            return "Completed curve generation"
        if success_count == len(generators) and pairs_generated:
            print(
                f"WARNING: {_COMPLETION_ARTIFACT.name} was not updated for {asof.isoformat()} "
                "so the completion marker was not written"
            )
            return "Warning: completion artifact not updated"
        else:
            print("WARNING: Some generators failed - check logs above for details")
            return "Warning: some generators failed"
              
    except Exception as e:
        print(f"CRITICAL: Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
#%%
if __name__ == "__main__":
    main()
  