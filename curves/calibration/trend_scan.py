# -*- coding: utf-8 -*-
"""TREND_ROUTED_INSTRUMENTS re-validation scan.

Reproduces the (undocumented, one-off) analysis that originally justified
``web/tabs/alpha/data/constants.py``'s ``TREND_ROUTED_INSTRUMENTS`` whitelist
(currently just ``{('TenorSpread', 'CGB-10s30s')}``), as a standalone,
re-runnable module rather than a hand-maintained constant with no audit
trail. See conversation notes 2026-09-19: nothing in the daily/EOD pipeline
re-validates that whitelist as the book grows, so newly added instruments
(TermBasisEvent, the OFR-ladder stages, SectorPCASpread, ...) have never
actually been tested for trend-routing eligibility.

Two independent checks must both agree before flagging an instrument as a
trend-routing candidate:

  1. Regime classification (``curves.calibration.regime.
     compute_regime_features_dual``) on its ~1yr long window votes
     'trending' as of the *latest* available observation. The long window is
     used deliberately -- see regime.py's ``LONG_REGIME_WINDOW`` docstring on
     why a 60d short window cannot see a multi-quarter trend. This is a
     point-in-time snapshot, not a walk-forward monthly reclassification: the
     question this scan answers is "is trend-routing still justified today",
     re-run periodically (monthly/quarterly), not "what should today's live
     trading regime be" (that decision is out of scope --
     ALLOW_TREND_STYLE_DEFAULT=False and stays that way regardless of this
     scan's output).
  2. Empirical backtest comparison: MR (engine_mr, fixed preset params) is
     flat-to-losing (near-zero trade count OR non-positive Sharpe) while
     trend, run through the SAME engine that actually trades a whitelisted
     instrument (engine_monthly.run_monthly_style_backtest, with
     allow_trend_style forced True and an all-'trend' schedule -- not
     engine_trend.run_trend_backtest standalone, see the correction below),
     is clearly and consistently profitable, over BOTH full history and a
     recent window -- the same bar the original scan used (see
     TREND_ROUTED_INSTRUMENTS's docstring: MR positive on 13/14 instruments,
     trend only won convincingly on CGB-10s30s). Fixed params across every
     instrument, deliberately -- see alpha-backtest-no-param-tuning: this is
     a routing test, not a tuning exercise, and per-instrument-tuned
     parameters would not generalize.

     CORRECTED 2026-09-25: this scan previously validated the trend leg with
     engine_trend.run_trend_backtest directly. That is NOT the engine a
     reviewed/whitelisted instrument actually trades under -- the individual
     backtest panel and the portfolio backtest's saved-state branch both run
     engine_monthly.run_monthly_style_backtest, which additionally applies
     trend_max_flip_age (a freshness gate on the first entry into a momentum
     flip, with no equivalent in run_trend_backtest) and the monthly review
     cadence. This mismatch let CGB-10s20s30s pass this scan
     (run_trend_backtest: full=0.51, recent=0.70) while actually losing money
     under the engine that trades it (run_monthly_style_backtest: 2y Sharpe
     -1.41, 5y -0.16) -- see TREND_ROUTED_INSTRUMENTS's removal note. Fixed
     by validating against run_monthly_style_backtest instead.

Only EventDriven types (BondNewIssue, TermBasisEvent) are excluded --
they have no continuous z-score history to run engine_mr/engine_trend
against by design (see engine_event.py's docstring).

Usage:
    python -m curves.calibration.trend_scan
    python -m curves.calibration.trend_scan --recent-years 2

Cadence: run monthly or quarterly (not daily -- a single month's regime
vote/backtest window rarely moves enough to change the routing conclusion,
and this is meant to catch drift over the book's evolution, not react to
daily noise). Does not mutate TREND_ROUTED_INSTRUMENTS automatically --
prints a diff against the current whitelist for a human to review.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from curves.calibration.regime import compute_regime_features_dual, LONG_REGIME_WINDOW


# Fixed preset params, identical for every instrument in the scan -- see
# module docstring on why these must not be tuned per instrument.
_MR_PARAMS: Dict[str, Any] = dict(entry_z=2.0, exit_z=0.5, stop_z=3.0, min_hold=7)
# Matches backtest_tab.py's preset_backtest_params TenorSpread preset -- the
# actual default an unreviewed instrument would run under in production,
# since the trend leg is now validated through run_monthly_style_backtest
# (see module docstring's 2026-09-25 correction), not the standalone
# run_trend_backtest engine.
_TREND_PARAMS: Dict[str, Any] = dict(
    entry_z=2.5, exit_z=0.25, stop_z=3.0, min_hold=10,
    theta_z=1.5, mom_window=30, vol_window=90, trailing_mult=2.0,
)

# MR must trade almost nothing, or lose money, for trend-routing to even be
# considered -- matches the original scan's "MR barely trades it (near-zero
# trade count) or loses money" bar (constants.py's TREND_ROUTED_INSTRUMENTS
# docstring).
_MR_MAX_TRADES_FOR_SPARSE = 3
_MR_MAX_SHARPE_FOR_LOSING = 0.0

# Trend must be unambiguously good, on both windows, to promote an
# instrument -- a marginal trend Sharpe is more likely noise than alpha
# given only 1 instrument qualified out of 48 candidates originally.
_TREND_MIN_SHARPE = 0.3
_TREND_MIN_TRADES = 5

RECENT_YEARS_DEFAULT = 3

# Minimum TOTAL history required before an instrument is even considered --
# well above compute_regime_features_dual's bare LONG_REGIME_WINDOW+5 (~265
# obs) warm-up floor. That floor only guarantees the regime classifier can
# run; it does not guarantee the *recent* and *full* backtest windows are
# meaningfully distinct, or that a 1-2yr-old bond's handful of trades over
# its short life are anything but noise. A freshly-issued bond (e.g.
# TBondCurve/CBondCurve's individual bond codes, which can be <18 months
# old) structurally cannot support this scan's "consistent across two
# independent windows" logic -- require enough history that the recent
# window (recent_years) is a genuine sub-period, not the whole series.
_MIN_TOTAL_YEARS = 4.0
_MIN_TOTAL_OBS = int(_MIN_TOTAL_YEARS * 250)

# EventDriven types have no continuous pair history (episodes rebind at
# every rank/roll change) -- excluded from this scan by design, matching
# engine_event.py's "never routed through MR/trend" rationale.
_EVENT_DRIVEN_TYPES = {'BondNewIssue', 'TermBasisEvent'}


@dataclass
class InstrumentScanResult:
    spread_type: str
    instrument: str
    n_obs: int
    regime_long: str
    regime_score_long: float
    long_window_available: bool
    mr_n_trades: int
    mr_sharpe: float
    mr_sparse_or_losing: bool
    trend_full_sharpe: float
    trend_full_n_trades: int
    trend_recent_sharpe: float
    trend_recent_n_trades: int
    trend_convincing: bool
    currently_whitelisted: bool
    recommend_trend_route: bool
    notes: List[str] = field(default_factory=list)


def _mr_sparse_or_losing(mr_result: Dict[str, Any]) -> bool:
    n_trades = int(mr_result.get('n_trades', 0) or 0)
    sharpe = float(mr_result.get('sharpe', 0.0) or 0.0)
    return n_trades <= _MR_MAX_TRADES_FOR_SPARSE or sharpe <= _MR_MAX_SHARPE_FOR_LOSING


def _trend_convincing(full_result: Dict[str, Any], recent_result: Dict[str, Any]) -> bool:
    def _ok(r: Dict[str, Any]) -> bool:
        return (
            int(r.get('n_trades', 0) or 0) >= _TREND_MIN_TRADES
            and float(r.get('sharpe', 0.0) or 0.0) >= _TREND_MIN_SHARPE
        )
    return _ok(full_result) and _ok(recent_result)


def scan_instrument(
    spread_type: str,
    instrument: str,
    spread_ts: pd.Series,
    *,
    currently_whitelisted: bool,
    recent_years: int = RECENT_YEARS_DEFAULT,
) -> Optional[InstrumentScanResult]:
    """Run both checks for one instrument's spread series. Returns None if

    there isn't enough TOTAL history for the full-vs-recent comparison to be
    meaningful (see ``_MIN_TOTAL_OBS`` -- well above
    compute_regime_features_dual's own, looser warm-up floor).
    """
    from web.tabs.alpha.backtest.engine_mr import run_spread_backtest
    from web.tabs.alpha.backtest.engine_monthly import run_monthly_style_backtest

    s = pd.to_numeric(spread_ts, errors='coerce').dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, errors='coerce')
        s = s[~s.index.isna()].sort_index()
    else:
        s = s.sort_index()

    if len(s) < _MIN_TOTAL_OBS:
        return None

    regime = compute_regime_features_dual(s)
    notes: List[str] = []
    if not regime.get('long_window_available', False):
        notes.append('long_window_unavailable_fallback_to_short')

    mr_result = run_spread_backtest(s, spread_type=spread_type, **_MR_PARAMS)

    def _all_trend_schedule(series: pd.Series) -> Dict[pd.Period, str]:
        """Every calendar month covered by `series` mapped to 'trend'.

        This scan asks "if this instrument were fully trend-routed, would the
        actual production engine make money on it" -- not "what does the
        monthly regime classifier decide" (that is a separate, orthogonal
        question the classifier answers for real at trade time, gated by
        allow_trend_style; see build_monthly_style_schedule). Using an
        all-trend schedule here isolates the engine/parameter comparison from
        the classifier's own monthly accuracy, matching what _TREND_PARAMS
        already does for the rest of this scan (fixed, uniform conditions).
        """
        return {p: 'trend' for p in series.index.to_period('M').unique()}

    trend_full = run_monthly_style_backtest(
        s, _all_trend_schedule(s), allow_short=True, spread_type=spread_type, **_TREND_PARAMS
    )

    # The recent window must be a genuinely distinct sub-period -- i.e. there
    # must be enough history *before* the cutoff too, or "recent" degenerates
    # into "the whole series again" and the two windows stop being
    # independent checks (caught in practice: a young instrument passing
    # _MIN_TOTAL_OBS by only a little would otherwise silently duplicate
    # trend_full into trend_recent).
    recent_cutoff = s.index.max() - pd.DateOffset(years=recent_years)
    s_recent = s.loc[s.index >= recent_cutoff]
    s_before_recent = s.loc[s.index < recent_cutoff]
    if len(s_recent) < LONG_REGIME_WINDOW + 5 or len(s_before_recent) < LONG_REGIME_WINDOW + 5:
        trend_recent = {'n_trades': 0, 'sharpe': 0.0}
        notes.append('recent_window_not_a_distinct_subperiod')
    else:
        trend_recent = run_monthly_style_backtest(
            s_recent, _all_trend_schedule(s_recent), allow_short=True,
            spread_type=spread_type, **_TREND_PARAMS,
        )

    mr_sparse_or_losing = _mr_sparse_or_losing(mr_result)
    trend_ok = _trend_convincing(trend_full, trend_recent)
    regime_votes_trending = regime.get('regime_long') == 'trending'

    recommend = mr_sparse_or_losing and trend_ok
    if recommend and not regime_votes_trending:
        notes.append('empirical_bar_met_but_regime_long_disagrees_review_before_promoting')

    return InstrumentScanResult(
        spread_type=spread_type, instrument=instrument, n_obs=len(s),
        regime_long=str(regime.get('regime_long', 'uncertain')),
        regime_score_long=float(regime.get('regime_score_long', np.nan)),
        long_window_available=bool(regime.get('long_window_available', False)),
        mr_n_trades=int(mr_result.get('n_trades', 0) or 0),
        mr_sharpe=float(mr_result.get('sharpe', 0.0) or 0.0),
        mr_sparse_or_losing=mr_sparse_or_losing,
        trend_full_sharpe=float(trend_full.get('sharpe', 0.0) or 0.0),
        trend_full_n_trades=int(trend_full.get('n_trades', 0) or 0),
        trend_recent_sharpe=float(trend_recent.get('sharpe', 0.0) or 0.0),
        trend_recent_n_trades=int(trend_recent.get('n_trades', 0) or 0),
        trend_convincing=trend_ok,
        currently_whitelisted=currently_whitelisted,
        recommend_trend_route=recommend,
        notes=notes,
    )


def run_full_scan(recent_years: int = RECENT_YEARS_DEFAULT) -> List[InstrumentScanResult]:
    """Scan every instrument across every non-EventDriven spread type in the

    book's SPREAD_TYPE_OPTIONS universe. Skips instruments with too little
    history (see scan_instrument) rather than erroring.
    """
    from web.tabs.alpha.data.constants import SPREAD_TYPE_OPTIONS, TREND_ROUTED_INSTRUMENTS
    from web.tabs.alpha.data.loaders import load_spread_timeseries

    results: List[InstrumentScanResult] = []
    spread_types = sorted({
        o['value'] for o in SPREAD_TYPE_OPTIONS if o['value'] not in _EVENT_DRIVEN_TYPES
    })

    for spread_type in spread_types:
        ts = load_spread_timeseries(spread_type)
        if not isinstance(ts, pd.DataFrame) or ts.empty:
            continue
        for instrument in ts.columns:
            result = scan_instrument(
                spread_type, str(instrument), ts[instrument],
                currently_whitelisted=(spread_type, str(instrument)) in TREND_ROUTED_INSTRUMENTS,
                recent_years=recent_years,
            )
            if result is not None:
                results.append(result)
    return results


def print_report(results: List[InstrumentScanResult]) -> None:
    from web.tabs.alpha.data.constants import TREND_ROUTED_INSTRUMENTS

    recommended = {(r.spread_type, r.instrument) for r in results if r.recommend_trend_route}
    current = set(TREND_ROUTED_INSTRUMENTS)

    print(f"Scanned {len(results)} instruments.\n")

    flagged = sorted(
        (r for r in results if r.recommend_trend_route or r.currently_whitelisted),
        key=lambda r: (not r.recommend_trend_route, r.spread_type, r.instrument),
    )
    if flagged:
        print(f"{'spread_type':<18}{'instrument':<20}{'regime_long':<16}{'mr_n':>6}{'mr_shp':>8}"
              f"{'tr_full_shp':>12}{'tr_rec_shp':>12}{'whitelisted':>13}{'recommend':>11}")
        for r in flagged:
            print(f"{r.spread_type:<18}{r.instrument:<20}{r.regime_long:<16}{r.mr_n_trades:>6}"
                  f"{r.mr_sharpe:>8.2f}{r.trend_full_sharpe:>12.2f}{r.trend_recent_sharpe:>12.2f}"
                  f"{str(r.currently_whitelisted):>13}{str(r.recommend_trend_route):>11}")
            for note in r.notes:
                print(f"    note: {note}")
    else:
        print("No instrument met the empirical bar (MR sparse/losing AND trend convincing "
              "on both full-history and recent windows).")

    added = recommended - current
    removed = current - recommended
    print("\n--- Diff vs. current TREND_ROUTED_INSTRUMENTS ---")
    if not added and not removed:
        print("No change recommended: whitelist still matches this scan's conclusions.")
    else:
        for item in sorted(added):
            print(f"  + ADD    {item}")
        for item in sorted(removed):
            print(f"  - REMOVE {item}  (no longer meets the bar this run -- review before removing; "
                  f"could be a temporary regime shift rather than a durable change)")
    print("\nThis script never mutates TREND_ROUTED_INSTRUMENTS automatically -- "
          "update web/tabs/alpha/data/constants.py by hand after review.")


def scan_report_dict(recent_years: int = RECENT_YEARS_DEFAULT) -> Dict[str, Any]:
    """JSON-serializable version of :func:`print_report`, for the EOD pipeline.

    Never mutates ``TREND_ROUTED_INSTRUMENTS`` (same contract as the CLI) --
    this is a report for a human to review, not an auto-apply. See
    ``calibrate_trend_routing`` in ``curves/interface.py`` for the caller that
    persists this as a run artifact on a monthly cadence.
    """
    from web.tabs.alpha.data.constants import TREND_ROUTED_INSTRUMENTS

    results = run_full_scan(recent_years=recent_years)
    recommended = {(r.spread_type, r.instrument) for r in results if r.recommend_trend_route}
    current = set(TREND_ROUTED_INSTRUMENTS)
    added = sorted(f"{st}/{inst}" for st, inst in (recommended - current))
    removed = sorted(f"{st}/{inst}" for st, inst in (current - recommended))

    flagged = sorted(
        (r for r in results if r.recommend_trend_route or r.currently_whitelisted),
        key=lambda r: (not r.recommend_trend_route, r.spread_type, r.instrument),
    )
    return {
        'n_scanned': len(results),
        'recent_years': recent_years,
        'current_whitelist': sorted(f"{st}/{inst}" for st, inst in current),
        'recommend_add': added,
        'recommend_remove': removed,
        'in_sync': not added and not removed,
        'flagged': [
            {
                'spread_type': r.spread_type,
                'instrument': r.instrument,
                'regime_long': r.regime_long,
                'mr_n_trades': r.mr_n_trades,
                'mr_sharpe': r.mr_sharpe,
                'trend_full_sharpe': r.trend_full_sharpe,
                'trend_recent_sharpe': r.trend_recent_sharpe,
                'currently_whitelisted': r.currently_whitelisted,
                'recommend_trend_route': r.recommend_trend_route,
                'notes': r.notes,
            }
            for r in flagged
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recent-years', type=int, default=RECENT_YEARS_DEFAULT,
                         help='Length of the "recent window" trend check, in years (default: %(default)s)')
    args = parser.parse_args()
    results = run_full_scan(recent_years=args.recent_years)
    print_report(results)


if __name__ == '__main__':
    main()
