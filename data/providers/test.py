from threading import Lock
import time
from typing import Any

from WindPy import w
import pandas as pd


blist = ['250313.IB', '250220.IB']

quote_df = pd.DataFrame(
    index=blist,
    columns=['Time', 'Bid', 'Ofr', 'Last'],
    dtype=object,
)
quote_lock = Lock()

field_map = {
    'RT_BID1': 'Bid',
    'RT_ASK1': 'Ofr',
    'RT_LAST': 'Last',
}


def on_data(d):
    fields = [str(field).upper() for field in d.Fields]
    event_time = d.Times[0] if d.Times else None

    with quote_lock:
        for code_idx, code in enumerate(d.Codes):
            if code not in quote_df.index:
                quote_df.loc[code] = [None, None, None, None]

            quote_df.loc[code, 'Time'] = event_time
            for field_idx, field_name in enumerate(fields):
                column_name = field_map.get(field_name)
                if column_name is None:
                    continue
                quote_df.loc[code, column_name] = d.Data[field_idx][code_idx]

        print("\n--- Current Quote ---")
        print(quote_df)

w.start()
w.wsq(blist, 'rt_bid1,rt_ask1,rt_last', callback=on_data)


try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n停止订阅")
    wind.stop()