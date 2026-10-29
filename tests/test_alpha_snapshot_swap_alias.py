import numpy as np
import pandas as pd

from curves.refreshers.alpha_snapshot import _with_swap_ts_alias
from web.tabs.alpha.data.constants import _build_tenor_spread_timeseries


def _raw_cnbd():
    idx = pd.bdate_range('2026-01-01', periods=60)
    rng = np.random.default_rng(0)

    def curve(cols, base):
        return pd.DataFrame({c: base + rng.normal(0, 0.01, len(idx)) for c in cols}, index=idx)

    cgb_tenors = (1, 2, 5, 7, 10, 20, 30)
    return {
        'CGB': curve([f'中债国债到期收益率:{t}年' for t in cgb_tenors], 1.8),
        'CDB': curve([f'中债国开债到期收益率:{t}年' for t in (1, 2, 5, 7, 10)], 2.0),
        'ICP': curve(['中债商业银行同业存单到期收益率(AAA):1年'], 1.7),
        # database-px.pkl names the swap curves 'IRS', not 'SwapTS'
        'IRS': curve(['FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S5Y.IR'], 1.6),
    }


def test_raw_database_px_dict_lacks_repo_spreads_without_alias():
    assert 'CGBRepo7d-5y' not in _build_tenor_spread_timeseries(_raw_cnbd())


def test_swap_ts_alias_restores_swap_based_tenor_spreads():
    ts = _build_tenor_spread_timeseries(_with_swap_ts_alias(_raw_cnbd()))
    assert {'CGBRepo7d-1y', 'CGBRepo7d-5y', 'NCDRepo7d-1y'} <= set(ts)


def test_alias_leaves_already_aliased_or_non_dict_input_alone():
    d = {'SwapTS': 1, 'IRS': 2}
    assert _with_swap_ts_alias(d) is d
    assert _with_swap_ts_alias(None) is None
