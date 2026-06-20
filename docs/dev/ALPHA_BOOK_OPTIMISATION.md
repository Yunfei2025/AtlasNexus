# AtlasNexus — Alpha Book Sub-tab Layout Optimisation Plan

> **Scope:** All six Alpha Book sub-tabs (Candidates · Portfolio · Backtest · Spread · Pairs · Volatility).
> **Implementation target:** Plotly Dash (Python + CSS).
> **Design reference:** `templates/alpha-book/AlphaBook.dc.html` — interactive visual reference for all six tabs.
> **Design system:** `tokens/colors.css`, `tokens/spacing.css`, `tokens/typography.css`, `components/core/`, `components/data/`, `dash_integration/`.

---

## 0 · Token Alignment (prerequisite — same as Beta Book)

Before any per-tab work, align `dash_integration/atlasnexus-design.css` with canonical tokens (see `SUBTAB_LAYOUT_OPTIMISATION.md §0`). Alpha Book uses `--accent-amber: #e0a23c` as its accent colour — ensure this is available via the `--an-amber` shim alias.

```python
# atlas_components.py — Alpha Book accent constant
_AMBER = "#e0a23c"   # --accent-amber
```

---

## 1 · Sub-tab Navigation Bar

**Current issue:** Sub-tab buttons inherit Dash's `dcc.Tab` default style — equal-width flex cells, no amber underline, no hover transition. Active tab uses a background fill rather than the spec'd 2px underline.

**Fix — CSS (add to `atlasnexus-design.css`):**

```css
/* ── Alpha Book sub-tab bar ─────────────────────────────────────── */
.alpha-subtab-bar {
  display: flex;
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-sunken);    /* #0c1830 */
  padding: 0 var(--app-pad-x);
  gap: 0;
}

.alpha-subtab-bar .tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  padding: 12px 20px;
  font-family: var(--font-sans);
  font-size: var(--fs-body);
  font-weight: var(--fw-regular);
  letter-spacing: var(--ls-tab);
  color: var(--text-muted);
  cursor: pointer;
  white-space: nowrap;
  transition: color var(--dur-normal) var(--ease-standard),
              border-color var(--dur-normal) var(--ease-standard);
}

.alpha-subtab-bar .tab:hover  { color: var(--text-primary); }

.alpha-subtab-bar .tab--active {
  color: var(--text-primary);
  border-bottom-color: var(--accent-amber);   /* amber, not blue */
  font-weight: var(--fw-medium);
}
```

**Fix — Python:** apply `className="alpha-subtab-bar"` to the nav container and `className="tab tab--active"` / `"tab"` to each item. Do **not** use `flex:1` on tab items — let them size to content.

---

## 2 · Candidates Tab

**File:** `web/tabs/alpha_book/candidates.py`

### 2a · Spread Categories panel

No structural change needed — the existing checkbox row is already correct. Ensure the panel uses `--surface-raised` (`--navy-750`) for its background, not `--navy-700`, to lift it slightly off the page.

```python
html.Div([
    html.Div("Spread Categories", style={
        "font": "var(--type-label)", "textTransform": "uppercase",
        "letterSpacing": "var(--ls-label)", "color": _MUTED, "marginBottom": "11px",
    }),
    dcc.Checklist(
        id="alpha-spread-cats",
        options=["Bond-Curve","Bond-Swap","Swap Spreads","Tenor Spreads",
                 "Bond-Futures","Calendar Spreads","Futures-Swap"],
        value=["Bond-Curve","Bond-Swap","Swap Spreads","Tenor Spreads"],
        inline=True,
        inputStyle={"accentColor": _PURPLE},
        labelStyle={"display":"inline-flex","alignItems":"center","gap":"7px",
                    "marginRight":"22px","fontSize":"13px","color":_TEXT,"cursor":"pointer"},
    ),
], style={"background": _NAVY_750, "border": f"1px solid {_BORDER}",
          "borderRadius": "8px", "padding": "12px 22px"})
```

### 2b · Z-Score + Direction — UNIFIED panel (key improvement)

**Current issue:** Z-Score slider and Direction radios live in **separate** panels, wasting vertical space and making their relationship non-obvious.

**Fix:** Combine into one panel with a two-column internal layout: slider on the left, value readout + radio group on the right.

```python
html.Div([
    # Left: slider
    html.Div([
        html.Div("Z-Score Threshold (MR candidates only)", style={...label_style...}),
        dcc.Slider(id="alpha-zscore", min=1, max=3.5, step=0.1, value=2.0,
                   marks={1:"1.0σ",1.5:"1.5σ",2:"2.0σ",2.5:"2.5σ",3:"3.0σ",3.5:"3.5σ"},
                   tooltip={"placement":"bottom"}),
    ], style={"flex":"1","paddingRight":"22px","borderRight":f"1px solid {_BORDER}"}),

    # Right: value + direction
    html.Div([
        html.Div([
            html.Label("Value", style={...label_style...}),
            dcc.Input(id="alpha-zscore-display", type="number", value=2.0,
                      style={"width":"56px", **_BASE_INPUT, "textAlign":"right"}),
        ], style={"display":"flex","alignItems":"center","gap":"10px","marginBottom":"12px"}),
        html.Div("Direction", style={...label_style...}),
        dcc.RadioItems(
            id="alpha-direction",
            options=[
                {"label":"All",              "value":"all"},
                {"label":"BUY (z < -thd)",   "value":"buy"},
                {"label":"SELL (z > +thd)",  "value":"sell"},
            ],
            value="all",
            inputStyle={"accentColor": _PURPLE},
            labelStyle={"display":"block","marginBottom":"5px","fontSize":"13px","cursor":"pointer"},
        ),
    ], style={"width":"260px","paddingLeft":"22px","flexShrink":"0"}),

], style={"display":"flex","alignItems":"flex-start","background":_NAVY_750,
          "border":f"1px solid {_BORDER}","borderRadius":"8px","padding":"12px 22px"})
```

### 2c · Seasonal Gate — collapsible `<details>` (key improvement)

**Current issue:** Seasonal gate occupies a full-height panel whether active or not, adding ~80px of dead space when disabled.

**Fix:** Wrap in `html.Details` / `html.Summary` so it collapses when unchecked:

```python
html.Details([
    html.Summary([
        dcc.Checklist(id="alpha-seasonal-gate", options=[{
            "label": " Apply seasonal gate before scan (exclude noise months)",
            "value": "on"
        }], value=[], inputStyle={"accentColor":_PURPLE},
        labelStyle={"fontSize":"14px","cursor":"pointer","color":_TEXT}),
        html.Span("▾ expand", style={"fontSize":"11px","color":_MUTED,"marginLeft":"auto"}),
    ], style={"display":"flex","alignItems":"center","gap":"10px","listStyle":"none",
              "padding":"11px 22px","cursor":"pointer"}),

    # Expanded body
    html.Div([
        html.P("When ON: instruments whose current-month seasonality is statistically weak "
               "(low consistency or high p-value) are excluded from scan results.",
               style={"fontStyle":"italic","fontSize":"12px","color":_FAINT,"marginTop":"4px"}),
        html.Div([
            html.Div([
                html.Label("Min consistency (%)", style={...label_style...}),
                dcc.Slider(id="alpha-min-cons", min=50, max=100, step=5, value=75,
                           marks={50:"50%",62:"62%",75:"75%",87:"87%",100:"100%"}),
            ], style={"flex":"1"}),
            html.Div([
                html.Label("p-value threshold", style={...label_style...}),
                dcc.Dropdown(id="alpha-pval", options=["0.10","0.05","0.01"],
                             value="0.10", clearable=False, style={"width":"130px"}),
            ], style={"flexShrink":"0","width":"130px"}),
        ], style={"display":"grid","gridTemplateColumns":"1fr 130px","gap":"20px","alignItems":"end"}),
    ], style={"padding":"4px 22px 14px","borderTop":f"1px solid {_NAVY_800}"}),

], style={"background":_NAVY_750,"border":f"1px solid {_BORDER}","borderRadius":"8px","overflow":"hidden"})
```

Add to `atlasnexus-design.css`:
```css
details.seasonal-gate > summary::-webkit-details-marker { display: none; }
details.seasonal-gate > summary { list-style: none; }
```

### 2d · Scan button — amber accent

**Current issue:** Scan button uses `--accent-blue` (Beta Book colour). Alpha Book primary action should be `--accent-amber`.

```python
button("🔍 SCAN CANDIDATES", id="btn-alpha-scan", variant="alpha")
# or inline:
html.Button("🔍 SCAN CANDIDATES", id="btn-alpha-scan",
    style={"background":_AMBER,"color":"#0c0c00","fontFamily":_MONO,
           "fontWeight":"700","fontSize":"12px","letterSpacing":".05em",
           "padding":"10px 20px","border":"none","borderRadius":"5px","cursor":"pointer"})
```

---

## 3 · Portfolio Tab

**File:** `web/tabs/alpha_book/portfolio.py`

### 3a · Two-column body for Step 1 (key improvement)

**Current issue:** Candidate Instruments and Saved Positions are stacked vertically, forcing Saved Positions far below the fold. Candidate Instruments is usually empty, wasting the top half.

**Fix:** Side-by-side grid — Candidates left (1fr), Saved Positions right (2fr):

```python
html.Div([
    # Left column: Candidate Instruments
    html.Div([
        section_header("Candidate Instruments", count=len(candidates), accent="blue"),
        html.Div("Run Check Correlation in the Candidates subtab to populate this list.",
                 style={"fontStyle":"italic","fontSize":"12px","color":_FAINT}) if not candidates
        else instrument_list(candidates),
    ], style={"flex":"1","padding":"13px 22px","borderRight":f"1px solid {_NAVY_800}"}),

    # Right column: Saved Positions — compact 3-col card grid
    html.Div([
        section_header("Saved Positions", count=len(positions), accent="amber",
                       sub="read-only"),
        html.Div([position_card(p) for p in positions],
                 style={"display":"grid","gridTemplateColumns":"repeat(3,1fr)","gap":"6px"}),
        html.P("Click ↺ Recalculate Correlation to build the matrix for all instruments.",
               style={"fontStyle":"italic","fontSize":"12px","color":_FAINT,"marginTop":"10px"}),
    ], style={"flex":"2","padding":"13px 22px"}),

], style={"display":"flex","borderBottom":f"1px solid {_NAVY_800}","minHeight":"180px"})
```

**Position card helper:**
```python
def position_card(pos: dict) -> html.Div:
    regime_badge = badge(pos["regime"], tone="amber" if pos["regime"]=="MOM" else "cyan")
    dir_badge    = badge(pos["direction"], tone="buy" if pos["direction"]=="BUY" else "sell")
    return html.Div([
        html.Div(pos["id"],   style={"font":f"500 12px {_MONO}","color":_TEXT,"marginBottom":"2px"}),
        html.Div(f"{pos['type']} · z=—", style={"fontSize":"11px","color":_MUTED,"marginBottom":"6px"}),
        html.Div([regime_badge, dir_badge],
                 style={"display":"flex","justifyContent":"space-between"}),
    ], style={"background":_NAVY_800,"border":f"1px solid {_BORDER}",
              "borderRadius":"5px","padding":"8px 10px"})
```

### 3b · Step 2 — inline config strip

**Current issue:** Step 2 Configuration is a standalone panel that looks disconnected from Steps 1 and 3.

**Fix:** Compact horizontal strip — all controls on one line:

```python
html.Div([
    html.Span("Step 2 — Configuration",
              style={"font":f"500 14px {_SANS}","color":_TEXT,"marginRight":"20px"}),
    label_field("Total Capital",
        dcc.Input(id="alpha-total-cap", type="number", value=10,
                  style={"width":"60px",**_BASE_INPUT,"textAlign":"right"})),
    html.Span("Billion CNY", style={"fontSize":"12px","color":_MUTED}),
    html.Div(style={"width":"1px","height":"18px","background":_BORDER,"margin":"0 14px"}),
    label_field("Total Single Side DV01",
        dcc.Input(id="alpha-dv01", type="number", value=5,
                  style={"width":"60px",**_BASE_INPUT,"textAlign":"right"})),
    html.Span("Million CNY", style={"fontSize":"12px","color":_MUTED}),
    html.Div(style={"width":"1px","height":"18px","background":_BORDER,"margin":"0 14px"}),
    html.Span("Method", style={**_LABEL_STYLE,"marginRight":"7px"}),
    html.Span("Risk Parity", style={"fontSize":"13px","color":_CYAN,"fontWeight":"600"}),
], style={"display":"flex","alignItems":"center","gap":"8px","flexWrap":"wrap",
          "padding":"12px 22px","background":_NAVY_750,"border":f"1px solid {_BORDER}","borderRadius":"8px"})
```

### 3c · Step 3 — RUN OPTIMIZATION in panel header actions

Move the `RUN OPTIMIZATION` button into the Panel's `actions` slot (right side of the header), so it sits alongside the title rather than floating after the stats strip.

```python
card("Step 3 — Portfolio Allocation Results",
     children=[stats_strip, results_table],
     actions=[button("▶ RUN OPTIMIZATION", id="btn-alpha-optimize", variant="primary")])
```

---

## 4 · Backtest Tab

**File:** `web/tabs/alpha_book/backtest.py`

### 4a · Compact segmented toggle (key improvement)

**Current issue:** Individual Spread / Portfolio toggle spans 100% width, making it look like two separate primary buttons rather than a single binary control.

**Fix:** Left-aligned `inline-flex` pill, ~400px max:

```css
/* atlasnexus-design.css */
.alpha-bt-toggle {
  display: inline-flex;
  border: 1px solid var(--border-strong);
  border-radius: 5px;
  overflow: hidden;
  background: var(--navy-800);
}
.alpha-bt-toggle__btn {
  padding: 9px 28px;
  border: none;
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text-muted);
  background: transparent;
  cursor: pointer;
  transition: background 90ms, color 90ms;
}
.alpha-bt-toggle__btn--active {
  background: var(--accent-blue);
  color: #fff;
  font-weight: 500;
}
```

Python: `html.Div([...], className="alpha-bt-toggle", style={"alignSelf":"flex-start"})`.

### 4b · Min Holding merged into Spread Selection (key improvement)

**Current issue:** Min Holding (days) is isolated in its own full-width panel between Spread Selection and Trend Parameters, creating a fragmented three-panel layout.

**Fix:** Move Min Holding into the Spread Selection panel as a third row item, separated by a thin vertical divider:

```python
# Inside Spread Selection panel body:
html.Div([
    # Spread Type + Instrument
    html.Div([
        label_field("Spread Type", dropdown(..., style={"minWidth":"190px"})),
        label_field("Instrument",  input_text(id="alpha-instrument", value="220019.IB")),
    ], style={"display":"flex","gap":"16px","alignItems":"flex-end","flexWrap":"wrap"}),

    # Trade Style row
    html.Div([...radio items...]),

    # Bottom row: Min Holding (previously its own panel)
    html.Div([
        label_field("Min Holding (days)",
            dcc.Input(id="alpha-min-hold", type="number", value=7,
                      style={"width":"72px",**_BASE_INPUT,"textAlign":"center"})),
    ], style={"paddingTop":"10px","borderTop":f"1px solid {_BORDER}"}),

], style={"padding":"14px 22px","display":"flex","flexDirection":"column","gap":"12px"})
```

### 4c · Trend Parameters — 5-column grid

**Current issue:** The five Trend Parameters (`Theta · Mom window · Vol window · Trail mult · Momentum buffer`) are in a single `flex` row that overflows at ≤1280px and has uneven spacing.

**Fix:** CSS Grid with 5 equal columns:

```css
.alpha-trend-params {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px 16px;
}
```

Each parameter: label stacked above input, `width: 100%`, right-aligned mono value.

### 4d · Run button — green, directly below params

**Current issue:** `RUN INDIVIDUAL BACKTEST` button uses `#27ae60` which doesn't match `--accent-green: #2f9d6b` (see §0 token alignment). Also floats disconnected below params.

**Fix:** Use `button(..., variant="success")` after constant alignment, and place it immediately below the Trend Parameters panel with no extra spacing panel between.

---

## 5 · Spread Tab

**File:** `web/tabs/alpha_book/spread.py`

### 5a · True 2-column sidebar layout (key improvement)

**Current issue:** The Spread Explorer controls panel is positioned top-left as an isolated box. The charts (`DAILY SPREAD STATISTICS`, `SPREAD TIME SERIES`) start below the sidebar, wasting the right half of the screen when the sidebar is present.

**Fix:** CSS Grid two-column layout — fixed 260px sidebar + flex-1 chart area:

```css
.alpha-spread-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 14px;
  align-items: start;
}

.alpha-spread-sidebar {
  position: sticky;
  top: 14px;                          /* stays visible while chart area scrolls */
}
```

Python:
```python
html.Div([
    html.Div([...sidebar controls...], className="alpha-spread-sidebar"),
    html.Div([daily_spread_chart, time_series_chart],
             style={"display":"flex","flexDirection":"column","gap":"14px"}),
], className="alpha-spread-layout")
```

### 5b · Sidebar section headers — amber eyebrow

Use `--accent-amber` for the "SPREAD EXPLORER" title to reinforce the Alpha Book accent:

```python
html.Div("SPREAD EXPLORER", style={
    "fontFamily": _MONO, "fontWeight": "700", "fontSize": "12px",
    "letterSpacing": ".09em", "textTransform": "uppercase",
    "color": _AMBER, "padding": "11px 18px",
    "borderBottom": f"1px solid {_NAVY_800}",
})
```

Each control (Spread Type, Futures Season, Highlight Month, Years) uses the 10px uppercase label style + full-width select, with `14px` vertical gap between groups.

---

## 6 · Pairs Tab

**File:** `web/tabs/alpha_book/pairs.py`

### 6a · Config panel — compact header strip (key improvement)

**Current issue:** The config section (Pairs Analysis title, pair inputs, Days, Refresh button) is a tall bordered box with excessive internal padding. Days and Refresh float separately below the pair inputs.

**Fix:** Move title + Days + Refresh into the panel's **header row** (space-between); the pair inputs stay in the panel body as a structured table grid.

```python
# Panel header
html.Div([
    html.Div([
        html.Span("Pairs Analysis", style={"font":f"500 15px {_SANS}","color":_TEXT}),
        html.Span("Interactive spread analysis with confidence bands (in basis points)",
                  style={"fontSize":"12px","color":_MUTED,"marginLeft":"12px"}),
    ]),
    html.Div([
        label_field("Days", dcc.Input(id="pairs-days", type="number", value=90,
                                      style={"width":"60px",**_BASE_INPUT,"textAlign":"center"})),
        button("↻ REFRESH PLOTS", id="btn-pairs-refresh", variant="secondary"),
        html.Span(id="pairs-last-updated",
                  style={"fontSize":"11px","color":_MUTED,"fontFamily":_MONO}),
    ], style={"display":"flex","alignItems":"center","gap":"10px"}),
], style={"display":"flex","alignItems":"center","justifyContent":"space-between",
          "flexWrap":"wrap","gap":"10px","padding":"11px 22px",
          "borderBottom":f"1px solid {_NAVY_800}"})
```

### 6b · Pair inputs — data-grid table pattern

**Current issue:** Pair inputs (Leg 1, Leg 2 across PAIR 1–4) are laid out as ad-hoc cells without consistent row/column structure.

**Fix:** CSS Grid with a row-label column:

```css
.pairs-input-grid {
  display: grid;
  grid-template-columns: 60px repeat(4, 1fr);
  border-top: 1px solid var(--navy-800);
}

.pairs-input-grid .row-label {
  background: var(--navy-800);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-top: 1px solid var(--border-default);
  border-right: 1px solid var(--navy-800);
}

.pairs-input-grid .col-header {
  background: var(--surface-th);
  font: var(--type-th);
  letter-spacing: var(--ls-label);
  text-transform: uppercase;
  color: var(--text-muted);
  text-align: center;
  padding: 8px 12px;
  border-right: 1px solid var(--navy-800);
}

.pairs-input-grid .cell {
  padding: 8px 12px;
  border-top: 1px solid var(--border-default);
  border-right: 1px solid var(--navy-800);
}
```

### 6c · Charts — 2×2 grid

**Current issue:** Charts for PAIR 1 and PAIR 2 are shown side-by-side at ~50% width each, while PAIR 3 and PAIR 4 have no chart area visible in the viewport.

**Fix:** Explicit 2×2 grid so all four pairs are visible without scrolling (assuming 1440px+ viewport):

```css
.pairs-chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
```

Each chart card: panel header with `PAIR N: Leg1 vs Leg2`, then `dcc.Graph` at 300px height with `config={"displayModeBar":False}`.

---

## 7 · Volatility Tab

**File:** `web/tabs/alpha_book/volatility.py`

### 7a · Config panel — inline header controls (key improvement)

**Current issue:** Controls (Ticker, Lookback Period, Std Deviation Multiplier, Run Analysis, Refresh Data) are stacked in a separate panel, taking ~100px above the KPI strip.

**Fix:** Inline all controls into the panel header row, to the right of the title:

```python
html.Div([
    html.Span("🎯 Volatility Trading Strategy Analysis",
              style={"font":f"500 15px {_SANS}","color":_TEXT,"whiteSpace":"nowrap"}),
    html.Div(style={"width":"1px","height":"20px","background":_BORDER,"flexShrink":"0"}),
    label_field("Ticker",    dropdown(id="vol-ticker", options=[...], style={"minWidth":"140px"})),
    label_field("Lookback",  input_text(id="vol-lookback", value="10", width="50px")),
    label_field("Std Dev ×", input_text(id="vol-stddev",   value="2",  width="50px")),
    button("▶ RUN ANALYSIS",  id="btn-vol-run",     variant="primary"),
    button("↻ REFRESH DATA",  id="btn-vol-refresh", variant="secondary"),
], style={"display":"flex","alignItems":"center","gap":"14px","flexWrap":"wrap",
          "padding":"11px 22px","borderBottom":f"1px solid {_NAVY_800}"})
```

### 7b · Unified KPI strip — single row (key improvement)

**Current issue:** KPIs are split across **two** separate card rows (Ticker + IV maturities + Signal, then performance stats), forcing unnecessary scrolling and obscuring the relationship between IV levels and strategy performance.

**Fix:** Merge into **one horizontal strip** — the ticker acts as the strip anchor, a thin vertical divider separates IV readings from performance stats:

```python
def kpi_cell(label, value, color=_TEXT, first=False, last=False):
    radius = "5px 0 0 5px" if first else ("0 5px 5px 0" if last else "0")
    border_left = "" if first else "none"
    return html.Div([
        html.Div(label, style={"fontSize":"10px","fontWeight":"700","letterSpacing":".07em",
                               "textTransform":"uppercase","color":_MUTED,"marginBottom":"5px",
                               "fontFamily":_MONO}),
        html.Div(value, style={"fontSize":"16px","fontWeight":"600","color":color,
                               "fontFamily":_MONO,"lineHeight":"1"}),
    ], style={"background":_NAVY_700,"border":f"1px solid {_BORDER}",
              "borderLeft":border_left or f"1px solid {_BORDER}",
              "borderRadius":radius,"padding":"10px 14px","flexShrink":"0"})

kpi_strip = html.Div([
    kpi_cell("Ticker",        ticker_val,    first=True),
    kpi_cell("1M IV",         iv_1m),
    kpi_cell("2M IV",         iv_2m),
    kpi_cell("3M IV",         iv_3m),
    kpi_cell("Signal",        signal_val),
    html.Div(style={"width":"1px","background":_BORDER_STR,"margin":"6px 0","flexShrink":"0"}),
    kpi_cell("Total Return",  total_ret,  color=_GREEN),
    kpi_cell("Ann. Return",   ann_ret,    color=_GREEN),
    kpi_cell("Volatility",    vol_val),
    kpi_cell("Sharpe",        sharpe_val),
    kpi_cell("Win Rate",      win_rate),
    kpi_cell("Max Drawdown",  max_dd,     color=_RED),
    kpi_cell("Num Trades",    n_trades,   last=True),
], style={"display":"flex","overflowX":"auto"})
```

### 7c · Plotly modebar theming

Both Volatility charts expose the Plotly modebar (camera, zoom, pan). Apply dark theme from `atlasnexus-design.css` (same rule as Beta Book §5c):

```css
.js-plotly-plot .plotly .modebar {
  background: var(--surface-panel) !important;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 2px 4px;
}
.js-plotly-plot .plotly .modebar-btn path { fill: var(--text-muted) !important; }
.js-plotly-plot .plotly .modebar-btn:hover path { fill: var(--text-primary) !important; }
```

---

## 8 · Implementation Order

| Priority | Change | File(s) | Effort |
|---|---|---|---|
| 🔴 P0 | Token alignment — amber constant | `atlas_components.py`, `atlasnexus-design.css` | 5 min |
| 🔴 P0 | Sub-tab bar — amber underline | `atlasnexus-design.css`, layout shell | 10 min |
| 🟠 P1 | Spread: 2-column sidebar layout | `spread.py`, `atlasnexus-design.css` | 15 min |
| 🟠 P1 | Backtest: compact toggle + merge Min Holding | `backtest.py`, `atlasnexus-design.css` | 20 min |
| 🟠 P1 | Portfolio: 2-col Step 1 body + Step 2 strip | `portfolio.py` | 25 min |
| 🟡 P2 | Candidates: unified Z-Score+Direction panel + collapsible seasonal gate | `candidates.py`, `atlasnexus-design.css` | 20 min |
| 🟡 P2 | Volatility: inline config + unified KPI strip | `volatility.py` | 20 min |
| 🟡 P2 | Backtest: Trend Parameters 5-col grid | `backtest.py`, `atlasnexus-design.css` | 10 min |
| 🟢 P3 | Pairs: compact header + 2×2 chart grid | `pairs.py`, `atlasnexus-design.css` | 20 min |
| 🟢 P3 | Scan button — amber primary | `candidates.py` | 2 min |
| 🟢 P3 | Plotly modebar theming | `atlasnexus-design.css` | 5 min |

---

## 9 · CSS additions to `atlasnexus-design.css`

Add all of the following in one block at the end of `atlasnexus-design.css`:

```css
/* ═══════════════════════════════════════════════════════════════════
   Alpha Book — Layout Optimisation (alpha_book_optimisation §1–7)
   ═══════════════════════════════════════════════════════════════════ */

/* § 1 · Sub-tab bar */
.alpha-subtab-bar { display:flex; border-bottom:1px solid var(--border-default); background:var(--surface-sunken); padding:0 var(--app-pad-x); }
.alpha-subtab-bar .tab { background:transparent; border:none; border-bottom:2px solid transparent; margin-bottom:-1px; padding:12px 20px; font-family:var(--font-sans); font-size:var(--fs-body); font-weight:var(--fw-regular); letter-spacing:var(--ls-tab); color:var(--text-muted); cursor:pointer; white-space:nowrap; transition:color var(--dur-normal),border-color var(--dur-normal); }
.alpha-subtab-bar .tab:hover { color:var(--text-primary); }
.alpha-subtab-bar .tab--active { color:var(--text-primary); border-bottom-color:var(--accent-amber); font-weight:var(--fw-medium); }

/* § 2c · Seasonal gate collapsible */
details.seasonal-gate > summary { list-style:none; display:flex; align-items:center; gap:10px; padding:11px 22px; cursor:pointer; }
details.seasonal-gate > summary::-webkit-details-marker { display:none; }

/* § 4a · Backtest segmented toggle */
.alpha-bt-toggle { display:inline-flex; border:1px solid var(--border-strong); border-radius:5px; overflow:hidden; background:var(--navy-800); }
.alpha-bt-toggle__btn { padding:9px 28px; border:none; font-family:var(--font-sans); font-size:14px; color:var(--text-muted); background:transparent; cursor:pointer; transition:background 90ms,color 90ms; }
.alpha-bt-toggle__btn--active { background:var(--accent-blue); color:#fff; font-weight:500; }

/* § 4c · Trend parameters grid */
.alpha-trend-params { display:grid; grid-template-columns:repeat(5,1fr); gap:12px 16px; }

/* § 5a · Spread 2-column layout */
.alpha-spread-layout { display:grid; grid-template-columns:260px 1fr; gap:14px; align-items:start; }
.alpha-spread-sidebar { position:sticky; top:14px; }

/* § 6b · Pairs input grid */
.pairs-input-grid { display:grid; grid-template-columns:60px repeat(4,1fr); }
.pairs-input-grid .col-header { background:var(--surface-th); font:var(--type-th); letter-spacing:var(--ls-label); text-transform:uppercase; color:var(--text-muted); text-align:center; padding:8px 12px; border-right:1px solid var(--navy-800); }
.pairs-input-grid .row-label { background:var(--navy-800); font-size:12px; font-weight:600; color:var(--text-secondary); display:flex; align-items:center; padding:8px 12px; border-top:1px solid var(--border-default); border-right:1px solid var(--navy-800); }
.pairs-input-grid .cell { padding:8px 12px; border-top:1px solid var(--border-default); border-right:1px solid var(--navy-800); }

/* § 6c · Pairs 2×2 chart grid */
.pairs-chart-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }

/* § 7 · Plotly modebar */
.js-plotly-plot .plotly .modebar { background:var(--surface-panel) !important; border:1px solid var(--border-subtle); border-radius:var(--radius-xs); padding:2px 4px; }
.js-plotly-plot .plotly .modebar-btn path { fill:var(--text-muted) !important; }
.js-plotly-plot .plotly .modebar-btn:hover path { fill:var(--text-primary) !important; }
```

---

## 10 · Token Quick Reference (Alpha Book)

| Token | Value | Use |
|---|---|---|
| `--accent-amber` | `#e0a23c` | Alpha Book accent — active tab, scan button, section glyphs |
| `--accent-blue` | `#3d8bd4` | Primary action buttons (Run, Refresh) |
| `--accent-cyan` | `#45b6e6` | Links, Method label, MR regime badge |
| `--accent-purple` | `#7c70d6` | Checkbox / radio / slider accent |
| `--positive` | `#41b078` | Gain text (returns, win rate when good) |
| `--negative` | `#d56b6b` | Loss text (drawdown, negative PnL) |
| `--buy-bg/fg` | `#2f9d6b / #eafff5` | BUY direction badge |
| `--sell-bg/fg` | `#d4564f / #fff1ef` | SELL direction badge |
| `--surface-panel` → `--navy-700` | `#122a4c` | Card / section background |
| `--surface-raised` → `--navy-750` | `#102544` | Slightly elevated panels |
| `--surface-input` → `--navy-600` | `#17345c` | Input / select fill |
| `--border-default` | `#1e3a5f` | Panel borders |
| `--border-strong` | `#2a517f` | Input borders, dividers |
| `--panel-pad` | `22px` | Panel internal padding |
| `--app-pad-x` | `28px` | Page horizontal gutter |
| `--radius-md` | `8px` | Panel border-radius |
| `--radius-xs` | `3px` | Cell / input / badge border-radius |
| `--font-mono` | IBM Plex Mono | All numbers, tickers, KPIs, badges, buttons |
| `--font-sans` | IBM Plex Sans | Labels, headings, body, nav |
