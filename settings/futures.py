#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Futures-related configuration parameters.
"""
import datetime
from typing import List
import sys
import os

# Allow this module to be executed directly (python settings/futures.py)
# by ensuring the project root is importable.
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
    
from settings.general import DateConfig
from data.providers.retrieve import _wss
from settings.paths import DIR_INPUT

class FuturesConfig:
    SEASON_MAP = {0: '03', 1: '06', 2: '09', 3: '12'}
    CONTRACT_TYPES = ['T', 'TL', 'TF', 'TS']
    INTERVAL_LIST = ['1Min', '2Min', '5Min']
    CRITERIA_LIST = [1, 2, 4]
    SEASONS = {'本季': 'NQ1', '近季': 'NQ2', '远季': 'NQ3'}
    SYMBOLS = [
        'T.CFE', 
        'TL.CFE', 
        'TF.CFE', 
        'TS.CFE',
        'IF.CFE',
        'IC.CFE',
        'IH.CFE',
        'IM.CFE',
        'AU.SHF',
        'AG.SHF',
        'CU.SHF',
        'AL.SHF',
        'ZN.SHF',
        'RB.SHF',
        'LC.GFE',  # 碳酸锂 广期所
        'SA.CZC',  # 纯碱 郑商所
        'SC.INE',  # 原油 上期能源
        'JM.DCE',
        'EC.INE',  # 集运指数 上期能源
    ]
    VOL_SYMBOLS = [
        '000016.SH',
        '000300.SH',
        '000852.SH',
        'AU.SHF',
        'AG.SHF',
        'CU.SHF',
        'SA.CZC',  # 纯碱 郑商所
        'SC.INE',  # 原油 上期能源
        'LC.GFE',
        'RB.SHF',
    ]
    @classmethod
    def get_ticker_list(cls) -> List[str]:
        today = datetime.datetime.today()
        year = today.year
        season = today.month // 4
        if today > datetime.datetime(today.year, (season + 1) * 3, 15):
            season += 1
        ticker_list = []
        count = 0
        while count < 3:
            for contract_type in cls.CONTRACT_TYPES:
                if season <= 3:
                    ticker_list.append(f"{contract_type}{str(year)[2:]}{cls.SEASON_MAP[season % 4]}.CFE")
                else:
                    ticker_list.append(f"{contract_type}{str(year + 1)[2:]}{cls.SEASON_MAP[season % 4]}.CFE")
            season += 1
            count += 1
        return ticker_list
    @classmethod
    def get_contract_no(cls) -> List[str]:
        # Localized new-config convenience variables
        _date_strs = DateConfig.get_date_strings()
        flist = FuturesConfig.SYMBOLS
        
        import pickle
        pkl_path = os.path.join(DIR_INPUT, "futures-code.pkl")
        clist = None
        
        # Check cache
        if os.path.exists(pkl_path):
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(pkl_path))
                if (datetime.datetime.now() - mtime).days > 7:
                    clist = _wss(flist, "trade_hiscode,", "tradeDate="+_date_strs["d"])
                    if clist.shape[0] > 1:
                        with open(pkl_path, 'wb') as f:
                            pickle.dump(clist, f)
                with open(pkl_path, 'rb') as f:
                    clist = pickle.load(f)
            except Exception:
                pass

        # Regenerate if needed
        if clist is None:
            print(flist)
            # import pdb; pdb.set_trace()
            clist = _wss(flist, "trade_hiscode,", "tradeDate=" + _date_strs["d"])
            print(clist)
            with open(pkl_path, 'wb') as f:
                pickle.dump(clist, f)

        # Handle both DataFrame and Series cases
        clist_ = clist.values.flatten().tolist()
        return clist_


if __name__ == "__main__":
    # Lightweight self-test to make it obvious whether imports work when
    # executing this file directly.
    print("Running futures config self-test...")
    print("Project root:", _project_root)
    print("DIR_INPUT:", DIR_INPUT)
    try:
        sample = FuturesConfig.get_contract_no()
        print("Loaded contract codes:", sample[:10])
        print("OK")
    except Exception as e:
        print("FAILED:", repr(e))
        raise