#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Jan 15 16:09:22 2023

@author: mayunfei
"""
import pandas as pd
import numpy as np
import sympy as sp
from scipy import interpolate

import curves.affine.affine as af
import curves.affine.pricingYield as yd
from settings.general import GeneralConfig
from settings.fixed_income import IRSConfig, BondConfig
from curves.utils.cn_calendar import getScheduleDays


def quote_quality_weights(
    is_live: pd.Series,
    spread_bp: pd.Series = None,
    volume: pd.Series = None,
    max_spread_bp: float = 15.0,
    min_weight: float = 0.1,
) -> pd.Series:
    """Map per-reference-point quote-quality signals into a factor-extraction
    weight, for use with ``Curve.extractFactorsRobust(..., weights=...)``.

    Args:
        is_live: True where the point's YTM comes from a genuine live/traded
            quote; False where it fell back to a CNBD model valuation
            (`估价收益率:%(中债)`), which for illiquid off-the-run refs can lag
            the market by days (see F9). Required.
        spread_bp: bid-ofr YTM spread in bp, where available. A wider spread
            means a less certain price, so it should count for less.
        volume: recent traded volume/turnover, where available. Larger
            volume means a more reliable print.
        max_spread_bp: spread at or above which the spread factor bottoms
            out at ``min_weight`` (same scale as BondConfig.REF_BID_OFR_MAX_BP).
        min_weight: floor for any individual quality factor, so a single bad
            signal never fully zeroes out a point the way the binary MAD
            screen would -- it should count for less, not nothing (that is
            still ultimately possible via the separate MAD screen if the
            point is a genuine outlier once fit).

    Returns:
        Weight per point (same index as the inputs), in (0, 1], product of
        the individual quality factors that have data. A point missing all
        optional signals (spread_bp, volume) gets weight 1.0 if live, or the
        live/CNBD factor alone if not.

    See docs/dev/affine-curve-improvement-plan.md F9 / item 2.3.
    """
    idx = is_live.index
    live_factor = pd.Series(np.where(is_live.to_numpy(dtype=bool), 1.0, min_weight), index=idx)

    weight = live_factor.copy()

    if spread_bp is not None:
        s = pd.to_numeric(spread_bp.reindex(idx), errors='coerce')
        # Linear ramp from weight 1.0 at spread=0 down to min_weight at
        # spread=max_spread_bp, floored at min_weight beyond that. Missing
        # spread info does not penalize the point (factor of 1.0).
        spread_factor = 1.0 - (1.0 - min_weight) * (s.clip(lower=0.0, upper=max_spread_bp) / max_spread_bp)
        spread_factor = spread_factor.fillna(1.0)
        weight = weight * spread_factor

    if volume is not None:
        v = pd.to_numeric(volume.reindex(idx), errors='coerce')
        v_valid = v.dropna()
        if not v_valid.empty and v_valid.max() > 0:
            # Rank-based, not raw-magnitude: turnover distributions are
            # heavy-tailed across a reference set of very different tenors,
            # so a linear or log scaling would let one very liquid point
            # dominate. Rank into [min_weight, 1.0] instead.
            ranks = v.rank(method='average', na_option='keep')
            n_valid = v_valid.shape[0]
            volume_factor = min_weight + (1.0 - min_weight) * ((ranks - 1.0) / max(n_valid - 1, 1))
            volume_factor = volume_factor.fillna(1.0)
        else:
            volume_factor = pd.Series(1.0, index=idx)
        weight = weight * volume_factor

    # Floor at min_weight, NOT min_weight**2. Three independent factors
    # (live/CNBD, spread width, volume rank) multiply together, so a bond
    # that looks mediocre on each -- very common, since outside live Wind
    # hours BondRT falls back to the CNBD mark and EVERY bond scores
    # live=False -- compounded to ~0.03 and effectively dropped out of the
    # fit. That both defeats the purpose of graded weighting (the whole
    # point of item 2.3 was "count less", not "count as nothing") and
    # measurably degraded the fit: on real TBond data the compounded
    # weights nearly doubled anchor-fit RMSE (3.7bp -> 6.3bp) versus the
    # unweighted fit. min_weight is the intended worst case for any single
    # point; clip the product there.
    return weight.clip(lower=min_weight, upper=1.0)


def _instantaneous_forward_from_log_discount(log_discount, tenors):
    log_discount = np.asarray(log_discount, dtype=float)
    tau = np.asarray(tenors, dtype=float)
    if log_discount.size == 0:
        return pd.Series(dtype=float, name='ForwardRate')
    if log_discount.size == 1:
        return pd.Series(np.zeros(1, dtype=float), index=np.round(tau, 10), name='ForwardRate')

    valid = np.isfinite(log_discount) & np.isfinite(tau)
    if valid.sum() == 0:
        return pd.Series(dtype=float, name='ForwardRate')

    out = np.full(log_discount.shape, np.nan, dtype=float)
    if valid.sum() == 1:
        out[valid] = 0.0
        return pd.Series(out, index=np.round(tau, 10), name='ForwardRate')

    valid_pos = np.flatnonzero(valid)
    tau_valid = tau[valid]
    log_discount_valid = log_discount[valid]
    order = np.argsort(tau_valid)
    tau_sorted = tau_valid[order]
    log_discount_sorted = log_discount_valid[order]

    edge_order = 2 if tau_sorted.size > 2 else 1
    forward_sorted = -100 * np.gradient(log_discount_sorted, tau_sorted, edge_order=edge_order)
    out[valid_pos[order]] = forward_sorted
    return pd.Series(out, index=np.round(tau, 10), name='ForwardRate')


def _instantaneous_forward_from_discount(discount_factors, tenors):
    discount = np.asarray(discount_factors, dtype=float)
    clipped = np.clip(discount, 1e-12, None)
    return _instantaneous_forward_from_log_discount(np.log(clipped), tenors)


def _instantaneous_forward_from_spot(spot_rates, tenors):
    spot = np.asarray(spot_rates, dtype=float)
    tau = np.asarray(tenors, dtype=float)
    if spot.size == 0:
        return pd.Series(dtype=float, name='ForwardRate')
    log_discount = -spot * tau / 100
    return _instantaneous_forward_from_log_discount(log_discount, tau)


class Curve:
    def __init__(self,d,btype):
        self.day = pd.Timestamp(d)
        self.type = btype
        self.gamma = GeneralConfig.GAMMA
        self.mtype = GeneralConfig.MODEL_TYPE
        self.caltype = GeneralConfig.CALC_TYPE
        # Curve-quality flags, populated by calibrate()/fitting(); see F3,
        # F12 / item 1.5 in docs/dev/affine-curve-improvement-plan.md.
        self.affine_cov_converged = None
        self.affine_unstable = None

    def calibrate(self,term,spot):
        print('Update S2 Matrix on ',self.day.strftime("%Y-%m-%d"))
        self.S2, self.affine_cov_converged = af.calAffineCov(term,spot,self.gamma,self.mtype,self.caltype)
        return self
    
    def extractFactors(self,df_bs,bond_ref):
        self.factors = af.getAffineFactors(df_bs,self.S2,self.gamma,self.mtype,self.caltype)
        self.reference = bond_ref
        return self

    def extractFactorsRobust(self, df_bs, bond_ref, k_mad=2.0, min_points=4, weights=None):
        """3-factor extraction with MAD-based outlier screening, and optional
        per-point quality weighting.

        First-pass (weighted, if `weights` given) OLS, then drop reference
        points whose residual exceeds k_mad × scaled-MAD; re-fit (again
        weighted) on the survivors. Falls back to the first-pass fit if
        fewer than `min_points` survive.

        Args:
            weights: optional per-reference-point quality weight (same
                order/index as ``df_bs``), e.g. from
                ``quote_quality_weights`` below. A weighted point still
                counts in proportion to its weight rather than only ever
                being fully believed or fully dropped by the binary MAD
                screen. None (default) reproduces the previous unweighted
                behavior exactly. See
                docs/dev/affine-curve-improvement-plan.md F9 / item 2.3.

        Diagnostics: self._fit_residuals, self._fit_kept, self._fit_dropped,
        self._fit_weights (the weights actually used, or None).

        Raises:
            ValueError: if fewer than 3 usable reference points are supplied.
                A 3-factor fit needs at least 3 anchors; an empty/near-empty
                df_bs previously slipped through np.linalg.lstsq and returned
                a garbage near-zero factor vector, yielding a degenerate
                near-flat curve (~0.25% at every tenor) that no downstream
                guard caught -- `fitting()`'s affine_unstable check itself
                requires len(ref_input) >= 3, so it never even ran. Fail
                loudly here instead of publishing a silently-wrong curve.
        """
        df_bs = pd.to_numeric(pd.Series(df_bs), errors='coerce').dropna()
        if len(df_bs) < 3:
            raise ValueError(
                f"extractFactorsRobust: need >=3 usable reference points for a "
                f"3-factor fit, got {len(df_bs)}. Upstream reference/yield "
                f"lookup most likely returned no data (see "
                f"curves/calibration/selector.py::extract_yield)."
            )

        weights_arr = None
        if weights is not None:
            weights_arr = pd.Series(weights).reindex(df_bs.index).to_numpy(dtype=float)
            if not np.isfinite(weights_arr).all():
                raise ValueError("extractFactorsRobust: weights must be finite and cover every point in df_bs")
        self._fit_weights = pd.Series(weights_arr, index=df_bs.index) if weights_arr is not None else None

        # First-pass fit
        self.factors = af.getAffineFactors(df_bs, self.S2, self.gamma, self.mtype, self.caltype, weights=weights_arr)
        self.reference = bond_ref

        taus = df_bs.index.values.astype(float)
        obs = df_bs.values.astype(float)
        S2_flat = tuple(float(self.S2[i, j]) for i in range(3) for j in range(3))
        gamma_f = float(self.gamma)
        if isinstance(self.factors, sp.MatrixBase):
            x_arr = np.array([float(self.factors[i]) for i in range(3)])
        else:
            x_arr = np.asarray(self.factors, dtype=float).ravel()
        model = np.empty_like(obs)
        for i, t in enumerate(taus):
            a, B = af.calAB_np(gamma_f, float(t), S2_flat, self.mtype)
            model[i] = a + B @ x_arr
        residuals = obs - model

        med = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - med)))
        scaled_mad = 1.4826 * mad
        if scaled_mad > 0:
            keep = np.abs(residuals - med) <= k_mad * scaled_mad
        else:
            keep = np.ones_like(residuals, dtype=bool)

        self._fit_residuals = pd.Series(residuals, index=df_bs.index, name='residual')
        # Full pre-MAD input (already screened by staleness + TTM band upstream).
        # The short-end overlay uses this set so points the affine model treats
        # as outliers — because the model is structurally too smooth at the
        # short end — are still visible in the displayed curve.
        self._fit_ref_input = df_bs
        if keep.sum() >= min_points and keep.sum() < len(residuals):
            df_kept = df_bs.iloc[keep]
            weights_kept = weights_arr[keep] if weights_arr is not None else None
            self.factors = af.getAffineFactors(df_kept, self.S2, self.gamma, self.mtype, self.caltype, weights=weights_kept)
            self._fit_kept = keep
            self._fit_dropped = self._fit_residuals[~keep]
        else:
            self._fit_kept = np.ones_like(residuals, dtype=bool)
            self._fit_dropped = pd.Series(dtype=float, name='residual')
        return self
        
    def affinePricing(self,bonds,bonds_quo):
        quote = pd.DataFrame(index=bonds.index,columns=['全价','净价','收益率'])
        sen = pd.DataFrame(index=bonds.index,columns=['Greek1','Greek2','Greek3'])
        schedule = {}
        total = len(bonds_quo)
        log_every = max(1, total // 20)
        for ib, b in enumerate(bonds_quo):
            if ib % log_every == 0 or ib == total - 1:
                percentage = 100*ib/max(1,total)
                print('\rAffine pricing: ',b,'%.2f%% completed.'%percentage,' '*100, end='')
            row = bonds.loc[b]
            name = row['证券全称']
            mats = pd.Timestamp(row['起息日期'])
            mate = pd.Timestamp(row['到期日期'])
            freq = row['每年付息次数']
            # Use a single no-tax convention for both calibration and pricing.
            # TBond and CDB quotes are both generated directly from the affine
            # curve without adding a coupon-specific tax premium.
            tax = 0.
            # Genuine discount / zero-coupon bonds (freq == 0) are priced on
            # their own simple-interest short-end formula (pricing.py /
            # pricingAffine); never fabricate a synthetic freq to force them
            # through the coupon-bearing path (see affine plan F1 / item 1.1).
            if freq == 0.:
                coup = 0.
            else:
                coup = row['票面利率:%']
                if np.isnan(freq):
                    freq = 1.
            if mats < self.day:
                if b not in schedule:
                    schedule[b] = yd.scheduleDate(mats, mate, name, freq)
                price, clean, sen0, price_pretax, clean_pretax = yd.pricingAffine(self.day,coup,tax,schedule[b],freq,self.factors,self.S2,self.gamma,self.mtype,self.caltype)
                price_is_implausible = (not np.isfinite(price)) or (not np.isfinite(clean)) or price <= 1.0 or price > 200.0
                quote.loc[b,'全价'] = price
                quote.loc[b,'净价'] = clean
                if price_is_implausible:
                    print(f'Implausible price for {b} on {self.day}: price=nan')
                    quote.loc[b,'收益率'] = np.nan
                else:
                    try:
                        # Invert directly from the model dirty price under the
                        # shared no-tax convention used for calibration.
                        quote.loc[b,'收益率'] = yd.pricingYield(self.day,coup,schedule[b],freq,float(price))
                        quote.loc[b,'剩余期限'] = (mate-self.day).days/365
                    except Exception as _e:
                        quote.loc[b,'收益率'] = np.nan
                        print(f'Pricing {b} failed on {self.day}: {_e}')
                sen.loc[b,:] = [sen0[0,s] for s in range(sen0.shape[1])]     
            else:
                quote.loc[b,'收益率'] = np.nan
        return quote.astype(float).dropna(),sen.astype(float).dropna()
        
    def Pricing(self,bonds_quo,bonds,*args,hist=False,ytm_other=False):
        quote = pd.DataFrame(index=bonds_quo,columns=['全价','净价','收益率','剩余期限'])
        # pricing bonds_quo with maturities between 1Y and 10Y
        mat = pd.to_datetime(bonds['到期日期']) - self.day
        bonds['剩余期限'] = [i.days/365 for i in mat]
        schedule = {}
        total = len(bonds_quo)
        log_every = max(1, total // 20)
        for ib, b in enumerate(bonds_quo):
            if ib % log_every == 0 or ib == total - 1:
                percentage = 100*ib/max(1,total)
                print('\rConverting YTM to dirty/clean price: ',b,'%.2f%% completed.'%percentage,' '*100, end='')
            row = bonds.loc[b]
            name = row['证券全称']
            mats = pd.Timestamp(row['起息日期'])
            mate = pd.Timestamp(row['到期日期'])
            freq = row['每年付息次数']
            if ytm_other:
                ytm  = args[0].loc[b]
            else:
                if hist:
                    ytm  = args[0]['Close'].loc[args[0], b] if isinstance(args[0], dict) and 'Close' in args[0] else np.nan
                else:
                    ytm  = row['成交收益率']
                    
            # See affine plan F1 / item 1.1: never fabricate a synthetic freq
            # for genuine discount/zero-coupon bonds.
            if freq == 0.:
                coup = 0.
            else:
                coup = row['票面利率:%']
                if np.isnan(freq):
                    freq = 1.
            if mats < self.day:
                if np.isnan(ytm):
                    quote.loc[b,'收益率'] = np.nan
                else:
                    if b not in schedule:
                        schedule[b] = yd.scheduleDate(mats,mate,name,freq) 
                    price, clean, dur, cov = yd.pricing(self.day,coup,schedule[b],freq,ytm)
                    quote.loc[b,'全价'] = price
                    quote.loc[b,'净价'] = clean
                    quote.loc[b,'剩余期限'] = (mate-self.day).days/365
                    try:
                        quote.loc[b,'收益率'] = ytm
                    except:
                        quote.loc[b,'收益率'] = np.nan
                        print('Pricing ',b, ' failed, on ',self.day.strftime("%Y-%m-%d"))
            else:
                quote.loc[b,'收益率'] = np.nan
        return quote.astype(float)
    
    def PricingYTM(self,bond_price,bonds):
        quote = pd.DataFrame(index=bond_price.index,columns=['全价','收益率','剩余期限'])
        # pricing bonds_quo with maturities between 1Y and 10Y
        mat = pd.to_datetime(bonds['到期日期']) - self.day
        bonds['剩余期限'] = [i.days/365 for i in mat]
        schedule = {}
        total = bond_price.shape[0]
        log_every = max(1, total // 20)
        for ib, b in enumerate(bond_price.index):
            if ib % log_every == 0 or ib == total - 1:
                percentage = 100*ib/max(1,total)
                print('\rConverting dirty price to YTM: ',b,'%.2f%% completed.'%percentage,' '*100, end='')
            row = bonds.loc[b]
            name = row['证券全称']
            mats = pd.Timestamp(row['起息日期'])
            mate = pd.Timestamp(row['到期日期'])
            freq = row['每年付息次数']
            price  = bond_price.loc[b]
            # See affine plan F1 / item 1.1: never fabricate a synthetic freq
            # for genuine discount/zero-coupon bonds.
            if freq == 0.:
                coup = 0.
            else:
                coup = row['票面利率:%']
                if np.isnan(freq):
                    freq = 1.
            if mats < self.day:
                if b not in schedule:
                    schedule[b] = yd.scheduleDate(mats,mate,name,freq)      
                quote.loc[b,'全价'] = price
                quote.loc[b,'剩余期限'] = (mate-mats).days/365
                try:
                    quote.loc[b,'收益率'] = yd.pricingYield(self.day,coup,schedule[b],freq,float(price))
                    if abs(quote.loc[b,'收益率']) > 3:
                        print(f'WARNING: Abnormal yield {quote.loc[b,"收益率"]:.4f}% for {b} on {self.day}')
                except:
                    quote.loc[b,'收益率'] = np.nan
                    print('Pricing ',b, ' failed, on ',self.day.strftime("%Y-%m-%d"))
            else:
                quote.loc[b,'收益率'] = np.nan
        return quote.astype(float)
    
    def fitting(self):
        # 0.05y grid so that exact tenor lookups land on the grid.
        delt = 0.05
        max_display_tenor = 10.0
        taus = np.round(np.arange(0.05, max_display_tenor + delt / 2, delt), 2)
        gamma_f = float(self.gamma)

        ref_input = getattr(self, '_fit_ref_input', None)
        if isinstance(ref_input, pd.Series):
            ref_input = ref_input.dropna().sort_index()
            ref_input.index = pd.to_numeric(pd.Index(ref_input.index), errors='coerce')
            ref_input = ref_input[~pd.isna(ref_input.index)]
            ref_input = ref_input[ref_input.index <= max_display_tenor]
            ref_input = ref_input[~ref_input.index.duplicated(keep='last')].sort_index()
        else:
            ref_input = None

        S2_eff = np.asarray(self.S2, dtype=float)
        if not np.isfinite(S2_eff).all():
            S2_eff = np.eye(3) * 1e-4
        else:
            S2_eff = np.asarray(af._project_to_psd(S2_eff), dtype=float)

        if isinstance(self.factors, sp.MatrixBase):
            x_arr = np.array([float(self.factors[i]) for i in range(3)])
        else:
            x_arr = np.asarray(self.factors, dtype=float).ravel()

        def _evaluate_curve(S2_matrix, factors):
            S2_flat_local = tuple(float(v) for v in np.asarray(S2_matrix, dtype=float).ravel())
            out = np.empty(len(taus))
            for idx, tau in enumerate(taus):
                a_val, b_val = af.calAB_np(gamma_f, float(tau), S2_flat_local, self.mtype)
                out[idx] = a_val + b_val @ factors
            return pd.Series(out, index=taus, name='SpotRate')

        df_curve = _evaluate_curve(S2_eff, x_arr)

        if ref_input is not None and len(ref_input) >= 3:
            S2_flat_eff = tuple(float(v) for v in S2_eff.ravel())
            base_at_anchor = np.empty(len(ref_input))
            for idx, tau in enumerate(ref_input.index.to_numpy(dtype=float)):
                a_val, b_val = af.calAB_np(gamma_f, float(tau), S2_flat_eff, self.mtype)
                base_at_anchor[idx] = a_val + b_val @ x_arr

            anchor_fit_error = float(np.nanmax(np.abs(base_at_anchor - ref_input.to_numpy(dtype=float))))
            affine_unstable = (
                (not np.isfinite(base_at_anchor).all())
                or (not np.isfinite(df_curve.values).all())
                or np.linalg.norm(x_arr) > 1e3
                or np.nanmax(np.abs(df_curve.values)) > 100.0
                or anchor_fit_error > 5.0
            )

            # Surface the instability flag on the curve object itself (F12,
            # item 1.5) so trading logic can refuse to signal off a degraded
            # curve, not just fall back silently in this display path.
            self.affine_unstable = affine_unstable

            if affine_unstable:
                diag_cap = 1e-4
                max_diag = float(np.max(np.diag(S2_eff))) if S2_eff.size else 0.0
                if max_diag <= 0:
                    S2_display = np.eye(3) * diag_cap
                else:
                    shrink = min(1.0, diag_cap / max_diag)
                    S2_display = S2_eff * shrink
                x_display = af.getAffineFactors(ref_input, sp.Matrix(S2_display.tolist()), self.gamma, self.mtype, self.caltype)
                x_display = np.asarray(x_display, dtype=float).ravel()
                df_curve = _evaluate_curve(S2_display, x_display)
        else:
            self.affine_unstable = False

        exponent = -df_curve.values * df_curve.index.values.astype(float) / 100
        exponent = np.clip(exponent, -700, 700)
        discount_curve = np.exp(exponent)
        df_forward = _instantaneous_forward_from_discount(discount_curve, df_curve.index.values)
        df_curves = pd.concat([df_curve, df_forward], axis=1)
        return df_curves

class IRSCurve:
    def __init__(self,d,curve_type):
        self.day = d
        self.type = curve_type
        self.schedule = getScheduleDays(self.day,self.type)
        self.gamma = GeneralConfig.GAMMA
        self.mtype = GeneralConfig.MODEL_TYPE
        self.caltype = GeneralConfig.CALC_TYPE
        self.affine_cov_converged = None


    def extractKeySpot(self,df):    
        days_del = self.schedule.diff(1)
        days_del.iloc[0] = self.schedule.iloc[0]

        df.name = 'IRSRate'
        df = df.to_frame()
        _irs_terms = IRSConfig.get_irs_terms()
        daylist = [ (self.day + _irs_terms[i]-self.day).days for i in df.index]
        df['Days'] = daylist
        df = df.sort_values(by='Days')
        df['DelDays'] = df['Days'].diff()# days_del.values
        df.loc[df.index[0], 'DelDays'] = df['Days'].iloc[0]
        
        run_sum = 0.0
        for i in range(df.shape[0]):
            l = df.index[i]
            r = df.loc[l,'IRSRate']/100
            ds = df.loc[l,'DelDays']
            if pd.isna(r):
                df_val = 0
            else:
                if i == 0:
                    # ACT/365 for r7d (FR007 compounding), ACT/360 for s3m (SHIBOR3M simple)
                    yn_first = GeneralConfig.YN if self.type == 'r7d' else GeneralConfig.YN1
                    df_val = 1/(1+r*ds/yn_first)
                else:
                    df_val = (1-r*run_sum)/(1+r*ds/GeneralConfig.YN)
            df.loc[l,'DF'] = df_val
            run_sum += df.loc[l,'DelDays']*df_val/GeneralConfig.YN
        self.key_rate = df
        return self
       
    def interpolateCurve(self):
         days_nd = getScheduleDays(self.day,self.type,standard=False)
         f = interpolate.interp1d(self.key_rate['Days'],self.key_rate['DF'],kind='linear')
         df_nd = f(days_nd)
         df = pd.concat([days_nd,pd.Series(df_nd)],axis=1)
         df.columns = ['Days','DF']
         df['Tenor'] = df['Days']/GeneralConfig.YN
         df['Interval'] = df['Tenor'].diff()
         df = df.set_index('Tenor')
         t = df.index.values.astype(float)
         df_vals = df['DF'].values.astype(float)
         # Spot rates
         spot_rate = np.empty_like(df_vals)
         mask_short = t <= 1
         spot_rate[mask_short] = 100*(1/df_vals[mask_short]-1)/t[mask_short]
         mask_long = ~mask_short
         spot_rate[mask_long] = -100*np.log(df_vals[mask_long])/t[mask_long]
         # Forward rates
         df['SpotRate'] = np.round(spot_rate, 4)
         df['ForwardRate'] = _instantaneous_forward_from_discount(df_vals, df.index.values)
         df['SpotRate'] = df['SpotRate'].round(4)
         self.anchor = df
         return self
    
    def calibrate(self,term,spot):
        print('Update S2 Matrix on ',self.day.strftime("%Y-%m-%d"))
        self.S2, self.affine_cov_converged = af.calAffineCov(term,spot,self.gamma,self.mtype,self.caltype)
        return self
    
    def extractFactors(self,df_ref):
        self.factors = af.getAffineFactors(df_ref,self.S2,self.gamma,self.mtype,self.caltype)
        return self
    
    def fitting(self):
        # curve
        if self.type == 'r7d':
            delt = 7/GeneralConfig.YN
            dy = 1
            taus = np.arange(delt, 10+3*delt, delt/dy)
        elif self.type == 's3m':
            delt = 1/4
            dy = 10
            taus = np.arange(delt, 10+3*delt, delt/dy)
        else:
            pass

        spot_curve = []
        for tau in taus:
            y, b = af.Affine(tau, self.factors, self.S2, self.gamma, self.mtype, self.caltype)
            spot_curve.append(float(y))
        spot_arr = np.array(spot_curve)
        # Differentiate discount factors against the *unrounded* tau grid — rounding
        # the grid first (e.g. to 4dp) makes spacing slightly non-uniform, and
        # np.gradient amplifies that jitter into a visible zigzag in ForwardRate.
        # Only the display index is rounded, after the derivative is taken.
        df_DF_vals = np.exp(-spot_arr * taus / 100)
        df_forward = _instantaneous_forward_from_discount(df_DF_vals, taus)

        df_curve = pd.Series(spot_curve)
        df_curve.index = taus.round(4)
        df_curve.name = 'SpotRate'
        df_DF = pd.Series(df_DF_vals, name='DF', index=df_curve.index)
        df_forward.index = df_curve.index
        self.curves = pd.concat([df_curve, df_forward, df_DF], axis=1)
        return self
     
    def affinePricing(self,irs):
        sen = pd.DataFrame(index=irs.keys(),columns=['Greek1','Greek2','Greek3'])
        for i in irs.keys():
            price, clean, sen0, *_ = yd.pricingAffine(self.day,irs.fixrate,0,irs.schedule,irs.freq,self.factors,self.S2,self.gamma,self.mtype,self.caltype)
            sen.loc[i,:] = [sen0[0,s] for s in range(sen0.shape[1])]     
        return sen.astype(float).dropna()
    
    def adjFittingbyFunc(self,bp,a,b):
        # curve
        if self.type == 'r7d':
            delt = 7/GeneralConfig.YN
            dy = 1
        elif self.type == 's3m':
            delt = 1/4
            dy = 10
        else:
            pass
        y = lambda x: np.exp(-5*((x-(a+b)/2)*2/(b-a))**2)*bp/100
        df_forward = self.curves['ForwardRate'] + y(self.curves.index)
        df_spot = fwd2spt(df_forward)
        self.adjcurvesf = pd.concat([df_spot,df_forward],axis=1)
        self.adjcurvesf.columns=['SpotRate','ForwardRate']
        return self

    def adjFittingbyDate(self,fwd):
        # curve
        base_forward = self.curves['ForwardRate'].astype(float).copy()
        curve_index = base_forward.index.astype(float)

        fwd = pd.Series(fwd, copy=True).dropna()
        if fwd.empty:
            df_forward = base_forward.copy()
        else:
            fwd = fwd.astype(float)
            fwd.index = fwd.index.astype(float)
            fwd = fwd.groupby(level=0).last().sort_index()

            start_x = float(curve_index[0])
            end_x = float(curve_index[-1])
            if start_x not in fwd.index:
                fwd.loc[start_x] = float(base_forward.iloc[0])
            if end_x not in fwd.index:
                fwd.loc[end_x] = float(base_forward.iloc[-1])
            fwd = fwd.sort_index()

            if len(fwd) == 1:
                df_forward = pd.Series(float(fwd.iloc[0]), index=self.curves.index)
            else:
                f = interpolate.interp1d(
                    fwd.index.values,
                    fwd.values,
                    kind='linear',
                    bounds_error=False,
                    fill_value=(float(fwd.iloc[0]), float(fwd.iloc[-1])),
                    assume_sorted=True,
                )
                df_forward = pd.Series(f(self.curves.index), index=self.curves.index)
        df_spot = fwd2spt(df_forward)
        self.adjcurves = pd.concat([df_spot,df_forward],axis=1)
        self.adjcurves.columns=['SpotRate','ForwardRate']
        return self


def fwd2spt(df_forward):
    df_spot = df_forward.copy()
    vals = df_forward.values.astype(float)
    idx = df_forward.index.values.astype(float)
    out = np.empty_like(vals)
    out[0] = vals[0]
    for i in range(1, len(vals)):
        t1 = idx[i-1]
        t2 = idx[i]
        dres = t2 - t1
        out[i] = (out[i-1] * t1 + vals[i-1] * dres) / t2
    df_spot[:] = out
    return df_spot