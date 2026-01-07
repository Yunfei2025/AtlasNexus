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
from settings.paths import DIR_DATA
from curves.utils.file import updatePKL
from data.providers.retrieve import _wst, _wss
from settings.general import DateConfig

# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()


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
                temp = _wst(f, "last,ask,bid,volume", ds)
                if temp.shape[0] > 10:
                    tick_dict[d.date()] = temp
        tick_dict = updatePKL(tick_dict, file_path)

def get_contract_no():
    tlist = [ f+".CFE" for f in FuturesConfig.CONTRACT_TYPES ]
    flist =  tlist +FuturesConfig.SYMBOLS
    clist = _wss(flist, "trade_hiscode,", "tradeDate="+_date_strs["d"])
    clist_ = clist.squeeze().tolist()
    return clist_