# -*- coding: utf-8 -*-
"""
Created on Tue Jul 25 13:36:22 2023

@author: 马云飞
"""
import os
import numpy as np
import pandas as pd
from datetime import datetime as dt
from dateutil.relativedelta import relativedelta 
# local libraries
import sys
import pathlib
PATH = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PATH))
import tools.loading as ld
import tools.stat as st
import tools.retrieve as rd
from tools.config import DIR_INPUT, DateConfig
import affine.pricingYield as yd

def ConversionFactor(r,x,n,c,f,TS):
    if f == 2:
        k = 1. # frequency is the same as TBond
    else:
        k2 = 1/(1+r/2)**(x/TS)*(r/2+1) # TBond with two coupon payment per year
        kf = 1/(1+r/f)**(x/TS)*(r/f+1) # TBond with f coupon payment per year
        k = k2/kf
    return k*(1/(1+r/f)**(x/TS)*(c/f+c/r+(1-c/r)/(1+r/f)**(n-1)))-c/f*(1-x/TS)

def impliedPrice(env,f,b,strikeDate,cgb=True):
    d = dt.today()
    YN = 365
    price_list = np.arange(env['grid_range'][0],env['grid_range'][1],0.005).round(3)
    name = env['Def'].loc[b,'简称']
    mats = env['Def'].loc[b,'起息日期']
    mate = env['Def'].loc[b,'到期日期']
    freq = env['Def'].loc[b,'每年付息次数']
    coup = env['Def'].loc[b,'票面利率:%']
    schedule = yd.scheduleDate(mats,mate,name,freq)
    schedule = pd.Index(schedule)
    idx = schedule.get_indexer([strikeDate], method ='ffill')[0]
    
    scheduleDate_pre = schedule[idx]
    scheduleDate = schedule[idx+1]
    TS = (scheduleDate - scheduleDate_pre).days
    
    if cgb:
        cf = env['CTD-CGB'].loc[(f,b),'tbf_cvf']    
        if np.isnan(cf):
            x = (strikeDate - scheduleDate).days
            n = schedule.shape[0]-idx-1
            cf = ConversionFactor(0.03,x,n,coup/100,freq,TS)   
    else:
        x = (scheduleDate - strikeDate).days
        n = schedule.shape[0]-idx-1
        cf = ConversionFactor(0.03,x,n,coup/100,freq,TS)   
    
    # dres_fwd is the residual days between schedule date (before strike date) and strike date
    if strikeDate >= scheduleDate:
        dres_fwd = (strikeDate - scheduleDate).days
    else:
        dres_fwd = (strikeDate - scheduleDate_pre).days
    
    # dres is the residual days from trade date utill next schedule
    dres = (scheduleDate-d).days
    faccural = coup/freq*dres_fwd/TS
    
    # dres_stk is the residual days between trade date and strike date
    dres_stk = (strikeDate - d).days
    fundRate = np.interp(dres_stk/YN,np.array(irs['term']),np.array(irs['成交收益率']))
    carry = coup*dres_stk/YN
    discount = 1/(1+0.01*fundRate*(dres_stk/YN))
    
    df_grid = pd.DataFrame(index=price_list,
                           columns=['CTDFwdPrice','CTDFwdYld','CTDImpPrice','CTDImpYld']) 
    
    for future in price_list:
        clean_imf = future*cf 
        df_grid.loc[future,'CTDFwdPrice'] = clean_imf + faccural
        df_grid.loc[future,'CTDFwdYld'] = yd.pricingYield(strikeDate,coup,schedule,freq,df_grid.loc[future,'CTDFwdPrice'])
        
        df_grid.loc[future,'CTDImpPrice'] = (df_grid.loc[future,'CTDFwdPrice'] + carry)*discount  
        df_grid.loc[future,'CTDImpYld'] = yd.pricingYield(d,coup,schedule,freq,df_grid.loc[future,'CTDImpPrice'])
    return df_grid.astype(float).round(4),cf

