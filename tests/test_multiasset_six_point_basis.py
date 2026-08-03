import numpy as np

from multiasset.factor_backtest import get_factor_weighted_duration
from multiasset.pca_analyzer import DeterministicRiskFactorAnalyzer


def test_cn_six_point_basis_covers_each_configured_tenor():
    analyzer = DeterministicRiskFactorAnalyzer('.')

    weights = analyzer.get_weights_dataframe('CN')

    assert list(weights.index) == ['1Y', '2Y', '5Y', '10Y', '20Y', '30Y']
    assert np.isclose(weights['Level'].sum(), 1.0)
    assert np.isclose(weights['Slope'].sum(), 0.0)
    assert np.isclose(weights['Curvature'].sum(), 0.0)
    assert np.isclose(np.dot(weights['Level'], weights['Slope']), 0.0)
    assert np.isclose(np.dot(weights['Level'], weights['Curvature']), 0.0)

    assert analyzer.get_tenor_sensitivities('CN', '20Y') == {
        'IRDL': 1.0 / 6.0,
        'IRSL': 1.0 / 6.0,
        'IRCV': 0.0,
    }
    assert analyzer.get_tenor_sensitivities('CN', '30Y') == {
        'IRDL': 1.0 / 6.0,
        'IRSL': 5.0 / 18.0,
        'IRCV': 0.25,
    }


def test_cn_factor_duration_uses_the_six_point_grid():
    assert get_factor_weighted_duration('IRDL.CN') > 0.0
    assert get_factor_weighted_duration('IRSL.CN') > 0.0
    assert get_factor_weighted_duration('IRCV.CN') > 0.0