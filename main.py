#!/usr/bin/env python3

"""
Main entry point for FIEngine - Financial Engineering Platform
"""

import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Module-level logger placeholder; configured in __main__
logger = logging.getLogger(__name__)


def _parse_date(s: str) -> str:
    """Validate YYYY-MM-DD date strings for CLI."""
    datetime.strptime(s, "%Y-%m-%d")
    return s


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="FIEngine", description="FIEngine - Financial Engineering Platform")
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("daily-web", help="Start AtlasNexus Daily Console (Dash, port 8080)")
    sub.add_parser("intraday-web", help="Start AtlasNexus Intraday Console (Dash, port 8081)")

    eod = sub.add_parser("eod", help="Run daily EOD pipeline (engine)")
    eod.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    eod.add_argument("--update-data", action="store_true", help="Run retrieve.py updaters before computing")

    intra = sub.add_parser("intraday", help="Run intraday pipeline (engine)")
    intra.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    intra.add_argument("--update-data", action="store_true", help="Run intraday retrieve.py updater before computing")

    upd = sub.add_parser("update-data", help="Run data retrieval/update routines (engine)")
    upd.add_argument(
        "--modules",
        nargs="*",
        default=None,
        help="Optional list of module paths to run (defaults to engine defaults)",
    )
    upd.add_argument("--force", action="store_true", help="Force refresh even if data was already updated today")

    refresh = sub.add_parser("refresh", help="Run intraday refresh pipeline (engine)")
    refresh.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD")
    refresh.add_argument(
        "--steps",
        nargs="*",
        default=None,
        help="Refresh step names to run (default: all). Choices: rates, credit, irs, stat",
    )

    sched = sub.add_parser("scheduler", help="Start periodic refresh scheduler during trading hours")
    sched.add_argument("--interval", type=int, default=300, help="Seconds between refresh ticks (default: 300)")
    sched.add_argument("--start-hour", type=int, default=9, help="Trading window start hour (default: 9)")
    sched.add_argument("--end-hour", type=int, default=16, help="Trading window end hour (default: 16)")
    sched.add_argument(
        "--mode",
        choices=["refresh", "intraday"],
        default="refresh",
        help="Pipeline to run each tick (default: refresh)",
    )

    cb = sub.add_parser("curve-backtest", help="Run curve backtest (curves/backtest)")
    cb.add_argument("--btype", choices=["TBond", "CBond", "IRS"], default="IRS",
                    help="Instrument type (default: IRS)")
    cb.add_argument("--update-list", nargs="*", default=["pool"], dest="update_list",
                    help="Update steps: pool, bonds, cbts (default: pool)")
    cb.add_argument("--start", type=_parse_date, required=True, help="Backtest start date YYYY-MM-DD")
    cb.add_argument("--end", type=_parse_date, required=True, help="Backtest end date YYYY-MM-DD")
    cb.add_argument("--processes", type=int, default=4, help="Parallel workers (default: 4)")

    return p

def run_atlasnexus_daily_app():
    """Run AtlasNexus Daily Console (new app, port 8080)."""
    logger.info("Initializing AtlasNexus Daily Console...")
    try:
        from web.apps import atlasnexus_daily
        from web.core.scripts import run_initialise
        import webbrowser
        from threading import Timer

        logger.info("Starting AtlasNexus Daily Console")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")

        init_status = run_initialise()
        logger.info(f"AtlasNexus startup initialisation: {init_status}")

        Timer(1.5, lambda: webbrowser.open_new("http://127.0.0.1:8080/")).start()

        try:
            atlasnexus_daily.app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("AtlasNexus Daily Console stopped by user")
        except Exception as e:
            logger.error(f"❌ AtlasNexus Daily Console error: {e}")

    except ImportError as e:
        logger.error(f"❌ Failed to import AtlasNexus Daily app: {e}")
        logger.info("Make sure all dependencies are installed: pip install -r requirements/development.txt")
    except Exception as e:
        logger.error(f"❌ Failed to start AtlasNexus Daily Console: {e}")


def run_atlasnexus_intraday_app():
    """Run AtlasNexus Intraday Console (new app, port 8081)."""
    logger.info("Initializing AtlasNexus Intraday Console...")
    try:
        from web.apps import atlasnexus_intraday

        logger.info("🚀 Starting AtlasNexus Intraday Console")
        logger.info("Starting server on 127.0.0.1:8081...")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")

        try:
            atlasnexus_intraday.app.run(host="127.0.0.1", port=8081, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("👋 AtlasNexus Intraday Console stopped by user")
        except Exception as e:
            logger.error(f"❌ AtlasNexus Intraday Console error: {e}")

    except ImportError as e:
        logger.error(f"❌ Failed to import AtlasNexus Intraday app: {e}")
        logger.info("Make sure all dependencies are installed: pip install -r requirements/development.txt")
    except Exception as e:
        logger.error(f"❌ Failed to start AtlasNexus Intraday Console: {e}")

def main():
    """Main entrypoint.

    Default behavior (no args): start the FI dashboard.
    Use subcommands to run EOD/intraday pipelines and data updates.
    """

    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:])

    logger.info("=" * 60)
    logger.info(" AtlasNexus - Systematic Investment Platform")
    logger.info("=" * 60)

    # Default: start the main daily console.
    if not getattr(args, "cmd", None):
        run_atlasnexus_daily_app()
        return

    if args.cmd == "daily-web":
        run_atlasnexus_daily_app()
        return

    if args.cmd == "intraday-web":
        run_atlasnexus_intraday_app()
        return

    # Engine-driven orchestration
    if args.cmd in {"eod", "intraday", "update-data", "refresh", "scheduler"}:
        from engine.cli import main as engine_main

        engine_argv: list[str] = [args.cmd]
        if getattr(args, "asof", None):
            engine_argv.extend(["--asof", args.asof])
        if getattr(args, "update_data", False):
            engine_argv.append("--update-data")
        if args.cmd == "update-data" and getattr(args, "modules", None):
            engine_argv.extend(["--modules", *args.modules])
        if args.cmd == "update-data" and getattr(args, "force", False):
            engine_argv.append("--force")
        if args.cmd == "refresh" and getattr(args, "steps", None):
            engine_argv.extend(["--steps", *args.steps])
        if args.cmd == "scheduler":
            engine_argv.extend(["--interval", str(args.interval)])
            engine_argv.extend(["--start-hour", str(args.start_hour)])
            engine_argv.extend(["--end-hour", str(args.end_hour)])
            engine_argv.extend(["--mode", args.mode])

        engine_main(engine_argv, project_root=project_root)
        return

    if args.cmd == "curve-backtest":
        from curves.backtest.backtestor import Backtestor
        bt = Backtestor(
            btype=args.btype,
            start=args.start,
            end=args.end,
            update_list=args.update_list or ["pool"],
            processes=args.processes,
            serial=False,
        )
        bt.run()
        return

    raise ValueError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    # Configure logging and show live log window only in the main process
    try:
        from utils.log_window import setup_logging, get_logger
        # Ensure only the main process creates the GUI log window
        setup_logging(show_window=False)
        logger = get_logger(__name__)
    except Exception:
        # Fallback: continue without GUI logging
        logger = logging.getLogger(__name__)
    main()
