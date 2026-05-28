import os, pickle, numpy as np
from settings.paths import DIR_INPUT
from curves.utils.loader import loadInstrumentDefinition
import curves.affine.pricingYield as yd

bond = '180004.IB'
env = loadInstrumentDefinition('TBond')
row = env['Def'].loc[bond]
name, mats, mate, freq, coup = (
    row['证券全称'], row['起息日期'], row['到期日期'], row['每年付息次数'], row['票面利率:%'])
print(f"Bond : {bond}  {name}")
print(f"Coupon: {coup}%  Freq: {freq}  Maturity: {mate}")

with open(os.path.join(DIR_INPUT, 'TBond-cvobj.pkl'), 'rb') as f:
    cvobj = pickle.load(f)
with open(os.path.join(DIR_INPUT, 'TBond-cvpx.pkl'), 'rb') as f:
    cvpx = pickle.load(f)

ytm_act_series = cvpx['ytm_act'].get(bond)
if ytm_act_series is None:
    raise ValueError("Bond not in cvpx ytm_act")

valid_dates = [d for d in sorted(cvobj.keys())
               if d in ytm_act_series.index and np.isfinite(ytm_act_series[d])]
d = valid_dates[-1]
curve = cvobj[d]
schedule = yd.scheduleDate(mats, mate, name, freq)
ytm_act = float(ytm_act_series[d])
ytm_quo_stored = float(cvpx['ytm_quo'][bond].loc[d])

# ── 1) tax=0.0, invert from p_pretax (partial fix that ignores coupon effect) ──
_, _, _, pp0, _ = yd.pricingAffine(d, coup, 0.0, schedule, freq,
                                    curve.factors, curve.S2, curve.gamma,
                                    curve.mtype, curve.caltype)
ytm_tax0 = yd.pricingYield(d, coup, schedule, freq, float(pp0))

# ── 2) tax=0.25, invert from p (new code, old market-calibrated cvobj) ─────────
p25, _, _, _, _ = yd.pricingAffine(d, coup, 0.25, schedule, freq,
                                    curve.factors, curve.S2, curve.gamma,
                                    curve.mtype, curve.caltype)
ytm_dblcount = yd.pricingYield(d, coup, schedule, freq, float(p25))

# ── coupon PV and expected tax premium magnitude ──────────────────────────────
cpv = yd.coupon_pv_sum(d, coup, schedule, freq, ytm_act)
dur = yd.pricing(d, coup, schedule, freq, ytm_act)[2]
tax_premium_bp = 0.25 * cpv / dur * 100

print(f"\nDate : {d}")
print(f"{'ytm_act (market)':<38} {ytm_act:.4f}%")
print(f"{'ytm_quo stored in cvpx':<38} {ytm_quo_stored:.4f}%  resid={ytm_act-ytm_quo_stored:+.4f}%")
print()
print("── On EXISTING market-calibrated cvobj ──────────────────────────────")
print(f"{'tax=0.0  invert p_pretax  [partial]':<38} {ytm_tax0:.4f}%  resid={ytm_act-ytm_tax0:+.4f}%")
print(f"{'tax=0.25 invert p  [dbl-count]':<38} {ytm_dblcount:.4f}%  resid={ytm_act-ytm_dblcount:+.4f}%")
print()
print(f"coupon_pv_sum at ytm_act  : {cpv:.4f} price pts")
print(f"25% tax premium           : {0.25*cpv:.4f} price pts  ≈ {tax_premium_bp:.1f} bp")
print(f"After tax-free regen      : resid ≈ 0 bp (coupon effect correctly priced)")
