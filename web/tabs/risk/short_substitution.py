# -*- coding: utf-8 -*-
"""Short-constraint substitution for Summary > Risk.

Cash bonds may be shorted only in CGB 5Y / 10Y / 30Y. The alpha strategies are
kept exactly as backtested; whatever the combined book (Beta + Alpha, netted
per instrument) still holds net short outside that set is executed instead as
a DV01-matched short in an allowed instrument:

    long end (5Y+)  -> CGB 5Y / 10Y / 30Y on-the-run (7Y and 20Y split across
                       the two neighbouring allowed tenors by tenor distance)
    short end 1-3Y  -> pay FR007 IRS of the same tenor

Only the netted residual is substituted, never each trade's own short leg, so
the added basis risk stays small. Backtest of the Default TenorSpread alpha
book (2026-10-28): Sharpe 3.20 -> 2.85 on 2022-03..2026-10 (FR007 history
starts 2022-02-28) with max drawdown unchanged, versus ~1.4-1.7 for flooring
the net shorts or restricting candidates to one direction.
"""

from __future__ import annotations

import re
import warnings

import pandas as pd

from settings.paths import DIR_INPUT
from web.tabs.alpha.data.duration import _tenor_to_duration

ALLOWED_SHORT_BONDS = {('CGB', 5), ('CGB', 10), ('CGB', 30)}

_STD_TENORS = (1, 2, 3, 5, 7, 10, 20, 30)

# bucket tenor -> [(kind, tenor, DV01 share)]; kind 'CGB' = on-the-run CGB, 'IRS' = FR007 payer
_SUBSTITUTE = {
    1: [('IRS', 1, 1.0)],
    2: [('IRS', 2, 1.0)],
    3: [('IRS', 3, 1.0)],
    5: [('CGB', 5, 1.0)],
    7: [('CGB', 5, 0.6), ('CGB', 10, 0.4)],
    10: [('CGB', 10, 1.0)],
    20: [('CGB', 10, 0.5), ('CGB', 30, 0.5)],
    30: [('CGB', 30, 1.0)],
}

# Policy-bank issuers substitute like CDB; anything else in the CBond universe is credit.
_POLICY_BANKS = (('国家开发银行', 'CDB'), ('农业发展银行', 'ADBC'), ('进出口银行', 'EXIM'))

# Credit curve labels used by the Beta book (LGB1Y, NCD1Y, ...): never shortable, no substitute.
_CREDIT_LABEL = re.compile(r'^(LGB|NCD|MTN|ICP)(\d+)Y$', re.IGNORECASE)


def _load_bond_info() -> dict[str, tuple[str, float]]:
    """code -> (issuer, years to maturity) for the CGB and policy-bank universes."""
    info: dict[str, tuple[str, float]] = {}
    today = pd.Timestamp.today().normalize()
    for btype in ('TBond', 'CBond'):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                bi = pd.read_pickle(str(DIR_INPUT / f'{btype}-InstrumentInfo.pkl'))
        except Exception:
            continue
        if not isinstance(bi, pd.DataFrame) or '到期日期' not in bi.columns:
            continue
        ttm = (pd.to_datetime(bi['到期日期'], errors='coerce') - today).dt.days / 365.0
        names = bi['证券全称'].astype(str) if '证券全称' in bi.columns else pd.Series('', index=bi.index)
        for code, years in ttm.items():
            if pd.isna(years) or years <= 0:
                continue
            if btype == 'TBond':
                issuer = 'CGB'
            else:
                issuer = next((lab for kw, lab in _POLICY_BANKS if kw in names.get(code, '')), 'Credit')
            info[str(code)] = (issuer, float(years))
    return info


def _bucket(years: float) -> int:
    return min(_STD_TENORS, key=lambda t: abs(t - years))


def _substitute_leg(kind: str, tenor: int, otr_cgb: dict, info: dict) -> tuple[str, float]:
    """(instrument code, duration in years) for one substitute leg."""
    if kind == 'IRS':
        return f'FR007S{tenor}Y.IR', float(_tenor_to_duration(f'{tenor}y'))
    code = otr_cgb.get(f'{tenor}Y') or f'CGB-{tenor}Y'
    years = info.get(code, (None, float(tenor)))[1]
    return code, years * 0.92


def build_short_substitutions(net_pos: dict, otr_cgb: dict) -> list[dict]:
    """Disallowed net shorts in the combined book and their executable substitutes.

    ``net_pos`` is Risk's per-instrument {code: {'Beta': mm, 'Alpha': mm, ...}}.
    Returns one row per disallowed net-short instrument, largest DV01 first:
    {code, bond, net_mm, dv01, substitutes: [{code, notional_mm, dv01}], note}.
    DV01 is MM CNY/bp with the codebase's ttm x 0.92 duration proxy.
    """
    info = _load_bond_info()
    rows: list[dict] = []
    for code, vals in net_pos.items():
        net = float(vals.get('Beta', 0.0)) + float(vals.get('Alpha', 0.0))
        if net >= -1e-6:
            continue
        code = str(code)
        if code.upper().endswith('.IR') or code.upper().endswith('.CFE'):
            continue                                  # payer swaps / short futures are allowed
        m = _CREDIT_LABEL.match(code)
        if m:
            rows.append(dict(code=code, bond=f'{m.group(1).upper()} {m.group(2)}Y', net_mm=net,
                             dv01=net * int(m.group(2)) * 0.92 / 1e4, substitutes=[],
                             note='credit bond: not shortable, no substitute'))
            continue
        if code not in info:
            rows.append(dict(code=code, bond='unclassified', net_mm=net, dv01=0.0, substitutes=[],
                             note='bond not found in CGB/CBond universe'))
            continue
        issuer, years = info[code]
        tenor = _bucket(years)
        if issuer == 'CGB' and (issuer, tenor) in ALLOWED_SHORT_BONDS:
            continue
        dv01 = net * years * 0.92 / 1e4
        if issuer == 'Credit':
            rows.append(dict(code=code, bond=f'Credit {tenor}Y', net_mm=net, dv01=dv01, substitutes=[],
                             note='credit bond: not shortable, no substitute'))
            continue
        subs = []
        for kind, sub_tenor, share in _SUBSTITUTE[tenor]:
            sub_code, sub_dur = _substitute_leg(kind, sub_tenor, otr_cgb, info)
            sub_dv01 = dv01 * share
            subs.append(dict(code=sub_code,
                             notional_mm=round(sub_dv01 * 1e4 / sub_dur / 10.0) * 10.0,
                             dv01=sub_dv01))
        rows.append(dict(code=code, bond=f'{issuer} {tenor}Y', net_mm=net, dv01=dv01, substitutes=subs,
                         note='pay FR007' if _SUBSTITUTE[tenor][0][0] == 'IRS' else 'short CGB'))
    rows.sort(key=lambda r: r['dv01'])
    return rows
