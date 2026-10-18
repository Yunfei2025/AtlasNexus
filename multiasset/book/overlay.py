# -*- coding: utf-8 -*-
"""China-rates short routing: short cash bond, or a swap / future, per tenor.

A negative CN-bond notional (net short duration from IRDL, the short leg of a
slope/curve sleeve) is routed by ``RiskModelConfig.CN_SHORT_ROUTING``: 5Y and
longer stay short cash bonds (easy to borrow), 1Y and 2Y use FR007 swaps, and
futures (TS/TF/T/TL) can be chosen per tenor. A tenor's preference list is tried
in order and the first instrument with data that day wins, so swap tenors fall
back to the short bond before the swap history starts (2022-02-28). A derivative
is a PROXY of the bond, so the P&L differs from shorting it, and the backtest
models those differences explicitly:

* P&L is the instrument's OWN series, not the cash-CGB formula:
    - future:  contracts x face x dF/100  (back-adjusted continuous main contract,
               so roll P&L and the basis are inside the price series)
    - swap:    notional x [(swap rate - FR007)/365 - modDur x d(swap rate)]
               (negative notional = pay fixed / receive FR007)
  The basis between the instrument and the CGB yield it is meant to hedge shows
  up as tracking error; ``OverlayResult.summary`` reports it against the
  short-bond-equivalent P&L.
* No bond carry and no repo credit: a short bond pays the bond yield and the
  funding hurdle credits FR007 on the proceeds; a derivative does neither. Its
  carry is whatever the futures price drift / swap fixed-vs-FR007 leg gives.
  The funding hurdle is therefore NOT applied to overlay notional.
* Capital: a derivative ties up margin (3% of |notional|), not notional. Margin
  counts as used capital inside the utilisation cap and earns nothing.
* Sizing is DV01-matched with the annuity-duration proxy at the instrument's
  nominal tenor (no CTD data), lagged one day like the cash bonds.

Foreign (US/DE/JP/UK) shorts are untouched: they stay short cash bonds. A short
cash bond itself is untouched here (see ``SHORT_BOND_BORROW_COST_BP`` for its fee).
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from multiasset.book import hedge_instruments as hi

_CGB_COL = {
    '1Y': '中债国债到期收益率:1年', '2Y': '中债国债到期收益率:2年', '3Y': '中债国债到期收益率:3年',
    '5Y': '中债国债到期收益率:5年', '10Y': '中债国债到期收益率:10年',
    '20Y': '中债国债到期收益率:20年', '30Y': '中债国债到期收益率:30年',
}


@lru_cache(maxsize=2)
def _futures_artifact(path: str, mtime: float):
    return pd.read_pickle(path)


def _load_futures() -> Dict[str, pd.DataFrame]:
    from settings.paths import DIR_INPUT
    path = os.path.join(str(DIR_INPUT), 'futures-dailyK_con.pkl')
    return _futures_artifact(path, os.path.getmtime(path))


def _daily(series: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill a (possibly sparser / differently-calendared) series onto ``idx``."""
    s = series.copy()
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep='last')].sort_index()
    return s.reindex(s.index.union(idx)).ffill().reindex(idx)


def cn_rates_assets(columns, market_data) -> List[str]:
    """CN government-bond assets among ``columns`` (the ones whose shorts get routed)."""
    from multiasset.data import get_asset_type, get_asset_yield_series
    out = []
    for name in columns:
        if get_asset_type(name) != 'Rates':
            continue
        try:
            series, _n, country, is_bond = get_asset_yield_series(name, market_data)
        except Exception:
            continue
        if country == 'CN' and is_bond and series is not None:
            out.append(name)
    return out


@dataclass
class OverlayResult:
    cash_notional: pd.DataFrame      # input with CN rates shorts removed
    deriv_notional: pd.DataFrame     # date x instrument, signed CNY (negative = short future / pay fixed)
    deriv_pnl: pd.DataFrame          # CNY
    margin: pd.Series                # CNY
    routed_dv01: pd.Series           # CNY/bp of short DV01 routed (negative)
    short_bond_pnl: pd.Series        # what shorting the same bonds would have made (price + carry), attribution only
    short_bond_repo: pd.Series       # repo credit those shorts would earn via the funding hurdle, attribution only

    def add_to(self, book_pnl):
        """BookPnL with the derivative P&L appended to ``other`` (instrument columns)."""
        return dataclasses.replace(book_pnl, other=pd.concat([book_pnl.other, self.deriv_pnl], axis=1))

    def summary(self, total_capital: float) -> Dict:
        idx = self.deriv_pnl.index
        n_years = max(len(idx) / 252.0, 1e-9)
        pct = lambda x: float(x) / total_capital * 100.0                       # noqa: E731
        ann = lambda s: pct(s.sum() / n_years)                                 # noqa: E731
        d = self.deriv_pnl.sum(axis=1)
        sb = self.short_bond_pnl.reindex(idx).fillna(0.0)
        repo = self.short_bond_repo.reindex(idx).fillna(0.0)
        both = pd.concat([d, sb], axis=1)
        r2 = float(both.corr().iloc[0, 1] ** 2) if both.abs().sum().min() > 0 else float('nan')
        cum20 = d.rolling(20).sum()
        return {
            'avg_derivative_gross_pct': pct(self.deriv_notional.abs().sum(axis=1).mean()),
            'avg_margin_pct': pct(self.margin.mean()),
            'avg_routed_dv01_mm_per_bp': float(-self.routed_dv01.mean() / 1e6),
            'derivative_pnl_ann_pct': ann(d),
            'by_instrument_ann_pct': {c: ann(self.deriv_pnl[c]) for c in self.deriv_pnl.columns},
            'short_bond_equivalent_pnl_ann_pct': ann(sb),
            'short_bond_repo_credit_ann_pct': ann(repo),
            'overlay_minus_short_bond_ann_pct': ann(d) - ann(sb) - ann(repo),
            'daily_pnl_r2_vs_short_bond': r2,
            'worst_20d_derivative_pnl_pct': pct(cum20.min()) if cum20.notna().any() else 0.0,
            'worst_day_derivative_pnl_pct': pct(d.min()),
        }


def substitute_shorts(notional_daily: pd.DataFrame, market_data,
                      mapping: Optional[Dict[float, float]] = None) -> pd.DataFrame:
    """Hold shorts in an illiquid CN tenor as DV01-equivalent shorts in another tenor.

    ``mapping`` is ``{from_tenor_years: to_tenor_years}`` (default
    ``RiskModelConfig.CN_SHORT_SUBSTITUTE``, 20Y -> 30Y). Only the NEGATIVE notional of the
    source asset moves; it is scaled by modDur_from / modDur_to (yesterday's yields, like
    the cash sizing) so the DV01 is preserved, and it nets against any long already held in
    the target. A day with no lagged duration leaves the short where it is. If the target
    asset is not a column, the short is left in place.
    """
    from multiasset.config import RiskModelConfig
    from multiasset.data import get_asset_yield_series
    mapping = RiskModelConfig.CN_SHORT_SUBSTITUTE if mapping is None else mapping
    if not mapping:
        return notional_daily
    idx = pd.DatetimeIndex(notional_daily.index)
    by_tenor: Dict[float, str] = {}
    info: Dict[str, tuple] = {}
    for a in cn_rates_assets(notional_daily.columns, market_data):
        series, n, _c, _b = get_asset_yield_series(a, market_data)
        by_tenor[float(n)] = a
        info[a] = (series, float(n))
    out = notional_daily.copy()
    for t_from, t_to in mapping.items():
        a, b = by_tenor.get(float(t_from)), by_tenor.get(float(t_to))
        if a is None or b is None:
            continue
        dur_a = hi.mod_duration(_daily(info[a][0], idx).shift(1), info[a][1])
        dur_b = hi.mod_duration(_daily(info[b][0], idx).shift(1), info[b][1])
        ok = (dur_a.notna() & dur_b.notna() & (dur_b > 0)).to_numpy()
        neg = out[a].clip(upper=0.0).where(ok, 0.0)
        out[a] = out[a] - neg
        out[b] = out[b] + (neg * dur_a / dur_b).fillna(0.0)
    return out


def _routing(routing: Optional[Dict[float, List[str]]]) -> Dict[float, List[str]]:
    if routing is not None:
        return routing
    from multiasset.config import RiskModelConfig
    return RiskModelConfig.CN_SHORT_ROUTING


def overlay_routed_assets(columns, market_data,
                          routing: Optional[Dict[float, List[str]]] = None) -> List[str]:
    """CN-rates assets whose preferred short instrument is NOT the cash bond, i.e. the
    ones that cost margin instead of notional in the capital cap and DV01 scaling."""
    from multiasset.data import get_asset_yield_series
    routing = _routing(routing)
    out = []
    for a in cn_rates_assets(columns, market_data):
        _s, n, _c, _b = get_asset_yield_series(a, market_data)
        prefs = routing.get(float(n), ['bond'])
        if prefs and prefs[0] != 'bond':
            out.append(a)
    return out


def route_cn_shorts(
    notional_daily: pd.DataFrame,
    market_data,
    total_capital: Optional[float] = None,
    max_utilisation: float = 0.95,
    margin_rate: float = hi.DERIVATIVE_MARGIN_RATE,
    allow_swaps: bool = True,
    with_attribution: bool = True,
    routing: Optional[Dict[float, List[str]]] = None,
) -> OverlayResult:
    """Move the negative notional of CN-rates assets to derivatives where the routing says so.

    ``notional_daily``: date x asset signed CNY notional (the capital-constrained book).
    A short whose chosen instrument is 'bond' (or whose derivative has no data yet) is
    left in ``cash_notional`` as a short cash bond. If ``total_capital`` is given, any day
    whose cash gross + margin exceeds ``max_utilisation`` is scaled down proportionally.
    """
    from multiasset.data import get_asset_yield_series
    routing = _routing(routing)
    idx = pd.DatetimeIndex(notional_daily.index)
    _fx_curves, cn_data, _macro = market_data
    assets = cn_rates_assets(notional_daily.columns, market_data)

    cash = notional_daily.copy()
    inst_dv01: Dict[str, pd.Series] = {}
    routed_neg: Dict[str, pd.Series] = {}
    for a in assets:
        series, n, _c, _b = get_asset_yield_series(a, market_data)
        prefs = routing.get(float(n), ['bond'])
        chosen = pd.Series('bond', index=idx, dtype=object)
        for nm in reversed(prefs):                       # earliest preference wins
            if nm == 'bond':
                chosen[:] = 'bond'
                continue
            inst = hi.REGISTRY[nm]
            ok = idx >= pd.Timestamp(inst.first_date)
            if inst.gap_filler and not allow_swaps:
                ok = np.zeros(len(idx), dtype=bool)
            chosen[ok] = nm
        neg = notional_daily[a].clip(upper=0.0)
        y_lag = _daily(series, idx).shift(1)
        dv01 = (neg * hi.mod_duration(y_lag, float(n)) * 1e-4).fillna(0.0)
        for nm in set(chosen) - {'bond'}:
            m = (chosen == nm).to_numpy()
            inst_dv01.setdefault(nm, pd.Series(0.0, index=idx))
            inst_dv01[nm] = inst_dv01[nm] + dv01.where(m, 0.0)
            routed_neg[a] = neg.where(m, 0.0) + routed_neg.get(a, 0.0)
        if (chosen != 'bond').any():
            cash[a] = notional_daily[a].where(chosen == 'bond', notional_daily[a].clip(lower=0.0))
    inst_dv01_df = pd.DataFrame(inst_dv01, index=idx) if inst_dv01 else pd.DataFrame(index=idx)
    neg_routed = pd.DataFrame(routed_neg, index=idx).fillna(0.0) if routed_neg else pd.DataFrame(index=idx)

    # Notional per instrument and per-unit-notional daily return.
    futs = _load_futures() if any(hi.REGISTRY[n].is_future for n in inst_dv01_df.columns) else {}
    notional, unit_ret = {}, {}
    for nm in inst_dv01_df.columns:
        inst = hi.REGISTRY[nm]
        if inst.is_future:
            y = _daily(cn_data['CGB'][_CGB_COL[inst.yield_col]], idx)
            px = futs[inst.data_key]['Close'].copy()
            px.index = pd.to_datetime(px.index)
            r = (px.diff() / 100.0).reindex(idx).fillna(0.0)
        else:
            rate = _daily(cn_data['IRS'][inst.data_key], idx)
            fr007 = _daily(cn_data['IRS']['FR007.IR'], idx)
            y = rate
            from multiasset.data import calendar_gap_days
            r = ((rate - fr007) / 100.0 / 365.0 * calendar_gap_days(idx).to_numpy()
                 - hi.mod_duration(rate, inst.tenor_years) * rate.diff() / 100.0).fillna(0.0)
        dur_lag = hi.mod_duration(y.shift(1), inst.tenor_years)
        notional[nm] = (inst_dv01_df[nm] / (dur_lag * 1e-4)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        unit_ret[nm] = r
    deriv_notional = pd.DataFrame(notional, index=idx) if notional else pd.DataFrame(index=idx)
    margin = deriv_notional.abs().sum(axis=1) * margin_rate if notional else pd.Series(0.0, index=idx)

    # Capital: cash gross (incl. any remaining short bonds) + margin respects the ceiling.
    if total_capital:
        from multiasset.config import RiskModelConfig
        usage = (cash.clip(lower=0.0).sum(axis=1)
                 + RiskModelConfig.SHORT_CAPITAL_RATE * cash.clip(upper=0.0).abs().sum(axis=1)
                 + margin) / float(total_capital)
        scale = (max_utilisation / usage).clip(upper=1.0).where(usage > 1e-12, 1.0)
        # independent short-SIZE ceiling: cash shorts + derivative shorts (all negative notional)
        short_size = (cash.clip(upper=0.0).abs().sum(axis=1)
                      + deriv_notional.clip(upper=0.0).abs().sum(axis=1)) / float(total_capital)
        short_max = RiskModelConfig.SHORT_SIZE_MAX_RATIO * max_utilisation
        scale = np.minimum(scale, (short_max / short_size).clip(upper=1.0).where(short_size > 1e-12, 1.0))
        cash = cash.mul(scale, axis=0)
        deriv_notional = deriv_notional.mul(scale, axis=0)
        margin = margin * scale
        neg_routed = neg_routed.mul(scale, axis=0)

    deriv_pnl = pd.DataFrame({nm: deriv_notional[nm] * unit_ret[nm] for nm in deriv_notional.columns}, index=idx)

    short_pnl = pd.Series(0.0, index=idx)
    repo = pd.Series(0.0, index=idx)
    if with_attribution and not neg_routed.empty and float(neg_routed.abs().to_numpy().sum()) > 0:
        from multiasset.book.pnl import compute_book_pnl
        from multiasset.book.funding import build_domicile_of, book_funding_cost_daily
        short_pnl = compute_book_pnl(neg_routed, market_data, idx[0], idx[-1]).total.sum(axis=1)
        repo = -book_funding_cost_daily(
            neg_routed, build_domicile_of(neg_routed.columns, market_data)).reindex(idx).fillna(0.0)

    return OverlayResult(
        cash_notional=cash, deriv_notional=deriv_notional, deriv_pnl=deriv_pnl, margin=margin,
        routed_dv01=inst_dv01_df.sum(axis=1) if not inst_dv01_df.empty else pd.Series(0.0, index=idx),
        short_bond_pnl=short_pnl, short_bond_repo=repo,
    )
