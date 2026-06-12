# Seasonal Strategy Report — Review & Integration Plan for the Alpha Book Spread Subtab

*Review date: 2026-06-12. Source: `docs/seasonal_strategy_report_final.html`
(固定收益市场利差恒定季节性策略报告, generated 2026-05-26, 3.2 MB static HTML with
hand-rolled inline SVG charts). Target: the **Spread** subtab of the Alpha Book
(`build_spreads_layout` in `web/tabs/atlas_fi_tabs.py`, mounted at
`web/apps/atlasnexus_daily.py:400`).*

---

## 1. What the Report Is

- **Universe:** 44 core CNY rates spreads — CGB futures-implied vs cash (active /
  next / old OTR, 5Y/10Y/30Y), swap−bond (互换-国债 1Y…5Y), CDB−CGB (国开-国债),
  curve tenor spreads (国债 20s10s, 30s10s, …), futures cross-tenor (隐含30Y−2Y/5Y/10Y).
- **Data range:** 2019-01-02 → 2026-05-22 (3 to 8 yearly observations per spread).
- **Strategy definition:** for each (spread, calendar month) cell, take the spread
  change over that month in each available year. Direction (看涨利差 ↑ / 看跌利差 ↓)
  = the majority sign; the strategy is "hold that direction for the month, every year".
- **Metrics per cell:** 一致性 consistency (% of years with the majority sign), 平均回报
  average return (bps), 变异系数 coefficient of variation, 最大回撤 max drawdown,
  观测年数 years observed.
- **Output:** 187 monthly strategies passing the screen, 31 with 100% consistency,
  average +3.35 bps per monthly trade.
- **Layout:** per-month sections (1月…12月), each with a ranked table and then a
  per-strategy chart pair; a ⭐ "perfect consistency" roll-up table; a final
  key-cycles summary (e.g. December: 30Y futures-implied spreads consistently widen).

## 2. Methodology Review

### Sound and worth keeping
- **Calendar-month conditioning is a legitimate RV screen** for this market: CNY
  seasonality has identifiable drivers — quarter-end LCR/MPA balance-sheet effects on
  swap spreads, local-government bond supply waves (Q1, Aug–Sep), futures contract
  roll cycles (Mar/Jun/Sep/Dec) driving the implied-vs-cash basis, January
  deposit-rush duration grabbing. The report's strongest cells (December 30Y
  futures-implied widening, June 20s10s flattening) line up with these mechanisms.
- **Consistency + CV + years-observed as a robustness trio** is the right instinct:
  it triangulates hit-rate, payoff stability, and sample size rather than ranking on
  average return alone.
- **Direction-aware presentation** (看涨/看跌 with arrows and color) makes the table
  directly tradeable rather than a statistics dump.

### Needs hardening before any cell is traded
1. **Multiple testing dominates the headline numbers.** 44 spreads × 12 months ≈ 528
   tested cells. With only 3 years of data, a 100%-consistency cell has probability
   2×(1/2)³ = 25% under pure noise — so of the "31 perfect strategies", a large
   fraction are expected by chance (and indeed most 3-year perfect cells sit in the
   futures-implied family that only has 2023+ data). Hardening: require ≥ 6 years;
   compute a binomial p-value per cell and apply Benjamini–Hochberg FDR across the
   528 cells; prefer cells whose direction matches a nameable mechanism (supply,
   roll, quarter-end) over purely statistical ones.
2. **No costs or carry.** A +2.6 bp average monthly move is ~1–2 round-trip bid/offers
   in the relevant instruments, and a month of negative carry on a short-bond leg can
   exceed the seasonal edge. The alpha book already has exactly the machinery needed —
   `load_carry_roll_timeseries` and `_get_borrow_cost_annual_bp` in
   `web/tabs/alpha/data.py` — so the integrated version can report
   **net** seasonal edge (move + carry − borrow − spread cost), which the HTML report
   cannot.
3. **The max-drawdown column is broken.** Values like `-inf%` and `-223.1%` indicate a
   percentage drawdown computed against a near-zero or sign-crossing base (a spread
   level crossing 0 makes any %-of-level drawdown meaningless). For spreads, drawdown
   must be reported in **bp from the intra-month peak of the cumulative position PnL**,
   never as a percentage of the spread level.
4. **Sub-monthly path is invisible.** A month-end-to-month-end change hides whether the
   move happens in the first week (trade the first week only) or is a U-shape (the
   monthly number understates the tradeable edge). The integrated version should
   compute day-of-month average paths, which the overlay chart (§4) makes visual.
5. **No out-of-sample discipline.** Every year contributes to both pattern discovery
   and the reported performance. Minimal fix: rank cells on years 1..n−1, report year
   n separately ("would the screen have caught it last year?").

## 3. Data-Structure Review

The report is a one-shot static artifact: a single HTML with 108 hand-built inline SVG
charts (no plotly/echarts), all stats precomputed and frozen at generation time
(2026-05-26). That's fine for distribution but wrong as a workflow component — it can't
follow the data forward, can't be filtered, and duplicates spread series we already
maintain.

In FIEngine the equivalent inputs already exist as the EOD pickles consumed by the
Spread subtab and alpha loaders — `{'Spread': DataFrame(date × instrument),
'StatInfo': DataFrame}` per spread type (`TBond-spds.pkl`, `IRS-pxspds.pkl`,
`Tenor-spds.pkl`, `futures-spds.pkl`, `Misc-spds.pkl`). Seasonal statistics are cheap
(a groupby over ≤ 2000 rows per instrument), so:

- **Recommendation: compute on the fly** in the callback from the existing Spread
  DataFrames — no new artifact, always current.
- If a cross-instrument seasonal *screener* is added later (Phase 2), precompute a
  `seasonal-spds.pkl` (`{spread_type: DataFrame[instrument × month] of stats}`) in the
  EOD job alongside the existing `*-spds.pkl`, following the same
  `{'Stats': …}` convention.

## 4. Design Ideas Worth Adopting (ranked)

1. ★ **The year-overlay cycle chart** (策略周期图) — x = day-of-year (ticks 1月…11月),
   one line per year (2019…2026) overlaid, with the strategy's active month as a
   shaded band. This is the single best idea in the report: seasonality, regime
   shifts, and this-year-vs-history are all visible in one glance, and it
   generalizes beyond seasonal strategies — it is simply a better way to look at any
   mean-reverting spread. **This is the user-requested addition to the Spread
   subtab.** Improvements over the report's version: current year drawn thick and
   bright, older years faded by age; optional mean ± 1σ band across years; hover
   shows (year, date, level).
2. **Per-year PnL strip** (年度收益一览) — compact colored chips (+6.0 2025 / −0.6
   2024) under the chart. Adopt as a small bar chart (one bar per year of the
   highlighted month's spread change) — honest about sample size because you can
   count the bars.
3. **Month-ranked consistency table** — per instrument, 12 rows (month, direction
   arrow, consistency %, avg Δbps, years). Adopt as a compact stats table next to
   the overlay chart; later as a cross-instrument screener.
4. **"Perfect consistency" roll-up** — as a *filter/sort* on the screener (Phase 2),
   not a separate page; with the FDR caveat from §2.1 attached to the column header.
5. **Time-ordered presentation** (strategies arranged 1月→12月) — natural for a
   monthly trading calendar; keep for the Phase-2 screener.

Not worth adopting: static HTML generation, hand-rolled SVG, %-of-level drawdowns.

## 5. Integration Plan — Spread Subtab Seasonal Panel (future PR)

The Spread subtab today: z-score bar chart (`graph-spread-bar`) → click a ticker →
spread time series with mean/±σ bands (`graph-spread`), driven by `spread-type`,
`select-season`, `ticker` components, callbacks registered in
`atlas_fi_tabs.register_callbacks` (`web/tabs/atlas_fi_tabs.py:785-935`), series built
via `build_spread_series` (`web/core/graphs.py`) and, for futures types,
`_fut_stat_bucket` (`atlas_fi_tabs.py:476`).

### 5.1 New module `web/tabs/alpha/seasonal.py` (pure functions, unit-testable)
```python
def seasonal_pivot(s: pd.Series, years: int = 8) -> pd.DataFrame:
    """index = day-of-year (1..366), columns = year, values = spread level.
    Reindex each year onto day-of-year; do NOT interpolate across holidays."""

def monthly_seasonal_stats(s: pd.Series, min_years: int = 3) -> pd.DataFrame:
    """One row per calendar month: n_years, avg Δbps, consistency %, direction,
    binomial p-value, bp drawdown of the majority-direction position.
    Month change = last close in month − last close of prior month."""

def build_seasonal_overlay_figure(pivot, highlight_month, stats, theme) -> go.Figure:
    """Year-overlay chart: one trace per year (older years faded, current year
    THEME['accent'] width 2.5), optional cross-year mean ±1σ band,
    add_vrect shading for highlight_month, x-axis ticks at month starts."""
```
Conventions to reuse: THEME from `web/tabs/alpha/data.py:17`; plotly layout pattern
from `web/tabs/alpha/backtest/display.py` (`plot_bgcolor=THEME['bg_main']`, horizontal
legend, `add_vrect` for the month band); tz-naive index coercion via the
`_coerce_datetime_series` pattern (`display.py:16`).

### 5.2 Layout change (`build_spreads_layout`, atlas_fi_tabs.py:95-167)
Under the existing "Spread Time Series" graph add:
- `_chart_label("Seasonal Pattern")`,
- `dcc.Graph(id='graph-spread-seasonal')`,
- `html.Div(id='spread-seasonal-stats')` (the 12-month mini table),
- sidebar controls: `dcc.Dropdown(id='seasonal-highlight-month', options=Jan..Dec,
  value=<current month>)` and `dcc.Dropdown(id='seasonal-years', options=[3,5,8,'All'],
  value=5)`.

### 5.3 Callback (registered in `atlas_fi_tabs.register_callbacks`)
```
Output: graph-spread-seasonal.figure, spread-seasonal-stats.children
Inputs: spread-type, ticker, seasonal-highlight-month, seasonal-years
```
Series acquisition mirrors the existing `_update_spread_ts` split: futures types from
`_fut_stat_bucket(stype)[ticker]`; all other types from the same data
`build_spread_series` uses (or, simpler and already proven, the alpha loader
`load_spread_timeseries(stype)[ticker]` — keep whichever returns the longer history).
Then `seasonal_pivot` → `build_seasonal_overlay_figure`, and `monthly_seasonal_stats`
→ a small `dash_table.DataTable` with direction arrows and the consistency column
color-coded, p-value shown so 3-year "100%" cells look as weak as they are. Wrap pickle
loads with the existing mtime cache `_load_pickle_cached` (atlas_fi_tabs.py:432).

Net-carry column (optional, alpha types only): join `load_carry_roll_timeseries` to
show avg Δbps **and** Δbps + month carry, addressing §2.2.

### 5.4 Phase 2 (separate, later)
- **Seasonal screener**: precompute `monthly_seasonal_stats` for every instrument of a
  spread type in the EOD job (`seasonal-spds.pkl`), render the report's month-ranked
  table across instruments with FDR-adjusted significance, min-years filter, and a
  "send to Candidates" button (also closes the Spread→Candidates workflow gap noted in
  `Alpha_Book_Review.md` §7.18).
- **Seasonal term in the Candidates scan score**: add `seasonal_edge_bps` for the
  current month (signed by direction match) as an additive term in
  `compute_scan_score` — only for cells passing the significance gate.

### 5.5 Verification for the implementation PR
- Unit tests for `seasonal_pivot` (leap years, missing months, <1y history) and
  `monthly_seasonal_stats` (known synthetic seasonality recovers the right month,
  direction and consistency; binomial p matches `scipy.stats.binomtest`).
- Run the app (`web/apps/atlasnexus_daily.py`), Alpha Book → Spread: select
  TenorSpread / CGB-10s30s, confirm the overlay chart renders one line per year, the
  month band moves with the dropdown, and futures types (NetBasis) also render.
- Cross-check one cell against the HTML report (e.g. 互换-国债5年, January: 87.5%
  consistency, +4.85 bps over 8 years) to validate the stat definitions.

---

## 6. Summary

The report's chart idiom is excellent and its screen is a good first pass, but its
statistics are not yet tradeable evidence: 528 tested cells on 3–8 annual
observations, no costs/carry, and a broken drawdown column. The integration plan
brings the **year-overlay chart + monthly stats** into the live Spread subtab where
they stay current with EOD data, adds the significance and net-carry discipline the
report lacks, and leaves the cross-instrument screener and scan-score hook as a
clearly-scoped second phase.
