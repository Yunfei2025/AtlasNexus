"""
Created on Wed Jul  5 13:59:25 2023

Refactor: OOP structure with performance improvements for curve reference refreshing
@author: 马云飞
"""

import argparse
import os
import sys
import pickle
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, date
from multiprocessing import Pool
from typing import Dict, Any, Tuple, List, Optional, cast
import logging

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.loader import loadInstrumentDefinition, loadStatData, loadRefData
from curves.utils.retrieve import retrieveEnvRT
from settings.paths import DIR_INPUT
from settings.general import GeneralConfig, DateConfig
from settings.fixed_income import BondConfig
from curves.calibration.stat import statAdjust
from curves.utils.plot import plotCurve
from curves.calibration.selector import RefBondSelector, compute_spot_term_panels

# logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)

# --- Worker globals for multiprocessing (reduces pickling overhead on Windows) ---
_WORKER_ENV_DEF: Optional[pd.DataFrame] = None
_WORKER_CURVE: Any = None


def _init_worker(env_def, curve):
    global _WORKER_ENV_DEF, _WORKER_CURVE
    _WORKER_ENV_DEF = env_def
    _WORKER_CURVE = curve


def _price_bucket(bucket):
    if _WORKER_ENV_DEF is None or _WORKER_CURVE is None:
        raise RuntimeError("Pricing worker is not initialized")
    return _WORKER_CURVE.affinePricing(_WORKER_ENV_DEF, bucket)


class BondCurveRefresher:
    """Refresh curve prices in an object-oriented, performant way."""

    def __init__(self, bond_type: str, max_workers: Optional[int] = None, min_maturity: float = BondConfig.PRICING_MIN_TTM, max_maturity: float = BondConfig.PRICING_MAX_TTM):
        self.bond_type = bond_type
        self.max_workers = max_workers if max_workers is not None else GeneralConfig.N_CORE
        self.min_maturity = min_maturity
        self.max_maturity = max_maturity
        self.curve: Any = None
        self.env: Optional[Dict[str, Any]] = None
        self.stat: Optional[Dict[str, Any]] = None
        self.ref: Optional[Dict[str, Any]] = None
        self.bond_ref_df: Optional[pd.DataFrame] = None
        self.env_quo: Optional[pd.Index] = None

    # ---- IO / Loading ----
    def load_curve_and_env(self) -> Tuple[Any, Dict[str, Any]]:
        curve_file_path = os.path.join(DIR_INPUT, f'{self.bond_type}-cvrt.obj')
        try:
            
            with open(curve_file_path, 'rb') as file:
                curve = pd.read_pickle(file)
            env = loadInstrumentDefinition(self.bond_type)
            self.curve = curve
            self.env = env
            return curve, env
        except FileNotFoundError:
            logger.error(f"Curve file not found: {curve_file_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading curve/env: {e}")
            raise

    def refresh_market_data(self, calc_date: date) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        try:
            if self.env is None:
                raise ValueError("Environment must be loaded before refresh")
            env = cast(Dict[str, Any], retrieveEnvRT(self.env, self.bond_type))
            stat = cast(Dict[str, Any], loadStatData(self.bond_type))
            ref = cast(Dict[str, Any], loadRefData(self.bond_type))
            ref = self._refresh_missing_reference_bonds(env, ref, calc_date)
            # Use compute_spot_term_panels for single date computation
            price_range = [calc_date, calc_date]
            self.bond_ref_df = cast(
                pd.DataFrame,
                compute_spot_term_panels(env, price_range, ref['RefBond'], self.bond_type, 'inst', update=False),
            )
            self.env, self.stat, self.ref = env, stat, ref
            return env, stat, ref
        except Exception as e:
            logger.error(f"Error refreshing market data: {e}")
            raise

    def _refresh_missing_reference_bonds(self, env: Dict[str, Any], ref: Dict[str, Any], calc_date: date) -> Dict[str, Any]:
        """Refresh today's `RefBond` row if it points to bonds absent from the live universe."""
        ref_bond = ref.get('RefBond')
        if not isinstance(ref_bond, pd.DataFrame) or ref_bond.empty:
            selector = RefBondSelector()
            updated_ref_bond = selector.select_reference_bonds(
                env, [calc_date, calc_date], self.bond_type, daily=True, update=True
            )
            ref['RefBond'] = updated_ref_bond
            return ref

        if calc_date in ref_bond.index:
            ref_today = ref_bond.loc[calc_date]
        else:
            ref_today = ref_bond.iloc[-1]

        ref_ids = [bond_id for bond_id in ref_today.values if pd.notna(bond_id)]
        missing_ids = [bond_id for bond_id in ref_ids if bond_id not in env['Def'].index]
        if not missing_ids:
            return ref

        logger.warning(
            "Refreshing today's RefBond selection because these saved reference bonds are absent from live Def: %s",
            ", ".join(map(str, missing_ids)),
        )
        selector = RefBondSelector()
        updated_ref_bond = selector.select_reference_bonds(
            env, [calc_date, calc_date], self.bond_type, daily=True, update=True
        )
        ref['RefBond'] = updated_ref_bond
        return ref

    def compute_quoted_bonds(self) -> pd.Index:
        if self.env is None or self.curve is None:
            raise ValueError("Curve and environment must be loaded before computing quoted bonds")
        # ensure 剩余期限 exists or derive it
        if '剩余期限' not in self.env['Def'].columns:
            if '到期日期' in self.env['Def'].columns:
                # Convert curve.day to Timestamp to match the 到期日期 column type
                curve_day_ts = pd.Timestamp(self.curve.day).date()
                mat = self.env['Def']['到期日期'] - curve_day_ts
                self.env['Def']['剩余期限'] = [ d.days / 365 for d in mat ]
        filt = (self.env['Def']['剩余期限'] > self.min_maturity) & (self.env['Def']['剩余期限'] < self.max_maturity)
        bonds = self.env['Def'][filt].index
        self.env_quo = bonds
        return bonds

    @staticmethod
    def _make_buckets(index_like: pd.Index, worker_count: int) -> List[pd.Index]:
        if len(index_like) == 0:
            return []
        m = int(np.ceil(len(index_like) / worker_count))
        buckets = [index_like[m * i:m * (i + 1)] for i in range(worker_count)]
        return [b for b in buckets if len(b) > 0]

    # ---- Reference-point staleness filter ----
    def _stale_reference_info(self, side: str, max_spread_bp: float) -> Dict[Any, Tuple[float, str]]:
        """Identify reference bonds whose live quote on `side` is stale.

        A bond is flagged stale when:
          - It is missing from BondRT, OR
          - Its `side` YTM equals the CNBD valuation (fallback fired in
            curves/utils/retrieve._normalize_bondrt_frame), OR
          - Both bid and ofr are present and their spread > max_spread_bp.

        Returns {bond_id: (ttm, reason)}.
        """
        info: Dict[Any, Tuple[float, str]] = {}
        if self.env is None or self.ref is None or self.curve is None:
            return info
        bond_rt = self.env.get('BondRT')
        if bond_rt is None:
            return info
        if 'RefBond' not in self.ref or len(self.ref['RefBond']) == 0:
            return info
        df_def = self.env.get('Def', pd.DataFrame())
        if '剩余期限' not in df_def.columns or '估价收益率:%(中债)' not in df_def.columns:
            return info

        bond_ref_today = self.ref['RefBond'].iloc[-1]
        bid_col, ofr_col = '买价收益率', '卖价收益率'
        eps = 1e-6  # YTM equality tolerance (in %)

        for bond_id in bond_ref_today.values:
            if pd.isna(bond_id) or bond_id not in df_def.index:
                continue
            ttm = float(df_def.loc[bond_id, '剩余期限'])
            cnbd = pd.to_numeric(df_def.loc[bond_id, '估价收益率:%(中债)'], errors='coerce')

            reason: Optional[str] = None
            if bond_id not in bond_rt.index:
                reason = "absent from BondRT"
            else:
                row = bond_rt.loc[bond_id]
                bid_ytm = pd.to_numeric(row.get(bid_col), errors='coerce')
                ofr_ytm = pd.to_numeric(row.get(ofr_col), errors='coerce')
                side_ytm = bid_ytm if side == 'Bid' else ofr_ytm

                if pd.isna(side_ytm):
                    reason = f"no live {side}"
                elif pd.notna(cnbd) and abs(float(side_ytm) - float(cnbd)) < eps:
                    reason = f"{side}=CNBD (stale)"
                elif pd.notna(bid_ytm) and pd.notna(ofr_ytm):
                    spread_bp = abs(float(ofr_ytm) - float(bid_ytm)) * 100.0
                    if spread_bp > max_spread_bp:
                        reason = f"wide spread {spread_bp:.1f}bp"

            if reason is not None:
                info[bond_id] = (ttm, reason)
        return info

    def _drop_stale_refs(self, ref_series: pd.Series, side: str) -> pd.Series:
        """Drop stale reference points from `ref_series` (indexed by TTM)."""
        info = self._stale_reference_info(side, BondConfig.REF_BID_OFR_MAX_BP)
        if not info:
            return ref_series
        stale_ttms = np.array([t for (t, _) in info.values()], dtype=float)
        ref_ttms = ref_series.index.values.astype(float)
        # match each ref-point TTM to a stale-bond TTM within ~2 days
        tol = 2.0 / 365.0
        keep = np.array([not np.any(np.abs(stale_ttms - t) < tol) for t in ref_ttms])
        n_dropped = int((~keep).sum())
        if n_dropped == 0:
            return ref_series
        if (keep.sum()) < 4:
            logger.warning(
                f"{side} stale filter would leave <4 points "
                f"({int(keep.sum())} kept of {len(ref_ttms)}); skipping filter."
            )
            return ref_series
        logger.info(
            f"{side} dropped {n_dropped} stale ref point(s): "
            + "; ".join(f"τ={t:.2f}y {b} ({r})" for b, (t, r) in info.items())
        )
        return ref_series[keep]

    # ---- Pricing ----
    def _price_one_side(self, price_type: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        logger.info(f"Processing {price_type} curve...")
        # update curve factors for the side; sanitize NaNs

        if self.bond_ref_df is None or self.curve is None or self.env is None or self.env_quo is None:
            raise ValueError("Pricing inputs are not initialized")

        ref_series = self.bond_ref_df[price_type].dropna()
        # Mirror the generator: keep reference points within the FIT TTM band
        # (decoupled from PRICING window — includes <1.5y points for short-end stability,
        # skips only the last few weeks before maturity where price→YTM noise blows up).
        _ttm_idx = pd.to_numeric(pd.Series(ref_series.index), errors='coerce')
        _fit_mask = (_ttm_idx >= BondConfig.FIT_MIN_TTM) & (_ttm_idx <= BondConfig.FIT_MAX_TTM)
        if int(_fit_mask.sum()) >= 3:
            ref_series = ref_series.loc[_fit_mask.to_numpy(dtype=bool)]
        # Drop reference points whose live quote is stale (no live data, side fell
        # back to CNBD valuation, or bid-ofr spread > REF_BID_OFR_MAX_BP).
        ref_series = self._drop_stale_refs(ref_series, price_type)
        self.curve.extractFactorsRobust(ref_series, self.curve.reference, k_mad=2.0, min_points=4)
        
        # build buckets
        total = len(self.env_quo)
        if total == 0:
            return pd.DataFrame(), pd.DataFrame(), self.curve.fitting()
        
        worker_count = max(1, min(self.max_workers, total))
        buckets = self._make_buckets(self.env_quo, worker_count)
        
        # small tasks: use sequential to avoid overhead
        if total <= 500 or worker_count == 1 or len(buckets) <= 1:
            dict_p = [self.curve.affinePricing(self.env['Def'], b) for b in buckets]
        else:
            try:
                with Pool(processes=min(worker_count, len(buckets)), initializer=_init_worker, initargs=(self.env['Def'], self.curve)) as pool:
                    dict_p = pool.map(_price_bucket, buckets)
            except Exception as e:
                logger.warning(f"Parallel pricing failed ({e}), falling back to sequential")
                dict_p = [self.curve.affinePricing(self.env['Def'], b) for b in buckets]

        # merge results
        dict_quote = {i: dict_p[i][0] for i in range(len(dict_p))}
        dict_sen = {i: dict_p[i][1] for i in range(len(dict_p))}
        quote_df = pd.concat(dict_quote).droplevel(0).sort_index()
        sen_df = pd.concat(dict_sen).droplevel(0).sort_index()

        # ensure numeric and clean
        quote_df = quote_df.apply(pd.to_numeric, errors='coerce').dropna()
        sen_df = sen_df.apply(pd.to_numeric, errors='coerce').dropna()

        logger.info(f"Finished computing {price_type} curve at: {datetime.now().strftime('%H:%M:%S')}")
        return quote_df, sen_df, self.curve.fitting()

    # ---- Orchestration ----
    def run(self) -> Dict[str, Any]:
        # calculation date
        d = DateConfig.get_date_mappings()['d']
        logger.info(f"Refresh Market Data for {self.bond_type} at: {d.strftime('%H:%M:%S')}")
        calc_date = d.date()

        # load and refresh
        self.load_curve_and_env()
        env, stat, ref = self.refresh_market_data(calc_date)
        # bond ref and set members

        # self.bond_ref_df = pd.Series(spoti.values, index=termi.values) #create_bond_reference(spoti, termi)
        self.compute_quoted_bonds()

        # price both sides
        quotedict: Dict[str, pd.DataFrame] = {}
        sendict: Dict[str, pd.DataFrame] = {}
        curvedict: Dict[str, pd.DataFrame] = {}
        
        for side in ['Bid', 'Ofr']:
            q, s, cfit = self._price_one_side(side)
            quotedict[side] = q
            sendict[side] = s
            curvedict[side] = cfit

        if self.bond_ref_df is None:
            raise ValueError("Bond reference data is not initialized")

        sen = (sendict.get('Bid', pd.DataFrame()) + sendict.get('Ofr', pd.DataFrame())) / 2
        refspot_avg = self.bond_ref_df[['Bid', 'Ofr']].mean(axis=1, skipna=True).to_frame()
        pxrt = {
            'Curve': (curvedict['Bid'] + curvedict['Ofr']) / 2,
            'RefSpot': refspot_avg,
            'Quote': statAdjust(quotedict, env, stat['BondCurve']),
            'Sen': sen
        }

        # plot and save
        figure = plotCurve(self.bond_type, pxrt)
        self._save_results(self.curve, pxrt, self.bond_type, figure)

        logger.info(f"Finished refreshing {self.bond_type} Curve at: {datetime.now().strftime('%H:%M:%S')}")
        return pxrt

    @classmethod
    def main(cls, bond_type='CBond', max_workers: Optional[int] = None):
        """Main entry point for the BondCurveRefresher"""
        try:
            instance = cls(bond_type=bond_type, max_workers=max_workers)
            instance.run()
        except Exception as e:
            logger.error(f"Error in main execution: {e}")
            raise

    @staticmethod
    def _save_results(curve: Any, pxrt: Dict[str, Any], btype: str, figure: Any) -> None:
        try:
            with open(os.path.join(DIR_INPUT, f'{btype}-cvrt.obj'), 'wb') as f:
                pickle.dump(curve, f)
            with open(os.path.join(DIR_INPUT, f'{btype}-fig.obj'), 'wb') as f:
                pickle.dump(figure, f)
            with open(os.path.join(DIR_INPUT, f'{btype}-rtquo.pkl'), 'wb') as f:
                pickle.dump(pxrt, f)
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            raise

def main(bond_type='TBond', max_workers: Optional[int] = None):
    try:
        BondCurveRefresher.main(bond_type=bond_type, max_workers=max_workers)
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        sys.exit(1)
#%%
if __name__ == '__main__':
    main()
