import os
import datetime as dt
from settings.paths import DIR_INPUT
from settings.general import DateConfig, GeneralConfig
from data.providers.retrieve import _wsd
from curves.utils.file import updatePKL


# Localized new-config convenience variables
_dates = DateConfig.get_date_mappings()
_date_strs = DateConfig.get_date_strings()

def futuresDailyK():
    # 设置合约代码，例如10年期国债期货主力合约代码
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    # Check if file was updated today
    if os.path.exists(file_path):
        mtime = os.path.getmtime(file_path)
        file_date = dt.datetime.fromtimestamp(mtime).date()
        today = dt.datetime.today().date()
        if file_date == today:
            print(f"{file_path} was updated today, skipping futuresDailyK().")
        else:
            contract_code = ["TS.CFE","TF.CFE","T.CFE","TL.CFE"]
            # 设置日期范围
            dps = _date_strs['dp']
            if GeneralConfig.DSHIFT == 1:
                starts = _date_strs['d7d']
            else:
                starts = _date_strs['d1m']
            data_dict = {}
            # 获取日频历史K线数据
            for f in contract_code:
                data = _wsd(f, "open,high,low,close,volume", starts, dps)
                data.columns = [a.capitalize() for a in data.columns]
                data_dict[f] = data
            data_dict = updatePKL(data_dict, file_path)
    else:
        print("Futures daily K data file missing.")

def retrieveMarcoPx():
    file_path = os.path.join(DIR_INPUT, 'macro-px.pkl')
    today_str = dt.datetime.now().strftime('%Y-%m-%d')
    # Check if file exists and was created today
    file_ctime = dt.datetime.fromtimestamp(os.path.getctime(file_path)).strftime('%Y-%m-%d')
    macro_ts = {}
    if file_ctime != today_str:
        print("Updating macroeconomic time series...")
        from factors.config import MACRO_SYMBOLS
        if GeneralConfig.DSHIFT == 1:
            starts = "20251020"#_date_strs['d7d']
        else:
            starts = _date_strs['d1m']
        dps = "20251120"#_date_strs['dp']
        for m in MACRO_SYMBOLS.keys():
            macro_ts[m] = _wsd(MACRO_SYMBOLS[m], "close", starts, dps)
        macro_ts = updatePKL(macro_ts, file_path)
