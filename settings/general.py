#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
General application configuration, including dates and app constants.
"""
import pandas as pd
import datetime
from dateutil.relativedelta import relativedelta
from .paths import DIR_INPUT

app_color = {"graph_bg": "#082255", "graph_line": "#007ACE"}


class GeneralConfig:
    N_CORE = 6
    DSHIFT = 1
    PSHIFT = 1
    STAT_WINDOW = 3
    SIGMA_WINDOW_MONTHS = 1
    MIN_MATURITY = 0.7
    MAX_MATURITY = 10.0
    OUTER = 1.0
    INNER = 0.02
    GAMMA = 0.62
    MODEL_TYPE = 'Model A'
    CALC_TYPE = 'Matrix'
    YN = 365
    YN1 = 360

    @classmethod
    def load_calendar(cls) -> pd.DataFrame:
        return pd.read_pickle(DIR_INPUT.joinpath('calendar.pkl'))
    
    # App colors
    app_color = {"graph_bg": "#082255", "graph_line": "#007ACE"}


class DateConfig:
    @classmethod
    def get_date_mappings(cls):
        today = datetime.datetime.today()
        return {
            'd': today,
            'dp': today - pd.offsets.BDay(GeneralConfig.DSHIFT),
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


