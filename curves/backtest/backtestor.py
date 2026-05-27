# -*- coding: utf-8 -*-
"""
Created on Mon Oct 13 22:28:16 2025

@author: CMBC
"""

import os
import sys
import pathlib
import logging
import pandas as pd
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as _mp

# Local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(PATH))

from curves.utils.file import updatePKL
from curves.backtest import database as db
from curves.utils.loader import loadBacktestingInputs, loadCNBDTS
from settings.paths import DIR_INPUT

# Import core backtest functionality
from curves.backtest.core import (
    CurveManager, 
    CurveParameterExtractor, 
    CarryRollCalculator,
    PricingEngine,
    ResultsConsolidator
)

# Worker functions will be imported locally to avoid circular imports

# Configure logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)



class Backtestor:
    def __init__(self, btype: str, start: str, end: str, update_list=None, processes: int = 4, serial: bool = False):
        self.btype = btype
        self.start = start
        self.end = end
        self.processes = max(1, processes)
        self.serial = serial
        self.update_flags = self._build_update_flags(update_list or [])
        
        # Performance tracking
        self._timing = {}

    @staticmethod
    def _build_update_flags(update_list):
        options = ['pool', 'bonds', 'cbts']
        flags = {opt: (opt in update_list) for opt in options}
        return flags

    def _time_operation(self, operation_name):
        """Context manager for timing operations."""
        import time
        class Timer:
            def __init__(self, name, timing_dict):
                self.name = name
                self.timing_dict = timing_dict
                self.start_time = None
            
            def __enter__(self):
                self.start_time = time.time()
                logger.info(f"Starting {self.name}...")
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                elapsed = time.time() - self.start_time
                self.timing_dict[self.name] = elapsed
                logger.info(f"Completed {self.name} in {elapsed:.2f}s")
        
        return Timer(operation_name, self._timing)

    def _slice_periods(self, test_period, num_processes):
        """Split test period into chunks for parallel processing"""
        start_date = pd.to_datetime(test_period[0])
        end_date = pd.to_datetime(test_period[1])
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        
        if len(date_range) <= num_processes:
            return [[d.date()] for d in date_range]
        
        chunk_size = len(date_range) // num_processes
        periods = []
        for i in range(0, len(date_range), chunk_size):
            chunk = date_range[i:i+chunk_size]
            periods.append([d.date() for d in chunk])
        return periods

    def _build_periods(self):
        test_period = [self.start, self.end]
        periods = self._slice_periods(test_period, self.processes)
        prange = [d.date() for d in pd.date_range(start=test_period[0], end=test_period[1])]
        return test_period, periods, prange

    def _load_env(self, prange):
        """Load environment data (caching removed)."""
        if self.btype == 'IRS':
            env = loadCNBDTS()['SwapTS']
            prange = [ d for d in prange if d in env.index ]
            return env, prange
        
        # Caching removed: always load fresh data
        from dateutil.relativedelta import relativedelta
        # Allow backtest to explicitly retrieve data outside trading hours
        # (e.g., weekends) while keeping normal auto-retrieval gated.
        try:
            from data.providers import retrieve as dp_retrieve
            dp_retrieve.set_allow_nontrading_retrieval(True)
        except Exception:
            dp_retrieve = None

        window_range = [prange[0], prange[-1]]
        try:
            database = db.loadDB(self.btype, window_range, self.update_flags)
        finally:
            if 'dp_retrieve' in locals() and dp_retrieve is not None:
                try:
                    dp_retrieve.set_allow_nontrading_retrieval(False)
                except Exception:
                    pass
        env = loadBacktestingInputs(self.btype, window_range, database)
        prange = [ d for d in prange if d in env['Close'].index ] 
        return env, prange

    def _init_curve(self, env, prange):
        print(f"Initializing curves for {self.btype}...")
        
        if self.btype in ['TBond', 'CBond', 'IRS']:
            manager = CurveManager(self.btype)
            
            # Add parallel processing to curve initialization
            if not self.serial and self.processes > 1 and len(prange) > 10:
                print(f"Using parallel curve initialization for {self.btype}")
                dict_curve = self._parallel_initialize_curves(manager, env, prange)
            else:
                print(f"Using serial curve initialization for {self.btype}")
                dict_curve = manager.initialize_curves(env, prange)
                
            if self.btype != 'IRS':
                extractor = CurveParameterExtractor(self.btype)
                extractor.extract_parameters(dict_curve, prange)
            else:
                calculator = CarryRollCalculator()
                calculator.calculate_carry_roll(dict_curve, prange, env)
        else:
            dict_curve = {}
            self.btype = 'TBond'
        return dict_curve

    def _parallel_initialize_curves(self, manager, env, prange):
        """Initialize curves in parallel for better performance."""
        logger.info(f"Initializing curves in parallel with {self.processes} workers")
        
        # Split date range into chunks for parallel processing
        chunks = self._split_date_range(prange, self.processes)
        
        # Pre-compute reference data once (this is already optimized in CurveManager)
        if self.btype != 'IRS':
            manager._precompute_reference(env, prange)
        # Use ProcessPoolExecutor with initializer to share heavy context once per worker.
        # Prefer 'fork' when available, but fall back to the platform default on Windows.
        from curves.backtest.workers import _init_worker_curves, _init_curves_chunk_worker
        initargs = (manager.bond_type, manager._cache)
        if self.btype == 'IRS':
            initargs = (*initargs, env, prange)
        with ProcessPoolExecutor(
            max_workers=self.processes,
            mp_context=self._get_process_context(),
            initializer=_init_worker_curves,
            initargs=initargs,
        ) as executor:
            futures = [executor.submit(_init_curves_chunk_worker, chunk) for chunk in chunks]
            results = [future.result() for future in futures]
        
        # Merge results
        dict_curve = {}
        for chunk_result in results:
            dict_curve.update(chunk_result)
        
        # Save to file
        curve_file = os.path.join(DIR_INPUT, f'{manager.bond_type}-cvobj.pkl')
        updatePKL(dict_curve, curve_file)
        
        return dict_curve

    def _split_date_range(self, prange, num_chunks):
        """Split date range into balanced chunks."""
        chunk_size = max(1, len(prange) // num_chunks)
        chunks = []
        for i in range(0, len(prange), chunk_size):
            chunk = prange[i:i + chunk_size]
            if chunk:
                chunks.append(chunk)
        return chunks

    @staticmethod
    def _get_process_context():
        """Return the safest multiprocessing context for the current platform."""
        if 'fork' in _mp.get_all_start_methods():
            return _mp.get_context('fork')
        return _mp.get_context()

    def _run_pricing(self, dict_curve, env, test_period, periods):
        engine = PricingEngine(self.btype)
        
        if self.serial or self.processes == 1:
            print(f"Running pricing for {self.btype} in serial mode")
            return engine.price_instruments(dict_curve, env, test_period)
        else:
            print('Backtesting in parallel for ' + self.btype + f' with {self.processes} workers.')
            # Note: periods is a list of date chunks [[date1, date2, ...], [date3, date4, ...], ...]
            # Each chunk will be converted to [start, end] format inside the worker
            # Use ProcessPoolExecutor with initializer to share dict_curve/env once per worker
            from curves.backtest.workers import _init_worker_pricing, _price_chunk_worker
            with ProcessPoolExecutor(
                max_workers=self.processes,
                mp_context=self._get_process_context(),
                initializer=_init_worker_pricing,
                initargs=(self.btype, dict_curve, env),
            ) as executor:
                futures = [executor.submit(_price_chunk_worker, chunk) for chunk in periods]
                dict_price_chunks = [f.result() for f in futures]
            consolidator = ResultsConsolidator(self.btype)
            return consolidator.consolidate_pricing_results(dict_price_chunks)
    
    def run(self):
        """Main execution with performance monitoring."""
        with self._time_operation("Total Backtest"):
            with self._time_operation("Build Periods"):
                test_period, periods, prange = self._build_periods()
            
            with self._time_operation("Load Environment"):
                env, prange = self._load_env(prange)
                datelist = [d.strftime("%Y-%m-%d") for d in prange]
            print("Compute following days: ", ', '.join(datelist))
            
            with self._time_operation("Initialize Curves"):
                dict_curve = self._init_curve(env, prange)
            
            with self._time_operation("Save Curve Objects"):
                dict_curve = updatePKL(dict_curve, os.path.join(DIR_INPUT, self.btype + '-cvobj.pkl'))
            
            with self._time_operation("Run Pricing"):
                bond_px = self._run_pricing(dict_curve, env, test_period, periods)
                # import pdb; pdb.set_trace()
            with self._time_operation("Save Pricing Results"):
                bond_px = updatePKL(bond_px, os.path.join(DIR_INPUT, self.btype + '-cvpx.pkl'))
        
        # Print performance summary
        logger.info("=== Performance Summary ===")
        total_time = self._timing.get("Total Backtest", 0)
        for operation, elapsed in self._timing.items():
            if operation != "Total Backtest":
                percentage = (elapsed / total_time * 100) if total_time > 0 else 0
                logger.info(f"{operation}: {elapsed:.2f}s ({percentage:.1f}%)")
        logger.info(f"Backtest completed for {self.btype} in {total_time:.2f}s total.")
