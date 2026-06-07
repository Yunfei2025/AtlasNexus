# -*- coding: utf-8 -*-
"""
Created on Wed Aug 10 13:59:10 2022

@author: 马云飞
"""

import datetime as dt
import json
import pandas as pd
import re
import warnings
from dateutil.relativedelta import relativedelta

try:
    from chinese_calendar import get_holiday_detail, is_holiday, is_workday
    _CHINESE_CALENDAR_AVAILABLE = True
except ImportError:
    _CHINESE_CALENDAR_AVAILABLE = False

    def get_holiday_detail(target_date):
        raise NotImplementedError

    def is_holiday(target_date):
        raise NotImplementedError

    def is_workday(target_date):
        raise NotImplementedError

warnings.filterwarnings("ignore")

_CALENDAR_CACHE = {}


def _to_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value


def _weekend_is_holiday(target_date):
    return _to_date(target_date).weekday() >= 5


def _build_weekend_calendar(year):
    dates = pd.date_range(start=f'{year}-01-01', end=f'{year}-12-31', freq='D')
    holidays = [_weekend_is_holiday(d) for d in dates]
    details = ['Weekend fallback' if flag else None for flag in holidays]
    return pd.DataFrame({'Holiday': holidays, 'Detail': details}, index=dates)

def _get_calendar_frame(year):
    if year in _CALENDAR_CACHE:
        return _CALENDAR_CACHE[year]

    if not _CHINESE_CALENDAR_AVAILABLE:
        frame = _build_weekend_calendar(year)
    else:
        try:
            dates = pd.date_range(start=f'{year}-01-01', end=f'{year}-12-31', freq='D')
            holidays = [is_holiday(d.date()) for d in dates]
            details = []
            for current_date, holiday_flag in zip(dates, holidays):
                if holiday_flag:
                    details.append(get_holiday_detail(current_date.date())[1])
                else:
                    details.append(None)
            frame = pd.DataFrame({'Holiday': holidays, 'Detail': details}, index=dates)
        except NotImplementedError:
            frame = _build_weekend_calendar(year)

    _CALENDAR_CACHE[year] = frame
    return frame


def is_cn_holiday(target_date):
    date_value = _to_date(target_date)
    if not _CHINESE_CALENDAR_AVAILABLE:
        return _weekend_is_holiday(date_value)
    try:
        return is_holiday(date_value)
    except NotImplementedError:
        frame = _get_calendar_frame(date_value.year)
        return bool(frame.loc[pd.Timestamp(date_value), 'Holiday'])


def is_cn_workday(target_date):
    date_value = _to_date(target_date)
    if not _CHINESE_CALENDAR_AVAILABLE:
        return not _weekend_is_holiday(date_value)
    try:
        return is_workday(date_value)
    except NotImplementedError:
        frame = _get_calendar_frame(date_value.year)
        return not bool(frame.loc[pd.Timestamp(date_value), 'Holiday'])


def get_cn_holiday_detail(target_date):
    date_value = _to_date(target_date)
    if not _CHINESE_CALENDAR_AVAILABLE:
        holiday_flag = _weekend_is_holiday(date_value)
        detail = 'Weekend fallback' if holiday_flag else None
        return holiday_flag, detail
    try:
        return get_holiday_detail(date_value)
    except NotImplementedError:
        frame = _get_calendar_frame(date_value.year)
        holiday_flag = bool(frame.loc[pd.Timestamp(date_value), 'Holiday'])
        detail = frame.loc[pd.Timestamp(date_value), 'Detail'] if holiday_flag else None
        return holiday_flag, detail

def getScheduleDays(day,curve_type,standard=True):
    ends = {}
    if standard:
        if curve_type == 'r7d':
            ends['7D'] = day + relativedelta(days=7)
            ends['1M'] = day + relativedelta(months=1)
        #if curve_type == 's3m':
        ends['3M'] = day + relativedelta(months=3)
        ends['6M'] = day + relativedelta(months=6)
        ends['9M'] = day + relativedelta(months=9)
        for i in range(10):
            ends[str(i + 1) + 'Y'] = day + relativedelta(years=i + 1)
        # else:
        #     pass
        days = pd.Series()
        for k in ends.keys():
            days.loc[k] = (ends[k] - day).days
    else:    
        nsts = []
        if not standard:
            nst = day
            if curve_type == 'r7d':
                nsts.append(day+ relativedelta(days=7))
                nsts.append(day + relativedelta(months=1))
            for i in range(10*4):
                nst = nst + relativedelta(months=3)
                nsts.append(nst)
        days = [ (d - day).days for d in nsts ]        
        days = pd.Series(days)
    return days

def getCalendar(year):
    return _get_calendar_frame(year)['Holiday']

def getNextTradingDate(Cal,datelist=None):
    if datelist is None:
        datelist = Cal
    adjlist = []
    for d in datelist:
        while not is_cn_workday(pd.Timestamp(d).date()):
            d += relativedelta(days=1)
        adjlist.append(d)
    return adjlist
