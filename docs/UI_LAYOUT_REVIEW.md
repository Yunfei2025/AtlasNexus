# AtlasNexus — UI Layout Review

_Review date: 2026-06-14 · Scope: page/tab/subtab structure of the two Dash consoles_

This document maps the full navigation hierarchy of the AtlasNexus web app, comments on
each area, and lists suggested improvements for further development. It covers **layout and
navigation only** — not the financial logic behind each panel.

---

## 1. Application map

There are **two separate Dash apps**, launched from `main.py`:

| App | Port | Entry | Status |
|-----|------|-------|--------|
| **Daily Console** (EOD) | 8080 | `daily-web` / default | Fully built out |
| **Intraday Console** | 8081 | `intraday-web` | Skeleton / placeholder, **does not start** (see §4) |

### 1.1 Daily Console — tab tree

```
AtlasNexus · Daily  (header: latest-EOD line, refresh clock, Wind/job status pills)
│
├── Market          ← default tab
│   ├── Data        Money-market / reference bonds / bond futures / on-the-run / IRS fwd tables
│   ├── Trend
│   ├── Pricer
│   ├── Surface     (yield surface, delegates to surface/ package)
│   └── Curves      TBond / CBond / IRS spot / IRS forward
│
├── Beta Book
│   ├── Candidates  (id "factor" — label/value mismatch, see §3.1)
│   ├── Portfolio
│   ├── Backtest    (id "factor-model-bt")
│   ├── Factor      (id "factor-history")
│   ├── Bond
│   └── Futures     (id "backtest-factor")
│
├── Alpha Book
│   ├── Candidates
│   ├── Portfolio
│   ├── Backtest
│   ├── Spread
│   ├── Pairs
│   └── Volatility
│
├── Summary         (id "risk")  ← THREE levels of nested tabs, see §3.2
│   ├── Books
│   │   ├── Beta Book
│   │   └── Alpha Book
│   ├── Risk
│   └── Tickets
│
└── Run Center      (id "run-center")
    ├── Daily Pipeline card   (Update Data / Run EOD / Run EOD+update / Refresh Instruments + As-Of date)
    ├── Data Backfill card    (instrument type / steps / date range / workers / Run)
    └── Status & Logs card    (running-jobs banner + last-job detail + log tail)
```

### 1.2 Intraday Console — tab tree

```
AtlasNexus · Intraday  (header: Run Snapshot / Run +update buttons)
├── Session   (job log tail — works)
├── Signals   placeholder "Planned: ..."
├── Risk      placeholder "Planned: ..."
└── Tickets   placeholder "Planned: ..."
```

---

## 2. What works well

- **Consistent dark theme.** A single style module (`web/tabs/atlas_styles.py`) defines tab,
  subtab and Plotly-template constants, and a registered `atlas` Plotly template means every
  figure inherits the same palette. This is the right pattern.
- **State-preserving tab switches.** The Daily console pre-renders every main tab and subtab
  and toggles `display: block/none` via a generic `_make_tab_switcher` factory
  (`atlasnexus_daily.py:501`) instead of re-rendering on each click. Switching tabs keeps form
  state and avoids recompute — good for a heavy analytics app.
- **Clear three-book mental model.** Market → Beta → Alpha → Summary → Run Center reads as a
  sensible workflow (data in, strategy books, combined view, operations).
- **Run Center is genuinely useful.** Live job status, log tail, and a running-jobs banner give
  the operator real feedback. Header status pills (Wind connectivity, active job) are a nice touch.
- **Smart default dates.** As-of defaults respect CN working-day / 6pm-cutoff logic
  (`atlasnexus_daily.py:211`), which avoids a common operator footgun.

---

## 3. Layout / navigation issues

### 3.1 Tab `value` keys don't match their labels (Beta Book)  — _high priority_

In `build_tabs_panel` the Beta subtabs use legacy internal keys that no longer describe the tab:

| Label shown | `value` key | div id |
|-------------|-------------|--------|
| Candidates  | `factor`            | `beta-factor-div` |
| Backtest    | `factor-model-bt`   | `beta-factor-model-bt-div` |
| Factor      | `factor-history`    | `beta-factor-history-div` |
| Futures     | `backtest-factor`   | `beta-backtest-factor-div` |

This is a maintenance trap: "Candidates" is keyed `factor`, "Factor" is keyed `factor-history`,
and "Futures" is keyed `backtest-factor`. Anyone editing the switcher list in
`atlasnexus_daily.py:701` has to keep three differently-named identifiers mentally aligned.
**Suggestion:** rename keys to match labels (`candidates`, `bt`, `factor`, `futures`) in one pass,
updating the `dcc.Tab`, the div `id`, and the `_make_tab_switcher` arrays together.

### 3.2 Summary tab nests tabs three deep — _high priority_

"Summary" (`risk`) is the only top-level tab that contains its own `dcc.Tabs` (Books / Risk /
Tickets at `risk.py:158`), and **inside Books** there is yet another `dcc.Tabs` (Beta Book /
Alpha Book at `risk.py:252`). So the user navigates: top tab → sub-tab → sub-sub-tab. Every
other tab is two levels deep at most. This is inconsistent and easy to get lost in.
**Suggestion:** either (a) flatten — promote Books/Risk/Tickets to the same subtab bar style the
other tabs use, and replace the Beta/Alpha inner tabs with a side-by-side two-column view, or
(b) move "Tickets" out of Summary entirely (it overlaps conceptually with the Intraday Tickets tab).

### 3.3 Inconsistent subtab styling between tabs — _medium_

The Summary tab defines its **own** `_tab_style` / `_tab_sel` helpers inline (`risk.py`) and uses
`THEME` colors, while Market/Beta/Alpha use the shared `summary_subtab_style` /
`summary_subtab_selected_style` from `atlas_styles.py`. Two near-identical styling systems exist.
Result: Summary's tabs look subtly different from every other tab bar.
**Suggestion:** delete the inline styles in `risk.py` and reuse the shared helpers, or unify the
`THEME` dict (in `web/tabs/alpha/data.py`) with the `atlas_styles` constants so there is one source of truth.

### 3.4 Per-tab accent color is decorative, not semantic — _low_

Alpha subtabs are red (`#ef553b`), all others blue (`#3498db`); within Summary the inner tabs are
accent/warning/success. The color coding is inconsistent (Alpha = red implies "danger" but it's
just a book) and carries no learnable meaning.
**Suggestion:** pick one accent per *book* and apply it consistently (e.g. Beta = blue, Alpha =
amber), or drop per-tab coloring and rely on the active-tab underline only.

### 3.5 "Candidates" / "Portfolio" / "Backtest" labels are duplicated across Beta and Alpha — _low_

Beta Book and Alpha Book both have Candidates / Portfolio / Backtest subtabs. That's fine
conceptually, but combined with §3.1's mismatched keys it's easy to wire an Alpha callback to a
Beta component by accident. Keep the labels but ensure all `id`s are book-prefixed (Beta currently
mixes `beta-*` div ids with bare `factor`/`portfolio` values).

### 3.6 No active-tab indication in the URL / no deep-linking — _low_

All navigation is in-memory show/hide; there's no `dcc.Location` routing. Operators can't bookmark
"Alpha → Volatility" or share a link to a specific view, and a browser refresh always lands on
Market. **Suggestion:** add `dcc.Location` + a thin URL↔tab sync if shareable views are wanted.

---

## 4. Intraday Console is broken and stubbed — _high priority_

`web/apps/atlasnexus_intraday.py` will not start as written:

- Line 12 `import Path` should be `from pathlib import Path`.
- Line 18 uses `sys.path.insert(...)` but `sys` is never imported.
- `project_root` is computed twice (lines 17 and 27) with different parent depths.

Three of its four tabs (Signals, Risk, Tickets) are placeholder text ("Planned: ..."), and the tab
content is rendered with a single `_render_tab` callback driven by a 3s interval — note this is the
**opposite** pattern from the Daily console's keep-alive show/hide, so the two apps diverge
architecturally.

**Suggestions:**
1. Fix the import errors so the app boots (quick).
2. Decide whether Intraday should be a separate app at all, or a top-level tab inside the Daily
   console. Two ports / two windows is friction for a single operator; merging would let the
   Session/Signals/Risk/Tickets tabs reuse the existing styled components and the Run Center job
   machinery.
3. If kept separate, adopt the same keep-alive show/hide switcher so behavior matches Daily.

---

## 5. Smaller polish items

- **Run Center "Run Backfill" overloads two CLI commands.** The same button dispatches either
  `curve-backtest` or `futures-analytics-backfill` based on the instrument dropdown, and some
  fields (Workers) apply to one path only. Consider greying out / hiding inapplicable fields when
  "Futures Analytics" is selected so the form self-documents.
- **Mixed emoji usage.** Some headers use emoji (🎯 Factor Selection, 🤖 Train Model, 📊 Volatility,
  🪙 Commodities) and others don't. Fine as a deliberate style, but make it consistent per book.
- **Loading affordances are uneven.** Summary wraps its content in `dcc.Loading`; Market/Beta/Alpha
  subtabs mostly don't, so a slow data load shows a blank panel. Consider a shared loading wrapper.
- **Hard-coded pairs defaults.** The Pairs tab ships with literal bond codes (`250211.IB`, etc.)
  as default inputs — fine for a personal tool, but these will silently age out; consider deriving
  defaults from the latest on-the-run set.
- **`alpha-basket-div` removed but `build_basket_layout` is still imported** in
  `atlasnexus_daily.py:56` — dead import to clean up.
- **Magic intervals.** Refresh intervals (5s header, 5s run-center, 30min graph, 3s intraday) are
  scattered as literals. Centralize in one config block for tuning.

---

## 6. Suggested priority order for further development

1. **Fix the Intraday console import errors** (§4) — it currently can't launch.
2. **Rename Beta Book tab keys to match labels** (§3.1) — removes a standing maintenance hazard.
3. **Flatten / reconcile the Summary tab nesting** (§3.2) — biggest navigation inconsistency.
4. **Unify the two styling systems** (`atlas_styles` vs inline `THEME`) (§3.3).
5. **Decide Intraday's fate** — separate app vs. merged tab (§4.2).
6. Polish items in §5 as capacity allows.
