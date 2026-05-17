#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fixed income related configuration: bonds and IRS.
"""
import datetime
from typing import Dict, List
from dateutil.relativedelta import relativedelta


class BondConfig:
    TBOND_POOL_START = 5
    OBOND_POOL_START = 3
    SECTOR_MAP = {
        "TBond": "a101010101000000",
        "CBond": "a101010104000000",
        "LBond": "a101010102000000",
        "IDepo": "a101010103000000",
        "BCorp": "a10101010c000000",
        "BBond": "a101010106000000",
        "MNote": "a10101010e000000",
        "CP": "a10101010d000000",
        "SCP": "1000009011000000",
        "GBond": "1000006220000000",
    }
    BOND_MAP = {
        "TBond": "Treasury Bond",
        "CBond": "PolicyBank Bond",
        "LBond": "Local Treasury Bond",
        "IDepo": "Interbank Cash Deposit",
        "BCorp": "Corporate Bond",
        "BBond": "CommercialBank Bond",
        "MNote": "Medium Term Note",
        "CP": "Commercial Paper",
        "GBond": "Government-backed Bond",
        "SCP": "Super Short-term Commercial Paper",
    }
    EXCLUDE_KEYWORDS = [
        '抗疫', '战疫', '柜台', '置换', '美元', '定向',
        '土地储备', '棚户区改造', '二级资本', '债券通', '注资','上海清算所',
        '绿债', '增发', '增', '续', '新疆', '西藏', '甘肃', '青海',
        '专项', '再融资', 'CD'
    ]
    INCLUDE_FILTERS = {
        'LBond': ['广东', '山东', '浙江', '河南', '江苏', '北京', '上海'],
        'BBond': [
            '工商银行', '农业银行', '中国银行', '建设银行', '招商银行',
            '中信银行', '兴业银行', '浦发银行', '平安银行',
            '华夏银行', '光大银行'
        ],
        'GBond': ['汇金', '铁道'],
        'MNote': [
            '汇金', '中电投', '南电', '长电', '电网', '中车集',
            '中石油', '铁道'
        ],
    }
    SPREAD_MAP = {
        'TBondCurve': 'Treasury Bond 3+Model-Curve',
        'CBondCurve': 'Policybank Bond 3+Model-Curve',
        "LBondSpread": "Local Treasury Bond Spread",
        "BBondSpread": "CommercialBank Bond Spread",
        "MNoteSpread": "Medium Term Note Spread",
        'TBondSwap': 'Treasury Bond Repo7d-Swap',
        'CBondSwap': 'Policybank Bond Repo7d-Swap',
        'SwapSpread': 'Swaps',
        'AssetPCASpread': 'Multi-asset PCA',
        'SectorPCASpread': 'Sector PCA',
        'NetBasis': 'Net Basis of Futures Contract and Deliverable Bond',
        'TermBasis': 'Term Basis between Futures Contracts',
        'BinarySpread': 'Spread Regression',
        'InsPos': 'Institution'
    }
    COLUMNS_EN = [
        'NAME', 'FULLNAME', 'SEC_TYPE', 'OUTSTANDINGBALANCE', 'CARRYDATE','MATURITYDATE',
        'TERM',  'PTMYEAR', 'MODIDURA_CNBD', 'INTERESTTYPE', 'COUPONRATE','INTERESTFREQUENCY', 'CLAUSE',
        'DIRTYPRICE', 'CLEANPRICE', 'YTM_B','YIELD_CNBD',
        'VOLUME', 'RT_BID_PRICE1YTM', 'RT_ASK_PRICE1YTM',
        'RT_BID1', 'RT_ASK1', 'Bid', 'Ofr', 'RT_LAST_YTM', 'RT_TIME', 'CLOSE'
    ]
    COLUMNS_CN = [
        '简称', '证券全称', '类别', '债券余额:亿', '起息日期', '到期日期',
        '期限', '剩余期限', '修正久期', '利率类型', '票面利率:%', '每年付息次数', '特殊条款',
        '收盘价:元（全价）', '收盘价:元（净价）', '收盘收益率(%)', '估价收益率:%(中债)',
        '成交量', '买价收益率', '卖价收益率', '买价收益率', '卖价收益率',
        '买价收益率', '卖价收益率', '成交收益率', '时间', '收盘价'
    ]
    TERM_BUCKETS = {
        0.3: [0.1, 0.4], 0.5: [0.4, 0.6], 0.7: [0.6, 0.9],
        1: [0.9, 1.2], 1.5: [1.2, 1.6], 2: [1.6, 2.0],
        3: [2.0, 3.0], 5: [4.0, 5.0], 10: [8.0, 10.0]
    }
    PX = ['Bid', 'Ofr']
    BORROW_COST = {
        5: 10, 10: 40, 20: 100, 30: 120, 
    } # annual cost in bp
    @classmethod
    def get_column_mapping(cls) -> Dict[str, str]:
        return dict(zip(cls.COLUMNS_EN, cls.COLUMNS_CN))

    @classmethod
    def get_spread_units(cls) -> Dict[str, str]:
        units = {}
        for k in cls.SPREAD_MAP.keys():
            if k == 'InsPos':
                units[k] = "Volume, 1e8"
            elif k in ['NetBasis', 'TermBasis']:
                units[k] = "Basis, cent"
            else:
                units[k] = "Spread, bp"
        return units


class SpreadConfig:
    """Spread mapping configuration and labels."""
    @classmethod
    def build_ospreado(cls) -> List[str]:
        return [b + 'Spread' for b in BondConfig.INCLUDE_FILTERS.keys()]

    @classmethod
    def build_spreadmap(cls) -> Dict[str, str]:
        m = {}
        for k in BondConfig.INCLUDE_FILTERS.keys():
            m[k + 'Spread'] = BondConfig.BOND_MAP[k] + ' Spread'
        return m

    @classmethod
    def build_spdmap(cls) -> Dict[str, Dict[str, str]]:
        spdmap = {}
        r7d = ['FR007S1Y.IR', 'FR007S2Y.IR', 'FR007S3Y.IR', 'FR007S4Y.IR', 'FR007S5Y.IR']
        s3m = ['SHI3MS1Y.IR', 'SHI3MS2Y.IR', 'SHI3MS3Y.IR', 'SHI3MS4Y.IR', 'SHI3MS5Y.IR']
        cgb = ['中债国债到期收益率:1年', '中债国债到期收益率:2年', '中债国债到期收益率:3年', '中债国债到期收益率:4年', '中债国债到期收益率:5年']
        spdmap['r7d'] = dict(zip(r7d, cgb))
        spdmap['s3m'] = dict(zip(s3m, cgb))
        cgb_extended = [
            '中债国债到期收益率:1年', '中债国债到期收益率:2年', '中债国债到期收益率:3年', '中债国债到期收益率:4年', '中债国债到期收益率:5年',
            '中债国债到期收益率:7年', '中债国债到期收益率:10年', '中债国债到期收益率:20年', '中债国债到期收益率:30年'
        ]
        cdb = [
            '中债国开债到期收益率:1年', '中债国开债到期收益率:2年', '中债国开债到期收益率:3年', '中债国开债到期收益率:4年', '中债国开债到期收益率:5年',
            '中债国开债到期收益率:7年', '中债国开债到期收益率:10年', '中债国开债到期收益率:20年', '中债国开债到期收益率:30年'
        ]
        spdmap['CDB'] = dict(zip(cdb, cgb_extended))
        return spdmap

class IRSConfig:
    TERM_MAP = {
        '7d': 7/90, '1m': 1/3, '3m': 1, '6m': 2, '9m': 3, '1y': 4, '2y': 8, '3y': 12,
        '4y': 16, '5y': 20, '7y': 28, '10y': 40
    }
    IRS_LIST = [
        'FR007S1M.IR',
        'FR007S3M.IR', 'FR007S6M.IR', 'FR007S9M.IR', 'FR007S1Y.IR',
        'FR007S2Y.IR', 'FR007S3Y.IR', 'FR007S4Y.IR', 'FR007S5Y.IR',
        'FR007S7Y.IR', 'FR007S10Y.IR',
        'SHI3MS6M.IR', 'SHI3MS9M.IR', 'SHI3MS1Y.IR',
        'SHI3MS2Y.IR', 'SHI3MS3Y.IR', 'SHI3MS4Y.IR', 'SHI3MS5Y.IR',
        'SHI3MS7Y.IR', 'SHI3MS10Y.IR'
    ]
    FIXING_LIST = ['FR001.IR', 'FR007.IR', 'SHIBOR3M.IR']
    R7D_LIST = {
        'FR007.IR': 7/365,
        'FR007S1Y.IR': 1,
        'FR007S2Y.IR': 2,
        'FR007S5Y.IR': 5,
        'FR007S10Y.IR': 10
    }
    S3M_LIST = {
        'SHIBOR3M.IR': 1/4,
        'SHI3MS1Y.IR': 1,
        'SHI3MS2Y.IR': 2,
        'SHI3MS5Y.IR': 5,
        'SHI3MS10Y.IR': 10
    }
    CURVE_TYPES = ['r7d', 's3m']
    TENOR_MAP = {
        7/365: "7d", 1/4: "1s", 1/2: "2s", 3/4: "3s",
        1: "4s", 2: "8s", 3: "12s", 4: "16s", 5: "20s", 7: "28s", 10: "40s"
    }
    PAIRS = ['Repo-3m6m', 'Repo-6m9m', 'Repo-9m1y', 'Repo-1y2y', 'Repo-2y3y', 'Repo-3y4y', 'Repo-4y5y',
             'Repo-3m9m', 'Repo-6m1y', 'Repo-9m2y', 'Repo-1y3y', 'Repo-2y4y', 'Repo-3y5y',
             'Repo-3m1y', 'Repo-6m2y', 'Repo-9m3y', 'Repo-1y4y', 'Repo-2y5y',
             'Repo-3m2y', 'Repo-6m3y', 'Repo-9m4y', 'Repo-1y5y',
             'Shi3M-6m9m', 'Shi3M-9m1y', 'Shi3M-1y2y', 'Shi3M-2y3y', 'Shi3M-3y4y', 'Shi3M-4y5y',
             'Shi3M-6m1y', 'Shi3M-9m2y', 'Shi3M-1y3y', 'Shi3M-2y4y', 'Shi3M-3y5y',
             'Shi3M-6m2y', 'Shi3M-9m3y', 'Shi3M-1y4y', 'Shi3M-2y5y',
             'Shi3M-6m3y', 'Shi3M-9m4y', 'Shi3M-1y5y']
    BOX = ['Basis-6m9m', 'Basis-9m1y', 'Basis-1y2y', 'Basis-2y3y', 'Basis-3y4y', 'Basis-4y5y',
           'Basis-6m1y', 'Basis-9m2y', 'Basis-1y3y', 'Basis-2y4y', 'Basis-3y5y',
           'Basis-6m2y', 'Basis-9m3y', 'Basis-1y4y', 'Basis-2y5y',
           'Basis-6m3y', 'Basis-9m4y', 'Basis-1y5y']
    CARRY_LIST = ['Value(bp)', 'Carry(3m,bp)', 'Carry(6m,bp)', 'Carry(1y,bp)', 'Roll(3m,bp)', 'Roll(6m,bp)', 'Roll(1y,bp)']
    YSMAP = {7/365: "7d", 1/4: "1s", 1/2: "2s", 3/4: "3s", 1: "4s", 2: "8s", 3: "12s", 4: "16s", 5: "20s", 7: "28s", 10: "40s"}

    @classmethod
    def get_irs_ref(cls) -> Dict[str, List[str]]:
        return {'r7d': list(cls.R7D_LIST.keys()), 's3m': list(cls.S3M_LIST.keys())}

    @classmethod
    def get_ylist(cls) -> Dict[str, List[float]]:
        return {'r7d': list(cls.R7D_LIST.values()), 's3m': list(cls.S3M_LIST.values())}

    @classmethod
    def get_slist(cls) -> Dict[str, List[str]]:
        ylist = cls.get_ylist()
        return {c: [cls.YSMAP[i] for i in ylist[c]] for c in cls.CURVE_TYPES}

    @classmethod
    def get_irs_terms(cls) -> Dict[str, relativedelta]:
        return {
            'FR007.IR': relativedelta(days=7),
            'FR007S1M.IR': relativedelta(months=1),
            'FR007S3M.IR': relativedelta(months=3),
            'FR007S6M.IR': relativedelta(months=6),
            'FR007S9M.IR': relativedelta(months=9),
            'FR007S1Y.IR': relativedelta(years=1),
            'FR007S2Y.IR': relativedelta(years=2),
            'FR007S3Y.IR': relativedelta(years=3),
            'FR007S4Y.IR': relativedelta(years=4),
            'FR007S5Y.IR': relativedelta(years=5),
            'FR007S7Y.IR': relativedelta(years=7),
            'FR007S10Y.IR': relativedelta(years=10),
            'SHIBOR3M.IR': relativedelta(months=3),
            'SHI3MS6M.IR': relativedelta(months=6),
            'SHI3MS9M.IR': relativedelta(months=9),
            'SHI3MS1Y.IR': relativedelta(years=1),
            'SHI3MS2Y.IR': relativedelta(years=2),
            'SHI3MS3Y.IR': relativedelta(years=3),
            'SHI3MS4Y.IR': relativedelta(years=4),
            'SHI3MS5Y.IR': relativedelta(years=5),
            'SHI3MS7Y.IR': relativedelta(years=7),
            'SHI3MS10Y.IR': relativedelta(years=10),
        }


class InstitutionConfig:
    INSTITUTION_TYPES = [
        '基金公司及产品', '证券公司', '保险公司', '大型商业银行/政策性银行',
        '股份制商业银行', '外资银行', '城市商业银行', '农村金融机构',
        '货币市场基金', '理财子公司及理财类产品'
    ]
    BOND_TYPES = [
        '国债-新债', '国债-老债', '政策性金融债-新债', '政策性金融债-老债',
        '地方政府债', '同业存单', '短期/超短期融资券', '中期票据',
        '企业债', '资产支持证券'
    ]
    TERM_BUCKETS = [
        '≦1Y', '1-3Y', '3-5Y', '5-7Y', '7-10Y', '10-15Y',
        '15-20Y', '20-30Y', '>30Y', '合计'
    ]
