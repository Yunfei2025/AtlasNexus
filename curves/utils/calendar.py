# -*- coding: utf-8 -*-
"""
Created on Wed Aug 10 13:59:10 2022

@author: 马云飞
"""

import datetime as dt
import json
import pandas as pd
import re
import requests
import warnings
from chinese_calendar import get_holiday_detail, is_holiday, is_workday
from dateutil.relativedelta import relativedelta

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


def _fetch_remote_calendar(year):
    frames = []
    up1 = 'https://sp1.baidu.com/8aQDcjqpAAV3otqbppnN2DJv/api.php?tn=wisetpl&format=json&resource_id=39043&query='
    up2 = '月&t=1642579711570&cb=op_aladdin_callback1642579711570'

    for month in range(1, 13):
        url = ''.join([up1, str(year), '年', str(month), up2])
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        parts = re.split(r'[()]', response.text, maxsplit=2)
        if len(parts) < 2:
            raise ValueError(f'Unexpected calendar payload for {year}-{month:02d}')

        payload = json.loads(parts[1])
        month_data = pd.DataFrame(payload['data'])
        almanac = pd.DataFrame(month_data['almanac'][0])
        almanac = almanac[almanac['month'] == str(month)].copy()
        almanac['date'] = pd.to_datetime(almanac['year'] + '/' + almanac['month'] + '/' + almanac['day'])
        almanac['weekday'] = almanac['date'].dt.dayofweek + 1

        if 'status' in almanac.columns:
            almanac['status'] = pd.to_numeric(almanac['status'], errors='coerce').fillna(0).astype(int)
            judge = (almanac['weekday'] >= 6).astype(int) + almanac['status']
            almanac['Holiday'] = ((judge == 1) | (judge == 2)).astype(bool)
        else:
            almanac['Holiday'] = (almanac['weekday'] >= 6).astype(bool)

        detail_col = None
        for candidate in ['term', 'desc', 'cnDay']:
            if candidate in almanac.columns:
                detail_col = candidate
                break

        almanac['Detail'] = almanac[detail_col].where(almanac['Holiday'], None) if detail_col else None
        frames.append(almanac[['date', 'Holiday', 'Detail']])

    calendar_frame = pd.concat(frames, ignore_index=True).drop_duplicates(subset=['date']).set_index('date').sort_index()
    return calendar_frame


def _get_calendar_frame(year):
    if year in _CALENDAR_CACHE:
        return _CALENDAR_CACHE[year]

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
        try:
            frame = _fetch_remote_calendar(year)
        except Exception:
            frame = _build_weekend_calendar(year)

    _CALENDAR_CACHE[year] = frame
    return frame


def is_cn_holiday(target_date):
    date_value = _to_date(target_date)
    try:
        return is_holiday(date_value)
    except NotImplementedError:
        frame = _get_calendar_frame(date_value.year)
        return bool(frame.loc[pd.Timestamp(date_value), 'Holiday'])


def is_cn_workday(target_date):
    date_value = _to_date(target_date)
    try:
        return is_workday(date_value)
    except NotImplementedError:
        frame = _get_calendar_frame(date_value.year)
        return not bool(frame.loc[pd.Timestamp(date_value), 'Holiday'])


def get_cn_holiday_detail(target_date):
    date_value = _to_date(target_date)
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
