# -*- coding: utf-8 -*-
"""FuturesAnalyticsGenerator — pre-computation layer for CGB futures analytics.

Builds ``futures-analytics.pkl``: a dict keyed by ctype (``'T'``, ``'TF'``,
``'TL'``, ``'TS'``), each value a date-indexed DataFrame sourced **directly**
from Wind bond-futures analytics fields (no local CTD reconstruction).

Output columns per ctype:

============== ======================================================
Column         Description
============== ======================================================
contract_code  Front (main) contract code on that date (e.g. T2606.CFE)
ctd_code       CTD bond code (Wind tbf_ctd02)
futures_close  Front contract settlement price (per 100 face)
next_close     Next-season contract settlement price (per 100 face)
irr            Implied repo rate of the CTD (%, Wind tbf_irr02)
fytm           Futures implied YTM (%, Wind tbf_fytm02)
============== ======================================================

Data source: ``DIR_DATA/futures-db.pkl`` for full-history backfill, and an
incremental Wind window (``fetchFuturesDatabaseWindow``) for daily EOD updates.

Two modes:
  * ``run(rewrite=...)``  — backfill: reshape the full ``futures-db.pkl``
    (populated by ``retrieveFuturesDatabaseTS``) into per-ctype frames.  Used
    by the run-center ``futures-analytics-backfill`` job.
  * ``main(date)`` / ``update()`` — incremental: fetch a short Wind window and
    append new rows.  Used by the daily EOD pipeline.

Downstream: ``StatGenerator.compute_futures_stats`` reads this file to build
Bond-Futures (IRR − repo), Term Basis (front − next) and Futures-Swap
(FYTM − matched-tenor FR007 IRS) statistics into ``futures-spds.pkl``.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Optional

import pandas as pd
from dateutil.relativedelta import relativedelta

# ── bootstrap project root ────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from curves.utils.file import updatePKL, loadPKL
from settings.paths import DIR_INPUT, DIR_DATA


ANALYTICS_FILE = os.path.join(DIR_INPUT, 'futures-analytics.pkl')
FUTURES_DB_FILE = os.path.join(DIR_DATA, 'futures-db.pkl')

# ctype → column name in the futures-db frames
_CTYPE_COL = {'T': 'T.CFE', 'TF': 'TF.CFE', 'TS': 'TS.CFE', 'TL': 'TL.CFE'}

# Calendar-day lookback applied to the last stored date when fetching the
# incremental window — generous enough to absorb a few non-trading days and
# any late Wind revisions of recent values.
_INCREMENTAL_LOOKBACK_DAYS = 20

# Default history pulled when no existing analytics file is found and
# futures-db.pkl is also unavailable (incremental cold-start).
_COLDSTART_YEARS = 1


def _reshape_db(db: Optional[dict]) -> dict:
    """Reshape a futures-db window dict into per-ctype analytics frames."""
    out: dict = {}
    if not isinstance(db, dict):
        return out

    _numeric = {'irr', 'ytm', 'contract_cls', 'contract1_cls'}

    def _col(key: str, ctype_col: str):
        df = db.get(key)
        if not isinstance(df, pd.DataFrame) or ctype_col not in df.columns:
            return None
        s = df[ctype_col]
        return pd.to_numeric(s, errors='coerce') if key in _numeric else s

    for ctype, col in _CTYPE_COL.items():
        futures_close = _col('contract_cls', col)
        if futures_close is None:
            continue
        frame = pd.DataFrame({
            'contract_code': _col('contract', col),
            'ctd_code':      _col('ctd', col),
            'futures_close': futures_close,
            'next_close':    _col('contract1_cls', col),
            'irr':           _col('irr', col),
            'fytm':          _col('ytm', col),
        })
        frame.index = pd.DatetimeIndex(frame.index)
        frame.index.name = 'date'
        out[ctype] = frame.sort_index()
    return out


def _merge(existing: dict, new: dict) -> dict:
    """Merge per-ctype frames, preferring new rows on date collisions."""
    updated = dict(existing) if isinstance(existing, dict) else {}
    for ctype, ndf in new.items():
        if ndf is None or ndf.empty:
            continue
        prev = updated.get(ctype)
        if isinstance(prev, pd.DataFrame) and not prev.empty:
            combined = pd.concat([prev, ndf])
            combined = combined[~combined.index.duplicated(keep='last')].sort_index()
            updated[ctype] = combined
        else:
            updated[ctype] = ndf.sort_index()
    return updated


class FuturesAnalyticsGenerator:
    """Build / incrementally update ``futures-analytics.pkl``."""

    CTYPES = ('T', 'TF', 'TL', 'TS')

    def __init__(self, asof: Optional[str] = None, start: Optional[str] = None) -> None:
        self.asof  = pd.Timestamp(asof)  if asof  else pd.Timestamp.today()
        self.start = pd.Timestamp(start) if start else None

    @classmethod
    def main(cls, date: Optional[str] = None) -> None:
        """Standard EOD entry-point (curves/initialise.py) — incremental update."""
        cls(asof=date).update()

    # ── backfill (run-center) ──────────────────────────────────────────────────
    def run(self, rewrite: bool = False) -> None:
        """Reshape the full ``futures-db.pkl`` into ``futures-analytics.pkl``.

        Backfill path: ``futures-db.pkl`` is expected to have been refreshed by
        ``retrieveFuturesDatabaseTS`` beforehand.  With ``rewrite=True`` the
        analytics file is fully rebuilt; otherwise new rows are merged in.
        """
        db = loadPKL(FUTURES_DB_FILE)
        if not db:
            print(f'FuturesAnalyticsGenerator: {FUTURES_DB_FILE} missing/empty — nothing to backfill.')
            return

        reshaped = _reshape_db(db)
        reshaped = self._clip(reshaped)
        if not reshaped:
            print('FuturesAnalyticsGenerator: no ctype frames reshaped from futures-db — skipping.')
            return

        existing = {} if rewrite else (loadPKL(ANALYTICS_FILE) or {})
        updated = _merge(existing, reshaped)
        updatePKL(updated, ANALYTICS_FILE, rewrite=True)
        self._report(reshaped, mode='backfill')
        print(f'FuturesAnalyticsGenerator: saved {ANALYTICS_FILE} (asof {self.asof.date()})')

    # ── incremental (daily EOD) ────────────────────────────────────────────────
    def update(self) -> None:
        """Fetch a short Wind window and append new rows to the analytics file.

        Skips Wind fetch if:
        - Analytics already current for today, OR
        - futures-px.pkl is missing/stale (no data fetched during EOD --update-data)
        """
        existing = loadPKL(ANALYTICS_FILE) or {}

        # Find last date in existing analytics
        last_analytics_date = None
        for ctype in self.CTYPES:
            df = existing.get(ctype)
            if isinstance(df, pd.DataFrame) and not df.empty:
                ctype_max = df.index.max()
                last_analytics_date = ctype_max if last_analytics_date is None else max(last_analytics_date, ctype_max)

        # If analytics are current for today, skip fetch
        if last_analytics_date is not None and last_analytics_date.date() == self.asof.date():
            print(f'FuturesAnalyticsGenerator: analytics already current for {self.asof.date()} — skipping fetch')
            return

        # Check if futures-px.pkl has been updated (indicates data retrieval was run)
        futures_db = loadPKL(os.path.join(DIR_INPUT, 'futures-px.pkl')) or {}
        if not futures_db:
            print(f'FuturesAnalyticsGenerator: futures-px.pkl missing/empty — skipping fetch (run with --update-data to retrieve)')
            return

        # Find latest date in futures-px.pkl
        futures_max_date = None
        for key, df in futures_db.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                df_max = df.index.max()
                futures_max_date = df_max if futures_max_date is None else max(futures_max_date, df_max)

        if futures_max_date is None:
            print(f'FuturesAnalyticsGenerator: futures-px.pkl has no data — skipping fetch')
            return

        # If futures data is older than last analytics, no new data to process
        if last_analytics_date is not None and futures_max_date <= last_analytics_date:
            print(f'FuturesAnalyticsGenerator: no new data in futures-px.pkl (latest: {futures_max_date.date()}, analytics: {last_analytics_date.date()}) — skipping fetch')
            return

        from curves.utils.retrieve import fetchFuturesDatabaseWindow

        prange = self._incremental_range(existing)
        print(f'FuturesAnalyticsGenerator: incremental window '
              f'{prange[0].date()} → {prange[-1].date()}')

        try:
            db = fetchFuturesDatabaseWindow(prange, on_demand=True)
        except Exception as exc:
            print(f'FuturesAnalyticsGenerator: Wind fetch failed ({exc}) — '
                  'analytics left unchanged.')
            return

        reshaped = self._clip(_reshape_db(db))
        if not reshaped:
            print('FuturesAnalyticsGenerator: incremental fetch produced no rows — '
                  'analytics left unchanged.')
            return

        updated = _merge(existing, reshaped)
        updatePKL(updated, ANALYTICS_FILE, rewrite=True)
        self._report(reshaped, mode='incremental')
        print(f'FuturesAnalyticsGenerator: saved {ANALYTICS_FILE} (asof {self.asof.date()})')

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _incremental_range(self, existing: dict) -> list:
        """Return ``[start, asof]`` for the incremental Wind fetch."""
        last = None
        for ctype in self.CTYPES:
            df = existing.get(ctype)
            if isinstance(df, pd.DataFrame) and not df.empty:
                last = df.index.max() if last is None else max(last, df.index.max())

        if last is not None:
            start = last - relativedelta(days=_INCREMENTAL_LOOKBACK_DAYS)
        else:
            # Cold start (no analytics yet): pull a year so OU stats have history.
            start = self.asof - relativedelta(years=_COLDSTART_YEARS)
        return [start.to_pydatetime(), self.asof.to_pydatetime()]

    def _clip(self, reshaped: dict) -> dict:
        """Clip frames to the requested [start, asof] window, dropping all-NaN rows."""
        asof_ts = pd.Timestamp(self.asof.date())
        start_ts = pd.Timestamp(self.start.date()) if self.start is not None else None
        out = {}
        for ctype, df in reshaped.items():
            if df is None or df.empty:
                continue
            clipped = df[df.index <= asof_ts]
            if start_ts is not None:
                clipped = clipped[clipped.index >= start_ts]
            clipped = clipped.dropna(subset=['futures_close'])
            if not clipped.empty:
                out[ctype] = clipped
        return out

    @staticmethod
    def _report(reshaped: dict, *, mode: str) -> None:
        for ctype, df in reshaped.items():
            if df is None or df.empty:
                continue
            print(f'FuturesAnalyticsGenerator: {ctype} — {len(df)} rows ({mode}) '
                  f'[{df.index[0].date()} to {df.index[-1].date()}]')


# ── CLI entry point ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Build / update futures-analytics.pkl')
    p.add_argument('--date',        default=None, help='As-of date YYYYMMDD (default: today)')
    p.add_argument('--start',       default=None, help='Start date YYYYMMDD for partial rebuild')
    p.add_argument('--rewrite',     action='store_true', help='Rewrite from scratch (backfill)')
    p.add_argument('--incremental', action='store_true',
                   help='Incremental Wind fetch + append (default CLI is backfill)')
    args = p.parse_args()
    gen = FuturesAnalyticsGenerator(asof=args.date, start=args.start)
    if args.incremental:
        gen.update()
    else:
        gen.run(rewrite=args.rewrite)
