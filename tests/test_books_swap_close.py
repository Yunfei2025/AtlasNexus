import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from curves.refreshers.alpha_snapshot import AlphaSnapshotPaths, _snapshot_is_stale
from web.tabs.risk.books.swap_close import freshest_daily_closes, swap_spread_close_bp, zscore_from_close

LEGS = ['FR007S2Y.IR', 'FR007S1Y.IR', 'FR007S5Y.IR']          # belly, short wing, long wing


def _frame(data):
    idx = pd.to_datetime([d for d, _ in data])
    return pd.DataFrame([v for _, v in data], index=idx, columns=LEGS)


def test_fly_uses_all_three_legs_with_belly_doubled():
    df = _frame([('2026-10-28', [1.37, 1.3675, 1.4225]), ('2026-10-29', [1.37, 1.3725, 1.4225])])
    bp, day = swap_spread_close_bp(df, LEGS)
    assert bp == pytest.approx((2 * 1.37 - 1.3725 - 1.4225) * 100)     # -5.5bp, not the 2Y-1Y slope
    assert day == pd.Timestamp('2026-10-29')


def test_two_leg_slope_is_leg1_minus_leg2():
    df = _frame([('2026-10-29', [1.37, 1.3675, 1.4225])])
    bp, _ = swap_spread_close_bp(df, ['FR007S5Y.IR', 'FR007S1Y.IR'])
    assert bp == pytest.approx((1.4225 - 1.3675) * 100)


def test_uses_latest_day_on_which_every_leg_has_a_close():
    df = _frame([('2026-10-28', [1.37, 1.3675, 1.4225]), ('2026-10-29', [1.38, np.nan, 1.43])])
    _, day = swap_spread_close_bp(df, LEGS)
    assert day == pd.Timestamp('2026-10-28')


def test_missing_leg_or_empty_returns_none():
    df = _frame([('2026-10-29', [1.37, 1.3675, 1.4225])])
    assert swap_spread_close_bp(df, LEGS[:2] + ['FR007S9Y.IR']) is None
    assert swap_spread_close_bp(pd.DataFrame(), LEGS) is None


def test_freshest_daily_closes_prefers_feed_but_keeps_older_pipeline_history():
    feed = _frame([('2026-10-28', [1.0, 1.0, 1.0]), ('2026-10-29', [2.0, 2.0, 2.0])])
    pipeline = _frame([('2026-10-26', [9.0, 9.0, 9.0]), ('2026-10-28', [5.0, 5.0, 5.0])])
    out = freshest_daily_closes(feed, pipeline)
    assert out.loc['2026-10-29', LEGS[0]] == 2.0          # newest date from the feed
    assert out.loc['2026-10-28', LEGS[0]] == 1.0          # feed wins an overlapping date
    assert out.loc['2026-10-26', LEGS[0]] == 9.0          # older history still available
    assert freshest_daily_closes(None, pd.DataFrame()).empty


def test_zscore_from_close_uses_percent_units_and_rejects_bad_vol():
    assert zscore_from_close(-5.0, -0.08375, 0.0097892) == pytest.approx((-0.05 + 0.08375) / 0.0097892)
    assert zscore_from_close(-5.0, -0.08, 0.0) is None
    assert zscore_from_close(-5.0, np.nan, 0.01) is None


def test_newer_market_data_marks_alpha_snapshot_stale(tmp_path: Path):
    paths = AlphaSnapshotPaths(tmp_path)
    for src in paths.source_pickles:
        src.write_bytes(b'x')
    paths.out_snapshot.write_bytes(b'x')
    base = paths.out_snapshot.stat().st_mtime
    for src in paths.source_pickles:
        os.utime(src, (base - 100, base - 100))
    assert _snapshot_is_stale(paths) is False             # snapshot newer than every source
    os.utime(paths.cnbd_data, (base + 100, base + 100))   # daily data update lands
    assert _snapshot_is_stale(paths) is True              # next refresh rebuilds Z-Score / spreads
