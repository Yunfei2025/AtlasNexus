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

    sub.add_parser("web", help="Start FI dashboard (Dash)")
    sub.add_parser("daily-web", help="Start AtlasNexus Daily Console (Dash, port 8080)")
    sub.add_parser("intraday-web", help="Start AtlasNexus Intraday Console (Dash, port 8081)")
    sub.add_parser("surface", help="Start yield surface viewer (Dash)")
    sub.add_parser("factor", help="Run factor analysis")
    sub.add_parser("derivatives", help="Run derivative pricing / strategy")
    sub.add_parser("portfolio", help="Run portfolio optimization")

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

    return p

def run_web_app():
    """Run the web application"""
    logger.info("Initializing web application...")
    try:
        logger.info("Importing web.apps.fi module...")
        from web.apps import fi
        # Reduce HTTP access logs noise (Werkzeug/Flask)
        try:
            import logging as _logging
            _logging.getLogger("werkzeug").setLevel(_logging.WARNING)
            _logging.getLogger("werkzeug._internal").setLevel(_logging.WARNING)
            _logging.getLogger("werkzeug.serving").setLevel(_logging.WARNING)
            _logging.getLogger("urllib3.connectionpool").setLevel(_logging.WARNING)
        except Exception:
            pass
        
        logger.info("🚀 Starting FI Engine Dashboard")
        logger.info("📈 Fixed Income Curves and Spreads")
        
        # Always run in the current process when called from menu
        logger.info("Starting server on 127.0.0.1:8052...")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")
        
        try:
            fi.app.run(host='127.0.0.1', port=8052, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("👋 Web server stopped by user")
        except Exception as e:
            logger.error(f"❌ Web server error: {e}")
                
    except ImportError as e:
        logger.error(f"❌ Failed to import web app: {e}")
        logger.info("Make sure all dependencies are installed: pip install -r requirements/development.txt")
    except Exception as e:
        logger.error(f"❌ Failed to start web server: {e}")

def run_surface_app():
    """Run the yield surface visualization application"""
    logger.info("Initializing yield surface visualization...")
    try:
        logger.info("Importing web.apps.surface module...")
        from web.apps.surface import run
        # Reduce HTTP access logs noise
        try:
            import logging as _logging
            _logging.getLogger("werkzeug").setLevel(_logging.WARNING)
            _logging.getLogger("werkzeug._internal").setLevel(_logging.WARNING)
            _logging.getLogger("werkzeug.serving").setLevel(_logging.WARNING)
            _logging.getLogger("urllib3.connectionpool").setLevel(_logging.WARNING)
        except Exception:
            pass
        
        logger.info("🚀 Starting Yield Surface Viewer")
        logger.info("📊 3D Yield Curve Visualization")
        logger.info("Starting server on 127.0.0.1:8053...")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")
        
        try:
            run(debug=False, port=8053)
        except KeyboardInterrupt:
            logger.info("👋 Surface viewer stopped by user")
        except Exception as e:
            logger.error(f"❌ Surface viewer error: {e}")
                
    except ImportError as e:
        logger.error(f"❌ Failed to import surface app: {e}")
        logger.info("Make sure all dependencies are installed: pip install -r requirements/development.txt")
    except Exception as e:
        logger.error(f"❌ Failed to start surface viewer: {e}")


def run_atlasnexus_daily_app():
    """Run AtlasNexus Daily Console (new app, port 8080)."""
    logger.info("Initializing AtlasNexus Daily Console...")
    try:
        from web.apps import atlasnexus_daily

        logger.info("🚀 Starting AtlasNexus Daily Console")
        logger.info("Starting server on 127.0.0.1:8080...")
        logger.info("Web server starting... Press Ctrl+C to stop and return to main menu")

        try:
            atlasnexus_daily.app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            logger.info("👋 AtlasNexus Daily Console stopped by user")
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

def run_factor_analysis():
    """Run factor analysis"""
    logger.info("Initializing factor analysis...")
    try:
        logger.info("Importing factors.main module...")
        from factors.main import main
        logger.info("🧮 Starting factor analysis...")
        result = main()
        if result:
            logger.info("Factor analysis completed successfully")
        else:
            logger.warning("Factor analysis returned no result")
        return result
    except ImportError as e:
        logger.error(f"❌ Failed to import factor analysis: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error during factor analysis: {e}")
        return None

def run_derivative_pricing():
    """Run derivative pricing"""
    logger.info("Initializing derivative pricing...")
    try:
        logger.info("Importing derivatives.options.main module...")
        from derivatives.options.main import main
        logger.info("📊 Starting derivative pricing...")
        result = main()
        if result:
            logger.info("Derivative pricing completed successfully")
        else:
            logger.warning("Derivative pricing returned no result")
        return result
    except ImportError as e:
        logger.error(f"❌ Failed to import derivative pricing: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error during derivative pricing: {e}")
        return None

def run_portfolio_optimization():
    """Run portfolio optimization"""
    logger.info("Initializing portfolio optimization...")
    try:
        logger.info("Importing portfolio.generators.portfolio module...")
        # Updated import to match existing module name
        from portfolio.generators.portfolio import constructPortfolio
        logger.info("📈 Starting portfolio optimization...")
        result = constructPortfolio(xlwings=False)
        if result:
            logger.info("Portfolio optimization completed successfully")
        else:
            logger.warning("Portfolio optimization returned no result")
        return result
    except ImportError as e:
        logger.error(f"❌ Failed to import portfolio optimization: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error during portfolio optimization: {e}")
        return None

def main():
    """Main entrypoint.

    Default behavior (no args): start the FI dashboard.
    Use subcommands to run EOD/intraday pipelines and data updates.
    """

    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:])

    logger.info("=" * 60)
    logger.info("🏦 FIEngine - Financial Engineering Platform")
    logger.info("=" * 60)

    # Backwards-compatible default behavior
    if not getattr(args, "cmd", None):
        logger.info("Starting web interface (FI Dashboard)...")
        run_web_app()
        logger.info("Main process completed.")
        return

    if args.cmd == "web":
        run_web_app()
        return

    if args.cmd == "daily-web":
        run_atlasnexus_daily_app()
        return

    if args.cmd == "intraday-web":
        run_atlasnexus_intraday_app()
        return

    if args.cmd == "surface":
        run_surface_app()
        return

    if args.cmd == "factor":
        run_factor_analysis()
        return

    if args.cmd == "derivatives":
        run_derivative_pricing()
        return

    if args.cmd == "portfolio":
        run_portfolio_optimization()
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
        if args.cmd == "refresh" and getattr(args, "steps", None):
            engine_argv.extend(["--steps", *args.steps])
        if args.cmd == "scheduler":
            engine_argv.extend(["--interval", str(args.interval)])
            engine_argv.extend(["--start-hour", str(args.start_hour)])
            engine_argv.extend(["--end-hour", str(args.end_hour)])
            engine_argv.extend(["--mode", args.mode])

        engine_main(engine_argv, project_root=project_root)
        return

    raise ValueError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    # Configure logging and show live log window only in the main process
    try:
        from utils.log_window import setup_logging, get_logger
        # Ensure only the main process creates the GUI log window
        setup_logging(show_window=True)
        logger = get_logger(__name__)
    except Exception:
        # Fallback: continue without GUI logging
        logger = logging.getLogger(__name__)
    main()
