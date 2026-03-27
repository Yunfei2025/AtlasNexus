import os
import datetime as dt
from settings.paths import DIR_INPUT
from settings.general import DateConfig, GeneralConfig
from data.providers.retrieve import _wsd
from curves.utils.file import updatePKL


# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()


def _file_mtime_date(file_path: str):
    if not os.path.exists(file_path):
        return None
    return dt.datetime.fromtimestamp(os.path.getmtime(file_path)).date()


def _is_updated_today(file_path: str) -> bool:
    return _file_mtime_date(file_path) == dt.datetime.today().date()


def _force_update_requested(cfg=None) -> bool:
    return bool(getattr(cfg, "params", {}).get("force_update", False))

def futuresDailyK(cfg=None):
    # 设置合约代码，例如10年期国债期货主力合约代码
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    force_update = _force_update_requested(cfg)
    if _is_updated_today(file_path) and not force_update:
        print(f"{file_path} was updated today, skipping futuresDailyK().")
        return

    contract_code = ["TS.CFE", "TF.CFE", "T.CFE", "TL.CFE"]
    dps = _date_strs['dp']
    starts = _date_strs['d7d'] if GeneralConfig.DSHIFT == 1 else _date_strs['d1m']
    data_dict = {}
    for f in contract_code:
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
