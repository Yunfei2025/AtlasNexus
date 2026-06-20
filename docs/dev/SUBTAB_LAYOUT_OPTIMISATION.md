# AtlasNexus — Beta Book Sub-tab Layout Optimisation Plan

> **Scope:** All six Beta Book sub-tabs (Candidates · Portfolio · Backtest · Factor · Bond · Futures).  
> **Implementation target:** Plotly Dash (Python + CSS).  
> **Design system reference:** `tokens/colors.css`, `tokens/spacing.css`, `tokens/typography.css`, `components/core/`, `components/data/`, `dash_integration/atlas_components.py`, `dash_integration/atlasnexus-design.css`.

---

## 0 · Foundational: Token Alignment (do this first)

The single biggest source of visual drift is that **`dash_integration/atlasnexus-design.css` and `dash_integration/atlas_components.py` define their own hardcoded hex palette** that is close to — but not the same as — the canonical design system tokens in `tokens/colors.css`.

| Variable | `atlasnexus-design.css` value | Canonical `tokens/colors.css` value |
|---|---|---|
| `--an-navy-700` / `--navy-700` | `#0c2b64` | `#122a4c` |
| `--an-navy-600` / `--navy-600` | `#112e66` | `#17345c` |
| `--an-navy-500` / `--navy-500` | `#1a3a6e` | `#21426e` |
| `--an-navy-400` / border | `#2a5298` | `#1e3a5f` |

### Actions

**File: `dash_integration/atlasnexus-design.css` — top `:root` block**

Replace the entire custom `--an-*` variable block with `@import` of the design system tokens and aliases:

```css
/* Replace the hand-rolled :root block with the canonical tokens */
@import url('../../tokens/colors.css');
@import url('../../tokens/spacing.css');
@import url('../../tokens/typography.css');

/* Shim aliases so existing class rules keep working without a rename pass */
:root {
  --an-navy-900:  var(--navy-900);
  --an-navy-800:  var(--navy-800);
  --an-navy-700:  var(--navy-700);
  --an-navy-600:  var(--navy-600);
  --an-navy-500:  var(--navy-500);
  --an-border:    var(--border-default);
  --an-border2:   var(--border-subtle);
  --an-text:      var(--text-primary);
  --an-muted:     var(--text-muted);
  --an-cyan:      var(--accent-cyan);
  --an-blue:      var(--accent-blue);
  --an-amber:     var(--accent-amber);
  --an-green:     var(--accent-green);
  --an-red:       var(--negative);
  --an-purple:    var(--accent-purple);
  --an-r:         var(--radius-xs);
  --an-t:         var(--dur-normal) var(--ease-standard);
}
```

**File: `dash_integration/atlas_components.py` — colour constants block**

Replace all hardcoded `_NAVY_*`, `_BORDER`, accent hex literals at the top of the file with references pulled from the CSS custom properties at runtime, or (simpler for Dash) update the Python constants to match the canonical token values:

```python
_NAVY_800   = "#0e1d3a"   # --navy-800
_NAVY_700   = "#122a4c"   # --navy-700
_NAVY_600   = "#17345c"   # --navy-600
_NAVY_500   = "#21426e"   # --navy-500
_BORDER     = "#1e3a5f"   # --border-default
_BORDER_STR = "#2a517f"   # --border-strong
_BLUE       = "#3d8bd4"   # --accent-blue
_GREEN      = "#2f9d6b"   # --accent-green
_AMBER      = "#e0a23c"   # --accent-amber
_RED        = "#d56b6b"   # --negative
_PURPLE     = "#7c70d6"   # --accent-purple
_CYAN       = "#45b6e6"   # --accent-cyan
_MUTED      = "#a4b6d2"   # --text-secondary
```

---

## 1 · Shell: Sub-tab Navigation Bar

**Current issue:** The sub-tab row (Candidates · Portfolio · Backtest · Factor · Bond · Futures) is rendered as plain `html.Button` or `dcc.Tab` elements without the `2px` accent underline spec from `tokens/spacing.css` (`--bw-tab: 2px`). The active tab uses an ad-hoc style rather than `--accent-blue` (Beta Book accent).

**File to edit:** wherever the Beta Book sub-tab row is defined — typically `web/app.py` or `web/layout.py` inside the `dcc.Tabs` / `html.Div` that wraps the six sub-tabs.

### Actions

Add these CSS rules to **`dash_integration/atlasnexus-design.css`**:

```css
/* ── Beta Book sub-tab bar ─────────────────────────────────────── */
.beta-subtab-bar {
  display: flex;
  border-bottom: 1px solid var(--border-default);
  background: transparent;
  padding: 0 var(--app-pad-x);
  gap: 0;
}

.beta-subtab-bar .tab {
  background: transparent;
  border: none;
  border-bottom: var(--bw-tab) solid transparent;
  margin-bottom: -1px;
  padding: 12px 20px;
  font-family: var(--font-sans);
  font-size: var(--fs-body);
  font-weight: var(--fw-regular);
  letter-spacing: var(--ls-tab);
  color: var(--text-muted);
  cursor: pointer;
  transition: color var(--dur-normal) var(--ease-standard),
              border-color var(--dur-normal) var(--ease-standard);
}

.beta-subtab-bar .tab:hover  { color: var(--text-primary); }

.beta-subtab-bar .tab--active {
  color: var(--text-primary);
  border-bottom-color: var(--accent-blue);
  font-weight: var(--fw-medium);
}
```

In Python, apply `className="beta-subtab-bar"` to the container and `className="tab tab--active"` / `"tab"` to each item.

---

## 2 · Candidates Tab

**File:** `web/tabs/beta_book/candidates.py` (or equivalent — the tab rendering `Factor Selection Pool` + `Train Model & Predict`)

### 2a · Factor Selection Pool — layout

**Current issue:** The Interest Rates country grid (CN / US / EU / JP / UK × IRDL / IRSL / IRCV) uses a wrapping inline-block layout. The Commodities section uses an inconsistent 4-column grid. FX and Equities use single-line inline flows.

**Fix:** Switch every asset-class sub-section to an explicit CSS Grid so all sections share the same column rhythm and the checkboxes align vertically.

Add to `dash_integration/atlasnexus-design.css`:

```css
/* ── Candidates: factor selection grid ────────────────────────── */
.factor-pool-section {
  padding: var(--space-5) 0;
  border-bottom: 1px solid var(--border-subtle);
}
.factor-pool-section:last-child { border-bottom: none; }

.factor-pool-section__heading {
  font: var(--type-h3);
  color: var(--text-heading);
  margin: 0 0 var(--space-3) 0;
}

.factor-pool-section__note {
  font: var(--type-meta);
  color: var(--text-muted);
  font-style: italic;
  margin: 0 0 var(--space-4) 0;
}

/* IR: 5 country columns, each with 3 checkbox rows */
.ir-country-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(80px, 1fr));
  gap: var(--space-4) var(--space-5);
}

.ir-country-grid__col-head {
  font: var(--type-label);
  letter-spacing: var(--ls-label);
  text-transform: uppercase;
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
  display: flex;
  align-items: center;
  gap: 5px;
}

/* FX / EQ: single wrap row */
.factor-inline-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4) var(--space-7);
  padding: var(--space-2) 0;
}

/* Commodities: 4-column grid */
.cmd-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3) var(--space-7);
}
```

In `candidates.py`, structure each asset class section using `html.Div(className="factor-pool-section")` wrapping:
- `html.Div(className="ir-country-grid")` for Interest Rates
- `html.Div(className="factor-inline-row")` for FX and Equities
- `html.Div(className="cmd-grid")` for Commodities

### 2b · Cross-Asset Correlation Analysis — visibility

**Current issue:** The Cross-Asset Correlation Analysis section is partially visible, cut off below the fold. It is floating in the center (`justifyContent: center`) rather than left-aligned.

**Fix:** In `candidates.py`, remove any `justifyContent: "center"` or `margin: auto` from the correlation section wrapper. Instead use:

```python
html.Div([
    # ... controls
], style={
    "display": "flex",
    "alignItems": "center",
    "gap": "12px",
    "padding": "14px var(--panel-pad)",
    "borderTop": "1px solid var(--border-subtle)",
    "marginTop": "var(--space-6)",
    "background": "var(--surface-sunken)",
    "borderRadius": "0 0 var(--radius-md) var(--radius-md)",
})
```

### 2c · Train Model & Predict — separation

**Current issue:** "Train Model & Predict" visually merges with the Factor Selection Pool. It should be a distinct panel.

**Fix:** Wrap the Train section in `atlas_components.card("TRAIN MODEL & PREDICT", ...)` with a `style_overrides={"marginTop": "16px", "background": "var(--surface-raised)"}`.

---

## 3 · Portfolio Tab

**File:** `web/tabs/beta_book/portfolio.py`

### 3a · Configuration header — control alignment

**Current issue:** `Total Capital`, `Max Dur`, and `Model` controls in the header row use inconsistent widths and the `→ max DV01 5.0 MM` derived label is unstyled and hard to read.

**Fix:** Use a flex row with explicit `gap` and align the derived label using `--text-muted` and `--font-mono`:

```python
# Configuration header row
html.Div([
    lbl("Total Capital"),
    dcc.Input(id="total-capital", value=10, type="number",
              style={"width": "90px", **_BASE_INPUT}),
    dropdown(id="capital-unit", options=["Million","Billion"], value="Billion",
             style={"width": "110px"}, clearable=False),
    html.Span("CNY", style={"color": _MUTED, "fontSize": "13px"}),
    lbl("Max Dur"),
    dcc.Input(id="max-dur", value=5, type="number",
              style={"width": "64px", **_BASE_INPUT}),
    html.Span(id="dv01-label", style={
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "12px", "color": _MUTED,
    }),
    lbl("Model"),
    button("Deterministic", id="btn-model-toggle", variant="secondary"),
], style={
    "display": "flex", "alignItems": "center",
    "gap": "10px", "flexWrap": "wrap",
    "padding": "12px var(--panel-pad)",
    "borderBottom": "1px solid var(--border-subtle)",
})
```

### 3b · Asset Pool list

**Current issue:** Asset pool items use a wide amber bar that stretches to 100% width, hiding the `(Category — N/A)` suffix for shorter names. The bars are also all the same width (all 100%), losing the relative-weight signal.

**Fix:** Switch from a single wide bar to a compact tag layout. Each item is a pill-badge with `background: var(--accent-amber-soft)`, `color: var(--accent-amber)`, `border: 1px solid var(--accent-amber)33`. The item name is plain text; the sub-label `(Precious Metals — N/A)` is rendered as `--text-muted` mono at `--fs-meta`.

Add to `dash_integration/atlasnexus-design.css`:

```css
.asset-pool-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 260px;
  overflow-y: auto;
  padding-right: 4px;
}

.asset-pool-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 7px 12px;
  background: var(--accent-amber-soft);
  border: 1px solid rgba(224,162,60,0.25);
  border-radius: var(--radius-xs);
  cursor: default;
}

.asset-pool-item__name {
  font-family: var(--font-sans);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  color: var(--accent-amber);
  flex: 1;
}

.asset-pool-item__meta {
  font-family: var(--font-mono);
  font-size: var(--fs-meta);
  color: var(--text-muted);
}
```

### 3c · Risk Budgets table — column widths

**Current issue:** The Risk Budgets table has 7 columns (`Factor · Vol%ann · xadj · RP Max · DV01 · Coeff · Exposure`) crammed with equal widths. `Exposure (MM CNY)` — the most interacted-with column — is the narrowest due to the stepper controls.

**Fix:** Use `dash_table.DataTable` with explicit `column` widths or a plain `html.Table` using the design system `DataTable` pattern. Suggested widths:

| Column | Width |
|--------|-------|
| Factor | 130px |
| Vol %ann | 80px |
| xadj | 60px |
| RP Max (MM CNY) | 100px |
| DV01 (MM/bp) | 90px |
| Coeff | 70px |
| Exposure (MM CNY) — stepper | 200px (flex grow) |

The stepper `−  [value]  +` should use `--surface-input` background, `--border-strong` border, and `--accent-blue` for the `+` / `−` icon color. Example stepper CSS:

```css
.stepper {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xs);
  overflow: hidden;
}
.stepper__btn {
  width: 30px; height: 30px;
  background: var(--surface-input);
  color: var(--accent-blue);
  border: none; cursor: pointer;
  font-size: 16px; font-weight: 600;
  transition: background var(--dur-fast);
}
.stepper__btn:hover { background: var(--surface-hover); }
.stepper__input {
  width: 70px; text-align: center;
  background: var(--surface-input);
  color: var(--text-primary);
  border: none; border-left: 1px solid var(--border-subtle);
  border-right: 1px solid var(--border-subtle);
  font-family: var(--font-mono); font-size: 13px;
  padding: 0 6px;
}
```

### 3d · IRDL Hedge Overlay — footer treatment

**Current issue:** The shield emoji row sits as a bare paragraph at the bottom without visual containment, looking orphaned.

**Fix:** Give it a `surface-sunken` tinted footer:

```python
html.Div([
    html.Span("🛡", style={"marginRight": "8px"}),
    html.Strong("IRDL Hedge Overlay", style={"color": _CYAN, "fontFamily": _MONO}),
    html.Span(" · optional post-optimisation duration hedge via bond futures or pay-fixed IRS",
              style={"color": _MUTED, "fontStyle": "italic", "fontSize": "12px"}),
], style={
    "padding": "10px var(--panel-pad)",
    "background": "var(--surface-sunken)",
    "borderTop": "1px solid var(--border-subtle)",
    "borderRadius": "0 0 var(--radius-md) var(--radius-md)",
    "display": "flex", "alignItems": "center",
})
```

---

## 4 · Backtest Tab

**File:** `web/tabs/beta_book/backtest.py`

### 4a · Individual Factors / Portfolio toggle

**Current issue:** The toggle is a full-width two-cell div with a manual blue fill for the active side. It does not match the `Tabs` spec (no `--bw-tab` underline, uses background fill instead of underline, doesn't use `--accent-blue`).

**Fix:** Replace with the standard sub-tab pattern from `dash_integration/atlasnexus-design.css` (class `.beta-subtab-bar`) or a segmented toggle:

```css
/* Segmented toggle — for 2-option mode switches (not navigation) */
.seg-toggle {
  display: inline-flex;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--surface-sunken);
}
.seg-toggle__btn {
  padding: 9px 28px;
  font-family: var(--font-sans);
  font-size: var(--fs-body);
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: color var(--dur-fast), background var(--dur-fast);
}
.seg-toggle__btn--active {
  background: var(--accent-blue);
  color: var(--text-on-accent);
  font-weight: var(--fw-medium);
}
```

In `backtest.py`, use `html.Div(className="seg-toggle")` with two `html.Button(className="seg-toggle__btn seg-toggle__btn--active")` children, wired to a `dcc.Store` for state.

### 4b · Strategy Parameters row — wrapping grid

**Current issue:** Eight parameters (`Train window · IC threshold · Top N features · Sizing · Smooth window · Lookback · Start Date · End Date`) are in a single `display:flex` row that clips at narrow viewports and has uneven spacing.

**Fix:** Switch to a CSS Grid with auto-fit columns:

```css
.strategy-params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: var(--space-4) var(--space-6);
  align-items: end;
  padding: var(--space-5) var(--panel-pad);
}
```

Each parameter uses `label_field()` from `atlas_components.py`. Date pickers (`Start Date`, `End Date`) get `min_width="160px"` and `z_index=10` (already supported by `label_field`).

### 4c · Run Backtest & Save button

**Current issue:** The green button uses a raw hex (`#27ae60`) that doesn't match `--accent-green: #2f9d6b`.

**Fix:** Use `atlas_components.button("▶ Run Backtest & Save", id="btn-run-backtest", variant="success")` — after the `atlas_components.py` constant fix in Phase 0, `_GREEN = "#2f9d6b"` will be canonical.

---

## 5 · Factor Tab

**File:** `web/tabs/beta_book/factor.py`

### 5a · Sidebar width and label hierarchy

**Current issue:** The Factor Explorer sidebar labels (`ASSET CLASS`, `REGION / TYPE`, `FACTOR(S)`) use a custom style instead of the `--type-th` / `--ls-label` spec. The sidebar has no defined width constraint and stretches on wide viewports.

**Fix:** Constrain the sidebar to `280px` fixed width. Apply to sidebar wrapper:

```python
html.Div([...], style={
    "width": "280px",
    "flexShrink": "0",
    "background": "var(--surface-panel)",
    "border": "1px solid var(--border-default)",
    "borderRadius": "var(--radius-md)",
    "padding": "var(--panel-pad)",
    "display": "flex",
    "flexDirection": "column",
    "gap": "var(--space-6)",
})
```

For the eyebrow labels (`ASSET CLASS`, `REGION / TYPE`, `FACTOR(S)`), use `section_header()` from `atlas_components.py` which applies `--type-th`, uppercase, and `--text-muted` color.

### 5b · Empty state for Historical Performance

**Current issue:** "Please select factors from the dropdowns above" is centre-aligned white text floating in the dark chart area with no visual containment.

**Fix:** Use a structured empty state:

```python
html.Div([
    html.Div("📊", style={"fontSize": "32px", "marginBottom": "12px", "opacity": "0.3"}),
    html.Div("No factor selected", style={
        "fontFamily": "'IBM Plex Sans', sans-serif",
        "fontSize": "15px", "fontWeight": "500",
        "color": _MUTED, "marginBottom": "6px",
    }),
    html.Div("Select asset class → region → factor(s) in the sidebar.", style={
        "fontFamily": "'IBM Plex Mono', monospace",
        "fontSize": "12px", "color": _FAINT,
    }),
], style={
    "display": "flex", "flexDirection": "column",
    "alignItems": "center", "justifyContent": "center",
    "height": "400px",
    "background": "var(--surface-sunken)",
    "border": "1px solid var(--border-subtle)",
    "borderRadius": "var(--radius-md)",
})
```

### 5c · Chartboost toolbar alignment

**Current issue:** The Plotly chart toolbar icons (camera, zoom, pan, etc.) are right-floated but without a background, making them hard to hit on the dark surface.

**Fix:** Add to `atlasnexus-design.css`:

```css
/* Plotly modebar — match terminal theme */
.js-plotly-plot .plotly .modebar {
  background: var(--surface-panel) !important;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 2px 4px;
}
.js-plotly-plot .plotly .modebar-btn path {
  fill: var(--text-muted) !important;
}
.js-plotly-plot .plotly .modebar-btn:hover path {
  fill: var(--text-primary) !important;
}
```

---

## 6 · Bond Tab

**File:** `web/tabs/beta_book/bond.py`

### 6a · Maturity bucket grid — uniform column count

**Current issue:** The grid renders 3 columns on the first row (0-1Y · 1-3Y · 3-5Y) and 2 on the second (5-7Y · 7-10Y), leaving an unbalanced layout. The two bottom cards are extra-wide relative to the top three.

**Fix:** Use CSS Grid with `grid-template-columns: repeat(3, 1fr)` and let the 5th bucket span naturally. Alternatively, use `repeat(auto-fill, minmax(320px, 1fr))` to adapt to viewport width:

```css
.bond-bucket-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-6);
  padding: var(--panel-pad);
}

@media (max-width: 1200px) {
  .bond-bucket-grid { grid-template-columns: repeat(2, 1fr); }
}
```

### 6b · Per-bucket card structure

**Current issue:** Each bucket card (e.g. "0-1Y") has `SELL (LOW Z)` and `BUY (HIGH Z)` as plain red/green text headers without badge styling. The `Avg Z` pill uses an ad-hoc background.

**Fix:** 
- Render `SELL (LOW Z)` / `BUY (HIGH Z)` labels using `badge(tone="neg")` / `badge(tone="pos")` from `atlas_components.py` instead of raw styled `html.Div`.
- Render the `Avg Z` chip using `badge(tone="cyan" if z > 0 else "neg")` with the value formatted to 2dp.
- Apply consistent card padding via `atlas_components.card()`:

```python
def bucket_card(label, ttm_range, n_bonds, avg_z, sell_rows, buy_rows):
    return card(label, html.Div([
        html.Div(f"TTM in {ttm_range} years", style={...meta style...}),
        html.Div([
            html.Span(f"{n_bonds} bonds", style={...}),
            badge(f"Avg Z {avg_z:+.2f}",
                  tone="pos" if avg_z > 0 else "neg"),
        ], style={"display":"flex","gap":"8px","marginBottom":"10px"}),
        badge("SELL (LOW Z)", tone="neg"),
        DataTable(columns=BOND_COLS, rows=sell_rows, compact=True),
        html.Div(style={"height":"10px"}),
        badge("BUY (HIGH Z)", tone="pos"),
        DataTable(columns=BOND_COLS, rows=buy_rows, compact=True),
    ]), style_overrides={"margin":"0","padding":"14px"})
```

### 6c · Z-Score column — HeatCell usage

**Current issue:** The Z-SCORE column uses a plain red/green background cell but not the design-system `HeatCell` (`components/data/DataTable.jsx` → `HeatCell`) diverging scale (`--heat-neg-3` → `--heat-pos-3`).

For the Dash (Python) equivalent, add a `format_zscore_cell` helper to `atlas_components.py`:

```python
HEAT_SCALE = [
    ("#6e2a38","rgba(255,255,255,0.9)"),  # ≤ −2.5
    ("#5a2c3e","rgba(255,255,255,0.85)"), # −2.5 to −1.5
    ("#3a2d45","rgba(255,255,255,0.8)"),  # −1.5 to −0.5
    ("#16294a","rgba(255,255,255,0.7)"),  # −0.5 to +0.5
    ("#1c3a52","rgba(255,255,255,0.8)"),  # +0.5 to +1.5
    ("#1f4f6b","rgba(255,255,255,0.85)"), # +1.5 to +2.5
    ("#236a86","rgba(255,255,255,0.9)"),  # ≥ +2.5
]

def zscore_cell_style(z: float) -> dict:
    idx = min(6, max(0, round(z) + 3))
    bg, fg = HEAT_SCALE[idx]
    return {"backgroundColor": bg, "color": fg,
            "fontWeight": "600", "textAlign": "center",
            "borderRadius": "2px", "padding": "3px 6px"}
```

Apply via `dash_table.DataTable`'s `style_data_conditional` or a custom cell renderer.

### 6d · Header bar — Bond Type + Refresh alignment

**Current issue:** `Bond Type` dropdown and `Refresh Data` button are right-floated with inconsistent vertical alignment relative to the title/description block.

**Fix:** Use a two-column `justify-content: space-between` header:

```python
html.Div([
    # Left: title + subtitle
    html.Div([
        html.H2("Bond Trading Signals (Z-Score)", style={"margin":0,"font":"var(--type-h1)","color":"var(--text-heading)"}),
        html.P("Realtime relative-value signals by maturity bucket...", style={"margin":"4px 0 0","font":"var(--type-meta)","color":"var(--text-muted)"}),
    ]),
    # Right: controls
    html.Div([
        label_field("Bond Type", dropdown(id="bond-type", options=[...], clearable=False, style={"width":"220px"})),
        button("↻ Refresh Data", id="btn-bond-refresh", variant="secondary"),
    ], style={"display":"flex","alignItems":"flex-end","gap":"12px"}),
], style={
    "display":"flex","justifyContent":"space-between",
    "alignItems":"flex-end","padding":"var(--panel-pad)",
    "borderBottom":"1px solid var(--border-subtle)",
})
```

---

## 7 · Futures Tab

**File:** `web/tabs/beta_book/futures.py`

### 7a · Two-panel proportion

**Current issue:** The Strategy Config sidebar has no defined width, causing it to shrink/expand with content. The chart panel doesn't fill remaining space.

**Fix:** Use a named CSS Grid layout for the two-panel split:

```css
.futures-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--space-6);
  padding: var(--panel-pad);
  min-height: calc(100vh - 120px);
}
```

In Python: `html.Div([sidebar, chart_panel], className="futures-layout")`.

### 7b · Strategy Config sidebar — section separation

**Current issue:** DATA SETTINGS, STRATEGIES, REGIME LOGIC, and PARAMETERS run together in the sidebar with only thin dividers. PARAMETERS is especially long and causes the sidebar to scroll past the chart height.

**Fix:** Use collapsible `<details>` / `<summary>` sections for PARAMETERS (which contain the per-strategy stepper controls), keeping DATA SETTINGS, STRATEGIES, and REGIME LOGIC always visible:

```css
.sidebar-section {
  border-bottom: 1px solid var(--border-subtle);
  padding: var(--space-5) 0;
}
.sidebar-section:last-child { border-bottom: none; }

.sidebar-section__head {
  font: var(--type-th);
  letter-spacing: var(--ls-label);
  text-transform: uppercase;
  color: var(--accent-blue);
  margin-bottom: var(--space-4);
}

/* Collapsible parameters block */
details.param-group { margin-bottom: var(--space-3); }
details.param-group summary {
  font: var(--type-label);
  letter-spacing: var(--ls-label);
  text-transform: uppercase;
  color: var(--text-secondary);
  cursor: pointer;
  margin-bottom: var(--space-2);
}
details.param-group summary::-webkit-details-marker { color: var(--text-muted); }
```

Wrap each strategy's parameter block (MA, Bollinger, VWAP, etc.) in a `html.Details` / `html.Summary` pair.

### 7c · Strategies checkbox grid — 2-column alignment

**Current issue:** The strategies (MA, DeMark, Bollinger, VWAP, Momentum, ATR, SAR, Mid Regime) use irregular column breaks. Some rows have 3 items, some 2.

**Fix:** Apply a consistent 2-column CSS Grid:

```css
.strategies-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3) var(--space-5);
}
```

In Python, wrap all `dcc.Checklist` items in `html.Div(className="strategies-grid")`.

### 7d · Date Range controls — inline alignment

**Current issue:** `Date Range` with two date pickers and an arrow separator (`→`) has inconsistent vertical alignment. The arrow is a plain character without flex centering.

**Fix:**

```python
html.Div([
    dcc.DatePickerSingle(id="date-start", ...),
    html.Span("→", style={"color": _MUTED, "fontSize": "14px", "alignSelf": "center"}),
    dcc.DatePickerSingle(id="date-end", ...),
], style={"display": "flex", "alignItems": "center", "gap": "8px"})
```

Add to `atlasnexus-design.css` to fix `dcc.DatePickerSingle` theming (currently inherits light browser default):

```css
.SingleDatePickerInput {
  background: var(--surface-input) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--radius-xs) !important;
}
.DateInput_input {
  background: transparent !important;
  color: var(--text-primary) !important;
  font-family: var(--font-mono) !important;
  font-size: 13px !important;
  padding: 6px 10px !important;
}
.DayPicker { background: var(--navy-700) !important; }
```

---

## 8 · Implementation Order

| Priority | Change | Files |
|---|---|---|
| 🔴 P0 | Token alignment — fix hex drift | `dash_integration/atlas_components.py`, `dash_integration/atlasnexus-design.css` |
| 🔴 P0 | Sub-tab bar CSS spec | `dash_integration/atlasnexus-design.css`, shared shell layout file |
| 🟠 P1 | Bond: bucket grid + ZScore HeatCell | `web/tabs/beta_book/bond.py`, `dash_integration/atlas_components.py` |
| 🟠 P1 | Backtest: segmented toggle + params grid | `web/tabs/beta_book/backtest.py`, `dash_integration/atlasnexus-design.css` |
| 🟠 P1 | Portfolio: asset pool tags + Risk Budgets columns | `web/tabs/beta_book/portfolio.py`, `dash_integration/atlasnexus-design.css` |
| 🟡 P2 | Candidates: IR grid + Commodities grid + Cross-Asset footer | `web/tabs/beta_book/candidates.py`, `dash_integration/atlasnexus-design.css` |
| 🟡 P2 | Futures: sidebar grid + collapsible params + date pickers | `web/tabs/beta_book/futures.py`, `dash_integration/atlasnexus-design.css` |
| 🟢 P3 | Factor: fixed sidebar width + empty state | `web/tabs/beta_book/factor.py`, `dash_integration/atlasnexus-design.css` |
| 🟢 P3 | Plotly modebar theming | `dash_integration/atlasnexus-design.css` |

---

## 9 · Token Quick Reference

All values below are already defined in `tokens/colors.css` and `tokens/spacing.css`. Reference them in Python via the `--an-*` shim aliases added in Phase 0, or directly via `var(--navy-700)` etc. in CSS classes.

| Token | Value | Use |
|---|---|---|
| `--surface-panel` → `--navy-700` | `#122a4c` | Card/section background |
| `--surface-input` → `--navy-600` | `#17345c` | Input/select fill |
| `--surface-hover` → `--navy-500` | `#21426e` | Hover row / button hover |
| `--border-default` | `#1e3a5f` | Panel borders |
| `--border-strong` | `#2a517f` | Input borders |
| `--accent-blue` | `#3d8bd4` | Beta Book primary (tabs, focus) |
| `--accent-cyan` | `#45b6e6` | Links, active underline, status |
| `--accent-amber` | `#e0a23c` | Asset pool, Alpha accent |
| `--accent-purple` | `#7c70d6` | Checkboxes, ML controls |
| `--positive` | `#41b078` | Gains, BUY text |
| `--negative` | `#d56b6b` | Losses, SELL text |
| `--panel-pad` | `22px` | Panel internal padding |
| `--space-4` | `8px` | Tight gap |
| `--space-6` | `16px` | Standard gap |
| `--radius-md` | `8px` | Panel corners |
| `--radius-xs` | `3px` | Cell / input corners |
| `--font-mono` | IBM Plex Mono | All numbers, tickers, buttons |
| `--font-sans` | IBM Plex Sans | Labels, headings, body |
