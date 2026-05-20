# -*- coding: utf-8 -*-
"""
Created on Wed Nov 15 15:33:02 2023

@author: 马云飞
"""
import os
import sys  
import pickle
import pathlib
import pandas as pd
from datetime import datetime
import numpy as np
import xlwings as xw

# local libraries
PATH = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0,str(PATH))

# Setup logging using centralized setup
from utils.log_window import get_logger
logger = get_logger(__name__)

from curves.utils.loader import loadInstrumentDefinition, loadCNBDTS
from curves.utils.retrieve  import retrieveEnvRT
from utils.io import save_frame
from settings.paths import DIR_INPUT
from settings.general import GeneralConfig, DateConfig
from settings.fixed_income import IRSConfig
from curves.utils.file import updatePKL

from curves.utils.plot import plotIRSSpotCurve, plotIRSForwardCurve
from curves.calibration import irscurves as irs

class IRSRefresher:
	def __init__(self):
		self.today_date = DateConfig.get_date_mappings()['d'].date()
		self.previous_bday = (self.today_date - pd.tseries.offsets.BDay(1)).date()
		self.environment = None
		self.environment_time_series = None
		self.fixings = None
		self.curves = {}
		self.curve_dictionary = {
			'close': {},
			'closefit': {},
			'inst': {},
			'instfit': {},
		}
		self.forward_shift = {}
		self.forward_data = None
		self.forward_data_adjusted = None
		self.r7d_forward = None
		self.s3m_forward = None
		self.quote_rate = None
		self.quote_frame = None
		self.contracts = None
		self.contracts_adjusted = None
		self.cv_irs = None
		self.qt_irs = None
		self.cv_spreads = None
		self.qt_spreads = None
		self.spreads_list = None
		self.cv_irs_adjusted = None
		self.cv_spreads_adjusted = None

	def load_environment_and_series(self):
		logger.info("Loading environment and time series data...")
		self.environment = loadInstrumentDefinition('TBond')
		logger.info("Loaded instrument definition for TBond")
		self.environment = retrieveEnvRT(self.environment, 'TBond')
		logger.info("Retrieved real-time environment data")
		self.environment_time_series = loadCNBDTS()['SwapTS']
		logger.info("Loaded CNBD time series data")

		fr007 = self.environment_time_series['FR007.IR'].dropna()
		if self.previous_bday not in fr007.index:
			self.previous_bday = fr007.index[-1]
			logger.info(f"Adjusted previous business day to {self.previous_bday}")
		shibor3m = self.environment_time_series['SHIBOR3M.IR'].dropna()
		
		logger.info(f"Using business day: {self.previous_bday}")
		
		self.fixings = {
			'close': {
				'r7d': fr007.loc[self.previous_bday],
				's3m': shibor3m.loc[self.previous_bday]
			},
			'inst': {
				'r7d': self.environment['SwapRT'].loc['FR007.IR', '成交收益率'],
				's3m': self.environment['SwapRT'].loc['SHIBOR3M.IR', '成交收益率']
			}
		}
		
		logger.info(f"Set fixings - Close: R7D={self.fixings['close']['r7d']:.4f}%, S3M={self.fixings['close']['s3m']:.4f}%")
		logger.info(f"Set fixings - Inst: R7D={self.fixings['inst']['r7d']:.4f}%, S3M={self.fixings['inst']['s3m']:.4f}%")

	def load_close_curves(self):
		logger.info("Loading close curves from IRS-cvrt.obj...")
		with open(os.path.join(DIR_INPUT, 'IRS-cvrt.obj'), 'rb') as file:
			self.curves['close'] = pickle.load(file)
		logger.info("Successfully loaded close curves")

	def _get_fallback_swap_quotes(self):
		if self.environment_time_series is None or self.environment_time_series.empty:
			return pd.Series(dtype=float)
		if self.previous_bday in self.environment_time_series.index:
			return self.environment_time_series.loc[self.previous_bday]
		return self.environment_time_series.iloc[-1]

	def build_instantaneous_curves(self):
		logger.info("Building instantaneous curves...")
		fallback_quotes = self._get_fallback_swap_quotes()
		for tenor_type in ['close', 'inst']:
			logger.info(f"Processing {tenor_type} curves...")
			for ctype in IRSConfig.CURVE_TYPES:
				self.curve_dictionary[tenor_type][ctype] = self.curves[tenor_type][ctype].anchor
				self.curve_dictionary[tenor_type + 'fit'][ctype] = self.curves[tenor_type][ctype].curves
			self.curve_dictionary[tenor_type]['basis'] = (self.curve_dictionary[tenor_type]['s3m'] - self.curve_dictionary[tenor_type]['r7d']) * 100
			self.curve_dictionary[tenor_type + 'fit']['basis'] = (self.curve_dictionary[tenor_type]['s3m'] - self.curve_dictionary[tenor_type]['r7d']) * 100
			if tenor_type == 'close':
				logger.info("Building instantaneous curves from close curves...")
				irs_ref = {'r7d': list(IRSConfig.R7D_LIST.keys()), 's3m': list(IRSConfig.S3M_LIST.keys())}
				self.curves['inst'] = irs.refIRSCurves(self.environment, self.curves[tenor_type], irs_ref, fallback_quotes=fallback_quotes)
				logger.info("Successfully built instantaneous curves")

	def _init_empty_forward_shifts(self):
		"""Initialize empty forward shift series as fallback."""
		self.forward_shift['r7d'] = pd.Series(dtype=float)
		self.forward_shift['s3m'] = pd.Series(dtype=float)
		logger.warning("Using empty forward shifts as fallback")

	def _index_to_days(self, index_labels, ref_date=None):
		"""Convert index labels like 'Today', '7D', '1M', '2Y' to integer days.
		
		Parameters
		----------
		index_labels : Index or iterable
			Labels to convert (e.g., ['Today', '7D', '1M', '2Y'])
		ref_date : datetime-like, optional
			Reference date to compute days from. If None, uses self.today_date.
		
		Returns
		-------
		pd.Index
			Integer days relative to ref_date
		"""
		import re
		
		if ref_date is None:
			ref_date = pd.Timestamp(self.today_date)
		else:
			ref_date = pd.Timestamp(ref_date)
		
		def label_to_days(lbl):
			if lbl == 'Today':
				return 0
			# Match patterns like '7D', '1M', '2Y'
			match = re.fullmatch(r'(\d+)([DMY])', str(lbl))
			if not match:
				# Try to parse as date directly
				try:
					date = pd.Timestamp(lbl)
					return (date - ref_date).days
				except:
					raise ValueError(f"Cannot parse label: {lbl}")
			
			num, unit = int(match.group(1)), match.group(2)
			if unit == 'D':
				target_date = ref_date + pd.Timedelta(days=num)
			elif unit == 'M':
				target_date = ref_date + pd.DateOffset(months=num)
			elif unit == 'Y':
				target_date = ref_date + pd.DateOffset(years=num)
			else:
				raise ValueError(f"Unknown unit: {unit}")
			
			return (target_date - ref_date).days
		
		days = [label_to_days(lbl) for lbl in index_labels]
		return pd.Index(days)

	def load_forward_shift_from_dashboard(self):
		"""Forward shifts are now managed via the web UI panel.
		
		This method is kept for backward compatibility but always initialises
		empty shifts so the refresher does not depend on Dashboard.xlsm being
		available or unlocked.
		"""
		logger.info("Using empty forward shifts (managed via web UI panel)")
		self._init_empty_forward_shifts()


	def apply_forward_shift_adjustments(self): 
		for ctype in IRSConfig.CURVE_TYPES:
			logger.info(f"Adjusting {ctype} curve with forward shifts")
			self.curves['inst'][ctype].adjFittingbyDate(self.forward_shift[ctype])
			self.curve_dictionary['instfit'][ctype]['adjSpotRate'] = self.curves['inst'][ctype].adjcurves['SpotRate']
			self.curve_dictionary['instfit'][ctype]['adjForwardRate'] = self.curves['inst'][ctype].adjcurves['ForwardRate']
		logger.info("Forward shift adjustments applied successfully")

	def price_contracts(self):
		logger.info("Pricing IRS contracts...")
		self.forward_data = irs.curves2Fixings(self.today_date, self.environment_time_series, self.curves['inst'])
		logger.info("Generated forward data from curves")
		
		self.r7d_forward = self.forward_data['fixing']['r7d'].loc[self.today_date:]
		self.s3m_forward = self.forward_data['fixing']['s3m'].loc[self.today_date:]
		logger.info(f"Extracted forward rates: R7D ({len(self.r7d_forward)} periods), S3M ({len(self.s3m_forward)} periods)")
		
		fallback_quotes = self._get_fallback_swap_quotes()
		self.quote_frame = irs.get_swap_quote_frame(self.environment['SwapRT'], IRSConfig.IRS_LIST, fallback_quotes=fallback_quotes)
		self.quote_rate = self.quote_frame['Mid']
		logger.info(f"Calculated quote rates for {len(self.quote_rate)} instruments")
		
		self.contracts = irs.evalueContract(self.today_date, self.quote_rate, self.forward_data, GeneralConfig.PSHIFT)
		logger.info("Evaluated IRS contracts")
		
		self.cv_irs = self.contracts['value'].loc[IRSConfig.IRS_LIST, 'FixRate'].to_frame().T
		self.qt_irs = pd.DataFrame([self.quote_rate.values], index=[0], columns=self.quote_rate.index)
		self.cv_spreads = irs.irsSpreads(self.cv_irs)
		self.qt_spreads = irs.irsSpreads(self.qt_irs)
		self.spreads_list = self.cv_spreads.columns
		logger.info(f"Calculated spreads for {len(self.spreads_list)} spread instruments")

	def price_contracts_with_shift(self):
		"""Price contracts using forward-shift adjusted curves."""
		logger.info("Pricing contracts with forward shift adjustments...")
		# Generate adjusted forward data using the fitted instantaneous curves
		self.forward_data_adjusted = irs.curves2Fixings(
			self.today_date, self.environment_time_series, self.curves['inst'], adj=True
		)
		# Re-evaluate contracts using adjusted forward data
		self.contracts_adjusted = irs.evalueContract(
			self.today_date, self.quote_rate, self.forward_data_adjusted, GeneralConfig.PSHIFT)
		# Extract adjusted fix rates
		self.cv_irs_adjusted = self.contracts_adjusted['value'].loc[IRSConfig.IRS_LIST, 'FixRate'].to_frame().T
		# Calculate spreads for adjusted curves
		self.cv_spreads_adjusted = irs.irsSpreads(self.cv_irs_adjusted)
		logger.info("Completed pricing with shift adjustments")

	def _interpolate_tbond_cbond_forward(self, bond_type: str):
		with open(os.path.join(DIR_INPUT, f"{bond_type}-fig.obj"), 'rb') as file:
			figure = pickle.load(file)
        
		x_src = np.asarray(figure['data'][1].x, dtype=float)
		y_src = np.asarray(figure['data'][1].y, dtype=float)
		sort_idx_src = np.argsort(x_src)
		x_src = x_src[sort_idx_src]
		y_src = y_src[sort_idx_src]

		target_index = self.curve_dictionary['instfit']['r7d'].index.values.astype(float)
		first_target_x = float(target_index[0])
		first_target_y = float(self.curve_dictionary['instfit']['r7d']['ForwardRate'].iloc[0])

		if not np.isclose(x_src, first_target_x).any():
			if first_target_x < x_src[0]:
				x_src = np.insert(x_src, 0, first_target_x)
				y_src = np.insert(y_src, 0, first_target_y)
			elif first_target_x > x_src[-1]:
				x_src = np.append(x_src, first_target_x)
				y_src = np.append(y_src, first_target_y)
			else:
				insert_pos = np.searchsorted(x_src, first_target_x)
				x_src = np.insert(x_src, insert_pos, first_target_x)
				y_src = np.insert(y_src, insert_pos, first_target_y)
		else:
			y_src[np.where(np.isclose(x_src, first_target_x))[0][0]] = first_target_y

		interpolated_values = np.interp(target_index, x_src, y_src)
		self.curve_dictionary['instfit']['r7d'][f"{bond_type}ForwardRate"] = interpolated_values
		# Also store SpotRate (data[0]) for carry/roll computation in the forward-curve plot
		x_spot = np.asarray(figure['data'][0].x, dtype=float)
		y_spot = np.asarray(figure['data'][0].y, dtype=float)
		sort_spot = np.argsort(x_spot)
		self.curve_dictionary['instfit']['r7d'][f"{bond_type}SpotRate"] = np.interp(
			target_index, x_spot[sort_spot], y_spot[sort_spot]
		)

	def plot_curves(self):
		logger.info("Generating curve plots...")
		for bond_type in ['TBond', 'CBond']:
			logger.info(f"Interpolating {bond_type} forward rates")
			self._interpolate_tbond_cbond_forward(bond_type)
		
		logger.info("Creating spot curve plot...")
		fig_spot = plotIRSSpotCurve(self.fixings, self.curve_dictionary)
		logger.info("Creating forward curve plot...")
		fig_forward = plotIRSForwardCurve(self.fixings, self.curve_dictionary, self.contracts['value'])

		logger.info("Saving curve plots...")
		with open(os.path.join(DIR_INPUT, 'IRS-spotfig.obj'), 'wb') as file_fig:
			pickle.dump(fig_spot, file_fig)
		with open(os.path.join(DIR_INPUT, 'IRS-forwardfig.obj'), 'wb') as file_fig:
			pickle.dump(fig_forward, file_fig)
		logger.info("Curve plots saved successfully")

	def compute_stats(self):
		"""Compute spreads statistics and forward rates."""
		logger.info("Computing statistics...")
		
		# Load existing statistics
		cvpx_stat = updatePKL({}, os.path.join(DIR_INPUT, 'IRS-pxspds.pkl'))
		spreads = cvpx_stat['StatInfo']
		logger.info(f"Loaded existing statistics for {len(spreads)} instruments")
		
		# Update pricing data
		spreads.loc[IRSConfig.IRS_LIST, 'CvPx'] = self.cv_irs.loc['FixRate']
		spreads.loc[self.spreads_list, 'CvPx'] = self.cv_spreads.loc['FixRate']
		spreads.loc[IRSConfig.IRS_LIST, 'QtPx'] = self.qt_irs.loc[0]
		spreads.loc[self.spreads_list, 'QtPx'] = self.qt_spreads.loc[0]
		if self.quote_frame is not None and not self.quote_frame.empty:
			spreads.loc[IRSConfig.IRS_LIST, 'Bid'] = self.quote_frame['Bid']
			spreads.loc[IRSConfig.IRS_LIST, 'Ofr'] = self.quote_frame['Ofr']
			try:
				spreads.loc[self.spreads_list, 'Bid'] = irs.irsQuoteComposite(
					self.spreads_list,
					self.quote_frame['Bid'],
					quote_side='Bid',
					opposite_cost=self.quote_frame['Ofr'],
				).round(4)
				spreads.loc[self.spreads_list, 'Ofr'] = irs.irsQuoteComposite(
					self.spreads_list,
					self.quote_frame['Ofr'],
					quote_side='Ofr',
					opposite_cost=self.quote_frame['Bid'],
				).round(4)
			except Exception as exc:
				logger.warning(f"Could not derive IRS spread bid/ofr quotes: {exc}")
		
		# Calculate spreads and Z-scores
		spreads['spread'] = spreads['QtPx']
		spreads.loc[IRSConfig.IRS_LIST, 'spread'] = spreads.loc[IRSConfig.IRS_LIST, 'QtPx'] - spreads.loc[IRSConfig.IRS_LIST, 'CvPx']
		spreads['Zscore'] = (spreads['spread'] - spreads['mean']) / spreads['vol']
		
		# Update changes in basis points
		spreads.loc[IRSConfig.IRS_LIST, 'Chg(bp)'] = (self.cv_irs_adjusted.loc['FixRate'] * 100).round(2)
		spreads.loc[self.spreads_list, 'Chg(bp)'] = (self.cv_spreads_adjusted.loc['FixRate'] * 100).round(2)
		
		# Update carry metrics
		for key in IRSConfig.CARRY_LIST:
			composite = irs.irsSpreadComposite(self.spreads_list, self.contracts['value'][key])
			spreads.loc[self.spreads_list, key] = composite.round(2)
			spreads.loc[IRSConfig.IRS_LIST, key] = self.contracts['value'].loc[IRSConfig.IRS_LIST, key].round(2)
	
		# Create time-based forward rates dataframe
		logger.info("Creating time-based forward rates dataframe...")
		today_ts = pd.Timestamp(self.today_date)
		time_periods = [today_ts]
		time_periods.extend([today_ts + pd.Timedelta(days=d) for d in [7, 14]])
		time_periods.extend([today_ts + pd.DateOffset(months=m) for m in range(1, 13)])
		time_periods.extend([today_ts + pd.DateOffset(years=y) for y in range(2, 11)])
		
		index_labels = ['Today', '7D', '14D']
		index_labels.extend([f'{m}M' for m in range(1, 13)])
		index_labels.extend([f'{y}Y' for y in range(2, 11)])
		
		# Get forward rates for each period
		r7d_forwards = []
		s3m_forwards = []
		for date in time_periods:
			if date in self.r7d_forward.index:
				r7d_forwards.append(self.r7d_forward.loc[date])
			else:
				pos = self.r7d_forward.index.get_indexer([date], method='nearest')[0]
				r7d_forwards.append(self.r7d_forward.iloc[pos])
			
			if date in self.s3m_forward.index:
				s3m_forwards.append(self.s3m_forward.loc[date])
			else:
				pos = self.s3m_forward.index.get_indexer([date], method='nearest')[0]
				s3m_forwards.append(self.s3m_forward.iloc[pos])
		
		time_based_df = pd.DataFrame({
			'Date': [date.strftime('%Y%m%d') for date in time_periods],
			'R7D_Forward': r7d_forwards,
			'S3M_Forward': s3m_forwards
		}, index=index_labels)
		time_based_df.index.name = 'Term'

		# Save forward rate table so the web dashboard can read it without touching Dashboard.xlsm
		try:
			with open(os.path.join(DIR_INPUT, 'IRS-forward.pkl'), 'wb') as _f:
				import pickle as _pickle
				_pickle.dump(time_based_df, _f)
		except Exception as _e:
			logger.warning(f"Could not save IRS-forward.pkl: {_e}")

		logger.info("Statistics computation completed")
		return spreads, time_based_df

	def save_to_dashboard(self, spreads, time_based_df):
		"""Save spreads and forward rates to Dashboard.xlsm (optional).
		
		Skipped silently when the file is absent or locked — all web-facing
		pickle files (IRS-forward.pkl, IRS-spdsrt.pkl) are already written
		by this point and do not depend on Excel.
		"""
		logger.info("Writing data to Dashboard.xlsm...")
		dashboard_path = PATH.parent.joinpath('Dashboard.xlsm').resolve()
		
		if not dashboard_path.exists():
			logger.warning(f"Dashboard.xlsm not found — skipping Excel write: {dashboard_path}")
			return
		
		# Check if file is already open by another Excel instance
		try:
			existing_wb = None
			for app in xw.apps:
				for book in app.books:
					if book.fullname.lower() == str(dashboard_path).lower():
						logger.warning(f"Dashboard.xlsm is already open in another Excel instance")
						existing_wb = book
						break
				if existing_wb:
					break
			
			if existing_wb:
				logger.info("Using already open Dashboard.xlsm instance")
				wb = existing_wb
				app = wb.app
				should_close = False
			else:
				app = xw.App(visible=False, add_book=False)
				app.display_alerts = False
				app.screen_updating = False
				logger.info("Opening Dashboard.xlsm...")
				wb = app.books.open(str(dashboard_path), update_links=False, read_only=False)
				should_close = True
			
			original_calc = app.calculation
			app.calculation = 'manual'
			
			try:
				# Write spreads to SwapData sheet
				logger.info("Writing spreads data to SwapData sheet...")
				try:
					ws_swapdata = wb.sheets['SwapData']
				except:
					ws_swapdata = wb.sheets.add('SwapData')
				
				ws_swapdata.clear_contents()
				ws_swapdata.range('A1').options(index=True).value = spreads
				logger.info("Successfully wrote spreads data")
				
				# Write time-based data to Main sheet
				logger.info("Writing time-based data to Main sheet...")
				ws_main = wb.sheets['Main']
				
				# Convert DataFrame to simple types to avoid COM conversion issues
				time_based_clean = time_based_df.copy()
				# Convert index to column so we can control the write
				time_based_clean = time_based_clean.reset_index()
				
				# Convert all numeric columns to float (avoid numpy types that COM can't handle)
				for col in time_based_clean.columns:
					if time_based_clean[col].dtype in ['float64', 'int64']:
						time_based_clean[col] = time_based_clean[col].astype(float)
					elif time_based_clean[col].dtype == 'object':
						time_based_clean[col] = time_based_clean[col].astype(str)
				
				# Write header separately
				ws_main.range('M2').value = list(time_based_clean.columns)
				
				# Write data rows starting at M3
				ws_main.range('M3').value = time_based_clean.values.tolist()
				logger.info("Successfully wrote time-based data")
				
				logger.info("Saving Dashboard.xlsm...")

				wb.save()
				logger.info("Dashboard saved successfully")
				
			finally:
				app.calculation = original_calc
				app.screen_updating = True
				if should_close:
					try:
						wb.close()
						app.quit()
					except:
						pass
						
		except Exception as e:
			logger.warning(f"Could not write to Dashboard.xlsm (skipping): {e}")

	def save_rt_pickle(self, spreads):
		logger.info("Saving real-time data to pickle file...")
		swaps_rt = self.contracts['value'].copy()
		if self.quote_frame is not None and not self.quote_frame.empty:
			for col in ['Bid', 'Ofr']:
				swaps_rt.loc[self.quote_frame.index, col] = self.quote_frame[col]
			swaps_rt.loc[self.quote_frame.index, 'Quote'] = self.quote_frame['Mid']
		irs_rt = {
			'swaps': swaps_rt,
			'spreads': spreads
		}
		save_frame(irs_rt, os.path.join(DIR_INPUT, 'IRS-spdsrt.pkl'))
		logger.info("Real-time data saved to IRS-spdsrt.pkl")

	def run(self):
		logger.info(f"Starting IRS curve refresh process at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
		logger.info(f"Processing date: {self.today_date}")
		try:
			self.load_environment_and_series()
			self.load_close_curves()
			self.build_instantaneous_curves()
			self.load_forward_shift_from_dashboard()
			self.apply_forward_shift_adjustments()
			self.price_contracts()
			self.price_contracts_with_shift()
			self.plot_curves()
			spreads, time_based_df = self.compute_stats()
			self.save_to_dashboard(spreads, time_based_df)
			self.save_rt_pickle(spreads)
			# Build normalized alpha snapshot for Atlas UI candidate scanning.
			# Keep this non-fatal to avoid breaking the refresh pipeline.
			try:
				from curves.refreshers.alpha import save_alpha_spreads_snapshot
				save_alpha_spreads_snapshot(DIR_INPUT, rewrite=True)
				logger.info("Saved Alpha-spreadsrt.pkl")
			except Exception as e:
				logger.warning(f"Failed to build Alpha-spreadsrt.pkl: {e}")
			
			logger.info(f"Successfully completed IRS curve refresh at {datetime.now().strftime('%H:%M:%S')}")
			print('\nFinish refreshing Swap Curve at：', datetime.now().strftime("%H:%M:%S"))
			
		except Exception as e:
			logger.error(f"Error during IRS curve refresh: {e}")
			logger.exception("Full traceback:")
			raise

	@classmethod
	def main(cls):
		"""Main entry point for the IRSRefresher"""
		logger.info("Initializing IRSRefresher...")
		try:
			instance = cls()
			instance.run()
			logger.info("IRSRefresher completed successfully")
		except Exception as e:
			logger.error(f"IRSRefresher failed: {e}")
			logger.exception("Full traceback:")
			raise

#%
if __name__== '__main__':
	IRSRefresher.main()