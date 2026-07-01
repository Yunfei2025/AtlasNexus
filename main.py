#!/usr/bin/env python3

"""
Main entry point for FIEngine - Financial Engineering Platform
"""

import os
import sys
import logging
import argparse
import socket
import multiprocessing as mp
from datetime import datetime
from pathlib import Path

def _configure_stdio() -> None:
    """Best-effort unbuffered text stdio for immediate log output."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            fileno = stream.fileno()
        except (AttributeError, OSError, ValueError):
            continue
        try:
            setattr(sys, name, open(fileno, mode='w', encoding='utf8', buffering=1, closefd=False))
        except OSError:
            continue


def _should_show_log_window(argv: list[str]) -> bool:
    """Return whether the Tk log window should be shown for this process."""
    env_override = os.environ.get("FI_SHOW_LOG_WINDOW")
    if env_override is not None:
        return env_override.strip().lower() in {"1", "true", "yes", "on"}

    cmd = argv[0] if argv else None
    if sys.platform.startswith("win") and cmd in {None, "daily-web", "intraday-web"}:
        return False
    return True


_configure_stdio()

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Module-level logger placeholder; configured in __main__
logger = logging.getLogger(__name__)


def _resolve_browser_host() -> str:
    """Return a browser-friendly host for local app launch.

    The web server may bind to ``0.0.0.0`` so it listens on all interfaces,
    but browsers cannot navigate to that address. Prefer a real local IPv4
    address and fall back to localhost.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0]
        if host and not host.startswith("127.") and host != "0.0.0.0":
            return host
    except OSError:
        pass
    return "127.0.0.1"


def _browser_url(port: int) -> str:
    return f"http://{_resolve_browser_host()}:{port}/"


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

    ri = sub.add_parser("refresh-instruments", help="Refresh *-InstrumentInfo.pkl for all bond/futures types")
    ri.add_argument("--asof", type=_parse_date, default=None, help="As-of date YYYY-MM-DD (defaults to previous working day)")

    cb = sub.add_parser("curve-backtest", help="Run curve backtest (curves/backtest)")
    cb.add_argument("--btype", choices=["TBond", "CBond", "IRS"], default="IRS",
                    help="Instrument type (default: IRS)")
    cb.add_argument("--update-list", nargs="*", default=["pool"], dest="update_list",
                    help="Update steps: pool, bonds, cbts (default: pool)")
    cb.add_argument("--start", type=_parse_date, required=True, help="Backtest start date YYYY-MM-DD")
    cb.add_argument("--end", type=_parse_date, required=True, help="Backtest end date YYYY-MM-DD")
    cb.add_argument("--processes", type=int, default=4, help="Parallel workers (default: 4)")

    fa = sub.add_parser("futures-analytics-backfill",
                        help="Refresh futures-db.pkl + rebuild futures-analytics.pkl (IRR/FYTM/CTD/closes history)")
    fa.add_argument("--start", type=_parse_date, default=None, dest="fa_start",
                    help="Start date YYYY-MM-DD (default: all available)")
    fa.add_argument("--end", type=_parse_date, default=None, dest="fa_end",
                    help="End date YYYY-MM-DD (default: today)")
    fa.add_argument("--rewrite", action="store_true",
                    help="Rewrite from scratch instead of incrementally appending")

    fs = sub.add_parser("futures-stats-update",
                        help="Compute Bond-Futures/TermBasis/FuturesSwap spreads → futures-spds.pkl")
    fs.add_argument("--asof", type=_parse_date, default=None, dest="fs_asof",
                    help="As-of date YYYY-MM-DD (default: today)")

    return p

def run_atlasnexus_daily_app():
    """Run AtlasNexus Daily Console (new app, port 8080)."""
    logger.info("Initializing AtlasNexus Daily Console...")
    try:
        from web.apps import atlasnexus_daily
        from web.core.scripts import run_initialise, start_periodic_refresh
        import webbrowser
        from threading import Timer

        logger.info("Starting AtlasNexus Daily Console")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")

        # Run initialise in a background thread so the Dash server starts
        # immediately and the page is accessible while data updates run.
        import threading
        def _bg_init():
            try:
                status = run_initialise()
                logger.info(f"AtlasNexus startup initialisation: {status}")
            except Exception as exc:
                logger.warning(f"AtlasNexus background initialisation error: {exc}")
        threading.Thread(target=_bg_init, daemon=True).start()

        # Drive periodic refreshers from a plain daemon thread instead of
        # Dash background callbacks. DiskcacheManager spawns a worker via
        # `multiprocess` which deadlocks on Windows because spawn re-imports
        # this module; the in-process thread behaves the same on every OS.
        start_periodic_refresh()

        browser_url = _browser_url(8080)
        logger.info(f"Opening AtlasNexus Daily Console in browser: {browser_url}")
        Timer(1.5, lambda: webbrowser.open_new(browser_url)).start()

        try:
            atlasnexus_daily.app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("AtlasNexus Daily Console stopped by user")
        except Exception as e:
            logger.error(f"❌ AtlasNexus Daily Console error: {e}")

    except ImportError as e:
        logger.error(f"❌ Failed to import AtlasNexus Daily app: {e}")
        logger.info("Make sure all dependencies are installed: pip install -r requirements/production.txt")
    except Exception as e:
        logger.error(f"❌ Failed to start AtlasNexus Daily Console: {e}")


def run_atlasnexus_intraday_app():
    """Run AtlasNexus Intraday Console (new app, port 8081)."""
    logger.info("Initializing AtlasNexus Intraday Console...")
    try:
        from web.apps import atlasnexus_intraday

        logger.info("🚀 Starting AtlasNexus Intraday Console")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")

        try:
            atlasnexus_intraday.app.run(host="0.0.0.0", port=8081, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("👋 AtlasNexus Intraday Console stopped by user")
        except Exception as e:
            logger.error(f"❌ AtlasNexus Intraday Console error: {e}")

    except ImportError as e:
        logger.error(f"❌ Failed to import AtlasNexus Intraday app: {e}")
        logger.info("Make sure all dependencies are installed: pip install -r requirements/production.txt")
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

    if args.cmd == "refresh-instruments":
        from curves.utils.retrieve import updateInstrumentDef
        asof = getattr(args, "asof", None)
        print(f"Refreshing instrument definitions (asof={asof or 'previous working day'})...")
        updateInstrumentDef(asof=asof, on_demand=True)
        print("Instrument definitions updated.")
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
        force_serial = (
            sys.platform.startswith("win")
            and args.processes > 1
            and os.environ.get("FI_DISABLE_WINDOWS_CURVE_MP", "0") == "1"
        )
        if force_serial:
            logger.warning(
                "Curve backtest multiprocessing was disabled explicitly on Windows; "
                "falling back to serial execution because FI_DISABLE_WINDOWS_CURVE_MP=1."
            )
        bt = Backtestor(
            btype=args.btype,
            start=args.start,
            end=args.end,
            update_list=args.update_list or ["pool"],
            processes=args.processes,
            serial=force_serial,
        )
        bt.run()
        return

    if args.cmd == "futures-analytics-backfill":
        import datetime as _dt
        from dateutil.relativedelta import relativedelta as _rd
        from curves.utils.retrieve import retrieveFuturesDatabaseTS
        from curves.generators.futures_analytics import FuturesAnalyticsGenerator
        # fa_start / fa_end arrive as 'YYYY-MM-DD' strings (or None).
        end_date = _dt.datetime.strptime(args.fa_end, "%Y-%m-%d").date() if args.fa_end else _dt.date.today()
        start_date = _dt.datetime.strptime(args.fa_start, "%Y-%m-%d").date() if args.fa_start else (end_date - _rd(years=2))
        # Step 1: refresh DIR_DATA/futures-db.pkl with the full Wind analytics
        # history (irr / fytm / ctd / contract closes) over the requested window.
        prange = [start_date, end_date]
        logger.info(
            f"futures-analytics-backfill: fetching futures-db.pkl {start_date} → {end_date}..."
        )
        try:
            retrieveFuturesDatabaseTS(prange, on_demand=True)
        except Exception as exc:
            logger.warning(f"futures-analytics-backfill: Wind retrieval failed ({exc}), "
                           "rebuilding from existing futures-db.pkl")
        # Step 2: reshape futures-db.pkl into futures-analytics.pkl
        start_str = args.fa_start.replace("-", "") if args.fa_start else None
        end_str = args.fa_end.replace("-", "") if args.fa_end else None
        rewrite = getattr(args, "rewrite", False)
        logger.info(
            f"futures-analytics-backfill: reshape start={start_str or 'all'}, "
            f"end={end_str or 'today'}, rewrite={rewrite}"
        )
        gen = FuturesAnalyticsGenerator(asof=end_str, start=start_str)
        gen.run(rewrite=rewrite)
        logger.info("futures-analytics-backfill: done.")
        return

    if args.cmd == "futures-stats-update":
        import datetime as _dt
        from curves.generators.stat import StatGenerator
        # fs_asof arrives as 'YYYY-MM-DD' string (or None).
        asof = _dt.datetime.strptime(args.fs_asof, "%Y-%m-%d").date() if args.fs_asof else _dt.date.today()
        asof_str = asof.strftime('%Y%m%d')
        logger.info(f"futures-stats-update: computing futures spreads for {asof}...")
        try:
            gen = StatGenerator(date=asof_str)
            gen.compute_futures_stats()
            logger.info("futures-stats-update: done.")
        except Exception as exc:
            logger.error(f"futures-stats-update: failed ({exc})")
            raise
        return

    raise ValueError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    # Configure logging and show live log window only in the main process
    try:
        from utils.log_window import setup_logging, get_logger
        mp.freeze_support()
        # Ensure only the main process creates the GUI log window
        setup_logging(show_window=_should_show_log_window(sys.argv[1:]))
        logger = get_logger(__name__)
    except Exception:
        # Fallback: continue without GUI logging
        logger = logging.getLogger(__name__)
    main()
