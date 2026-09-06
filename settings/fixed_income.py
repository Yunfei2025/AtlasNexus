#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fixed income related configuration: bonds and IRS.
"""
import datetime
from typing import Dict, List
from dateutil.relativedelta import relativedelta


# ── Factor model transaction cost ─────────────────────────────────────────────
# Flat notional-based bid-ask cost applied to every factor uniformly.
# Units: basis points of notional per side (0.3 bp = 0.00003).
# Rationale: Chinese treasury futures (T/TF/TS) spread ≈ 0.2–0.4 bp; cash bonds
# slightly wider.  Using a single notional-based cost avoids duration-scaling
# complexity while being conservative enough for a 10B CNY beta book.
FACTOR_TX_COST_BP: float = 0.3


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
        '抗疫', '战疫', '柜台', '置换', '美元','定向','清发',
        '土地储备', '棚户区改造', '二级资本', '债券通', '注资','上海清算所',
        '绿债', '绿色', '增发', '增', '续', '新疆', '西藏', '甘肃', '青海',
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
        'TenorSpread': 'Curve & Cross-Asset Spreads',
        'BondNewIssue': 'New-Issue OTR/OFR Event',
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
        1: [0.9, 1.2], 1.5: [1.2, 1.6], 2: [1.6, 2.5],
        3: [2.5, 3.5], 5: [4.0, 6.0], 
        10: [8.5, 10.0],
    }
    PX = ['Bid', 'Ofr']
    BORROW_COST = {
        5: 10, 10: 40,
    } # annual cost in bp
    # Curve pricing filter (years). Bonds outside this TTM band are excluded
    PRICING_MIN_TTM = 1.0
    PRICING_MAX_TTM = 10.0
    # Calibration fit window (years) — decoupled from the pricing window.
    # Reference points in [FIT_MIN_TTM, FIT_MAX_TTM] are used to extract the
    # 3-factor affine factors. Including <1.5y points stabilizes the short end
    # (important for bootstrapping); FIT_MIN_TTM=0.25 still skips the last few
    # weeks before maturity where YTM is most price-sensitive.
    #
    # DO NOT raise this to exclude the sub-1y buckets. That was tried on
    # 2026-09-05 (FIT_MIN_TTM=0.9) to remove an apparent sub-1y inversion and
    # it CAUSED a much worse one. In Model A the loadings are B -> [1, 1, 0]
    # as tau -> 0, i.e. y(0+) -> L + S: the sub-1y reference points are the
    # only observations that pin the L + S combination (the short-rate
    # asymptote). Drop them and L + S is set purely by extrapolating the
    # 1y-10y fit, which on 2026-09-04 CBond data put the asymptote at 1.4786
    # while the 1y market spot was 1.3748 -- the fitted curve then had to fall
    # ~10bp from tau=0 down to 1y, manufacturing an inversion that is not in
    # the bootstrapped data (which rises monotonically 1.2955 -> 1.7444).
    # Measured short-end fit error, CBond 2026-09-04:
    #     FIT_MIN_TTM=0.9 : +13.7bp @0.34y, +6.3bp @0.49y, +7.2bp @0.73y
    #     FIT_MIN_TTM=0.25: +3.5bp @0.34y, -1.9bp @0.49y, +1.5bp @0.73y
    # The convexity term a(tau) is NOT implicated (|a| < 0.004 below 1y), and
    # S2 converges in ~5 iterations either way.
    FIT_MIN_TTM = 0.25
    FIT_MAX_TTM = 10.0
    # Least-squares weight applied to reference points at or below
    # FIT_SHORT_TTM when extracting the 3 affine factors. The goal is to fit
    # the >1y points (where pricing and RV actually happen) as tightly as
    # possible, while still keeping the sub-1y points in the fit so they pin
    # the L + S short-rate asymptote and prevent the spurious front-end
    # inversion documented on FIT_MIN_TTM above.
    #
    # Calibrated 2026-09-05 by leave-one-out CV scored ONLY on >1y points,
    # over each curve's full history (TBond 961d / CBond 717d), holding the
    # held-out set identical across policies:
    #     weight   TBond >1y LOO   CBond >1y LOO
    #      1.00      14.88bp          9.40bp
    #      0.50      13.78bp          9.50bp
    #      0.25      13.04bp          9.54bp   <- TBond best (-12%)
    #      0.00      21.82bp         10.27bp   <- dropping <1y is much WORSE
    # Fully excluding the short end is the worst option for BOTH curves: with
    # only ~5 surviving points a 3-factor fit is under-determined, and the
    # unpinned asymptote drags the long end too. TBond gains materially from
    # downweighting (consistent in 3 of 4 calendar years); CBond is flat to
    # marginally worse, so it stays at 1.0 (no change to current behaviour).
    # Do NOT go below ~0.25: at w<=0.1 the front-end inversion reappears.
    FIT_SHORT_TTM = 1.0
    FIT_SHORT_WEIGHT = {'TBond': 0.25, 'CBond': 1.0}
    # Reference-point staleness filter (applied in the realtime refresher
    # before fitting). A bond is treated as stale and dropped if:
    #   - It is missing from BondRT, OR
    #   - Its live BID/OFR YTM equals the CNBD valuation (= fallback fired),
    #     i.e. no real quote on that side, OR
    #   - The bid-offer YTM spread exceeds REF_BID_OFR_MAX_BP.
    REF_BID_OFR_MAX_BP = 15.0
    # EWMA blend weight for the realtime curve refit (weight on the NEW fit;
    # 1-alpha stays on the previously-fitted factors). Each intraday refresh
    # re-fits the 3-factor (level/slope/curvature) affine curve from scratch
    # with no memory of the prior fit, so a reference point flipping across
    # the MAD-outlier or REF_BID_OFR_MAX_BP gate between refreshes can rotate
    # the whole curve and swing an unrelated bond's fitted yield by several bp.
    # alpha=0.5 damps that discrete refresh-to-refresh jump while still
    # tracking genuine intraday yield moves within one refresh.
    RT_FACTOR_EWM_ALPHA = 0.5
    # Coupon-vintage adjustment for reference-bond yields before bootstrapping
    # (affine plan F13 / item 1.7). TBond's 1-3Y reference set mixes
    # high-coupon 2022/2023 vintages (2.4-2.6%) with low-coupon 2025/2026
    # issues (1.3-1.5%); fit residuals correlate +0.80 with coupon there, at
    # ~6.6bp per 1% of coupon, which the 3-factor affine curve cannot
    # represent. Fitting spot panels on de-couponed yields (with S2 and the
    # stored history rebuilt on the SAME convention -- a mixed
    # adjusted-anchors/unadjusted-history state is worse than either) cut
    # TBond 1-10Y anchor-fit RMSE from 3.94 to 1.88bp.
    #
    # Enabled PER ASSET CLASS, because the effect is CGB-specific. Fitting
    # beta over the full 961-day history:
    #   TBond 2024 -0.029(sd .051) | 2025 -0.055(sd .077) | 2026 -0.086(sd .017, negative 99% of days)
    #   CBond 2024 +0.001(sd .011) | 2025 +0.004(sd .073) | 2026 +0.008(sd .013)
    # CDB shows no coupon effect despite comparable coupon dispersion
    # (1.44-2.73% today), matching the documented CGB-specific tax/liquidity
    # vintage story -- so enabling it there would only add noise. Beta is
    # exactly 0 in 2022 for both (coupons were homogeneous then), so the
    # adjustment is self-disabling over that history.
    #
    # DISABLED FOR TBOND as of 2026-09-06: the validation above only covered
    # 2024-2026, where beta is small and stable. Backtesting 2023-03..2024-03
    # found TBond beta swings to mean +0.09 to +0.12 (sd up to 0.24, max
    # +0.76, only 33-54% of days negative) through 2023 and Feb-Jun 2024 --
    # the opposite sign and an order of magnitude noisier than the validated
    # range. Applying `ytm - beta*coupon` with beta=+0.53 cut one 2.29%-coupon
    # reference bond's yield by 121bp before bootstrapping, collapsing the
    # fitted spot curve to -1.02% at 10Y against a ~2.4% market (see
    # docs/dev/affine-curve-improvement-plan.md). Re-enable per-window only
    # after beta's stability is re-validated for whatever history is in use.
    APPLY_COUPON_ADJUSTMENT = {'TBond': False, 'CBond': False}
    # signal_variant options for the TBondCurve/CBondCurve spread_type (see
    # docs/dev/tbondcurve-30y-otr-ofr-plan.md). "otr_ofr_rv" is the mature
    # OTR/OFR relative-value pair, distinct from the BondNewIssue event strategy.
    TBOND_CURVE_VARIANTS = {"model_curve", "otr_ofr_rv"}

    @classmethod
    def get_column_mapping(cls) -> Dict[str, str]:
        return dict(zip(cls.COLUMNS_EN, cls.COLUMNS_CN))

    @classmethod
    def get_spread_units(cls) -> Dict[str, str]:
        units = {}
        for k in cls.SPREAD_MAP.keys():
            if k in ['NetBasis', 'TermBasis']:
                units[k] = "Basis, cent"
            else:
                units[k] = "Spread, bp"
        return units


class NewIssueConfig:
    """Config for the BondNewIssue new-issue roll-pressure event strategy.

    Unlike ``otr_ofr_rv`` (a signal_variant under TBondCurve/CBondCurve),
    BondNewIssue is a dedicated event-driven spread type whose instrument is
    role-based (OTR / 1st-OFR / 2nd-OFR) and rebinds at every auction roll.
    Asset distinction is carried by metadata (asset_class, issuer_class,
    tenor_bucket), not by separate spread type names.
    See docs/dev/tbondcurve-30y-otr-ofr-plan.md for the full design.
    """
    ISSUER_CLASS_MAP = {"TBond": "CGB", "CBond": "CDB"}

    # Tenor buckets for OTR/OFR identity selection, keyed by *original* issuance
    # term (BondConfig.COLUMNS_CN '期限'), not remaining maturity. This is
    # intentionally separate from BondConfig.TERM_BUCKETS, which is capped at
    # 10Y for affine curve calibration and must not be extended to cover 30Y.
    TENOR_BUCKETS: Dict[str, List[float]] = {
        "5Y": [4.0, 6.0],
        "10Y": [8.5, 10.0],
        "30Y": [25.0, 30.0],
    }

    # (asset_class, tenor_bucket) pairs the universe builder may construct.
    # Building the universe artifact for a bucket is independent from granting
    # it trading eligibility — see DATA_READY_BUCKETS and the plan's gates.
    ACTIVE_BUCKETS = {
        ("TBond", "5Y"), ("TBond", "10Y"), ("TBond", "30Y"),
        ("CBond", "5Y"), ("CBond", "10Y"), ("CBond", "30Y"),
    }

    # Buckets audited enough for prototype research as of 2026-07-31 (see plan).
    # A pass for one bucket never unlocks any other bucket.
    DATA_READY_BUCKETS = {("TBond", "30Y")}

    # OTR issuance-age entry window (calendar days) for BondNewIssue eligibility.
    ENTRY_AGE_MIN_DAYS = 0
    ENTRY_AGE_MAX_DAYS = 90

    # Depth of the turnover-ranked off-the-run ladder built per bucket: OFR1..OFR{depth}.
    # OFR1 feeds Stage 2 (otr_ofr1) of BondNewIssue; OFR1..OFR{depth} feed mature RV.
    OFR_LADDER_DEPTH = 5

    # A turnover-rank challenger (new OTR or new OFR-k) only replaces the confirmed
    # incumbent once it has held the raw turnover lead for this many consecutive
    # observations — avoids splicing mature-RV/event history across noise-driven
    # rank flips (see docs/dev/tbondcurve-30y-otr-ofr-plan.md "Rank Definitions").
    OTR_RANK_PERSISTENCE_DAYS = 3

    # Minimum turnover-ratio gap (OTR - NIB) required to treat a cohort as having
    # a live NIB->OTR migration lag worth trading (Stage 1 existence-of-lag gate).
    # Units match `_turnover_ratio` (volume / balance, fractional).
    LAG_TURNOVER_GAP_THRESHOLD = 0.01

    @classmethod
    def issuer_class(cls, asset_class: str) -> str:
        return cls.ISSUER_CLASS_MAP.get(asset_class, asset_class)

    @classmethod
    def active_tenor_buckets(cls, asset_class: str) -> List[str]:
        return [tb for (ac, tb) in cls.ACTIVE_BUCKETS if ac == asset_class]

    @classmethod
    def is_data_ready(cls, asset_class: str, tenor_bucket: str) -> bool:
        return (asset_class, tenor_bucket) in cls.DATA_READY_BUCKETS


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
    PAIRS = ['Repo7d-3m6m', 'Repo7d-6m9m', 'Repo7d-9m1y', 'Repo7d-1y2y', 'Repo7d-2y3y', 'Repo7d-3y4y', 'Repo7d-4y5y',
             'Repo7d-3m9m', 'Repo7d-6m1y', 'Repo7d-9m2y', 'Repo7d-1y3y', 'Repo7d-2y4y', 'Repo7d-3y5y',
             'Repo7d-3m1y', 'Repo7d-6m2y', 'Repo7d-9m3y', 'Repo7d-1y4y', 'Repo7d-2y5y',
             'Repo7d-3m2y', 'Repo7d-6m3y', 'Repo7d-9m4y', 'Repo7d-1y5y',
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
