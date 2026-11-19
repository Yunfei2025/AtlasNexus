import sys, json
from pathlib import Path
import pandas as pd
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from settings.paths import DIR_INPUT

tenors=['1Y','2Y','5Y','10Y','20Y','30Y']
bands={'1Y':(0.9,1.2),'2Y':(1.6,2.5),'5Y':(4.0,6.0),'10Y':(8.5,10.0),'20Y':(15.0,25.0),'30Y':(25.0,30.0)}
p=DIR_INPUT/'TBond-InstrumentInfo.pkl'
print('load', p)
bi=pd.read_pickle(str(p))
print('loaded', bi.shape)
today=pd.Timestamp.today().normalize()
volume=pd.to_numeric(bi['成交量'], errors='coerce')
balance=pd.to_numeric(bi['债券余额:亿'], errors='coerce')
turnover=volume/balance/1e4
turnover=turnover.replace([np.inf,-np.inf],0).fillna(0)
maturity=pd.to_datetime(bi['到期日期'], errors='coerce')
start_date=pd.to_datetime(bi['起息日期'], errors='coerce')
terms=(maturity-today).dt.days/365.0
name_mask=bi['证券全称'].astype(str).str.contains('国债', na=False)
state_path=DIR_INPUT/'market_otr_sticky_state.json'
state=json.loads(state_path.read_text(encoding='utf-8'))
btype_state=state.setdefault('TBond',{})
state_changed=False
selected={}
for tenor in tenors:
    lo,hi=bands[tenor]
    bucket_mask=(terms.notna() & start_date.notna() & (start_date<today) & (maturity>today) & (terms>lo) & (terms<=hi) & name_mask & (balance>0) & (volume>0))
    bucket_turnover=turnover[bucket_mask]
    print('tenor', tenor, 'eligible', int(bucket_mask.sum()), 'turnover_rows', len(bucket_turnover))
    if bucket_turnover.empty or (bucket_turnover <= 0).all():
        selected[tenor]='—'
        continue
    candidate_id=bucket_turnover.idxmax()
    candidate_start=start_date.get(candidate_id)
    prev_id=btype_state.get(tenor)
    prev_start=start_date.get(prev_id) if prev_id in bucket_mask.index and bucket_mask.get(prev_id, False) else None
    if prev_id is None or prev_start is None or pd.isna(prev_start):
        chosen_id=candidate_id
    elif candidate_start is not None and pd.notna(candidate_start) and candidate_start > prev_start:
        chosen_id=candidate_id
    else:
        chosen_id=prev_id
    if btype_state.get(tenor) != chosen_id:
        btype_state[tenor]=chosen_id
        state_changed=True
    selected[tenor]=chosen_id
    print('chosen', tenor, chosen_id)
print('state_changed', state_changed)
print('selected', selected)
