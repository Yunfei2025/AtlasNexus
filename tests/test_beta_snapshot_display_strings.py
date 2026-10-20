from datetime import datetime

import pandas as pd

from web.tabs.beta.callbacks.portfolio_run._run_analysis import build_allocation_results


def test_snapshot_converts_display_strings_to_numbers():
    table = pd.DataFrame({
        'Asset Type': ['Rates', 'Rates', 'TOTAL'],
        'Asset Name': ['A', 'B', ''],
        'Capital (CNY)': ['4,930.00', '530.00', '5,460.00'],
        'Weight (%)': ['49.30%', '5.30%', '54.60%'],
    })
    res, _ = build_allocation_results(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        table, table, 'x', 10_000_000_000.0, 5, datetime(2026, 10, 20),
    )
    snap = pd.DataFrame(res['beta_snapshot'])
    assert snap['Capital (CNY)'].tolist() == [4930e6, 530e6]
    assert snap['Weight (%)'].tolist() == [49.3, 5.3]
