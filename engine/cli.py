from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path

from engine.context import build_run_config
from settings.general import TradingHoursConfig

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> date:
    # Accept YYYY-MM-DD
    return datetime.strptime(s, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="FIEngine", description="FIEngine orchestration CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ── EOD ────────────────────────────────────────────────────────────
    eod = sub.add_parser("eod", help="Run daily EOD pipeline")
    eod.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    eod.add_argument("--update-data", action="store_true", help="Run retrieve.py updaters before computing")

    # ── Intraday ───────────────────────────────────────────────────────
    intra = sub.add_parser("intraday", help="Run intraday pipeline (single snapshot)")
    intra.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    intra.add_argument("--update-data", action="store_true", help="Run intraday retrieve.py updater before computing")

    # ── Refresh ────────────────────────────────────────────────────────
    refresh = sub.add_parser("refresh", help="Run intraday refresh pipeline (rates/credit/irs/stat)")
    refresh.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    refresh.add_argument(
        "--steps",
        nargs="*",
        default=None,
        help="Refresh step names to run (default: all). Choices: rates, credit, irs, stat",
    )

    # ── Scheduler ──────────────────────────────────────────────────────
    sched = sub.add_parser("scheduler", help="Start periodic refresh scheduler during trading hours")
    sched.add_argument("--interval", type=int, default=300, help="Seconds between refresh ticks (default: 300)")
    sched.add_argument("--start-hour", type=int, default=TradingHoursConfig.START_HOUR, help=f"Trading window start hour (default: {TradingHoursConfig.START_HOUR})")
    sched.add_argument("--end-hour", type=int, default=TradingHoursConfig.END_HOUR, help=f"Trading window end hour (default: {TradingHoursConfig.END_HOUR})")
    sched.add_argument(
        "--mode",
        choices=["refresh", "intraday"],
        default="refresh",
        help="Pipeline to run each tick (default: refresh)",
    )

    # ── Data update ────────────────────────────────────────────────────
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
    upd.add_argument(
        "--force",
        action="store_true",
        help="Force refresh even if a target artifact was already updated today",
    )

    return p


def main(argv: list[str] | None = None, *, project_root: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = project_root or Path(__file__).resolve().parents[1]

    if args.cmd == "eod":
        from engine.pipeline import eod as eod_pipeline
        cfg = build_run_config(project_root=project_root, mode="eod", asof=args.asof)
        eod_pipeline.run(cfg, update_data=args.update_data)
        return 0

    if args.cmd == "intraday":
        from engine.pipeline import intraday as intraday_pipeline
        cfg = build_run_config(project_root=project_root, mode="intraday", asof=args.asof)
        intraday_pipeline.run(cfg, update_data=args.update_data)
        return 0

    if args.cmd == "refresh":
        from engine.pipeline import refresh as refresh_pipeline
        cfg = build_run_config(project_root=project_root, mode="refresh", asof=args.asof)
        refresh_pipeline.run(cfg, steps=args.steps)
        return 0

    if args.cmd == "scheduler":
        from engine.scheduler import TradingHoursScheduler

        if args.mode == "intraday":
            from engine.pipeline import intraday as intraday_pipeline
            def _pipeline(c: "RunConfig") -> None:
                intraday_pipeline.run(c, update_data=True)
        else:
            def _pipeline(c: "RunConfig") -> None:
                from engine.pipeline import refresh as refresh_pipeline
                refresh_pipeline.run(c)

        scheduler = TradingHoursScheduler(
            pipeline_fn=_pipeline,
            project_root=project_root,
            interval_seconds=args.interval,
            start_hour=args.start_hour,
            end_hour=args.end_hour,
        )
        scheduler.run_blocking()
        return 0

    if args.cmd == "update-data":
        # Lazy import to keep CLI snappy
        from engine.data_update import load_default_retrievers, run_data_update
        from engine.schema import RunManifest

        cfg = build_run_config(project_root=project_root, mode="data", asof=date.today())
        load_default_retrievers(extra_modules=args.modules)
        status = run_data_update(cfg, names=args.retrievers, force=args.force)
        # Record a manifest so the run dir is non-empty and discoverable by
        # web/services/artifacts.find_latest_run("data") — previously these
        # dirs were created empty.
        RunManifest(
            run_id=cfg.run_id,
            mode=cfg.mode,
            asof=cfg.asof.isoformat(),
            generated_at=datetime.utcnow().isoformat(),
            status="completed",
            steps=status,
        ).write(cfg.output_dir / "run_meta.json")
        return 0

    raise ValueError(f"Unknown cmd: {args.cmd}")
