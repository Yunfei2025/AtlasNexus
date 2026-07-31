import pandas as pd

from web.tabs.alpha.callbacks.backtest_tab import _apply_monthly_style_schedule


def test_apply_monthly_style_schedule_assigns_trend_to_uncertain():
    schedule = pd.DataFrame([
        {'review_date': pd.Timestamp('2024-01-01'), 'regime': 'uncertain', 'assigned_style': 'mr'},
        {'review_date': pd.Timestamp('2024-02-01'), 'regime': 'trending', 'assigned_style': 'trend'},
    ])

    month_to_style, adjusted = _apply_monthly_style_schedule(schedule, 'mr', 'trend')

    assert month_to_style[pd.Period('2024-01', 'M')] == 'trend'
    assert month_to_style[pd.Period('2024-02', 'M')] == 'trend'
    assert adjusted.loc[0, 'assigned_style'] == 'trend'


def test_apply_monthly_style_schedule_keeps_manual_style_when_requested():
    schedule = pd.DataFrame([
        {'review_date': pd.Timestamp('2024-01-01'), 'regime': 'uncertain', 'assigned_style': 'mr'},
    ])

    month_to_style, adjusted = _apply_monthly_style_schedule(schedule, 'mr', 'manual')

    assert month_to_style[pd.Period('2024-01', 'M')] == 'mr'
    assert adjusted.loc[0, 'assigned_style'] == 'mr'
