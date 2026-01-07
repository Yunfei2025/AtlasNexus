#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wind/Curve identifiers and helper mappings.
"""

class WindConfig:
    WDINFO = "fullname,sec_type,outstandingbalance,carrydate,maturitydate,term,ptmyear,modidura_cnbd,interesttype,couponrate,interestfrequency,clause,dirtyprice,cleanprice,ytm_b,yield_cnbd,volume"
    DATATYPE = ['Close', 'Volume', 'CBClean', 'CBDirty']
    KEYS = ['yield_cnbd', 'volume', 'cleanprice', 'dirtyprice']
    DATAMAP = dict(zip(DATATYPE, KEYS))

    CDBCVD_IDS = "M1004258,M1004687,M1004259,M1004260,M1004261,M1004262,M1004263,M1004264,M1004265,M1004266,M1004267,M1004268,M1004269,M1004270,M1004688,M1004271,M1004273,M1004274"
    CGBCV_IDS = "M1004136,M1004677,M1004829,S0059741,S0059742,S0059743,S0059744,S0059745,S0059746,M0057946,S0059747,M0057947,S0059748,M1000165,M1004678,S0059749,S0059751,S0059752"
    CPCV_IDS  = "M1010882,M1010883,M1010884,M1010885"

    CDBCVD_LIST = CDBCVD_IDS.split(',')
    CGBCV_LIST = CGBCV_IDS.split(',')
    CPCV_LIST  = CPCV_IDS.split(',')

    CV_LIST = [
        '中债国开债到期收益率:0个月', '中债国开债到期收益率:1个月', '中债国开债到期收益率:2个月', '中债国开债到期收益率:3个月',
        '中债国开债到期收益率:6个月', '中债国开债到期收益率:9个月', '中债国开债到期收益率:1年', '中债国开债到期收益率:2年',
        '中债国开债到期收益率:3年', '中债国开债到期收益率:4年', '中债国开债到期收益率:5年', '中债国开债到期收益率:6年',
        '中债国开债到期收益率:7年', '中债国开债到期收益率:8年', '中债国开债到期收益率:9年', '中债国开债到期收益率:10年',
        '中债国开债到期收益率:20年', '中债国开债到期收益率:30年',
        '中债国债到期收益率:0个月', '中债国债到期收益率:1个月', '中债国债到期收益率:2个月', '中债国债到期收益率:3个月',
        '中债国债到期收益率:6个月', '中债国债到期收益率:9个月', '中债国债到期收益率:1年', '中债国债到期收益率:2年',
        '中债国债到期收益率:3年', '中债国债到期收益率:4年', '中债国债到期收益率:5年', '中债国债到期收益率:6年',
        '中债国债到期收益率:7年', '中债国债到期收益率:8年', '中债国债到期收益率:9年', '中债国债到期收益率:10年',
        '中债国债到期收益率:20年', '中债国债到期收益率:30年',
        '中债商业银行同业存单到期收益率(AAA):3个月', '中债商业银行同业存单到期收益率(AAA):6个月',
        '中债商业银行同业存单到期收益率(AAA):9个月', '中债商业银行同业存单到期收益率(AAA):1年',
    ]

    CV_ID_MAP = dict(zip(CDBCVD_LIST + CGBCV_LIST + CPCV_LIST, CV_LIST))

    KTID = {'CGB': {}, 'CDB': {}, 'ICP': {}}
    for t in ['S0059744', 'S0059745', 'S0059746', 'M0057946', 'S0059747', 'S0059748', 'S0059749', 'S0059751', 'S0059752']:
        KTID['CGB'][t] = CV_ID_MAP[t]
    for t in ['M1004263', 'M1004264', 'M1004265', 'M1004266', 'M1004267', 'M1004269', 'M1004271', 'M1004273', 'M1004274']:
        KTID['CDB'][t] = CV_ID_MAP[t]
    for t in ['M1010882', 'M1010883', 'M1010884', 'M1010885']:
        KTID['ICP'][t] = CV_ID_MAP[t]

    SOFR_STR = "SOFR.IR,SOFR1M.IR,SOFR3M.IR,SOFR6M.IR,SOFR12M.IR"
    FXSWAP   = "USDCNYONCS.IB,USDCNYTNCS.IB,USDCNYSNCS.IB,USDCNYSWCS.IB,USDCNY1MCS.IB,USDCNY3MCS.IB,USDCNY6MCS.IB,USDCNY1YCS.IB"
