"""Helper functions for futures price/volume processing used in Dash callbacks."""

from __future__ import annotations

import os
import sys
import pandas as pd
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from settings.futures import FuturesConfig
from settings.paths import DIR_DATA, DIR_INPUT
from curves.utils.file import updatePKL
from data.providers.retrieve import _wst, _wss, _wsd
from settings.general import DateConfig, GeneralConfig

# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()


def _file_mtime_date(file_path: str):
    if not os.path.exists(file_path):
        return None
    return pd.Timestamp(os.path.getmtime(file_path), unit='s').date()


def _is_updated_today(file_path: str) -> bool:
    return _file_mtime_date(file_path) == _dates['d']


def _force_update_requested(cfg=None) -> bool:
    return bool(getattr(cfg, "params", {}).get("force_update", False))


def retrieveTick(date, futures):
    from WindPy import w
    w.start()
    tick = w.wst(
        futures,
        "last,ask,bid,volume",
        date + " 09:00:00",
        date + " 15:15:00",
        "",
        usedf=True,
    )[1]
    tick = tick.drop(tick.index[0])
    tick = tick.set_index(pd.DatetimeIndex(pd.to_datetime(tick.index)))
    tick['volume'] = tick['volume'].diff(1)
    tick = tick.dropna()
    return tick

def retrieveFuturesTick():
    day_list = pd.bdate_range(_date_strs['d1m'], _date_strs['dp'])
    day_list = [ d.date() for d in day_list ]
    # for f in FuturesConfig.get_ticker_list():
    clist = get_contract_no()
    for f in clist:
        tick_dict = {}
        file_path = os.path.join(DIR_DATA, 'futures', f.split('.')[0] + '.pkl')
        tick_dict = updatePKL(tick_dict, file_path)
        for d in day_list:
            if d not in tick_dict.keys():
                ds = d.strftime('%Y-%m-%d')
                print("Updating ", f, ds)
                temp = _wst(f, "last,ask,bid,volume", ds)
                if temp.shape[0] > 10:
                    tick_dict[d] = temp
        try:
            print("Saving ", f)
            tick_dict = updatePKL(tick_dict, file_path)
        except Exception as e:
            print(f"Error updating {file_path}: {e}")

def get_contract_no():
    tlist = [ f+".CFE" for f in FuturesConfig.CONTRACT_TYPES ]
    flist =  FuturesConfig.SYMBOLS
    clist = _wss(flist, "trade_hiscode,", "tradeDate="+_date_strs["d"])
    clist_ = clist.squeeze().tolist()
    return clist_

def futuresDailyK(cfg=None):
    # 设置合约代码，例如10年期国债期货主力合约代码
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    force_update = _force_update_requested(cfg)
    if _is_updated_today(file_path) and not force_update:
        print(f"{file_path} was updated today, skipping futuresDailyK().")
        return

    flist = FuturesConfig.SYMBOLS
    dps = _date_strs['dp']
    starts = _date_strs['d7d'] if GeneralConfig.DSHIFT == 1 else _date_strs['d1m']
    data_dict = {}
    for f in flist:
        data = _wsd(f, "open,high,low,close,volume", starts, dps)
        data.columns = [a.capitalize() for a in data.columns]
        data_dict[f] = data
    updatePKL(data_dict, file_path)


def retrieveFuturesDailyK(cfg=None):
    futuresDailyK(cfg)


def retrieveMarcoPx(cfg=None):
    file_path = os.path.join(DIR_INPUT, 'macro-px.pkl')
    force_update = _force_update_requested(cfg)
    if _is_updated_today(file_path) and not force_update:
        print(f"{file_path} was updated today, skipping retrieveMarcoPx().")
        return

    print("Updating macroeconomic time series...")
    from factors.config import MACRO_SYMBOLS

    starts = _date_strs['d7d'] if GeneralConfig.DSHIFT == 1 else _date_strs['d1m']
    dps = _date_strs['dp']
    macro_ts = {}
    for macro_name, symbol in MACRO_SYMBOLS.items():
        macro_ts[macro_name] = _wsd(symbol, "close", starts, dps)
    updatePKL(macro_ts, file_path)

