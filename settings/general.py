#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
General application configuration, including dates and app constants.
"""
import datetime
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Optional
from curves.utils.cn_calendar import is_cn_workday, is_cn_holiday, get_cn_holiday_detail
from .paths import PATH, DIR_INPUT, DIR_OUTPUT, DIR_DATA, DIR_MODELS

app_color = {"graph_bg": "#082255", "graph_line": "#007ACE"}


class TradingHoursConfig:
    START_HOUR: int = 9
    END_HOUR: int = 22 #17
    CREDIT_START_HOUR: int = 10
    CREDIT_END_HOUR: int = 12
    INIT_END_HOUR: int = 18 # 18
    WEEKDAYS_ONLY: bool = True 


class GeneralConfig:
    N_CORE = 6
    DSHIFT = 1
    PSHIFT = 1
    STAT_WINDOW = 12
    SIGMA_WINDOW_MONTHS = 3
    # MIN_MATURITY / MAX_MATURITY moved to settings.fixed_income.BondConfig
    # (PRICING_MIN_TTM / PRICING_MAX_TTM) — they are bond-curve specific.
    OUTER = 1.0
    INNER = 0.02
    GAMMA = 0.62
    MODEL_TYPE = 'Model A'
    CALC_TYPE = 'Matrix'
    YN = 365
    YN1 = 360


class DateConfig:
    @staticmethod
    def _to_date(dt: datetime.date) -> datetime.date:
        if isinstance(dt, datetime.datetime):
            return dt.date()
        return dt

    @classmethod
    def is_cn_holiday(cls, dt: datetime.date) -> bool:
        return is_cn_holiday(cls._to_date(dt))

    @classmethod
    def is_cn_workday(cls, dt: datetime.date) -> bool:
        return is_cn_workday(cls._to_date(dt))

    @classmethod
    def cn_holiday_detail(cls, dt: datetime.date):
        return get_cn_holiday_detail(cls._to_date(dt))

    @classmethod
    def prev_cn_workday(cls, dt: datetime.date) -> datetime.date:
        d = cls._to_date(dt)
        while not cls.is_cn_workday(d):
            d -= datetime.timedelta(days=1)
        return d

    @classmethod
    def get_date_mappings(cls, asof: Optional[date] = None):
        """Return date mappings anchored to *asof* (defaults to today).

        Pass an explicit date when running historical EOD calibrations to avoid
        lookahead bias — all derived dates will be relative to *asof*, never
        past it.
        """
        if asof is None:
            today = datetime.datetime.today()
        else:
            today = datetime.datetime.combine(asof, datetime.time.min)
        d_prev = cls.prev_cn_workday(today.date() - datetime.timedelta(days=1))
        return {
            'd': today,
            'dp': datetime.datetime.combine(d_prev, datetime.time.min),
            'd2d': today - relativedelta(days=2),
            'd7d': today - relativedelta(days=7),
            'd1m': today - relativedelta(months=1),
            'd3m': today - relativedelta(months=3),
            'd6m': today - relativedelta(months=6),
            'd1y': today - relativedelta(years=1),
            'd10y': today - relativedelta(years=10)
        }

    @classmethod
    def get_date_strings(cls):
        dates = cls.get_date_mappings()
        return {k: v.strftime("%Y%m%d") for k, v in dates.items()}


