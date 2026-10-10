from datetime import date

import pandas as pd

from curves.refreshers.irs import IRSRefresher


def test_irs_refresher_normalizes_date_index_for_timestamp_lookups():
    ts = pd.Timestamp('2026-10-10 00:00:00')
    series = pd.Series([1.25], index=[date(2026, 10, 10)])

    normalized = IRSRefresher._normalize_date_index(series)

    assert ts in normalized.index
    assert normalized.loc[ts] == 1.25
