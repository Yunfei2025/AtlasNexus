# Beta Book — hedge the short-end floor with TS/TF futures instead of clipping

Status: **plan only, not implemented.** Complements
`docs/plans/beta_book_exposure_vs_capital.md` (Step 7's capital/exposure split that
`signed_sleeve_weights_daily` already implements) and extends the hedge-instrument
idea flagged but not designed in `multiasset/book/sizing.py:273-275`
("there is no IRS asset in this codebase yet — see
docs/plans/beta_book_exposure_vs_capital.md for a hedge-instrument panel" — that
panel was never actually written up; this doc is it, and it specifies CGB futures,
not an IRS leg, as the instrument, since futures already exist in this repo and IRS
asset objects in `multiasset/` do not).

Scope: give `signed_sleeve_weights_daily`
(`multiasset/book/sizing.py:232`) a second leg — short TS/TF bond-future contracts
— so that a negative net factor exposure at the short end (CN1Y/CN2Y/CN5Y, today's
`RiskModelConfig.SHORT_END_LONG_ONLY_TENORS`) is expressed as a futures short
instead of simply dropped (clipped to 0). Cash bond legs stay long-only everywhere
in the book; only the hedge overlay can go short.

---

## 1. Why (problem statement)

1. **The floor is a real cost, not a convenience.** `signed_sleeve_weights_daily`
   sums every factor's sleeve into the tenor's net weight, then
   `weights[floor_cols] = weights[floor_cols].clip(lower=0.0)`
   (`sizing.py:326-329`). On a day IRSL/IRCV/IRDL's combined signal would want
   CN1Y/2Y/5Y net short, that view is simply discarded — not re-expressed, not
   hedged, gone. An A/B backtest (2022-01 to 2026-09, factor_scaling mode, CN
   IRDL/IRSL/IRCV + USDCNY + AU/AL pool) confirmed removing the floor outright
   (letting the cash bond itself go net short) makes every Sharpe variant *worse*
   (gross Sharpe −0.309 → −0.388, turnover 56.4x → 58.4x) — so the floor is
   correctly protecting against a bad cash short, not merely a missed opportunity.
2. **But the right fix isn't "never short the short end" — it's "never short the
   cash bond."** The user's observation: bonds should always be held long enough
   to earn their coupon (carry is real, structurally positive money); the
   *factor exposure* that wants to go short is a separate thing from *which
   instrument* carries that exposure. CGB futures (TS=2Y, TF=5Y, T=10Y, TL=30Y;
   `settings/futures.py:24,35,39`) already exist in this codebash as a distinct
   asset class from the cash bonds `multiasset/` prices — shorting a future
   doesn't give up coupon carry on a holding, because there is no cash bond
   holding to give up; it's margin and mark-to-market only.
3. **No DV01/asset-object bridge exists yet between `futures/` and `multiasset/`.**
   `futures/` only has price/signal backtesting (`futures/daily/`,
   `futures/backtest/`) — no DV01 calc, no asset usable by
   `signed_sleeve_weights_daily`/`weights_to_notional`. `get_asset_type`
   (`multiasset/data.py:110`) already has a stub `'IRS' in asset_name -> 'Spread'`
   branch anticipating a hedge instrument, but nothing populates it, and futures
   contracts don't match that stub's naming (`TS`/`TF`/`T`/`TL`, not `*IRS*`).

**Outcome:** the short-end floor logic changes from "drop the negative residual"
to "keep the cash bond weight floored at 0, route the negative residual into a
short TS/TF futures weight," with its own DV01 sizing, duration proxy, and
funding/cost treatment (futures margin ≠ bond repo), so coupon income on every
actual bond holding is preserved while the factor-model view at the short end can
still be expressed.

---

## 2. Design decisions (proposed — not yet approved)

| # | Decision |
|---|---|
| 1 | **Only CN1Y/CN2Y/CN5Y's negative residual is hedged**, via **TS (2Y)** for CN1Y/CN2Y and **TF (5Y)** for CN5Y — the nearest-maturity contract, following the same per-tenor granularity the cash-bond floor already uses. CN10Y+ stays exactly as-is (fully signed cash bonds, no futures). |
| 2 | **Two-leg weight**: `net_tenor_weight = cash_weight (clipped ≥ 0) + futures_weight (≤ 0, only active when net_tenor_weight would have been negative)`. The futures leg is sized so the *combined* DV01 matches what the uncapped signed sleeve wanted — i.e. the futures hedge restores the factor exposure the clip used to destroy, it doesn't add a new independent view. |
| 3 | **Futures duration proxy**: reuse the existing annuity-formula mod-duration (`sizing.py:311`: `(1-(1+y)^-n)/(y(1+y))`) with `n = CONTRACT_TENOR[symbol]` and `y` = the corresponding cash-bond yield (CN2Y for TS, CN5Y for TF) as a CTD proxy. This is a simplification (ignores actual CTD switch, conversion factor) and must be labeled as such in code and in the Risk Budget panel — not a precise futures DV01. |
| 4 | **Funding treatment is NOT the same as `SHORT_END_LONG_ONLY_TENORS`'s today.** A short future carries margin (small, roughly the exchange margin rate × notional) and a basis P&L term (future vs. CTD cash yield), not a bond repo cost. `ann_funding_cost` needs a distinct component for the futures leg rather than reusing the bond funding-hurdle path. |
| 5 | **Basis risk is reported, not hedged away.** The futures-vs-cash-bond tracking error (CTD switches, repo-implied carry in the future's price, contract roll) is real slippage against the theoretical factor-mimicking portfolio that the cash-only sleeves don't have. Step 4 below quantifies this before any Sharpe claim is made on the hedged variant. |
| 6 | **No change to any factor-scaling behavior above CN5Y, and no change to Pure Risk Parity mode** — this only touches the short end's floor-residual routing in `signed_sleeve_weights_daily`, gated behind a new flag (e.g. `use_futures_hedge: bool`) so the current (floor-and-drop) behavior remains the default / A-B comparable. |

**Step 0 resolved (2026-10-08):** the continuous main-contract daily data
already exists and was located by directly inspecting
`../input/futures-dailyK_con.pkl` — see §3 for details. No new data-retrieval
task is needed to start implementation; `load_raw_market_data()` just needs to
be extended to surface it.

---

## 3. Data/code gaps (Step 0 — resolved)

- [x] **TS/TF/T/TL daily data confirmed present**, at `../input/futures-dailyK_con.pkl`
  (`DIR_INPUT/futures-dailyK_con.pkl`, i.e. `settings.paths.DIR_INPUT`). It is
  a `dict[str, pd.DataFrame]` keyed by Wind-style ticker (`'T.CFE'`, `'TS.CFE'`,
  `'TF.CFE'`, `'TL.CFE'`, plus the equity-index and commodity futures also
  traded in `futures/`). Each value is OHLCV:

  | Symbol | Columns | Date range (as of 2026-09-28) | Rows |
  |---|---|---|---|
  | `TS.CFE` (2Y) | Open, High, Low, Close, Volume | 2018-08-17 → 2026-09-28 | 1,930 |
  | `TF.CFE` (5Y) | Open, High, Low, Close, Volume | 2015-03-30 → 2026-09-28 | 2,760 |
  | `T.CFE` (10Y) | Open, High, Low, Close, Volume | 2015-03-23 → 2026-09-28 | 2,765 |
  | `TL.CFE` (30Y) | Open, High, Low, Close, Volume | 2023-04-21 → 2026-09-28 | 796 |

  These are **back-adjusted continuous main-contract** series (one "front
  contract" series splicing each quarterly roll), consistent with what
  `futures/daily/` and `futures/backtest/` already consume for signal
  backtesting — so this plan reuses the same artifact those modules use,
  not a new feed. `TL.CFE` only starts 2023-04 (the 30Y contract didn't exist
  before), which matters for any backtest window that wants to include a TL
  hedge leg — not relevant to this plan's CN1Y/2Y/5Y scope (TS/TF only), but
  worth flagging since CN10Y/CN20Y/CN30Y stay cash-only here anyway (§2
  Decision 1/6).
  **No OI, settlement-vs-close distinction, or CTD/conversion-factor field is
  present** — only Close is usable as the daily mark, reinforcing that
  Decision 3's duration-proxy approach (not a precise CTD-based DV01) is
  required, not just convenient.
- [x] **No existing CTD/duration/conversion-factor calc anywhere in the repo**
  (`grep -rl "duration|CTD|conversion.factor" futures/ settings/futures.py` —
  no hits). Decision 3's annuity-formula proxy is confirmed to be the only
  option available without pulling in exchange CTD/conversion-factor data
  from an external source — not just the simplest path.
- [ ] **Still open**: no margin-rate assumption exists anywhere in the repo
  either (`grep -rn "margin" settings/futures.py futures/*.py` — no hits).
  Decision 4's margin + basis funding term needs either a CFFEX-published
  margin-rate figure sourced externally, or an explicit flat-% placeholder
  the user signs off on before implementation — do not invent a number
  silently.

## 4. Implementation steps

1. **Load the futures artifact and add a `multiasset/data.py` branch.**
   Add a `_load_futures_artifact()` next to the existing `_load_macro_artifact()`
   (`multiasset/data.py:45`) that reads `futures-dailyK_con.pkl` from `DIR_INPUT`
   the same way (`dict[str, pd.DataFrame]` keyed by `'TS.CFE'`/`'TF.CFE'`/etc.,
   columns `Open/High/Low/Close/Volume` — confirmed in §3), and thread it
   through `load_raw_market_data()`'s return value. **Caller audit done**:
   `load_raw_market_data()` currently returns `(fx_curves, cn_data, macro_data)`;
   every caller except one binds the full return to a single `market_data`
   name and indexes it (`web/tabs/beta/callbacks/{report_export,
   portfolio_run/_run_analysis,backtest_hist/orchestrator}.py`,
   `multiasset/dashboard.py`, `tests/test_signed_sleeves.py`,
   `tests/test_book_pnl_{reconciliation,split}.py`) — these tolerate a 4th
   tuple element with no change. The one exception,
   `report_export.py:278` (`_, cn_data, _ = load_raw_market_data()`), is a
   positional 3-tuple unpack that **will raise `ValueError: too many values to
   unpack`** if a 4th element is added — update it to `_, cn_data, _, _ = ...`
   (or `market_data = ...; cn_data = market_data[1]`) in the same change.
   Then add a `TS`/`TF` branch in `get_asset_yield_series` (`multiasset/data.py:183`)
   alongside the existing `Rates`/`Commodities`/`Equities` branches: pulls
   `Close` from `futures_data['TS.CFE']`/`['TF.CFE']`, pairs it with the
   Decision-3 duration proxy, and returns `is_bond=False` (no coupon/carry
   path) so the P&L/carry engine doesn't try to accrue coupon income on a
   futures position.
2. **Extend `signed_sleeve_weights_daily`** (`sizing.py:232`): after the existing
   clip at line 328, compute the clipped-away residual per floored tenor, map it
   to the paired futures symbol (Decision 1), and add a signed futures weight
   column sized to the residual's DV01 using the Decision-3 proxy duration.
   Gate behind `use_futures_hedge` (Decision 6).
3. **Funding/cost wiring**: add a futures margin + basis term to
   `ann_funding_cost`'s computation (currently in `orchestrator.py` around the
   funding-hurdle Sharpe step) and a separate turnover/tx-cost line for futures
   (futures tx costs are typically far lower bps than cash bond turnover —
   don't reuse the bond tx-cost bps assumption uncritically).
4. **Quantify basis risk (Decision 5) before trusting any Sharpe number**:
   backtest the TS/TF-vs-CN2Y/CN5Y tracking error over the same 2022-2026
   window used in the floor A/B test, report correlation and realized basis
   P&L stdev, independent of whether the hedge leg "worked" directionally.
5. **Re-run the floor A/B test** (same methodology as the CN1Y/2Y/5Y
   floor-on/floor-off comparison already done) with a third variant: floor-on
   + futures-hedge-on. Compare against both existing variants on gross/net/
   post-funding Sharpe, max drawdown, and total realized capital-weighted
   coupon income (the metric this whole feature exists to protect) before
   recommending it replace the current default.

## 5. What this explicitly does NOT change

- Cash bond holdings anywhere in the book remain long-only. No cash bond is ever
  shorted by this design — only futures carry negative exposure.
- CN10Y/CN20Y/CN30Y's existing fully-signed treatment is untouched.
- Pure Risk Parity mode (`alloc_mode='risk_parity'`) is untouched — this is
  `factor_scaling`-mode only, same as the floor itself.
