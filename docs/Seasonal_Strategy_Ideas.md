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

## 5. Integration Plan — Seasonal Filter in Candidates Scan

### Overview
Seasonality should be **pre-filtered before entering the Candidates scan**, not a post-hoc Phase 2.
This prevents wasting compute on spreads with no statistical edge and makes the Candidates table
more trustworthy. The workflow:

1. **Spread subtab (Phase 1)**: year-overlay chart + monthly stats table — visualization & discovery
2. **Candidates subtab (Phase 1)**: add seasonal direction filter + gating in `compute_scan_score`
3. **Phase 2**: cross-instrument seasonal screener (separate report tool)

### 5.1 Core module `web/tabs/alpha/seasonal.py` (pure, testable functions)

```python
def seasonal_pivot(s: pd.Series, years: int = 8) -> pd.DataFrame:
    """Reindex series onto day-of-year (1..366), one column per year.
    Do NOT interpolate across holidays. Return shape: (n_doy, n_years)."""

def monthly_seasonal_stats(
    s: pd.Series, 
    min_years: int = 3,
    fdr_alpha: float = 0.05
) -> tuple[pd.DataFrame, dict]:
    """
    Compute seasonal statistics: one row per calendar month.
    Columns: month, n_years, direction (±1 for majority), consistency (%),
    avg_spread_change_bps, binomial_pvalue, fdr_adjusted_pvalue.
    
    Returns: (stats_df, current_month_stats_dict)
    where current_month_stats_dict = {
        'direction': ±1,
        'consistency': 0..1,
        'expected_move_bps': float,
        'pvalue_fdr': float,
        'passes_significance': bool (pvalue_fdr < fdr_alpha)
    }
    """

def build_seasonal_overlay_figure(
    pivot: pd.DataFrame,
    stats: pd.DataFrame,
    highlight_month: int,
    theme: dict
) -> go.Figure:
    """Year-overlay chart: one trace per year (older years faded, current thick & bright),
    cross-year mean ±1σ band, vrect shading for highlight_month, x-axis month ticks."""

def apply_fdr_correction(
    all_stats: pd.DataFrame,
    alpha: float = 0.05
) -> pd.Series:
    """Benjamini-Hochberg FDR correction across all (spread, month) cells.
    Return adjusted p-values; caller filters on adjusted_pvalue < alpha."""
```

Conventions: THEME from `web/tabs/alpha/data.py:17`; plotly layout from `display.py`;
tz-naive index via `_coerce_datetime_series`.

### 5.2 Phase 1a: Spread Subtab — Seasonal Visualization

Layout change (`build_spreads_layout`, `atlas_fi_tabs.py:95-167`):
- Under the existing "Spread Time Series" graph (`graph-spread`), add:
  - `_chart_label("Seasonal Pattern")`
  - `dcc.Graph(id='graph-spread-seasonal')`
  - `html.Div(id='spread-seasonal-stats')` (12-month mini table)
  - Sidebar dropdowns: `seasonal-highlight-month` (Jan…Dec, default=current), `seasonal-years` (3/5/8/All, default=5)

Callback (`atlas_fi_tabs.register_callbacks`):
```
Inputs: spread-type, ticker, seasonal-highlight-month, seasonal-years
Outputs: graph-spread-seasonal.figure, spread-seasonal-stats.children
```
Logic:
1. Load series (futures via `_fut_stat_bucket`, others via `build_spread_series`)
2. Call `monthly_seasonal_stats(series, min_years=3)` → stats_df + current_month_dict
3. Build overlay chart via `build_seasonal_overlay_figure`
4. Build mini DataTable with direction arrows, consistency %, p-value column color-coded:
   - p < 0.05 (FDR-corrected, pending cross-spread data): green ✓
   - 0.05 < p < 0.20: yellow ⚠ (weak/watch)
   - p ≥ 0.20: gray ✗ (noise)

Optional net-carry: join `load_carry_roll_timeseries` to show Δbps + carry + borrow costs
(addresses §2.2 "no costs").

### 5.2b Spread Subtab Unit Tests
- `seasonal_pivot`: leap years, missing months, <1y history, all-NaN input
- `monthly_seasonal_stats`: synthetic 100% seasonal signal recovers correct month + direction + consistency;
  binomial p matches `scipy.stats.binomtest`; FDR p-values rank-ordered by raw p
- `build_seasonal_overlay_figure`: renders without errors, has traces for each year, vrect for month

### 5.3 Phase 1b: Candidates Subtab — Seasonal Pre-Filter in Scan Score

Modify `compute_scan_score` in `web/tabs/alpha/callbacks/candidates.py`:

**New input parameter:**
```python
def compute_scan_score(
    ...
    use_seasonal_filter: bool = False,
    seasonal_min_consistency: float = 0.75,  # only use signals with ≥75% hit rate
    seasonal_fdr_alpha: float = 0.05,
) -> pd.Series:
```

**Logic:**
1. For each spread in the scan, call `monthly_seasonal_stats(series)` to get current month's stats
2. If `use_seasonal_filter=True`:
   - If `passes_significance=False` (FDR p ≥ alpha), **exclude from scan** (mask out)
   - If `consistency < seasonal_min_consistency`, **exclude from scan**
3. If the spread *passes* the gate, add a seasonal term to the scan score:
   ```
   score += 10 * sign(direction) * (consistency - 0.5)
   ```
   (e.g., a 80% consistent downward month adds -3 bps tilt to the RV signal)

**UI (Candidates layout):**
- New collapsible section "Seasonal Filter":
  - Toggle: "Apply seasonality gate" (default: OFF for backward compatibility)
  - Slider: "Min consistency (%)" [50…100, default 75]
  - Checkbox: "Show seasonal edge in score" (if ON, adds the consistency tilt)
- New column in results table (if seasonal filter is ON):
  - "Seasonal" = direction arrow + consistency % + FDR p-value indicator
  - Tooltip: "Month seasonality: ↑87% (p=0.02, FDR OK)"

**Callback change** (`_update_candidates_table`):
- Read `use_seasonal_filter`, `seasonal_min_consistency` from the UI
- Apply pre-filter before ranking
- Compute `seasonal_score_term` for each spread in the result
- Pass to table renderer

### 5.4 Candidates Callback Unit Tests
- Compute scan with/without seasonal filter; filtered set ⊂ unfiltered
- Spreads with low p-value (noise) are excluded when filter is ON
- Seasonal score term signed correctly (↑ direction = +, ↓ direction = −)

### 5.5 Phase 2 (later)
**Seasonal Screener (cross-instrument):**
- Precompute `monthly_seasonal_stats` for all spreads of each type in the EOD job
- Save as `seasonal-spds.pkl` following `{'Stats': DataFrame[spread × month × stat]}` convention
- Build a "Seasonal Calendar" report in a new subtab or modal:
  - Filter: month, min-years, FDR p-value threshold, spread-type
  - Table: rank spreads by (consistency, |expected_move|) with FDR-adjusted p-values
  - "Send to Candidates" button for selected spreads

---

## 6. Summary

Phase 1 integrates seasonality into the *live workflow*:
- **Spread subtab**: year-overlay chart makes seasonal patterns visible; stats table shows FDR-corrected significance
- **Candidates subtab**: seasonality gates out noisy spreads, optionally tilts RV score by consistency

This avoids wasting compute on non-seasonal instruments (esp. swaps where edge may be noise)
and keeps the signal honest via FDR correction (no false-positive epidemic from 528 tested cells).
Phase 2 builds the cross-spread screener for strategy review & portfolio construction.

---

## 6. Summary

The report's chart idiom is excellent and its screen is a good first pass, but its
statistics are not yet tradeable evidence: 528 tested cells on 3–8 annual
observations, no costs/carry, and a broken drawdown column. The integration plan
brings the **year-overlay chart + monthly stats** into the live Spread subtab where
they stay current with EOD data, adds the significance and net-carry discipline the
report lacks, and leaves the cross-instrument screener and scan-score hook as a
clearly-scoped second phase.
