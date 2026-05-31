# -*- coding: utf-8 -*-
"""IRS spreads, flies, basis, box, and composite tradable quotes."""

import re

import pandas as pd

from settings.fixed_income import IRSConfig


def irsSpreads(qtpx):
    """Calculate IRS spreads (serial, fly, basis, box) efficiently."""
    repo_cols = qtpx.columns[qtpx.columns.str.contains('FR007S') & ~qtpx.columns.str.contains('1M|2M|7Y|10Y')]
    shibor_cols = qtpx.columns[qtpx.columns.str.contains('SHI3MS') & ~qtpx.columns.str.contains('7Y|10Y')]
    repos, shibors = qtpx[repo_cols], qtpx[shibor_cols]
    spreads = {}
    for j in range(1, 5):
        spreads[f'repo{j}s'] = repos.diff(j, axis=1).iloc[:, j:]
    for j in range(1, 5):
        spreads[f'shi3M{j}s'] = shibors.diff(j, axis=1).iloc[:, j:]
    pairs = pd.concat(spreads, axis=1)
    pairs.columns = IRSConfig.PAIRS
    flys = _calculate_fly_spreads(repos, shibors)
    rmap = {0: '3m', 1: '6m', 2: '9m', 3: '1y', 4: '2y', 5: '3y', 6: '4y', 7: '5y'}
    basis = pd.DataFrame({f'Basis-{rmap[i+1]}': shibors.iloc[:, i] - repos.iloc[:, i+1]
                         for i in range(min(len(shibor_cols), len(repo_cols) - 1))})
    box = pd.concat({f'Basis-{j}s': basis.diff(j, axis=1).iloc[:, j:] for j in range(1, 5)}, axis=1)
    box.columns = IRSConfig.BOX
    return pd.concat([pairs, flys, basis, box], axis=1)


def _calculate_fly_spreads(repos, shibors):
    """Calculate fly spreads for repo and shibor."""
    rmap = {0: '3m', 1: '6m', 2: '9m', 3: '1y', 4: '2y', 5: '3y', 6: '4y', 7: '5y'}
    spreads = {}
    for i in range(len(repos.columns) - 2):
        for j in range(i + 1, len(repos.columns) - 1):
            for k in range(j + 1, len(repos.columns)):
                spreads[f'Repo7d-{rmap[i]}{rmap[j]}{rmap[k]}'] = 2 * repos.iloc[:, j] - (repos.iloc[:, i] + repos.iloc[:, k])
    for i in range(len(shibors.columns) - 2):
        for j in range(i + 1, len(shibors.columns) - 1):
            for k in range(j + 1, len(shibors.columns)):
                spreads[f'Shi3M-{rmap[i+1]}{rmap[j+1]}{rmap[k+1]}'] = 2 * shibors.iloc[:, j] - (shibors.iloc[:, i] + shibors.iloc[:, k])
    return pd.concat(spreads, axis=1) if spreads else pd.DataFrame()


def irsSpreadsRatio(spread_list):
    """Calculate ratio for each spread type."""
    ratio = {}
    for s in spread_list:
        note = s.split('-')[1]
        if len(note) == 2:
            ratio[s] = 1
        elif len(note) == 4:
            ratio[s] = IRSConfig.TERM_MAP[note[2:]] / IRSConfig.TERM_MAP[note[:2]]
        elif len(note) == 6:
            t1, t2, t3 = IRSConfig.TERM_MAP[note[2:4]], IRSConfig.TERM_MAP[note[:2]], IRSConfig.TERM_MAP[note[4:]]
            ratio[s] = [t1 / t2 / 2, t1 / t3 / 2]
    return ratio


def _irs_quote_spread_weights(sp):
    """Return quote weights matching the spread definitions used in QtPx."""
    f, s, t = 'FR007S', 'SHI3MS', '.IR'
    stype, note = sp.split('-')
    tenors = [token.upper() for token in re.findall(r'\d+[my]', note.lower())]

    if stype in ['Repo7d', 'Shi3M']:
        prefix = f if stype == 'Repo7d' else s
        if len(tenors) == 2:
            return {
                prefix + tenors[1] + t: 1.0,
                prefix + tenors[0] + t: -1.0,
            }
        if len(tenors) == 3:
            return {
                prefix + tenors[1] + t: 2.0,
                prefix + tenors[0] + t: -1.0,
                prefix + tenors[2] + t: -1.0,
            }
    if stype == 'Basis':
        if len(tenors) == 1:
            return {
                s + tenors[0] + t: 1.0,
                f + tenors[0] + t: -1.0,
            }
        if len(tenors) == 2:
            later = _irs_quote_spread_weights(f'Basis-{tenors[1].lower()}')
            earlier = _irs_quote_spread_weights(f'Basis-{tenors[0].lower()}')
            merged = later.copy()
            for instrument, weight in earlier.items():
                merged[instrument] = merged.get(instrument, 0.0) - weight
            return merged
    raise KeyError(f'Unsupported IRS quote spread: {sp}')


def irsQuoteComposite(spread_list, cost, *, quote_side, opposite_cost):
    """Calculate tradable bid/ofr quotes for IRS spreads using crossed-side legs."""
    spread_cost = pd.Series(index=spread_list, dtype=float)
    for sp in spread_list:
        weights = _irs_quote_spread_weights(sp)
        value = 0.0
        for instrument, weight in weights.items():
            if quote_side == 'Bid':
                series = cost if weight > 0 else opposite_cost
            else:
                series = cost if weight > 0 else opposite_cost
            value += weight * series[instrument]
        spread_cost[sp] = value
    return spread_cost


def irsSpreadComposite(spread_list, cost):
    """Calculate composite spread costs."""
    f, s, t = 'FR007S', 'SHI3MS', '.IR'
    irs_ratio = irsSpreadsRatio(spread_list)
    spread_cost = pd.Series(index=spread_list)
    for sp in spread_list:
        stype, note = sp.split('-')
        note = note.upper()
        if stype == 'Basis':
            if len(note) == 2:
                spread_cost[sp] = cost[s + note + t] - irs_ratio[sp] * cost[f + note + t]
            else:
                spread_cost[sp] = spread_cost[f'{stype}-{note[2:].lower()}'] - spread_cost[f'{stype}-{note[:2].lower()}']
        elif stype in ['Repo7d', 'Shi3M']:
            prefix = f if stype == 'Repo7d' else s
            if len(note) == 4:
                spread_cost[sp] = cost[prefix + note[2:] + t] - irs_ratio[sp] * cost[prefix + note[:2] + t]
            else:
                spread_cost[sp] = (cost[prefix + note[2:4] + t] - irs_ratio[sp][0] * cost[prefix + note[:2] + t] - irs_ratio[sp][1] * cost[prefix + note[4:] + t])
    return spread_cost
