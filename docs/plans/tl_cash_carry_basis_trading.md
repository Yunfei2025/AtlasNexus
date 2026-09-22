# TL Cash-and-Carry Basis Trading — Systematic Design

Status: design sketch, no code yet.
Scope: T-bond futures (TL, 30Y bucket) cash-and-carry, traded as a convergence
spread and closed before delivery — not held to maturity.

## 1. Why not plain IRR

IRR assumes you hold the current CTD to delivery. TL's deliverable basket spans
a wide duration range, so the CTD is yield-level dependent and can switch
before expiry. A static IRR computed at trade inception stops describing the
bond you'd actually end up delivering once CTD flips — you're implicitly
short a CTD-switch (delivery) option that IRR doesn't price.

Decision: don't hold to maturity, don't price the delivery option explicitly.
Instead trade the **CTD's net basis converging toward fair value**, exit
before delivery month, and use switch risk as a **gate**, not something we
try to monetize.

## 2. Reducing to one signal + one gate

Earlier draft had 5 candidate indicators (net basis z-score, CTD-switch
breakeven, IRR dispersion, CTD duration-bucket position, carry/roll
trajectory). Collapsed as follows — this is the important design decision,
not an afterthought:

| Original indicator | Role in final design |
|---|---|
| Net basis z-score | → **primary signal**, redefined as annualized rate (§3) |
| Carry/roll trajectory | folded into the signal's fair-value baseline, not a separate feature |
| CTD-switch breakeven distance | → **primary gate** |
| CTD duration-bucket position | folded into the gate as a smoothing input, not separate |
| IRR dispersion across basket | kept as a **diagnostic only** (monitoring/logging), not gated on — redundant driver with the breakeven gate |

Net: **one signal, one gate, one diagnostic.**

## 3. Signal: annualized net-basis rate ("net basis IRR")

### Problem with raw net basis as a time series
Net basis in price terms shrinks mechanically as time-to-maturity shrinks
(less carry to accrue, less time for convergence). A trailing z-score of raw
net basis mixes together genuine mispricing with pure horizon effects, and
the "same lookback window" doesn't mean the same thing 90 days vs 10 days
before expiry.

### Fix: annualize it, same as IRR construction
Convert net basis to a rate so it's comparable across time-to-maturity,
instead of a rolling window on the raw price number:

```
NB_i(t)      = P_i(t) - F(t) * CF_i - carry_i(t)      [net basis, price terms]
t_mat        = calendar days from t to delivery/first-notice
NBR_i(t)     = NB_i(t) / P_i(t) * (365 / t_mat)         [net basis rate, annualized]
```

`NBR` (net basis rate) is the annualized repo-rate-equivalent value of the
mispricing — structurally this is "IRR minus repo," expressed as a rate, so
it's directly on the same footing as the funding/repo curve and comparable
across different expiries/contract months without a horizon-dependent window.

### NBR vs "IRR − Repo" — same residual, two conventions

These are algebraically the same information, not two competing signals.
Both are built from the same primitives (`P`, `F`, `CF`, carry, `t`) and both
reduce to "annualized version of (something minus carry-implied fair
value)." With carry computed identically in both, `NBR ≈ -(IRR - Repo)` up to
sign convention and small second-order terms.

The reason to build the signal on **NBR** rather than **IRR − Repo**
directly is about what each is centered on:

- `IRR − Repo` is *designed* to sit away from zero for the CTD — its
  positive residual is largely the value of the delivery option we're short
  (§1), and that option value itself drifts with basket composition and
  yield level. Z-scoring `IRR - Repo` directly conflates that drifting
  option-value baseline with genuine dislocation — exactly the
  horizon/regime contamination this section is trying to avoid.
- Net basis, by standard basis-trading convention (Burghardt et al.), is
  already constructed to net carry out first, leaving a residual that's
  supposed to isolate the option-value-plus-mispricing component with a
  more stable, closer-to-zero center. `NBR` inherits that property, which
  makes z-scoring it against a stable baseline (repo proxy, or zero) more
  defensible.

Net: pick **NBR** as the one signal convention used throughout this plan.
`IRR − Repo` is the same underlying quantity and can still be logged
alongside IRR dispersion (§5) as a familiar diagnostic, but is not used to
build the z-score, so there's no ambiguity later about the two being
different things.

### Signal construction
- Compute `NBR_CTD(t)` daily for the current CTD.
- Baseline/"fair value": short-term repo rate (GC repo or the relevant funding
  proxy already used elsewhere in `curves/refreshers/`), since `NBR` should
  sit near zero relative to true funding cost absent mispricing or switch-
  option effects.
- Signal = `NBR_CTD(t) - repo_proxy(t)`, z-scored against its own trailing
  distribution (window TBD empirically, likely 60–120 obs, consistent with
  other MR spreads in the book — do not hand-tune per instrument, see
  [[alpha-backtest-no-param-tuning]]).
- This is now a rate spread, same shape as other MR spreads in the book →
  reuse existing MR entry/exit/z-score machinery rather than building new
  signal infrastructure.

### Why this solves the "same time window" problem
Because `NBR` is already annualized, a z-score computed today (90 days to
expiry) and one computed next month (60 days to expiry) are on the same
scale — no need to renormalize the lookback window as expiry approaches.

## 4. Gate: CTD-switch breakeven distance

Standard conversion-factor breakeven calc: the parallel yield shift at which
the current CTD and the next-cheapest basket bond swap rank (min net basis /
max IRR). Compute in yield-shift terms (bp), not price terms, so it's
comparable across the basket's duration range.

```
for each adjacent pair (CTD, next-cheapest) in the ranked basket:
    solve for Δy such that NB_CTD(y0+Δy) = NB_next(y0+Δy)
breakeven_bp = min |Δy| over adjacent pairs
```

Use CTD's duration-bucket position within the basket as a smoothing input
here (continuous, not a separate signal) — e.g. weight the breakeven by how
close CTD sits to the basket's duration extremes vs its middle, since a CTD
in the middle of the duration distribution is closer to a switch for the same
yield move than one at an extreme.

### Gate logic
- `breakeven_bp` compared to a rolling estimate of realistic yield vol over
  the intended holding horizon (e.g. expected σ of 30Y yield over N trading
  days).
- `breakeven_bp / σ_horizon` → ratio determines position sizing:
  - ratio large → trade full size, basis is "clean"
  - ratio small → reduce size or sit out (per
    [[alpha-momentum-carry-score-gate-can-empty-bucket]] precedent: an empty
    bucket on a given day from a hard gate is expected behavior, not a bug)
- Forced exit if `breakeven_bp` collapses below threshold intraday/mid-trade,
  independent of the z-score signal — switch risk realizing overrides mean-
  reversion logic.

## 5. Diagnostic (not gated): IRR dispersion across basket

Track spread between top-2/top-3 ranked bonds' IRR for logging/monitoring
and as a cross-check against the breakeven gate (same underlying driver,
different lens — narrowing dispersion should track narrowing breakeven).
No separate trading logic; useful for post-hoc review and sanity-checking the
gate, and for flagging data/CF calculation issues if the two disagree.

## 6. Exit rules (whichever binds first)

1. Mean reversion: `NBR` z-score reverts toward zero (standard MR exit, reuse
   existing spread stop/re-entry logic — verify it actually binds, per
   [[alpha-mr-stop-loss-was-noop]], don't assume a parameter does something
   without testing it).
2. Gate breach: `breakeven_bp` collapses below threshold — forced exit,
   switch risk overrides thesis.
3. Time stop: fixed horizon before delivery/first notice date (e.g. N
   business days), regardless of signal state — hard cutoff, this trade is
   never held into delivery.

## 7. Execution: no mid-position bond rotation

**Rule: the bond leg is never rotated while a position is open.** A position
is entered against a specific bond (the CTD at entry) and is either held to
one of the §6 exits or closed outright — it is not seamlessly rolled into a
new bond as CTD changes.

Rationale:
- We don't know a switch is coming with certainty, only a probability (what
  the breakeven gate estimates). Preemptively rotating the bond leg on a
  forecast means paying the bid/ask twice (sell old bond, buy new bond) plus
  re-hedging the futures ratio (new CF) on a maybe-switch — expensive against
  a basis that's often only a few ticks wide.
- Waiting until the switch is confirmed is usually too late — net basis on
  the old CTD can gap once the market reprices the switch, so "rolling on
  confirmation" means exiting into an adverse move, not ahead of it.

So in practice: gate breach (§6.2) → close the whole position (sell bond,
unwind futures hedge), realizing whatever convergence has been captured.
If the new CTD's net basis then looks attractive, that is evaluated as a
**new, independent trade** through the normal signal pipeline (§3), with its
own entry sizing — not a continuation of the prior position. This keeps the
strategy always in one of two states per contract-month: long the *current*
CTD's basis, or flat. No two-bond-leg bookkeeping, no rollover logic.

### Explicitly out of scope: trading the switch itself
A different strategy — actively buying the bond *expected* to become CTD
before the market has repriced it, financed against the futures, profiting
as its net basis converges toward the new-CTD level as the switch is
realized — is a legitimate but distinct trade type (directional bet on
ranking change, not mean-reversion on level). It would need its own signal
(e.g. narrowing gap between CTD and next-cheapest net basis, combined with a
directional yield view) and its own risk framework. Noted as a candidate for
a future, separate plan; not built into this one.

## 8. Portfolio construction

- Treat as one more spread candidate in the alpha-candidates framework
  (`curves/refreshers/alpha_candidates.py`), one instance per active
  contract-month.
- Correlate this spread's **P&L**, not its level, against the existing
  14-instrument book before sizing/inclusion — per
  [[alpha-strategy-vs-level-correlation]], level-based filtering destroys
  Sharpe; P&L correlation is the right basis for portfolio construction.
- Expect modest standalone Sharpe (0.2–0.5 range per
  [[alpha-single-spread-sharpe-ceiling]]) — value is diversification, not
  standalone edge. Do not hand-tune this single instrument's parameters in
  isolation; if window/threshold choices are being fit to make this one
  spread look good, stop — see [[alpha-backtest-no-param-tuning]].

## 9. Data / inputs needed

- Full TL deliverable basket: bond list, conversion factors (per contract
  month), prices, accrued interest.
- Repo/GC funding proxy (already exists for T/TS/TF IRR calc — reuse).
- Futures price, contract delivery/first-notice calendar.
- Yield curve for breakeven Δy solve (existing curve calibration output).
- Realized/implied 30Y yield vol estimate for horizon σ (existing vol infra
  if available, else realized vol proxy).

## 10. Bond vs futures close-time mismatch

Bond (CIBM/interbank) and TL futures (CFFEX) do not share a close time, and
current data availability via Wind reflects each instrument's own native
close, not a matched snapshot. Since `NBR`/breakeven are cross-instrument
spreads computed at a single `t`, a timing mismatch between the two legs
injects noise (or spurious signal) purely from staleness — a leg that moved
in its own late session shows up as "basis divergence" even with no real
mispricing. This affects live signal generation and the backtest alike, and
should be handled the same way in both rather than solved only historically.

### What's available
Wind (`data/providers/retrieve.py`) exposes both daily (`_wsd`/`fetch_wind_data_day`)
and intraday bar (`_wsi`/`fetch_wind_data_bar`) pulls generically by symbol,
plus tick-level (`_wst`). So both legs can in principle be sampled on a
common intraday timestamp grid, not just matched at each instrument's own
daily close — this makes an actual alignment fix (not just a bounding
workaround) realistic, pending confirming intraday history depth/quality
for the specific bond codes needed (interbank bond intraday marks are
typically thinner than futures).

### Approach: snap both legs to the earlier close, using intraday bars
1. Determine which leg closes earlier on a given day (bond vs. futures
   session times can vary; don't hardcode an assumption — check both
   sessions' actual end times).
2. Pull intraday bars (`_wsi`) for whichever leg closes *later*, and use its
   last bar at-or-before the earlier leg's close time — i.e., both legs are
   read as of the same wall-clock cutoff, even though only one leg's
   official "close" print falls exactly there.
3. This sacrifices some information from the later-closing leg's remaining
   session, but guarantees the signal is never built from two prices that
   were never simultaneously tradeable.

### Fallback if intraday bond data proves too thin/unreliable
If intraday interbank bond marks aren't usable in practice (sparse ticks,
stale-fill artifacts), fall back to:
- Accept the native daily-close mismatch, but require the `NBR` z-score
  signal to persist across 2+ consecutive observations before triggering
  entry, so a single close-time-lag artifact on a volatile day can't trigger
  a trade on its own.
- Cross-check any large single-day signal move against whether the repo
  proxy/curve also moved that day; a move confined to just the close-time
  gap (not corroborated elsewhere) should be treated as suspect, not acted
  on.
- Log the measured typical lag explicitly (§12) rather than silently
  carrying it as unstated noise.

### Backtest implication
Whichever approach is used live must be used identically in the backtest —
if the backtest is built on same-day daily closes for both legs (mismatched)
while live trading snaps to a common intraday timestamp (or vice versa), the
backtest is not representative of live behavior. Pick one approach before
building the backtest, not after.

## 11. Backtest methodology

Follows the strategy's own state machine (§7: long-CTD-basis or flat, never
two legs) — the backtest should be a straightforward historical simulation,
not a model-fit exercise. Key points:

### 10.1 Reconstruct the basket and CTD, point-in-time
- For each historical date, reconstruct the *actual* eligible deliverable
  basket for the then-front (or then-relevant) TL contract, using
  point-in-time conversion factors and eligibility rules (basket composition
  changes as bonds age in/out of the 30Y-bucket eligibility window — this
  must not be looked up with today's basket).
- Compute NB_i(t), NBR_i(t), rank the basket, determine CTD(t) exactly as
  the live signal would have, using only information available at t (no
  lookahead — e.g. don't use a conversion factor or eligibility list that
  wasn't publicly known/computable on that date).

### 10.2 Simulate the signal and gate exactly as specified
- Roll `NBR_CTD(t) - repo_proxy(t)` forward, z-score against the trailing
  window under test.
- Compute `breakeven_bp(t)` and the horizon-vol ratio each period; apply as
  a sizing multiplier / hard gate per §4.
- Entries/exits per §6, exactly as the live rule set — including the time
  stop, so no trade is ever simulated as held past the pre-delivery cutoff.
- Enforce §7: on a gate breach or CTD change, close fully; any subsequent
  entry into a new CTD's basis is a fresh, independently-sized trade, not a
  continued position.

### 10.3 Costs and frictions (basis trades are thin — this matters more than usual)
- Bid/ask on both legs (bond and futures) at entry and exit.
- Repo financing cost actually realized over the holding period (not just
  the GC proxy used for signal generation — term repo can differ from GC,
  and this gap is real P&L, not noise).
- Futures roll cost if the position spans a futures roll.
- Margin/financing haircuts if material to sizing.
Given net basis trades are frequently a few ticks wide, an underestimate of
costs here can flip an apparently-profitable backtest to unprofitable — size
this carefully rather than defaulting to a flat bp assumption copied from a
wider-spread strategy.

### 10.4 CTD-switch realizations are the core thing being tested
Unlike T/TS/TF where CTD stability is a given, the backtest's main value for
TL is in how often/how well the gate (§4) avoided being caught by an actual
switch — i.e., look explicitly at historical episodes where CTD *did*
change and check: was the gate flagging elevated risk beforehand (breakeven
narrowing), did the forced exit trigger ahead of the switch or after, and
what was the realized P&L impact in each case. This is as important a
backtest output as the aggregate Sharpe — a strategy that "worked" only
because the historical sample had few switches is not validated for a
regime with more of them.

### 10.5 Standard checks (reuse existing backtest infra)
- Run through the same backtest harness as other spreads
  (`curve-backtest`/`futures/backtest/`), producing `BacktestResult` per
  `engine/schema.py` conventions, so it plugs into the existing
  alpha-candidates comparison pipeline (§8) without a bespoke report format.
- Walk-forward / out-of-sample split for any parameter chosen (lookback
  window, gate threshold, time-stop horizon) — per
  [[alpha-backtest-no-param-tuning]], do not fit these to maximize this one
  instrument's in-sample Sharpe; if a parameter only works in-sample, treat
  that as a red flag, not a result to keep.
- Compare against a naive baseline (e.g. always-hold-CTD-basis-to-time-stop,
  no gate) to isolate how much the gate itself is adding versus the raw
  mean-reversion signal.

## 12. Open questions / to validate empirically before build

- Lookback window for `NBR` z-score — start from existing MR spread defaults,
  don't tune per-instrument first.
- Horizon N for time-stop and for σ_horizon in the gate ratio — likely tied
  together (same holding-period assumption).
- Whether `NBR` should be measured against GC repo directly or against a
  richer funding curve (term repo matching horizon) — repo term structure
  may matter more here than for T/TS/TF given longer relevant horizons.
- Confirm conversion factor data availability/quality for full TL basket
  across historical sample before backtesting.
- Confirm intraday bond (CIBM) data depth/quality via Wind `_wsi` for the
  specific bond codes in the TL basket — determines whether §10's intraday
  alignment approach is usable or the daily-close fallback is needed.
- Measure and log the actual typical bond-vs-futures close lag (§10) once
  data is pulled, so it's an explicit, known noise source rather than
  discovered later during live P&L review.

## 13. Alternative signal considered: CTD YTM vs futures-implied YTM

Considered replacing `NBR` (§3) with a yield-space spread,
`YTM_CTD(t) - YTM_implied(t)` (the yield that makes the CTD's carried
forward price match its actual price). Attractive because it's
unit-consistent with §4's gate, which is already in yield-shift terms —
but it doesn't actually remove anything `NBR` carries: computing
`YTM_implied` still needs the same carry model, and the spread still
inherits the delivery-option-driven nonzero baseline (§1/§3.4), so it needs
the same z-scoring treatment anyway. Not a strict improvement — kept `NBR`.

Better use of the idea: as a smoothing input to §4's gate (a continuous
version of the duration-bucket proxy) rather than as the primary signal.
Revisit when tuning §4 empirically.

## 14. Summary

One signal (`NBR` z-score vs repo, MR-style), one gate (breakeven distance /
horizon vol, sizes or excludes), one diagnostic (IRR dispersion, monitoring
only). Reuses existing spread/MR infrastructure and alpha-candidates
portfolio construction rather than building bespoke machinery. No delivery-
option pricing required since the trade is always closed before expiry.
