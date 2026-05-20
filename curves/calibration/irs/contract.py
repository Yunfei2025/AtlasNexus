# -*- coding: utf-8 -*-
"""IRS contract definition and valuation."""

from datetime import date
from typing import List

import pandas as pd
from dateutil.relativedelta import relativedelta

from settings.general import GeneralConfig
from curves.affine.pricingYield import pricing, pricingYield, scheduleDate, floaters


class IRSContract:
    """Enhanced IRS Contract with better structure and validation."""

    def __init__(self, start_date: date, end_date: date, quote: float,
                 curve_type: str, frequency: int):
        """
        Initialize IRS contract.

        Parameters:
        -----------
        start_date : date
            Contract start date
        end_date : date
            Contract maturity date
        quote : float
            Fixed rate quote (in percentage)
        curve_type : str
            Curve type ('r7d' or 's3m')
        frequency : int
            Payment frequency (0 for short-term, 4 for standard)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.quote = quote
        self.curve_type = curve_type
        self.frequency = frequency

        self.schedule = scheduleDate(start_date, end_date, curve_type, frequency)

        ytm = pricingYield(self.schedule[0], quote, self.schedule, 4, 100)
        _, _, self.duration, self.convexity = pricing(
            self.schedule[0], quote, self.schedule, 4, ytm
        )

        self.cashflow = None
        self.fix_rate = None
        self.pnl_realised = None
        self.pnl_predicted = None
        self.pnl_predicted_dc = None
        self.pnl_total = None
        self.value = None
        self.pv_sum = None

    def valuation(self, notional: float, valuation_date: date,
                  fixing_series: pd.Series, spot_series: pd.Series):
        """
        Perform contract valuation.

        Parameters:
        -----------
        notional : float
            Contract notional amount
        valuation_date : date
            Date of valuation
        fixing_series : pd.Series
            Forward fixing rates indexed by date (built from smooth affine
            forward curve `curves['ForwardRate']` for the bulk; anchor only
            contributes for tenors < 0.25y where the short end is pinned to
            actual market fixing rates).
        spot_series : pd.Series
            Spot rates indexed by date (built from smooth affine
            `curves['SpotRate']` for the bulk; anchor for tenors <= 0.3y).
        """
        cashflow = pd.DataFrame(index=self.schedule[:-1])
        P = notional

        for i in range(len(self.schedule) - 1):
            s = self.schedule[i]
            s1 = self.schedule[i + 1]

            N = P * 1e4 if i == len(self.schedule) - 2 else 0

            cashflow.loc[s, 'CashFlowType'] = "Set" if s1 <= valuation_date else "Predicted"

            fdays = floaters(s, s1, 7)
            idx = [fixing_series.index.get_indexer([d], method="ffill")[0] for d in fdays]
            fs = fixing_series.iloc[idx]

            interval = (s1 - s).days / GeneralConfig.YN
            cashflow.loc[s, 'Fixing'] = fs.iloc[0]
            cashflow.loc[s, 'FixingDate'] = fs.index[0]

            if self.curve_type == 'r7d':
                r0 = self._calculate_r7d_floating(s, s1, fs, fdays)
            elif self.curve_type == 's3m':
                r0 = 1 + fs.iloc[0] * interval * GeneralConfig.YN / GeneralConfig.YN1 / 100

            cashflow.loc[s, 'Floating'] = 100 * (r0 - 1) / interval
            cashflow.loc[s, 'CashFlow(Float)'] = 1e4 * P * (r0 - 1) + N
            cashflow.loc[s, 'CashFlow(Fixed)'] = 100 * P * self.quote * interval + N
            cashflow.loc[s, 'PayDate'] = s1
            cashflow.loc[s, 'Interval'] = interval

        cashflow['CashFlow(NetPay)'] = cashflow['CashFlow(Float)'] - cashflow['CashFlow(Fixed)']

        schedule_set = list(cashflow[cashflow['CashFlowType'] == "Set"].index)
        schedule_fwd = list(cashflow[cashflow['CashFlowType'] == "Predicted"].index)

        cashflow['DF'] = 1.0
        cashflow['TermRes'] = 0.0
        cashflow['SpotRate'] = 0.0

        # Incremental running sum keeps the bootstrap O(N).
        interval_vals = cashflow['Interval'].to_numpy(dtype=float)
        df_vals = cashflow['DF'].to_numpy(dtype=float).copy()
        fwd_offset = len(cashflow) - len(schedule_fwd)
        sum_term = 0.0

        for i, s in enumerate(schedule_fwd):
            s1 = cashflow.loc[s, 'PayDate']
            res = (s1 - valuation_date).days / GeneralConfig.YN
            cashflow.loc[s, 'TermRes'] = res

            idx = spot_series.index.get_indexer([s1], method="ffill")[0]
            spot = spot_series.iloc[idx] / 100
            cashflow.loc[s, 'SpotRate'] = spot * 100

            if i == 0:
                new_df = 1 / (1 + spot * res * GeneralConfig.YN / GeneralConfig.YN1)
            else:
                new_df = (1 - spot * sum_term) / (1 + spot * cashflow.loc[s, 'Interval'])
            cashflow.loc[s, 'DF'] = new_df
            df_vals[fwd_offset + i] = new_df
            sum_term += interval_vals[i] * df_vals[i]

        cashflow['PV(Float)'] = cashflow['CashFlow(Float)'] * cashflow['DF']
        cashflow['PV(Fixed)'] = cashflow['CashFlow(Fixed)'] * cashflow['DF']
        cashflow['PV(NetPay)'] = cashflow['CashFlow(NetPay)'] * cashflow['DF']

        pv_sum = cashflow[[
            'CashFlow(Float)', 'CashFlow(Fixed)', 'CashFlow(NetPay)',
            'PV(Float)', 'PV(Fixed)', 'PV(NetPay)'
        ]].sum(axis=0)

        ND = P * 1e4 * cashflow['DF'].iloc[-1]
        temp = (cashflow['Interval'] * cashflow['DF']).sum()
        floating_leg = cashflow['PV(Float)'].sum() - ND

        self.fix_rate = floating_leg / temp / P / 100
        self.pnl_realised = cashflow.loc[schedule_set, 'CashFlow(NetPay)'].sum() if schedule_set else 0
        self.pnl_predicted = cashflow.loc[schedule_fwd, 'CashFlow(NetPay)'].sum() if schedule_fwd else 0
        self.pnl_predicted_dc = (
            cashflow.loc[schedule_fwd, 'CashFlow(NetPay)'] *
            cashflow.loc[schedule_fwd, 'DF']
        ).sum() if schedule_fwd else 0
        self.pnl_total = self.pnl_realised + self.pnl_predicted
        self.value = self.pnl_realised + self.pnl_predicted_dc
        self.cashflow = cashflow
        self.pv_sum = pv_sum

    def _calculate_r7d_floating(self, s: date, s1: date, fs: pd.Series, fdays: List[date]) -> float:
        """Calculate R7D floating accrual using actual overlap days for each reset."""
        r0 = 1.0
        for fixing_date, rate in zip(fdays, fs):
            period_start = max(s, fixing_date)
            period_end = min(s1, fixing_date + relativedelta(days=7))
            day_count = (period_end - period_start).days
            if day_count <= 0:
                continue
            r0 *= (1 + rate * day_count / GeneralConfig.YN1 / 100)
        return r0

    @property
    def PnL(self):
        """Alias for total PnL."""
        return self.pnl_total

    @property
    def Value(self):
        """Alias for contract value."""
        return self.value

    @property
    def fixrate(self):
        """Alias for fix rate."""
        return self.fix_rate

    @property
    def cov(self):
        """Alias for convexity."""
        return self.convexity


def irsContract(start_date, end_date, quote, curve_type, frequency):
    """Create IRS contract (legacy wrapper)."""
    return IRSContract(start_date, end_date, quote, curve_type, frequency)
