# -*- coding: utf-8 -*-
"""
Bond Selector Module - Simplified

This module provides simplified functions for bond selection and yield curve construction.
"""
import os
import time
import pandas as pd
import numpy as np
from datetime import datetime
import warnings

from settings.paths import DIR_INPUT, DIR_DATA
from settings.fixed_income import BondConfig
from settings.general import DateConfig
import curves.affine.bootstrap as bs
import curves.affine.pricingYield as yd
from ..utils.file import updatePKL, loadPKL

warnings.filterwarnings('ignore', category=FutureWarning)


class MissingVolumeDataError(RuntimeError):
    """Raised when turnover/volume data is missing for a required date.

    A domain exception instead of SystemExit so this stays catchable by
    the EOD pipeline's per-step isolation (a failing step is logged and
    skipped, not allowed to kill the host process). See
    docs/dev/affine-curve-improvement-plan.md F12 / item 1.4.
    """


# Configuration
class Config:
    """Global configuration for bond selector."""
    VERBOSE = False
    ENABLE_CACHING = True

# Utility functions
def filter_bonds_by_type(bond_names: pd.Series, bond_type: str) -> pd.Index:
    """Filter bonds by type."""
    if bond_type == 'TBond':
        mask = bond_names.str.contains('国债', na=False)
    elif bond_type == 'CBond':
        mask = bond_names.str.contains('国家开发银行', na=False)
    else:
        return bond_names.index
    return bond_names[mask].index


def filter_bonds_by_term(terms: pd.Series, min_term: float, max_term: float,
                          max_widen: float = 0.25, step: float = 0.005) -> pd.Index:
    """Filter bonds by term range.

    Widens the [min_term, max_term] band symmetrically when empty, capped at
    ``max_widen`` years each side so a bucket can never quietly capture a
    neighbouring bucket's bond. Returns an empty index (with a warning)
    rather than looping forever if no candidate is found within the cap.
    See docs/dev/affine-curve-improvement-plan.md F5 / item 1.3.
    """
    orig_min, orig_max = min_term, max_term
    widen = 0.0
    while widen <= max_widen:
        mask = (terms > min_term - widen) & (terms <= max_term + widen)
        bond_filtered = terms[mask].index
        if len(bond_filtered) > 0:
            return bond_filtered
        widen += step
    warnings.warn(
        f"filter_bonds_by_term: no bonds found for range ({orig_min}, {orig_max}] "
        f"even after symmetric widening by ±{max_widen}y; returning empty index."
    )
    return terms.iloc[0:0].index


def get_most_liquid_bond(turnover: pd.Series) -> str:
    """Select bond with highest turnover."""
    if len(turnover) == 0:
        return np.nan
    return turnover.idxmax() if len(turnover) > 1 else turnover.index[0]


def get_offtherun_bond(turnover: pd.Series, n_exclude: int = 1) -> str:
    """Select first-off-the-run bond by excluding the top n_exclude most liquid.

    For RV trading the on-the-run benchmark must NOT define the calibration
    curve — otherwise the curve chases the benchmark and the on/off spread
    collapses to zero. We exclude the most liquid bond(s) so the affine curve
    represents fair value for generic off-the-run bonds, and `ytm_act - ytm_quo`
    for the on-the-run bond becomes a clean on/off-the-run premium.

    Fallback: if the bucket has <= n_exclude bonds, return the most liquid
    one (avoids returning NaN for sparse tenor buckets such as 20Y/30Y).
    """
    if len(turnover) == 0:
        return np.nan
    if len(turnover) <= n_exclude:
        return turnover.idxmax()
    ranked = turnover.sort_values(ascending=False)
    return ranked.index[n_exclude]


def _as_scalar_bond_id(bond_id):
    """Normalize a bond identifier to a scalar hashable value.

    Some upstream pandas selections can return a one-element Series/Index/ndarray
    instead of a plain scalar. Downstream membership checks and DataFrame lookups
    require a hashable bond code.
    """
    if isinstance(bond_id, pd.Series):
        non_na = bond_id.dropna()
        return _as_scalar_bond_id(non_na.iloc[0]) if not non_na.empty else np.nan
    if isinstance(bond_id, (pd.Index, list, tuple, np.ndarray)):
        if len(bond_id) == 0:
            return np.nan
        return _as_scalar_bond_id(bond_id[0])
    return bond_id


def extract_yield(env: dict, bond_id: str, date: datetime, price_type: str) -> float:
    """Extract yield to maturity based on price type."""
    bond_id = _as_scalar_bond_id(bond_id)
    if price_type == 'hist':
        hist_data = env.get('Close')
        if hist_data is not None and date in hist_data.index and bond_id in hist_data.columns:
            yield_val = hist_data.loc[date, bond_id]
            if pd.notna(yield_val) and yield_val > 0:
                return yield_val
                
    elif price_type == 'close':
        try:
            return env['Def'].loc[bond_id, '估价收益率:%(中债)']
        except KeyError:
            if Config.VERBOSE:
                print(f"Missing data for {bond_id}")
            
    else:  # real time data
        # CNBD valuation is the fallback for every realtime lookup. It must be
        # resolved BEFORE the BondRT check: outside live Wind hours (or on a
        # cache miss) env['BondRT'] is None / missing the bond entirely, and
        # returning NaN there silently starved the whole reference set, so the
        # affine fit ran against ZERO anchor points and produced a degenerate
        # near-flat curve (~0.25% at every tenor) instead of failing loudly.
        try:
            fallback_yield = env['Def'].loc[bond_id, '估价收益率:%(中债)']
        except KeyError:
            fallback_yield = np.nan
        if not pd.notna(fallback_yield):
            fallback_yield = np.nan

        bond_rt_data = env.get('BondRT')
        if bond_rt_data is not None and bond_id in bond_rt_data.index:
            bond_rt = bond_rt_data.loc[bond_id]
            if price_type == 'Bid':
                ytm = bond_rt.get('买价收益率', fallback_yield)
            elif price_type == 'Ofr':
                ytm = bond_rt.get('卖价收益率', fallback_yield)
            else:
                ytm = fallback_yield
            return ytm if pd.notna(ytm) else fallback_yield
        if Config.VERBOSE:
            print(f'Missing real time data for {bond_id} {date}; using CNBD valuation')
        return fallback_yield

    return np.nan


def extract_bond_info(bond_data: pd.Series) -> dict:
    """Extract essential bond information."""
    return {
        'name': bond_data.get('证券全称', ''),
        'start_date': bond_data.get('起息日期'),
        'maturity_date': bond_data.get('到期日期'),
        'frequency': bond_data.get('每年付息次数', 1.0),
        'coupon': bond_data.get('票面利率:%', 0.0),
        'cnbd_yield': (bond_data.get('估价收益率:%(中债)') or 
                      bond_data.get('收盘收益率(%)') or 0.0)
    }


def prepare_bond_schedule(bond_info: dict) -> tuple:
    """Prepare bond schedule for pricing."""
    name, start, maturity, freq, coupon = (
        bond_info['name'], bond_info['start_date'], bond_info['maturity_date'],
        bond_info['frequency'], bond_info['coupon']
    )

    # Genuine discount / zero-coupon bonds (freq == 0, or '贴现' in the name)
    # are priced on their own simple-interest short-end formula in
    # pricing()/pricingYield()/pricingAffine -- never fabricate a coupon
    # frequency for them (see docs/dev/affine-curve-improvement-plan.md F1 /
    # item 1.1; this was the same defect already fixed in curve.py).
    is_discount = (pd.isna(freq) or freq == 0) or ('贴现' in str(name))
    if is_discount:
        coupon = 0.0
        freq = 0.0
    elif pd.isna(freq):
        freq = 1.0

    schedule = yd.scheduleDate(start, maturity, name, freq)
    return coupon, freq, schedule


def _remaining_flow_times(schedule, asof, ttm: float):
    """Remaining coupon dates as year fractions from ``asof``, for the bootstrap.

    Returns strictly-positive times below ``ttm`` (the redemption leg at ttm is
    handled separately by the bootstrapper), or None when the schedule is
    unusable so the caller falls back to the legacy (ttm, freq) reconstruction.

    A payment falling exactly on ``asof`` is excluded: the bond has gone
    ex-coupon and the dirty price passed alongside already reflects that.
    """
    if schedule is None or len(schedule) == 0:
        return None
    try:
        asof_ts = pd.Timestamp(asof)
        days = np.array(
            [(pd.Timestamp(s) - asof_ts).days for s in schedule], dtype=float
        )
    except (TypeError, ValueError):
        return None
    times = days / 365.0
    times = times[np.isfinite(times) & (times > 1e-10) & (times < ttm - 1e-10)]
    # No intermediate coupons left (final period) is a legitimate answer, but
    # an empty schedule parse is not distinguishable here -- returning an empty
    # array is correct either way: the bond then has only its redemption leg.
    return np.sort(times)


class RefBondSelector:
    """Main class for reference bond selection."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def select_reference_bonds(
        self,
        env: dict,
        date_range: list,
        bond_type: str,
        daily: bool,
        update: bool = True,
    ) -> pd.DataFrame:
        """Select reference bonds for given date range and bond type."""
        if self.verbose:
            print(f"Starting reference bond selection for {bond_type}...")
            start_time = time.time()
        
        # Initialize data structures
        bonds = self._prepare_bond_data(env)
        term_buckets = BondConfig.TERM_BUCKETS
  
        # Load existing results
        ref_file = os.path.join(DIR_INPUT, f'{bond_type}-cvref.pkl')
        existing_data = loadPKL(ref_file)

        if 'RefBond' in existing_data:
            result_df = existing_data['RefBond'].sort_index()
            result_df = result_df.loc[~result_df.index.duplicated(keep='first')]
            result_df = result_df.astype(object)
            # Back-compat: add columns for any new buckets not present in the stored file,
            # then reorder to match the current TERM_BUCKETS definition.
            expected_columns = [f'Term near {t}Y' for t in term_buckets.keys()]
            for col in expected_columns:
                if col not in result_df.columns:
                    result_df[col] = np.nan
            result_df = result_df[expected_columns]
        else:
            column_names = [f'Term near {t}Y' for t in term_buckets.keys()]
            result_df = pd.DataFrame(columns=column_names, dtype=object)
        # date_range and the indexes loaded from pickles may mix datetime.date
        # and pd.Timestamp depending on the caller/cache, and pandas rejects
        # comparisons across those types on newer versions. Compare via a
        # Timestamp-coerced copy but keep the original index values (and
        # dtype) flowing downstream, since later code compares them against
        # date-typed data in `bonds`/`env`.
        range_start = pd.Timestamp(date_range[0])
        range_end = pd.Timestamp(date_range[1])

        # Determine dates to process
        if daily:
            dates_to_process = [DateConfig.get_date_mappings()['dp'].date()]
        else:
            px_file = os.path.join(DIR_DATA, f'{bond_type}-px.pkl')
            datelist = loadPKL(px_file)['Close'].index
            datelist_ts = pd.DatetimeIndex(datelist)
            mask = (datelist_ts >= range_start) & (datelist_ts <= range_end)
            dates_to_process = datelist[mask]

        if update and len(result_df) > 0:
            result_index_ts = pd.DatetimeIndex(result_df.index)
            refresh_mask = (
                (result_index_ts >= range_start)
                & (result_index_ts <= range_end)
            )
            existing_result_df = result_df.drop(
                index=result_df.index[refresh_mask],
                errors='ignore'
            )
            result_df = pd.DataFrame(columns=result_df.columns, dtype=object)
        else:
            existing_result_df = result_df

        if not update and len(result_df) > 0:
            dates_to_process = [d for d in dates_to_process if d not in result_df.index]

        # Collect new rows in a dict and concat once instead of cell-by-cell assignment.
        # Also track reference-change events (item 3.2 / F6): a roll is
        # detected by comparing each day's freshly-selected bond against the
        # PREVIOUS actual selection for that bucket (not the ffilled value —
        # a gap day with no selection must not itself look like two rolls).
        new_rows: dict = {}
        change_events: list = []
        last_selected: dict = {}
        # Seed last_selected from the most recent existing row so a roll on
        # the very first date of this run is still detected against history,
        # not treated as a fresh/no-prior-value bucket.
        if len(existing_result_df) > 0:
            last_row = existing_result_df.ffill().iloc[-1]
            for bucket_name, bond_id in last_row.items():
                if pd.notna(bond_id):
                    last_selected[bucket_name] = _as_scalar_bond_id(bond_id)

        for i, current_date in enumerate(dates_to_process):
            if self.verbose and i % max(1, len(dates_to_process) // 10) == 0:
                progress = 100 * i / len(dates_to_process)
                print(f"Progress: {progress:.1f}% - Processing {current_date}")

            day_results = self._process_single_date(
                bonds, current_date, bond_type, term_buckets, result_df
            )
            new_rows[current_date] = day_results
            # Keep result_df up-to-date so stability logic can see the row
            for bucket_name, selected_bond in day_results.items():
                if bucket_name in result_df.columns:
                    result_df[bucket_name] = result_df[bucket_name].astype(object)
                result_df.loc[current_date, bucket_name] = selected_bond

                prev_bond = last_selected.get(bucket_name)
                if (
                    pd.notna(selected_bond)
                    and prev_bond is not None
                    and selected_bond != prev_bond
                ):
                    change_events.append({
                        'date': current_date,
                        'bucket': bucket_name,
                        'old_bond': prev_bond,
                        'new_bond': selected_bond,
                    })
                if pd.notna(selected_bond):
                    last_selected[bucket_name] = selected_bond

        # Merge new rows (if any) and persist
        if new_rows:
            new_rows_df = pd.DataFrame(new_rows).T
            result_df = pd.concat(
                [existing_result_df, new_rows_df]
            ).loc[lambda df: ~df.index.duplicated(keep='last')]
        else:
            new_rows_df = pd.DataFrame(columns=result_df.columns)
            result_df = existing_result_df
        result_df = result_df.sort_index()
        # ffill() only pre-existing gaps (a date never processed, or one with
        # no volume data). A NaN on a date THIS run just processed is not a
        # gap -- it means _process_single_date deliberately declined every
        # candidate for that bucket (most commonly: the only in-range bond
        # was already claimed by another bucket today, see the duplicate/
        # near-collinear guard above). Blanket ffill() used to backfill that
        # NaN with the previous day's bond regardless, silently recreating
        # the exact duplicate the guard had just blocked (seen on CBond
        # 2023-10-10..13: the guard correctly returned NaN for 0.7Y after
        # 0.5Y took 230206.IB, and ffill() immediately overwrote it with
        # 230206.IB again from 10-09). ffill only where this run did not
        # explicitly decide, then still allow later runs to ffill it once a
        # subsequent date away from the collision provides a real value.
        processed_mask = pd.DataFrame(
            False, index=result_df.index, columns=result_df.columns
        )
        processed_mask.loc[new_rows_df.index, new_rows_df.columns] = True
        filled = result_df.ffill()
        result_df = result_df.where(processed_mask, filled)
        result_df = result_df.dropna(how='all')

        final_data = {'RefBond': result_df}
        if change_events:
            # Composite (date, bucket) index: a plain date index is not
            # unique when multiple buckets roll on the same day, which would
            # silently collapse to one row under updatePKL's own
            # duplicate-index handling (and this module's own merge below).
            new_events_df = pd.DataFrame(change_events).set_index(['date', 'bucket'])
            existing_events = existing_data.get('RefBondChange')
            if isinstance(existing_events, pd.DataFrame) and not existing_events.empty:
                events_df = pd.concat([existing_events, new_events_df])
                events_df = events_df[~events_df.index.duplicated(keep='last')]
            else:
                events_df = new_events_df
            final_data['RefBondChange'] = events_df.sort_index()
        final_data = updatePKL(final_data, ref_file)
        if self.verbose:
            end_time = time.time()
            print(f"Completed in {end_time - start_time:.2f} seconds")
            print(f"Result shape: {result_df.shape}")
            if change_events:
                print(f"Recorded {len(change_events)} reference-change event(s)")

        return result_df
    
    def _prepare_bond_data(self, env: dict) -> dict:
        """Prepare and filter bond data for processing."""
        # Handle historical or single date data
        if 'Volume' in env:
            # Historical case with volume time series
            bonds = env['Volume'].columns.intersection(env['Def'].index)
            df_balance = env['Def']['债券余额:亿'].loc[bonds]
            
            # Filter valid bonds
            valid_mask = (df_balance != 0) & (df_balance.notna())
            bonds = bonds[valid_mask]
            df_balance = df_balance[valid_mask]
            
            # Calculate turnover time series
            df_turnover = env['Volume'][bonds].div(df_balance.values, axis=1) / 1e8
            df_turnover = df_turnover.replace([np.inf, -np.inf], 0).dropna(axis=0, how='all')
            # 20-day rolling mean smooths zero-volume days and gives stable
            # on/off-the-run ranking. min_periods=5 avoids penalising bonds
            # that just started trading (auction week).
            df_turnover = df_turnover.rolling(window=20, min_periods=5).mean()
        else:
            # Single date case
            required_cols = ['债券余额:亿', '成交量:万元', '到期日期', '起息日期', '证券全称']
            bonds = env['Def'].index
            
            for col in required_cols:
                if col not in env['Def'].columns:
                    raise KeyError(f"Required column '{col}' not found in env['Def']")
            
            df_balance = env['Def']['债券余额:亿'].loc[bonds]
            df_volume = env['Def']['成交量:万元'].loc[bonds]
            
            # Filter valid bonds
            valid_mask = (df_balance != 0) & (df_balance.notna())
            bonds = bonds[valid_mask]
            df_balance = df_balance[valid_mask]
            df_volume = df_volume[valid_mask]
            
            # Calculate turnover
            turnover_ratio = df_volume / df_balance / 1e4
            turnover_ratio = turnover_ratio.replace([np.inf, -np.inf], 0).dropna()
            
            # Create DataFrame structure for compatibility
            df_turnover = pd.DataFrame(index=[DateConfig.get_date_mappings()['dp'].date()], columns=bonds)
            df_turnover.loc[df_turnover.index[0]] = turnover_ratio
        
        return {
            'bonds': bonds,
            'balance': df_balance,
            'turnover': df_turnover,
            'maturity': env['Def']['到期日期'].loc[bonds],
            'start_date': env['Def']['起息日期'].loc[bonds],
            'bond_names': env['Def']['证券全称'].loc[bonds],
            'definition': env['Def']
        }
    
    def _process_single_date(self, bonds: dict, current_date: datetime,
                           bond_type: str, term_buckets: dict, existing_results: pd.DataFrame) -> dict:
        """Process bond selection for a single date."""
        day_results = {}
        # Filter by bond type
        type_filtered = filter_bonds_by_type(bonds['bond_names'], bond_type)
        available_bonds = bonds['bonds'].intersection(type_filtered)
        
        # Filter by start date
        started_mask = bonds['start_date'][available_bonds] < current_date
        end_mask = bonds['maturity'][available_bonds] > current_date
        available_bonds = available_bonds[started_mask & end_mask]
        
        if len(available_bonds) == 0:
            return day_results
        
        # Calculate terms — direct date arithmetic avoids strftime round-trips
        terms = (bonds['maturity'][available_bonds] - current_date).apply(
            lambda d: d.days / 365
        )
        
        # Get turnover for this date
        date_turnover = pd.Series(dtype=float)
        if current_date in bonds['turnover'].index:
            date_turnover = bonds['turnover'].loc[current_date, available_bonds]#.dropna()
        else:
            raise MissingVolumeDataError(
                f"Missing Volume data for date {current_date}; cannot select "
                f"reference bonds without turnover."
            )

        # Process each term bucket
        for bucket_term, (min_term, max_term) in term_buckets.items():
            bucket_name = f'Term near {bucket_term}Y'

            # Filter by term bucket
            bucket_bonds = filter_bonds_by_term(terms, min_term, max_term)
            candidate_bonds = available_bonds.intersection(bucket_bonds)

            # Special handling for short-end buckets: restrict to annually-
            # coupon-paying bonds (每年付息次数 == 1), NOT zero-coupon/discount
            # bonds (freq == 0) despite this block's original name — genuine
            # discount bills are a separate short-end convention (see affine
            # plan F1/F12, item 1.1) and are excluded here on purpose, since
            # this bucket's reference bond still needs a real coupon schedule
            # for the bootstrap/pricing path. Verified 2026-09-05: freq==0
            # rows do not appear in this universe's candidate set at all, so
            # this filter is not currently dropping any discount bills — it
            # exists to prefer semi-annual-coupon bonds' annual-coupon peers
            # for short-end bootstrap stability. Renamed from "zero coupon
            # bonds" to reflect actual intent.
            if bucket_term in [0.5, 1.0]:
                freq_data = bonds['definition'].loc[candidate_bonds, '每年付息次数']
                annual_coupon_mask = (freq_data == 1) & freq_data.notna()
                candidate_bonds = candidate_bonds[annual_coupon_mask]

            # For short-end buckets (<1.5Y) use the most liquid bond: near-maturity
            # off-the-run bonds often have stale CNBD yields that equal their coupon
            # rate (2-5%) rather than the current market rate, which inflates the
            # bootstrap spot. For longer buckets use first off-the-run to avoid
            # the calibration curve chasing on-the-run richness.
            available_turnover = date_turnover.loc[candidate_bonds].dropna()
            # Avoid duplication with ANY bucket already selected today, not
            # just the immediately preceding one — with symmetric widening
            # (see filter_bonds_by_term) a bond can land in two non-adjacent
            # buckets, and BootstrapYieldCurve.instruments is keyed by float
            # maturity so a duplicate would silently overwrite. See
            # docs/dev/affine-curve-improvement-plan.md F5, F12 / item 1.3.
            already_selected = {
                bond for bond in day_results.values()
                if isinstance(bond, str) and bond == bond  # excludes NaN
            }

            if already_selected:
                to_drop = [b for b in available_turnover.index if b in already_selected]
                if to_drop:
                    available_turnover = available_turnover.drop(index=to_drop)

            if bucket_term < 1.5:
                selected_bond = _as_scalar_bond_id(get_most_liquid_bond(available_turnover))
            else:
                selected_bond = _as_scalar_bond_id(get_offtherun_bond(available_turnover, n_exclude=1))

            # Sticky off-the-run: prefer the previous selection as long as
            # it is still in this bucket. This prevents day-to-day turnover
            # noise from flipping the reference between adjacent off-the-run
            # bonds, and lets new on-the-run issuance roll smoothly into the
            # calibration (old on-the-run becomes the new first off-the-run
            # only when the previous reference ages out of the bucket).
            #
            # Both sticky branches must re-apply the SAME two constraints the
            # fresh selection above already enforces, or they silently undo
            # them (F5/F12 item 1.3's duplicate guard was applied only to
            # `available_turnover`, which the sticky path bypasses):
            #   1. the bond must not already be another bucket's reference
            #      today -- BootstrapYieldCurve.instruments is keyed by float
            #      maturity, so a duplicate silently overwrites an anchor and
            #      leaves the bootstrap with two near-identical maturities;
            #   2. it must still sit in this bucket's NOMINAL range, not the
            #      ±max_widen band `bucket_bonds` was built from -- widening
            #      exists to find a candidate when a bucket is empty, not to
            #      let a stale reference drift indefinitely into a neighbour.
            # Both were violated on 2024-01-04..2024-02-01, where 220004.IB
            # held the 0.7Y AND 1Y buckets for 21 straight days at TTM
            # 1.07-1.14 (the 0.7Y bucket is [0.6, 0.9]). The resulting pair of
            # anchors 0.08y apart broke the bootstrap on the 2024-02-02 roll:
            # RefSpot 10Y fell 2.102% -> 1.563% while its own input bond
            # traded flat at 2.4684%, stayed ~100bp below market for two
            # months, and its recovery inflated S2 (cov of factor LEVELS) to
            # ~5.6, producing curves with -1.02% at 10Y and +400bp bond
            # pricing errors through 2024-06.
            def _sticky_ok(candidate) -> bool:
                if candidate not in bonds['start_date'].index:
                    return False
                if candidate in already_selected:
                    return False
                candidate_term = terms.get(candidate, np.nan)
                return bool(pd.notna(candidate_term)
                            and min_term < candidate_term <= max_term)

            previous_dates = existing_results.index[existing_results.index < current_date]
            if len(previous_dates) > 0:
                prev_date = previous_dates[-1]
                prev_bond = _as_scalar_bond_id(existing_results.loc[prev_date, bucket_name])
                if _sticky_ok(prev_bond):
                    selected_bond = prev_bond
                elif (pd.isna(selected_bond)
                      and prev_bond in bonds['start_date'].index
                      and prev_bond not in already_selected):
                    # Empty-bucket fallback: nothing fresh was selectable, so
                    # carry the previous reference forward even though it has
                    # aged out of the nominal range -- an out-of-range anchor
                    # is still better than a NaN hole in the bootstrap. The
                    # duplicate check is NOT relaxed here: reusing a bond that
                    # already anchors another bucket today is exactly the
                    # collision that breaks the bootstrap.
                    selected_bond = prev_bond
            day_results[bucket_name] = _as_scalar_bond_id(selected_bond)
        return day_results


def _fit_coupon_beta(coupons: np.ndarray, ytms: np.ndarray, ttms: np.ndarray) -> float:
    """Fit the per-date coupon-sensitivity term beta from a reference cross-
    section: ytm_i ~= level(ttm_i) + beta*coupon_i + eps_i.

    ``level(ttm)`` is approximated by a degree-1 polynomial in ttm (a full
    curve shape isn't known yet -- this only needs to be good enough to not
    let a term-structure slope masquerade as a coupon effect). Returns 0.0
    (no adjustment) if there are too few points or the coupon column has no
    variation, so a thin day never over-fits noise into beta.
    See docs/dev/affine-curve-improvement-plan.md F13 / item 1.7.
    """
    n = len(coupons)
    if n < 4 or np.nanstd(coupons) < 1e-6:
        return 0.0
    # Design matrix: [1, ttm, coupon]
    X = np.column_stack([np.ones(n), ttms, coupons])
    try:
        coef, _, rank, _ = np.linalg.lstsq(X, ytms, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    if rank < X.shape[1]:
        return 0.0
    beta = float(coef[2])
    # Sanity cap: a coupon-driven yield shift beyond +/-2 (in ytm-% per
    # coupon-% units) on a same-day fit is almost certainly overfitting a
    # thin/noisy cross-section (F5 reference-selection noise), not a real
    # liquidity/vintage/tax effect -- do not trust it.
    if not np.isfinite(beta) or abs(beta) > 2.0:
        return 0.0
    return beta


def coupon_adjustment_enabled(bond_type: str) -> bool:
    """Whether the coupon-vintage adjustment (item 1.7 / F13) applies to
    `bond_type`. The effect is CGB-specific -- CDB shows no coupon
    sensitivity despite comparable coupon dispersion -- so the setting is a
    per-asset-class mapping. A plain bool is still honoured for
    back-compatibility."""
    setting = getattr(BondConfig, 'APPLY_COUPON_ADJUSTMENT', False)
    if isinstance(setting, dict):
        return bool(setting.get(bond_type, False))
    return bool(setting)


class YieldCurveBuilder:
    """Build yield curves from reference bonds."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        # Diagnostic: per-date fitted coupon-sensitivity beta from the most
        # recent build_curve() call (F13 / item 1.7). None until fit, or when
        # apply_coupon_adjustment=False.
        self.last_coupon_beta: float = None

    def build_curve(self, bond_ref: pd.Series, env: dict, price_type: str, date: datetime,
                     tax: float = 0.0, apply_coupon_adjustment: bool = False) -> pd.DataFrame:
        """Build yield curve from reference bonds.

        Args:
            tax: Optional coupon-premium adjustment applied before bootstrapping.
                 The current bond-curve workflow uses ``tax=0`` for both TBond
                 and CBond so spot calibration and downstream pricing share the
                 same no-tax convention.
            apply_coupon_adjustment: when True, fits a per-date coupon-
                 sensitivity term beta from this date's reference cross-
                 section and bootstraps on the de-couponed yield
                 (ytm - beta*coupon) instead of the raw quoted yield, to
                 correct the short-end coupon-vintage dispersion documented
                 in F13. Off by default pending historical validation of
                 beta's stability -- see item 1.7. The fitted beta is always
                 exposed via ``self.last_coupon_beta`` regardless of this
                 flag, so it can be monitored before being trusted live.
        """
        yield_curve = bs.BootstrapYieldCurve()
        results = pd.DataFrame(index=bond_ref.index, columns=['bond_id', 'ttm', 'spot'], dtype=object)

        # First pass: collect raw (coupon, ytm, ttm, schedule info) per bucket
        # so beta can be fit on the whole day's cross-section before anything
        # is bootstrapped.
        collected = {}
        for bucket_name, bond_id in bond_ref.items():
            bond_id = _as_scalar_bond_id(bond_id)
            if pd.isna(bond_id):
                continue

            # Extract bond information
            if bond_id not in env['Def'].index:
                warnings.warn(
                    f"Skipping reference bond {bond_id} on {date}: not found in env['Def']"
                )
                continue
            bond_data = env['Def'].loc[bond_id]
            bond_info = extract_bond_info(bond_data)

            # Get yield
            ytm = extract_yield(env, bond_id, date, price_type)

            if pd.isna(ytm) or not np.isfinite(ytm):
                continue

            # Prepare schedule
            coupon, frequency, schedule = prepare_bond_schedule(bond_info)

            # Calculate time to maturity
            maturity_date = bond_info['maturity_date']
            date_1 = pd.Timestamp(maturity_date).date()
            date_2 = pd.Timestamp(date).date()
            ttm = (date_1 - date_2).days / 365

            collected[bucket_name] = dict(
                bond_id=bond_id, coupon=coupon, frequency=frequency,
                schedule=schedule, ttm=ttm, ytm=ytm,
            )

        # Fit the coupon-sensitivity term on this date's own cross-section
        # (freq == 0 discount bills excluded -- coupon is definitionally 0
        # there and they're a separate convention bucket, see F1).
        coupon_fit_rows = [v for v in collected.values() if v['frequency'] != 0]
        beta = _fit_coupon_beta(
            np.array([v['coupon'] for v in coupon_fit_rows], dtype=float),
            np.array([v['ytm'] for v in coupon_fit_rows], dtype=float),
            np.array([v['ttm'] for v in coupon_fit_rows], dtype=float),
        ) if coupon_fit_rows else 0.0
        self.last_coupon_beta = beta

        for bucket_name, info in collected.items():
            bond_id, coupon, frequency, schedule, ttm, ytm = (
                info['bond_id'], info['coupon'], info['frequency'],
                info['schedule'], info['ttm'], info['ytm'],
            )

            ytm_for_bootstrap = ytm
            if apply_coupon_adjustment and beta != 0.0 and frequency != 0:
                ytm_for_bootstrap = ytm - beta * coupon

            # Calculate pricing at the (possibly de-couponed) yield
            dirty, clean, duration, convexity = yd.pricing(
                date, coupon, schedule, frequency, ytm_for_bootstrap
            )

            # Under the current no-tax convention the dirty price is used
            # as-is. The branch is kept for optional future adjustments.
            if tax > 0.0 and np.isfinite(dirty):
                cpv = yd.coupon_pv_sum(date, coupon, schedule, frequency, ytm_for_bootstrap)
                dirty_for_bootstrap = dirty - tax * cpv
            else:
                dirty_for_bootstrap = dirty

            # Add to yield curve. Pass the bond's REAL remaining coupon dates
            # (as year fractions from `date`) so the bootstrap does not
            # reconstruct them from (ttm, frequency) -- that reconstruction
            # invents a coupon just after the pricing date on a bond's coupon
            # anniversary, when it has just gone ex-coupon, and forces the
            # solver to spike the terminal zero. See add_instrument's docstring.
            flow_times = _remaining_flow_times(schedule, date, ttm)
            # The redemption pays on the business-day-adjusted final schedule
            # date, which is 1-2 days after the raw maturity used for `ttm` on
            # ~25% of bond-days. `ttm` stays the curve node label; the actual
            # payment time is what the redemption leg must be discounted at
            # (worth up to ~0.8bp of implied zero at the short end).
            redemption_time = ttm
            try:
                if schedule is not None and len(schedule) > 0:
                    last_flow = max(pd.Timestamp(x) for x in schedule)
                    t_last = (last_flow.date() - pd.Timestamp(date).date()).days / 365.0
                    if np.isfinite(t_last) and t_last > 0:
                        redemption_time = t_last
            except (TypeError, ValueError):
                pass
            yield_curve.add_instrument(
                100, ttm, coupon, dirty_for_bootstrap, frequency,
                flow_times=flow_times, redemption_time=redemption_time,
            )

            # Record the bucket's identity/tenor. The spot-rate mapping below
            # keys off results['ttm'], so omitting these leaves every row NaN
            # and silently produces an empty reference set.
            results.loc[bucket_name, 'bond_id'] = bond_id
            results.loc[bucket_name, 'ttm'] = ttm

        # Extract yield curve
        maturities = yield_curve.get_maturities()
        zero_rates = yield_curve.get_zero_rates()
        rate_map = dict(zip(maturities, zero_rates))

        # Map spot rates
        for bucket_name in results.index:
            ttm = pd.to_numeric(results.loc[bucket_name, 'ttm'], errors='coerce')
            results.loc[bucket_name, 'spot'] = rate_map.get(float(ttm), np.nan) if pd.notna(ttm) else np.nan

        results['ttm'] = pd.to_numeric(results['ttm'], errors='coerce')
        results['spot'] = pd.to_numeric(results['spot'], errors='coerce')
        return results

def compute_spot_term_panels(
    env: dict,
    price_range: list,
    botr: pd.DataFrame,
    bond_type: str,
    price_type: str = "hist",
    update: bool = True,
):
    """Compute spot and term panels for a date range."""
    # Determine dates to compute. price_range and botr.index may mix
    # datetime.date and pd.Timestamp depending on the caller/cache, so
    # compare via Timestamp-coerced copies (see select_reference_bonds).
    start = pd.Timestamp(price_range[0])
    end = pd.Timestamp(price_range[1])

    botr_index_ts = pd.DatetimeIndex(botr.index)
    mask = (botr_index_ts >= start) & (botr_index_ts <= end)
    date_index = botr.index[mask]
    columns = list(botr.columns)
    
    # Load existing data
    file_path = os.path.join(DIR_INPUT, f'{bond_type}-cvref.pkl')
    existing_data = loadPKL(file_path)
    existing_spot = existing_data.get('RefSpot', None)
    existing_term = existing_data.get('RefTerm', None)

    if update:
        missing_dates = list(date_index)
    else:
        existing_spot_index = existing_spot.index if existing_spot is not None else pd.Index([])
        missing_dates = [d for d in date_index if d not in existing_spot_index]

    if price_type in ['hist','close']:
        if len(missing_dates) == 0:
            return existing_data
        else:
            # Compute new values
            new_spot = pd.DataFrame(index=missing_dates, columns=columns, dtype=float)
            new_term = pd.DataFrame(index=missing_dates, columns=columns, dtype=float)
            # Per-date coupon-sensitivity diagnostic (item 1.7 / F13). Persisted
            # so beta's stability can be monitored in production: a structural
            # coupon-vintage effect should stay smooth (historically about
            # -0.072, sd 0.007); a suddenly noisy or sign-flipping beta means
            # the fit is chasing reference-selection noise and the adjustment
            # should be reviewed (BondConfig.APPLY_COUPON_ADJUSTMENT).
            new_beta = pd.Series(index=missing_dates, dtype=float, name='CouponBeta')

            _tax = 0.0
            for d in missing_dates:
                bond_ref = botr.loc[d]
                builder = YieldCurveBuilder()
                dfp = builder.build_curve(
                    bond_ref, env, price_type, d, tax=_tax,
                    apply_coupon_adjustment=coupon_adjustment_enabled(bond_type),
                )

                ttm_series = pd.Series(index=columns, dtype=float)
                spot_series = pd.Series(index=columns, dtype=float)

                for bucket, bond_id in bond_ref.items():
                    if bucket in dfp.index:
                        ttm_value = pd.to_numeric(dfp.loc[bucket, 'ttm'], errors='coerce')
                        spot_value = pd.to_numeric(dfp.loc[bucket, 'spot'], errors='coerce')
                        ttm_series.loc[bucket] = float(ttm_value) if pd.notna(ttm_value) else np.nan
                        spot_series.loc[bucket] = float(spot_value) if pd.notna(spot_value) else np.nan

                new_term.loc[d] = ttm_series
                new_spot.loc[d] = spot_series
                new_beta.loc[d] = builder.last_coupon_beta

            # Save results
            final_data = {'RefSpot': new_spot, 'RefTerm': new_term,
                          'CouponBeta': new_beta}
            final_data = updatePKL(final_data, file_path)

            # updatePKL's merge (new_df.combine_first(target_df)) unions
            # columns and forward-fills, so a bucket removed from the
            # CURRENT TERM_BUCKETS (`columns`, from botr -- already trimmed
            # by select_reference_bonds) would otherwise linger in RefSpot/
            # RefTerm forever, ffilled with its last real value from before
            # removal and displayed as if it were live (e.g. Term near 7Y
            # kept showing a value frozen from before the 7Y bucket was
            # dropped from TERM_BUCKETS). Trim back to the current bucket
            # set and persist the trim. Must rewrite the FULL on-disk dict
            # (not just RefSpot/RefTerm) since updatePKL(rewrite=True)
            # replaces the entire file -- this pickle also holds RefBond,
            # ImpliedVol, Spot, Factors. See
            # docs/dev/affine-curve-improvement-plan.md F7.
            trimmed = False
            for key in ('RefSpot', 'RefTerm'):
                df = final_data.get(key)
                if isinstance(df, pd.DataFrame):
                    stale_cols = [c for c in df.columns if c not in columns]
                    if stale_cols:
                        final_data[key] = df.drop(columns=stale_cols)
                        trimmed = True
            if trimmed:
                full_on_disk = loadPKL(file_path)
                full_on_disk.update(final_data)
                updatePKL(full_on_disk, file_path, rewrite=True)
            return final_data
    else:
        d = botr.index[-1]
        bond_ref = botr.loc[d]
        plist = ['Bid', 'Ofr']
        ref_series = {}
        _tax = 0.0
        for p in plist:
            builder = YieldCurveBuilder()
            dfp = builder.build_curve(
                bond_ref, env, p, d, tax=_tax,
                apply_coupon_adjustment=coupon_adjustment_enabled(bond_type),
            )
            series = pd.Series(dfp['spot'].values, index=dfp['ttm'].values, dtype=float)
            series.index = pd.to_numeric(series.index, errors='coerce')
            series = series[~pd.isna(series.index)]
            series = series[~series.index.duplicated(keep='last')].sort_index()
            ref_series[p] = series
        ref_df = pd.concat(ref_series, axis=1).sort_index()
        return ref_df

def update_price(df_price, quote0, sen0, bonds, d0):
    """Update bond pricing data with new quotes and sensitivities."""
    bonds_ = quote0.index
    df_price['ytm_act'].loc[d0, bonds.index] = bonds.loc[bonds.index, '收盘收益率(%)']
    df_price['ytm_quo'].loc[d0, bonds_] = quote0.loc[bonds_, '收益率']
    df_price['dur_curva'].loc[d0, bonds_] = sen0.loc[bonds_, 'Greek1']
    df_price['dur_level'].loc[d0, bonds_] = sen0.loc[bonds_, 'Greek2']
    df_price['dur_slope'].loc[d0, bonds_] = sen0.loc[bonds_, 'Greek3']
        
    for k in df_price.keys():       
        df_price[k] = df_price[k].sort_index()       
    return df_price