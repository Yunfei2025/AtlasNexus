# -*- coding: utf-8 -*-
"""
Created on Sun Sep 17 14:05:04 2023

@author: CMBC
"""
import pandas as pd
import numpy as np
from scipy import interpolate
from curves.calibration.irscurves import irsSpreads


MAX_BOND_CURVE_ADJUSTMENT = 10.0  # percent; prevents corrupt historical stats from exploding CvBid/CvOfr

# Matches web/tabs/alpha/backtest/engine_monthly.py::MR_VOL_SPAN and
# engine_mr.py::MR_VOL_SPAN. Kept as an independent constant (rather than an
# import) to avoid a curves/ -> web/ dependency; see OU_calibrate's ewm_vol.
ZSCORE_EWM_VOL_SPAN = 60


def _suppress_curve_yield_outliers(
    curve_yield: pd.Series,
    close_yield: pd.Series,
    abs_limit: float = 20.0,
    diff_limit: float = 5.0,
) -> pd.Series:
    """Suppress impossible curve-yield spikes using the close-yield series as anchor."""
    curve = pd.to_numeric(curve_yield, errors='coerce').replace([np.inf, -np.inf], np.nan).astype(float).copy()
    if curve.empty:
        return curve

    close = pd.to_numeric(close_yield, errors='coerce').reindex(curve.index).astype(float)
    outlier = curve.abs().gt(abs_limit)
    if close.notna().any():
        outlier = outlier | (close.notna() & (curve - close).abs().gt(diff_limit))

    if not outlier.any():
        return curve

    curve = curve.mask(outlier)
    curve = curve.interpolate(method='linear', limit_area='inside').ffill().bfill()
    return curve

# Constants reused across functions
ANCHORS = ['FR007.IR','FR007S3M.IR','FR007S6M.IR','FR007S9M.IR','FR007S1Y.IR','FR007S2Y.IR','FR007S5Y.IR']
TERMS = [0, 1/4, 1/2, 3/4, 1, 2, 5]


def _is_constant_series(series: pd.Series) -> bool:
    values = pd.to_numeric(series, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return False
    return values.nunique() <= 1

def _adf_result(series: pd.Series):
    """Run ADF test for a 1D series and return (pvalue, stationary:str, stats, crit)"""
    if _is_constant_series(series):
        # A frozen series is NOT a mean-reverting process -- it is a dead
        # instrument whose quotes stopped updating (matured/delisted bond kept
        # alive by a stale InstrumentInfo fetch on the ytm_act leg and by
        # updatePKL's unbounded ffill on the ytm_quo leg). Reporting 'YES'
        # here made every such bond pass StatInfo's dropna(subset=['stationary'])
        # filter with the strongest possible p-value, and its ~0 vol then
        # became the z-score divisor (observed: 26 of 131 TBond bonds frozen
        # 20+ days, one for 612 days, median |residual| 74bp vs 5.9bp for live
        # bonds, producing a -44.8 z-score). Report 'NO' so it is filtered out.
        crit = {'1%': 'nan', '5%': 'nan', '10%': 'nan'}
        return 1.0, 'NO', 'nan', crit
    try:
        from statsmodels.tsa.stattools import adfuller
    except Exception as e:
        raise ImportError(
            "statsmodels is required for ADF tests (statsmodels.tsa.stattools.adfuller). "
            "Install it with: pip install statsmodels"
        ) from e
    result = adfuller(series.values, maxlag=1, autolag=None)
    pvalue = result[1]
    stationary = 'YES' if pvalue <= 0.05 else 'NO'
    stats = '%.3f' % result[0]
    crit = {k: '%.3f' % v for k, v in result[4].items()}
    return pvalue, stationary, stats, crit

def _fit_ar1_params(series: pd.Series):
    """Estimate AR(1) parameters y_t = a + b y_{t-1} + e using closed-form OLS.
    Returns (A=b, B=a, C=std(resid))."""
    y = series.values
    x = np.roll(y, 1)
    x, y = x[1:], y[1:]  # drop first
    if x.size < 2:
        return np.nan, np.nan, np.nan
    x_mean = x.mean()
    y_mean = y.mean()
    var_x = np.dot(x - x_mean, x - x_mean)
    if var_x == 0:
        return np.nan, np.nan, np.nan
    cov_xy = np.dot(x - x_mean, y - y_mean)
    b = cov_xy / var_x
    a = y_mean - b * x_mean
    resid = y - (a + b * x)
    c = np.sqrt(np.mean(resid**2))
    return b, a, c

def adftest(df):
    adf_df = pd.DataFrame(index=df.columns,columns=['p-value','stationary','stats','1%','5%','10%'])
    for i in df.columns:
        s = df.loc[:,i]
        pval, stationary, stats, crit = _adf_result(s)
        adf_df.loc[i,'stats'] = stats
        adf_df.loc[i,'p-value'] = pval
        adf_df.loc[i,'stationary'] = stationary
        for k, v in crit.items():
            adf_df.loc[i,k] = v
    return adf_df

def statAdjust(quote,env,stat): 
    quote_adj = pd.DataFrame()
    mean_adj = pd.to_numeric(stat['mean'], errors='coerce')
    mean_adj = mean_adj.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mean_adj = mean_adj.clip(lower=-MAX_BOND_CURVE_ADJUSTMENT, upper=MAX_BOND_CURVE_ADJUSTMENT)
    for k in quote.keys():
        quote_adj[k] = (pd.to_numeric(quote[k]['收益率'], errors='coerce') + mean_adj).clip(lower=0.0, upper=20.0)
    rt_bid = env['BondRT']['买价收益率']
    rt_ofr = env['BondRT']['卖价收益率']
    quote_mid = (rt_ofr + rt_bid) / 2
    df_stat = pd.concat([env['Def']['估价收益率:%(中债)'], quote_mid, rt_bid, rt_ofr, stat[['max','min','vol']]], axis=1)
    df_quote = pd.concat([quote_adj,df_stat],axis=1).dropna(how='all',axis=0)
    bonds = env['Def'].index.intersection(df_quote.index)
    df_quote = df_quote.loc[bonds]
    df_quote.index.name = 'ID'
    df_quote.reset_index(inplace=True)
    df_quote.index = env['Def'].loc[bonds,'剩余期限'].values.round(4)
    df_quote.columns = ['ID','CvBid','CvOfr','CNBD','RT','Bid','Ofr','max','min','vol']
    df_quote = df_quote[df_quote['CvBid'].notna()]
    return df_quote.sort_index().round(4)

def OU_calibrate(ts):
    # Ornstein–Uhlenbeck Process calibration, or normal statistics
    # formula reference: https://www.zhihu.com/question/268075949/answer/1531412127
    # spreadvalues between pca and actual spot rate
    # unit is %
    #
    # 'vol' is the static full-sample std -- kept as-is since it also feeds
    # portfolio-level risk sizing (web/tabs/alpha/scoring.py, portfolio.py),
    # not just the Z-score. 'ewm_vol' is a separate, EWMA(span=60) volatility
    # estimate intended for Zscore = (spread - mean) / vol scaling only, so a
    # live candidate snapshot uses the same "current regime" vol scale as the
    # backtest engines (engine_mr.py / engine_monthly.py, MR_VOL_SPAN=60)
    # instead of a static vol blended across the full history/lookback. Using
    # the static 'vol' for Zscore was the candidate-selection counterpart of
    # the entry-timing bias fixed in those engines: once realised volatility
    # drops well below its long-run level, a spread's current moves no longer
    # register as statistically extreme against a stale full-sample scale.
    statvs = ['halflife', 'mean', 'vol', 'ewm_vol', 'max', 'min']
    stat_info = pd.DataFrame(index=ts.columns, columns=['stationary'] + statvs)
    stat_info.index.name = 'ID'
    for b in ts.columns:
        sp = ts[b].dropna()
        if sp.shape[0] > 20:
            _, stationary, _, _ = _adf_result(sp)
            stat_info.loc[b, 'stationary'] = stationary
            ewm_span = min(ZSCORE_EWM_VOL_SPAN, sp.shape[0])
            ewm_vol = sp.ewm(span=max(ewm_span, 2), min_periods=max(min(ewm_span, sp.shape[0]), 2)).std().iloc[-1]
            stat_info.loc[b, 'ewm_vol'] = ewm_vol
            if stationary == 'YES':
                A, B, C = _fit_ar1_params(sp)
                if np.isfinite(A) and (1 - A) != 0 and A > 0:
                    theta = B / (1 - A)
                    kappa = -np.log(A)
                    stat_info.loc[b, 'halflife'] = np.log(2) / max(1e-12, kappa)
                    stat_info.loc[b, 'mean'] = theta
                    stat_info.loc[b, 'vol'] = sp.std()
                else:
                    stat_info.loc[b, 'halflife'] = np.nan
                    stat_info.loc[b, 'mean'] = sp.mean()
                    stat_info.loc[b, 'vol'] = sp.std()
            else:
                stat_info.loc[b, 'halflife'] = np.nan
                stat_info.loc[b, 'mean'] = sp.mean()
                stat_info.loc[b, 'vol'] = sp.std()
            stat_info.loc[b, 'max'] = sp.max()
            stat_info.loc[b, 'min'] = sp.min()
    stat_info[statvs] = stat_info[statvs].astype(float)
    return stat_info

def splice_reference_rolls(spread: pd.DataFrame, roll_dates) -> pd.DataFrame:
    """Level-adjust a residual panel across reference-bond roll dates.

    When a bucket's reference bond rolls, the fitted curve level steps
    discontinuously and every bond's ``ytm_act - ytm_quo`` residual steps with
    it. That step is an identity change, not a market move, and it
    contaminates the rolling volatility every z-score divides by -- measured
    at **1.5-6.6x inflation** on real TBond history, which *suppresses*
    genuine dislocations (missed entries).

    Splicing removes the roll-day *return* and re-cumulates, so the series
    stays level-continuous and the FULL history remains usable.

    A hard reset (restarting estimation after each roll) is deliberately NOT
    used here: rolls are frequent (median gap 12-50 days per bucket, and
    94-100% of days sit within 252 days of one), so resetting would leave the
    estimator below its minimum sample on 22-64% of days -- strictly worse
    than the contamination it removes. See
    docs/dev/affine-curve-improvement-plan.md section 3c/3d.

    Args:
        spread: residual panel, dates x bonds.
        roll_dates: dates on which a reference roll occurred. Dates not in
            ``spread.index`` are ignored.

    Returns:
        A level-adjusted copy. Unchanged when ``roll_dates`` is empty.
    """
    if spread is None or spread.empty or roll_dates is None:
        return spread
    try:
        idx_ts = pd.DatetimeIndex(pd.to_datetime(spread.index))
        roll_ts = {pd.Timestamp(d) for d in roll_dates}
    except (TypeError, ValueError):
        return spread
    mask = np.array([t in roll_ts for t in idx_ts], dtype=bool)
    if not mask.any():
        return spread

    diffs = spread.diff()
    diffs.loc[mask, :] = 0.0          # drop the identity-change step
    spliced = diffs.fillna(0.0).cumsum()
    # Re-anchor to the original ending level so downstream 'close'/'mean'
    # comparisons stay on the same scale as the raw series. Anchor on each
    # column's LAST VALID observation, not spread.iloc[-1]: a bond with no
    # quote on the panel's final date (e.g. the run's own as-of date, before
    # today's close exists, or a bond that has since matured) has NaN there,
    # and `spliced - spliced.iloc[-1] + spread.iloc[-1]` broadcasts that NaN
    # across the ENTIRE column, discarding up to 252 valid observations for
    # every bond missing only its most recent point (this wiped OU_calibrate
    # coverage from ~100+ TBond reference bonds down to 25 on 2026-09-06,
    # a non-trading Sunday with no fresh quote yet).
    # spliced (from fillna(0.0).cumsum()) is never NaN by construction -- a
    # gap is deliberately carried forward as "no change" so later values
    # stay level-continuous across it. The last-valid position must instead
    # come from `spread`, the original panel, which is where the real gaps
    # (including a still-missing latest date) actually are.
    last_valid_pos = spread.notna().to_numpy()[::-1].argmax(axis=0)
    last_valid_pos = spread.shape[0] - 1 - last_valid_pos
    has_any_valid = spread.notna().any(axis=0).to_numpy()
    cols = np.arange(spread.shape[1])
    anchor_spliced = pd.Series(
        np.where(has_any_valid, spliced.to_numpy()[last_valid_pos, cols], np.nan),
        index=spread.columns,
    )
    anchor_orig = pd.Series(
        np.where(has_any_valid, spread.to_numpy()[last_valid_pos, cols], np.nan),
        index=spread.columns,
    )
    spliced = spliced - anchor_spliced + anchor_orig
    # Positions that were NaN in the original panel stay NaN in the output --
    # cumsum() treats a gap as "no change" internally (needed to keep later
    # values level-continuous across it), but that gap itself was never an
    # observation and must not be reported as one.
    spliced = spliced.where(spread.notna())
    return spliced


#: A residual that has not moved for this many consecutive observations is
#: treated as dead (see _drop_stale_residual_bonds). 5 covers a normal trading
#: week: a genuinely illiquid but live bond still reprices off the CNBD
#: valuation yield daily, so a full week of bit-identical values means the
#: source stopped updating rather than that the market stood still.
MAX_FROZEN_OBS = 5


def _trailing_frozen_count(series: pd.Series) -> int:
    """Number of trailing observations identical to the most recent one."""
    values = pd.to_numeric(series, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return 0
    arr = values.to_numpy()
    last = arr[-1]
    changed = np.nonzero(arr != last)[0]
    return int(arr.size - changed[-1] - 1) if changed.size else int(arr.size)


def _drop_stale_residual_bonds(spread: pd.DataFrame, env, max_frozen: int = MAX_FROZEN_OBS):
    """Drop bonds whose residual is dead, returning (kept_spread, dropped_ids).

    Two independent upstream defects keep matured/delisted bonds in the panel
    with a bit-identical residual forever:

    1. ``ytm_act`` is written from ``InstrumentInfo``'s YIELD_CNBD
       (curves/calibration/selector.py::update_price). A failed Wind fetch
       leaves the previous pickle in place, so the same close yield is
       re-written every day -- the exact failure mode already documented at
       curves/utils/retrieve.py::updateInstrumentDef.
    2. ``ytm_quo`` is not in curves/utils/file.py::_NO_FFILL_KEYS, so
       updatePKL's unbounded ``combined.ffill()`` carries the last model
       yield forward indefinitely once a bond stops being quoted.

    Both legs freeze, so the difference is constant and survives every
    downstream filter. Screen on two signals: absence from the live
    instrument universe (a delisted bond has no valid remaining maturity),
    and a residual frozen for `max_frozen` observations.
    """
    if spread.empty:
        return spread, []

    ttm = pd.to_numeric(env['Def'].get('剩余期限'), errors='coerce') if '剩余期限' in env['Def'].columns else None
    dropped = []
    for b in spread.columns:
        if ttm is None or b not in ttm.index or not pd.notna(ttm.loc[b]) or ttm.loc[b] <= 0:
            dropped.append(b)
            continue
        if _trailing_frozen_count(spread[b]) >= max_frozen:
            dropped.append(b)
    if not dropped:
        return spread, []
    return spread.drop(columns=dropped), dropped


def statAnalysis_BC(env, df1, df2, zscore_lookback: int = 252, roll_dates=None):
    # Ornstein–Uhlenbeck Process calibration, or normal statistics
    # formula reference: https://www.zhihu.com/question/268075949/answer/1531412127
    # spreadvalues between quoted ytm and actual ytm

    bonds = df1.columns.intersection(env['Def'].index)
    df1 = pd.DataFrame(df1).apply(pd.to_numeric, errors='coerce')
    df2 = pd.DataFrame(df2).apply(pd.to_numeric, errors='coerce')
    df1 = df1.loc[:, bonds]
    df2 = df2.reindex(index=df1.index, columns=bonds)
    for b in bonds:
        df2[b] = _suppress_curve_yield_outliers(df2[b], df1[b])

    vol_ratio = df1.std() / df2.std().replace(0, np.nan)
    df2 = df2.reindex(index=df1.index)
    spread = df1 - df2
    spread = spread[bonds]
    # Remove dead instruments before any statistic is fit on them; a frozen
    # residual otherwise passes the stationarity filter and contributes a
    # near-zero vol divisor. See _drop_stale_residual_bonds.
    spread, _stale = _drop_stale_residual_bonds(spread, env)
    if _stale:
        bonds = spread.columns
        print(f"INFO: dropped {len(_stale)} stale/delisted bond(s) from BondCurve stats: "
              f"{', '.join(map(str, _stale[:8]))}{' ...' if len(_stale) > 8 else ''}")
    # Use a 1-year rolling window for mean/vol/stationarity so old regimes
    # don't dilute the normalisation. Full spread history is kept in the
    # returned dict for downstream charting.
    spread_stat = spread.iloc[-zscore_lookback:] if len(spread) > zscore_lookback else spread
    # Remove reference-roll step-changes from the SERIES THE STATS ARE FIT
    # ON (not from the returned `Spread`, which downstream charting expects
    # raw). OU_calibrate's signature is deliberately untouched -- it has 10
    # call sites across bond/IRS/spread/OTR-OFR paths and this finding
    # concerns only the bond-curve residual. See F6 / item 3.2.
    spread_stat = splice_reference_rolls(spread_stat, roll_dates)
    stat_info = OU_calibrate(spread_stat)
    for b in bonds:
        stat_info.loc[b,'ttm'] = env['Def'].loc[b,'剩余期限']
        # spreadvalue[b] = spread[b] - fr001 + fr007
        stat_info.loc[b,'max'] = stat_info.loc[b,'max']-stat_info.loc[b,'mean']
        stat_info.loc[b,'min'] = stat_info.loc[b,'min']-stat_info.loc[b,'mean']
        stat_info.loc[b,'vol_ratio'] = vol_ratio.loc[b]
        stat_info.loc[b,'close'] = df2[b].iloc[-1] + stat_info.loc[b,'mean']

    return dict(StatInfo=stat_info.dropna(subset=['stationary']),
                Spread=spread,
                CloseYield=df1,
                CurveYield=df2)

def statAnalysis_BS(env, df_act, irsKeyTS, bond_key_ts=None, zscore_lookback: int = 252):
    """Compute bond-swap spread statistics and BUY-side carry+roll time series.

    BondCarry stores the BUY-side (long bond, pay fixed IRS) annual carry+roll in bp:
        carry    = ytm_bond - fixrate_swap  (the bond-swap spread, annual %)
        roll_bond = (y_bond(TTM) - y_bond(TTM-3m)) * 4  (annualised 3m bond roll, %)
        roll_swap = (y_IRS(TTM)  - y_IRS(TTM-3m))  * 4  (annualised 3m IRS  roll, %)
        BondCarry = (carry + roll_bond + roll_swap) * 100  (annual bp)

    For SELL (short bond, receive fixed IRS), _carry_accrual multiplies by position=-1
    to negate: SELL carry+roll = -(carry + roll_bond + roll_swap).

    bond_key_ts : pd.DataFrame with float-year columns (1,2,3,4,5,7,10,...) and
                  DatetimeIndex containing the par yield (in %) of the bond curve at
                  each tenor.  If None, roll_bond defaults to 0.
    """
    ROLL_HORIZON = 0.25   # 3-month roll period in years
    ROLL_ANNUALIZE = 4.0  # convert 3m roll → annualised per-year figure

    bonds = df_act.columns.intersection(env['Def'].index)
    irs      = pd.DataFrame(index=df_act.index, columns=bonds)
    irs_roll = pd.DataFrame(0.0, index=df_act.index, columns=bonds)
    bond_roll = pd.DataFrame(0.0, index=df_act.index, columns=bonds)

    for d in irsKeyTS.index:
        irsKeyRates = irsKeyTS.loc[d, ANCHORS]
        irsKeyRates.index = TERMS
        irsKeyRates = irsKeyRates.dropna()
        if irsKeyRates.shape[0] < 2:
            continue
        f_irs = interpolate.interp1d(
            irsKeyRates.index, irsKeyRates.values, kind='linear',
            fill_value=(float(irsKeyRates.iloc[0]), float(irsKeyRates.iloc[-1])),
            bounds_error=False,
        )

        # Bond key-rate interpolator for this date (used for roll_bond)
        f_bond = None
        if bond_key_ts is not None:
            try:
                bkt_row = bond_key_ts.loc[d].dropna() if d in bond_key_ts.index else pd.Series(dtype=float)
                if len(bkt_row) >= 2:
                    xb = bkt_row.index.astype(float).to_numpy()
                    yb = bkt_row.values.astype(float)
                    f_bond = interpolate.interp1d(
                        xb, yb, kind='linear',
                        fill_value=(float(yb[0]), float(yb[-1])), bounds_error=False,
                    )
            except Exception:
                f_bond = None

        for b in bonds:
            dtm = env['Def'].loc[b, '到期日期']
            ttm = (dtm - d).days / 365
            ttm_roll = max(0.01, ttm - ROLL_HORIZON)
            try:
                # IRS rate at TTM (capped at 5y, matching original behaviour)
                if ttm <= TERMS[-1]:
                    y_irs = float(f_irs(ttm))
                else:
                    y_irs = float(irsKeyRates.iloc[-1])
                irs.loc[d, b] = y_irs

                # IRS roll: annualised yield change from rolling 3m down the IRS curve
                y_irs_roll_pt = float(f_irs(min(ttm_roll, TERMS[-1])))
                irs_roll.loc[d, b] = (y_irs - y_irs_roll_pt) * ROLL_ANNUALIZE

                # Bond roll: annualised yield change from rolling 3m down the par bond curve
                if f_bond is not None:
                    y_bond_at_ttm  = float(f_bond(ttm))
                    y_bond_at_roll = float(f_bond(ttm_roll))
                    bond_roll.loc[d, b] = (y_bond_at_ttm - y_bond_at_roll) * ROLL_ANNUALIZE
            except Exception:
                pass

    irs = irs.astype(float)
    irs_roll = irs_roll.astype(float)
    bond_roll = bond_roll.astype(float)

    vol_ratio = df_act.std() / irs.std()
    spreadvalue = pd.DataFrame(columns=bonds)
    fr001 = irsKeyTS['FR001.IR']
    fr007 = irsKeyTS['FR007.IR']
    r7d3m = irsKeyTS['FR007S3M.IR']

    spread = df_act - irs
    spread = spread[bonds]
    # Use a 1-year rolling window for mean/vol/stationarity so old regimes
    # don't dilute the normalisation. Full spread history is kept in the
    # returned dict for downstream charting (matches statAnalysis_BC).
    spread_stat = spread.iloc[-zscore_lookback:] if len(spread) > zscore_lookback else spread
    stat_info = OU_calibrate(spread_stat)
    for b in bonds:
        stat_info.loc[b, 'ttm'] = env['Def'].loc[b, '剩余期限']
        # BUY-side annual carry+roll in bp:
        #   carry     = ytm_bond − fixrate_swap  (annual %, stored in spread[b])
        #   roll_bond = bond curve roll over 3m, annualised (annual %)
        #   roll_swap = IRS  curve roll over 3m, annualised (annual %)
        #   BondCarry = (carry + roll_bond + roll_swap) × 100  (annual bp)
        rb = bond_roll[b].reindex(spread.index).fillna(0.0)
        rs = irs_roll[b].reindex(spread.index).fillna(0.0)
        spreadvalue[b] = (spread[b] + rb + rs) * 100.0
        stat_info.loc[b, 'vol_ratio'] = vol_ratio.loc[b]
    spreadvalue = spreadvalue[bonds]
    return dict(StatInfo=stat_info.dropna(subset=['stationary']),
                Spread=spread,
                BondCarry=spreadvalue)

def statAnalysis_30Y(bonds30Y,bonds30Y_ts):
    # Ornstein–Uhlenbeck Process calibration, or normal statistics
    # formula reference: https://www.zhihu.com/question/268075949/answer/1531412127
    # spreadvalues between quoted ytm and actual swap rate
    bonds30Yt = bonds30Y[bonds30Y['证券全称'].str.contains('国债')]
    bonds30Yt['换手率'] = bonds30Yt['成交量'] / bonds30Yt['债券余额:亿'] / 1e8
    bonds30Yt.sort_values(by='换手率', inplace=True, ascending=False)
    anchor = bonds30Yt.index[0]
    spread = bonds30Y_ts.sub(bonds30Y_ts[anchor], axis=0)
    spread = spread.drop([anchor], axis=1)
    stat_info = OU_calibrate(spread)
    for b in stat_info.index:
        stat_info.loc[b,'ttm'] = bonds30Y.loc[b,'剩余期限']
    stat_info = stat_info.dropna(subset=['stationary']).sort_index()
    return dict(StatInfo=stat_info,
                Spread=spread,Anchor=anchor,
                CNBDYield=bonds30Y_ts)

def statAnalysis_IRS(df1,df2):
    # spreadvalues between quoted ytm and actual ytm
    irs = df1 - df2
    vol_ratio = df1.std() / df2.std()
    stat_info = OU_calibrate(irs)
    for b in stat_info.index:
        stat_info.loc[b, 'max'] = stat_info.loc[b, 'max'] - stat_info.loc[b, 'mean']
        stat_info.loc[b, 'min'] = stat_info.loc[b, 'min'] - stat_info.loc[b, 'mean']
        stat_info.loc[b, 'vol_ratio'] = vol_ratio.loc[b]
    df2_ = df2 + stat_info['mean'].T

    spds = irsSpreads(df1)
    stat_info_spds = OU_calibrate(spds)
    for b in stat_info_spds.index:
        stat_info_spds.loc[b, 'max'] = stat_info_spds.loc[b, 'max'] - stat_info_spds.loc[b, 'mean']
        stat_info_spds.loc[b, 'min'] = stat_info_spds.loc[b, 'min'] - stat_info_spds.loc[b, 'mean']
    stat_infoa = pd.concat([stat_info,stat_info_spds],axis=0)
    spread = pd.concat([irs,spds],axis=1)
    close = pd.concat([df1,spds],axis=1)
    curve = pd.concat([df2_,spds],axis=1)
    return dict(StatInfo=stat_infoa,
                Spread=spread,
                CloseYield=close,
                CurveYield=curve)
def statAnalysis(spread):
    # Ornstein–Uhlenbeck Process calibration, or normal statistics
    # formula reference: https://www.zhihu.com/question/268075949/answer/1531412127
    # spreadvalues between quoted ytm and actual swap rate
    stat_info = OU_calibrate(spread)
    return dict(StatInfo=stat_info.dropna(subset=['stationary']),
                Spread=spread)
