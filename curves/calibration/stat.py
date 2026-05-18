# -*- coding: utf-8 -*-
"""
Created on Sun Sep 17 14:05:04 2023

@author: CMBC
"""
import pandas as pd
import numpy as np
from scipy import interpolate
from curves.calibration.irscurves import irsSpreads

# Constants reused across functions
ANCHORS = ['FR007.IR','FR007S3M.IR','FR007S6M.IR','FR007S9M.IR','FR007S1Y.IR','FR007S2Y.IR','FR007S5Y.IR']
TERMS = [0, 1/4, 1/2, 3/4, 1, 2, 5]

def _adf_result(series: pd.Series):
    """Run ADF test for a 1D series and return (pvalue, stationary:str, stats, crit)"""
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
    for k in quote.keys():
        quote_adj[k] = quote[k]['收益率']+stat['mean']
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
    statvs = ['halflife', 'mean', 'vol', 'max', 'min']
    stat_info = pd.DataFrame(index=ts.columns, columns=['stationary'] + statvs)
    stat_info.index.name = 'ID'
    for b in ts.columns:
        sp = ts[b].dropna()
        if sp.shape[0] > 20:
            _, stationary, _, _ = _adf_result(sp)
            stat_info.loc[b, 'stationary'] = stationary
            if stationary == 'YES':
                A, B, C = _fit_ar1_params(sp)
                if np.isfinite(A) and (1 - A) != 0 and A > 0:
                    theta = B / (1 - A)
                    kappa = -np.log(A)
                    sigma = C * np.sqrt(max(1e-12, 2 * kappa / (1 - A ** 2)))
                    stat_info.loc[b, 'halflife'] = np.log(2) / max(1e-12, kappa)
                    stat_info.loc[b, 'mean'] = theta
                    stat_info.loc[b, 'vol'] = sigma
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

def statAnalysis_BC(env,df1,df2):
    # Ornstein–Uhlenbeck Process calibration, or normal statistics
    # formula reference: https://www.zhihu.com/question/268075949/answer/1531412127
    # spreadvalues between quoted ytm and actual ytm

    vol_ratio = df1.std()/df2.std()
    # spreadvalue = pd.DataFrame(columns=spread.columns)
    # irsKeyRates = env['irs_ts'].loc[df1.index[0]:df1.index[-1]]
    # fr001 = irsKeyRates['FR001.IR']
    # fr007 = irsKeyRates['FR007.IR']
    bonds = df1.columns.intersection(env['Def'].index)
    spread = df1 - df2
    spread = spread[bonds]
    stat_info = OU_calibrate(spread)
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
                CurveYield=df2)#+stat_info['mean'].T

def statAnalysis_BS(env, df_act, irsKeyTS, bond_key_ts=None):
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
    stat_info = OU_calibrate(spread)
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
