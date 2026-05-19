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
from settings.fixed_income import IRSConfig
from curves.utils.calendar import getScheduleDays


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
        self.day = d
        self.type = btype
        self.gamma = GeneralConfig.GAMMA
        self.mtype = GeneralConfig.MODEL_TYPE
        self.caltype = GeneralConfig.CALC_TYPE
        
    def calibrate(self,term,spot):
        print('Update S2 Matrix on ',self.day.strftime("%Y-%m-%d"))
        self.S2 = af.calAffineCov(term,spot,self.gamma,self.mtype,self.caltype)
        return self
    
    def extractFactors(self,df_bs,bond_ref):
        self.factors = af.getAffineFactors(df_bs,self.S2,self.gamma,self.mtype,self.caltype)
        self.reference = bond_ref
        return self

    def extractFactorsRobust(self, df_bs, bond_ref, k_mad=2.0, min_points=4):
        """3-factor extraction with MAD-based outlier screening.

        First-pass OLS, then drop reference points whose residual exceeds
        k_mad × scaled-MAD; re-fit on the survivors. Falls back to the
        first-pass fit if fewer than `min_points` survive.

        Diagnostics: self._fit_residuals, self._fit_kept, self._fit_dropped.
        """
        # First-pass fit
        self.factors = af.getAffineFactors(df_bs, self.S2, self.gamma, self.mtype, self.caltype)
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
            self.factors = af.getAffineFactors(df_kept, self.S2, self.gamma, self.mtype, self.caltype)
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
            mats = row['起息日期']
            mate = row['到期日期']
            freq = row['每年付息次数']
            if '国债' in name:
                tax = 0# 0.25
            else:
                tax = 0.
            if freq == 0.:
                coup = 0.
                freq = round((365/(mate-mats).days),0)
            else:
                coup = row['票面利率:%']
            if np.isnan(freq):
                freq = 1.       
            if mats < self.day:
                if b not in schedule:
                    schedule[b] = yd.scheduleDate(mats, mate, name, freq)
                price, clean, sen0 = yd.pricingAffine(self.day,coup,tax,schedule[b],freq,self.factors,self.S2,self.gamma,self.mtype,self.caltype)
                quote.loc[b,'全价'] = price
                quote.loc[b,'净价'] = clean
                try:
                    quote.loc[b,'收益率'] = yd.pricingYield(self.day,coup,schedule[b],freq,float(price))
                    quote.loc[b,'剩余期限'] = (mate-self.day).days/365
                except:
                    quote.loc[b,'收益率'] = np.nan
                    print('Pricing ',b, ' failed, on ',self.day.strftime("%Y-%m-%d"))
                sen.loc[b,:] = [sen0[0,s] for s in range(sen0.shape[1])]     
            else:
                quote.loc[b,'收益率'] = np.nan
        return quote.astype(float).dropna(),sen.astype(float).dropna()
        
    def Pricing(self,bonds_quo,bonds,*args,hist=False,ytm_other=False):
        quote = pd.DataFrame(index=bonds_quo,columns=['全价','净价','收益率','剩余期限'])
        # pricing bonds_quo with maturities between 1Y and 10Y 
        mat = bonds['到期日期'] - self.day
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
            mats = row['起息日期']
            mate = row['到期日期']
            freq = row['每年付息次数']
            if ytm_other:
                ytm  = args[0].loc[b]
            else:
                if hist:
                    ytm  = args[0]['Close'].loc[args[0], b] if isinstance(args[0], dict) and 'Close' in args[0] else np.nan
                else:
                    ytm  = row['成交收益率']
                    
            if freq == 0.:
                coup = 0.
                freq = round((365/(mate-mats).days),0)
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
        mat = bonds['到期日期'] - self.day
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
            mats = row['起息日期']
            mate = row['到期日期']
            freq = row['每年付息次数']
            price  = bond_price.loc[b]
            if freq == 0.:
                coup = 0.
                freq = round((365/(mate-mats).days),0)
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
        # 0.05y grid so that exact 0.25/0.5/0.75 tenor lookups land on the grid.
        delt = 0.05
        taus = np.round(np.arange(0.05, 10.05, delt), 2)
        S2_flat = tuple(float(self.S2[i,j]) for i in range(3) for j in range(3))
        gamma_f = float(self.gamma)
        if isinstance(self.factors, sp.MatrixBase):
            x_arr = np.array([float(self.factors[i]) for i in range(3)])
        else:
            x_arr = np.asarray(self.factors, dtype=float).ravel()
        spot_curve = np.empty(len(taus))
        for idx, tau in enumerate(taus):
            a, B = af.calAB_np(gamma_f, float(tau), S2_flat, self.mtype)
            spot_curve[idx] = a + B @ x_arr
        df_curve = pd.Series(spot_curve, index=taus, name='SpotRate')

        discount_curve = np.exp(-df_curve.values * df_curve.index.values.astype(float) / 100)
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
        self.S2 = af.calAffineCov(term,spot,self.gamma,self.mtype,self.caltype)
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
        df_curve = pd.Series(spot_curve)
        df_curve.index = taus.round(4)
        df_curve.name = 'SpotRate'
        df_DF = np.exp(-np.array(df_curve.values) * np.array(df_curve.index) / 100)
        df_DF = pd.Series(df_DF, name='DF',index=df_curve.index)
        df_forward = _instantaneous_forward_from_discount(df_DF.values, df_curve.index.values)
        self.curves = pd.concat([df_curve, df_forward, df_DF], axis=1)
        return self
     
    def affinePricing(self,irs):
        sen = pd.DataFrame(index=irs.keys(),columns=['Greek1','Greek2','Greek3'])
        for i in irs.keys():
            price, clean, sen0 = yd.pricingAffine(self.day,irs.fixrate,0,irs.schedule,irs.freq,self.factors,self.S2,self.gamma,self.mtype,self.caltype)
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