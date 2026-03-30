"""Debug script to inspect curves data and identify zigzag root cause."""
import pandas as pd
import numpy as np
import os
import pickle
import sys
import math

sys.path.insert(0, r'D:\PyProjects\FIEngine\bin-v4.0')
INPUT = r'D:\PyProjects\FIEngine\input'

from curves.calibration.selector import YieldCurveBuilder, extract_yield, extract_bond_info, prepare_bond_schedule
from curves.calibration.bootstrap import BootstrapYieldCurve
from curves.utils.loader import loadInstrumentDefinition
from curves.utils.retrieve import retrieveEnvRT
from curves.affine import pricingYield as yd
from settings.general import DateConfig

# --- Load reference bonds ---
ref_path = os.path.join(INPUT, 'TBond-cvref.pkl')
with open(ref_path, 'rb') as f:
    ref = pickle.load(f)

botr = ref['RefBond']
d = botr.index[-1]
bond_ref = botr.loc[d]

print(f"Calc date: {d}")
print(f"Reference bonds: {dict(bond_ref)}\n")

# --- Load env + RT ---
env = loadInstrumentDefinition('TBond')
env = retrieveEnvRT(env, 'TBond')

# --- Trace build_curve step by step for Bid ---
print("=" * 70)
print("Tracing build_curve for Bid side, bond by bond:")
print("=" * 70)

yield_curve = BootstrapYieldCurve()

for bucket, bond_id in bond_ref.items():
    bond_data = env['Def'].loc[bond_id]
    bond_info = extract_bond_info(bond_data)
    ytm = extract_yield(env, bond_id, d, 'Bid')
    
    if pd.isna(ytm) or not np.isfinite(ytm):
        print(f"  {bucket:18s} {bond_id:12s} SKIPPED (ytm={ytm})")
        continue
    
    coupon, frequency, schedule = prepare_bond_schedule(bond_info)
    dirty, clean, duration, convexity = yd.pricing(d, coupon, schedule, frequency, ytm)
    
    maturity_date = bond_info['maturity_date']
    date_1 = pd.Timestamp(maturity_date).date()
    date_2 = pd.Timestamp(d).date()
    ttm = (date_1 - date_2).days / 365
    
    # What path does bootstrap take?
    periods = ttm * frequency
    path = "SIMPLE" if int(periods) == 0 else f"COUPON (n={int(periods)})"
    
    yield_curve.add_instrument(100, ttm, coupon, dirty, frequency)
    
    print(f"  {bucket:18s} {bond_id:12s} ytm={ytm:7.4f}%  coup={coupon:5.2f}%  freq={frequency}  "
          f"ttm={ttm:.4f}  dirty={dirty:8.4f}  path={path}")

# Now get zero rates
maturities = yield_curve.get_maturities()
zero_rates = yield_curve.get_zero_rates()

print(f"\nBootstrap zero rates:")
for t, r in zip(maturities, zero_rates):
    print(f"  TTM={t:.4f}  ZeroRate={r:.6f}%")

# Check monotonicity
print(f"\nMonotonicity check:")
for i in range(1, len(zero_rates)):
    direction = "UP" if zero_rates[i] > zero_rates[i-1] else "DOWN <<<" 
    delta = zero_rates[i] - zero_rates[i-1]
    print(f"  {maturities[i-1]:.3f} -> {maturities[i]:.3f}: {delta:+.4f}% {direction}")

# Check the 0.7Y bond specifically  
print(f"\n{'='*70}")
print("Detail for 0.7Y reference bond:")
bond_07 = bond_ref['Term near 0.7Y']
bd = env['Def'].loc[bond_07]
print(f"  Bond: {bond_07}")
print(f"  Name: {bd.get('证券全称','?')}")
print(f"  Coupon: {bd.get('票面利率:%','?')}%")
print(f"  Frequency: {bd.get('每年付息次数','?')}")
print(f"  Maturity: {bd.get('到期日期','?')}")
print(f"  Start: {bd.get('起息日期','?')}")
print(f"  CNBD yield: {bd.get('估价收益率:%(中债)','?')}%")
if env.get('BondRT') is not None and bond_07 in env['BondRT'].index:
    rt = env['BondRT'].loc[bond_07]
    print(f"  RT Bid yield: {rt.get('买价收益率','?')}")
    print(f"  RT Ofr yield: {rt.get('卖价收益率','?')}")
else:
    print(f"  No RT data!")

print("\nDone.")
