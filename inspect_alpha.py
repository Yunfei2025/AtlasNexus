import os
import pandas as pd
from settings.paths import DIR_INPUT

path = os.path.join(DIR_INPUT, 'summary_alpha_portfolio.parquet')
print('path', path, 'exists', os.path.exists(path))
df = pd.read_parquet(path) if os.path.exists(path) else None
if df is not None:
    print('shape', df.shape)
    print(df.columns.tolist())
    rows = df[df['ID'].astype(str).str.contains('250208.IB|260203.IB', na=False, regex=True)]
    print(rows[['ID','spread_type','spread','direction','Open price (bp)','Close Price (bp)','MTM spd (bp)']].to_string())
