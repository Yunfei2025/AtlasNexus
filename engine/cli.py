from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path

from engine.context import build_run_config
from engine.pipeline import eod as eod_pipeline
from engine.pipeline import intraday as intraday_pipeline

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> date:
    # Accept YYYY-MM-DD
    return datetime.strptime(s, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="FIEngine", description="FIEngine orchestration CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    eod = sub.add_parser("eod", help="Run daily EOD pipeline")
    eod.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    eod.add_argument("--update-data", action="store_true", help="Run retrieve.py updaters before computing")

    intra = sub.add_parser("intraday", help="Run intraday pipeline (single snapshot)")
    intra.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    intra.add_argument("--update-data", action="store_true", help="Run intraday retrieve.py updater before computing")

    # Placeholder for a unified data update command
    upd = sub.add_parser("update-data", help="Run data retrieval/update routines")
    upd.add_argument(
        "--modules",
        nargs="*",
        default=None,
        help="Optional list of additional retrieve module paths to import/register (in addition to engine defaults)",
    )
    upd.add_argument(
        "--retrievers",
        nargs="*",
        default=None,
        help="Optional list of registered retriever names to run (defaults to all registered)",
    )

    return p


def main(argv: list[str] | None = None, *, project_root: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = project_root or Path(__file__).resolve().parents[1]

    if args.cmd == "eod":
        cfg = build_run_config(project_root=project_root, mode="eod", asof=args.asof)
        eod_pipeline.run(cfg, update_data=args.update_data)
        return 0

    if args.cmd == "intraday":
        cfg = build_run_config(project_root=project_root, mode="intraday", asof=args.asof)
        intraday_pipeline.run(cfg, update_data=args.update_data)
        return 0

    if args.cmd == "update-data":
        # Lazy import to keep CLI snappy
        from engine.data_update import load_default_retrievers, run_data_update

        cfg = build_run_config(project_root=project_root, mode="data", asof=date.today())
        load_default_retrievers(extra_modules=args.modules)
        run_data_update(cfg, names=args.retrievers)
        return 0

    raise ValueError(f"Unknown cmd: {args.cmd}")
