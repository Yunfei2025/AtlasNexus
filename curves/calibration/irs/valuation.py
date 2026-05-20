# -*- coding: utf-8 -*-
"""IRS contract evaluation: carry, roll, carry+roll metrics.

Carry uses contractual cashflows projected through the smooth fitted
forward curve (anchor at short end). Roll uses the smooth fitted spot
curve to avoid stepped-curve artifacts at key tenor nodes — see
`curves/calibration/irs/fixings.py` for how `spot_ts` and `fixing_ts`
are constructed.
"""

import pandas as pd
from scipy import interpolate

from settings.general import DateConfig
from settings.fixed_income import IRSConfig

from curves.calibration.irs.contract import IRSContract


def evalueContract(di, quote_rt, fwddata, pshift):
    """Evaluate IRS contracts and compute carry/roll/carry-roll metrics."""
    d = DateConfig.get_date_mappings()['d'].date()
    fixing_ts, spot_ts, fwd_date = fwddata['fixing'], fwddata['spot'], fwddata['date']
    # spot_ts is built from the smooth affine spot curve (see getSpot in fixings.py).
    # Linear interpolation between adjacent daily points of an already-smooth
    # curve preserves smoothness — roll is therefore computed against the
    # smooth fitted curve, not the stepped bootstrap.
    interpolators = {
        ct: interpolate.interp1d(
            [(day - d).days / 365 for day in spot_ts[ct].index],
            spot_ts[ct].values,
            kind='linear',
        )
        for ct in spot_ts
    }
    irs_val = pd.DataFrame(index=IRSConfig.IRS_LIST)
    irs_contracts = {}
    notional = 1
    term_map = {'3m': 0.25, '6m': 0.5, '1y': 1}
    for instrument in irs_val.index:
        start_date = (di + pd.offsets.BDay(pshift)).date()
        end_date = start_date + IRSConfig.get_irs_terms()[instrument]
        term = (end_date - start_date).days / 365
        curve_type = 'r7d' if 'FR00' in instrument else 's3m'
        frequency = 0 if term < 0.25 else 4
        contract = IRSContract(start_date, end_date, quote_rt.loc[instrument], curve_type, frequency)
        contract.valuation(notional, fwd_date, fixing_ts[curve_type], spot_ts[curve_type])
        irs_contracts[instrument] = contract
        cashflow = contract.cashflow
        irs_val.loc[instrument, 'Quote'] = contract.quote
        irs_val.loc[instrument, 'FixRate'] = contract.fixrate
        irs_val.loc[instrument, 'Value(bp)'] = contract.Value
        irs_val.loc[instrument, 'Duration'] = contract.duration
        irs_val.loc[instrument, 'Convexity'] = contract.cov
        irs_val.loc[instrument, 'Carry(3m,bp)'] = cashflow['CashFlow(NetPay)'].iloc[0]
        irs_val.loc[instrument, 'Carry(6m,bp)'] = cashflow['CashFlow(NetPay)'].iloc[:2].sum()
        irs_val.loc[instrument, 'Carry(1y,bp)'] = cashflow['CashFlow(NetPay)'].iloc[:4].sum()
        _calculate_roll_returns(irs_val, instrument, term, interpolators[curve_type], term_map)
    for period in ['3m', '6m', '1y']:
        irs_val[f'CarryRoll({period},bp)'] = irs_val[f'Carry({period},bp)'] + irs_val[f'Roll({period},bp)']
    return {'value': irs_val.round(4), 'obj': irs_contracts}


def _calculate_roll_returns(irs_val, instrument, term, interpolator, term_map):
    """Calculate roll returns for different periods (-Duration * Δspot)."""
    years = interpolator.x if hasattr(interpolator, 'x') else []
    if hasattr(interpolator, 'y'):
        if term >= 10:
            term = years[-1] if len(years) else 10
        elif term <= years[0] if len(years) else term <= 0:
            term = years[0] if len(years) else 0.01
    s0 = interpolator(term)
    for period, period_term in term_map.items():
        if term - period_term <= 0.01:
            irs_val.loc[instrument, f'Roll({period},bp)'] = 0
        else:
            sr = interpolator(term - period_term)
            irs_val.loc[instrument, f'Roll({period},bp)'] = -100 * (s0 - sr) * irs_val.loc[instrument, 'Duration']
