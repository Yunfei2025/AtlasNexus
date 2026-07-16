import pandas as pd

from web.tabs.alpha.callbacks.candidates import _apply_seasonal_quality_gate


def test_seasonal_gate_filters_scored_candidates_with_weak_current_month_data():
    candidates = pd.DataFrame(
        [
            {'spread_type': 'TenorSpread', 'ID': 'strong', 'style': 'carry', 'score': 3.0},
            {'spread_type': 'TenorSpread', 'ID': 'weak', 'style': 'carry', 'score': 2.0},
            {'spread_type': 'TenorSpread', 'ID': 'mr_weak', 'style': 'meanreversion', 'score': 1.5},
            {'spread_type': 'TenorSpread', 'ID': 'missing', 'style': 'carry', 'score': 1.0},
        ]
    )
    seasonal_data = {
        'TenorSpread': pd.DataFrame(
            {
                'm7': [
                    {'consistency': 0.80, 'p_value': 0.05},
                    {'consistency': 0.60, 'p_value': 0.20},
                    {'consistency': 0.55, 'p_value': 0.40},
                ]
            },
            index=['strong', 'weak', 'mr_weak'],
        )
    }

    filtered, excluded, evaluated = _apply_seasonal_quality_gate(
        candidates,
        seasonal_data,
        min_consistency=0.75,
        p_value_threshold=0.10,
        month=7,
    )

    assert filtered['ID'].tolist() == ['strong', 'mr_weak', 'missing']
    assert excluded == 1
    assert evaluated == 2