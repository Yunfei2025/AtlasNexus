# AtlasNexus Design System — Improvement Plan

**Date:** 2026-06-19  
**Scope:** Full app (`atlasnexus_daily.py`) — layout, typography, spacing, colors,
per-book accents, navy ramp, signal/trade colors, Z-score bar chart, component tokens.

---

## Why Nothing Is Changing — Root Causes

This is the most important section. There are four structural reasons why CSS edits
have no visible effect. Fix these first, or any styling change will continue to fail.

---

### Root Cause 1 — CSS file missing its `z_` prefix (CRITICAL) — STATUS: UNFIXED

**File:** `web/assets/atlasnexus-design.css`

Dash serves all files in `web/assets/` in **lexicographic (alphabetical) order**.
The file's own header comment explicitly states:

> *"DROP THIS FILE … as: `z_atlasnexus-design.css` — The `z_` prefix ensures this
> loads LAST, winning all conflicts."*

The file was renamed back to `atlasnexus-design.css` (without the `z_` prefix),
so it loads **before** `style.css` alphabetically. Current load order is:

| Load order | File | Problem |
|---|---|---|
| 1 | `app.css` | Sets `html { font-size: 62.5% }`, `body { font-family: Open Sans }` |
| 2 | `atlasnexus-design.css` | ← **Design system overrides** |
| 3 | `atlasnexus_tabs.css` | Partially overrides #2 |
| 4 | `style.css` | **Loads last** — re-applies `.app__container { margin: 3% 5% }`, `.app__content { display:flex; margin-top:20px }`, `button { color:#fff }`, `.futures__price__container { background:#082255 }`, and more. Undoes design-system work. |

**Fix:**
```bash
# In the project root (or your GitHub repo):
git mv web/assets/atlasnexus-design.css web/assets/z_atlasnexus-design.css
git add web/assets/z_atlasnexus-design.css
git commit -m "fix: rename atlasnexus-design.css → z_atlasnexus-design.css to ensure CSS load order"
```

After the rename the load order becomes:
`app.css` → `atlasnexus_tabs.css` → `style.css` → **`z_atlasnexus-design.css`** (wins all conflicts).

---

### Root Cause 2 — Python inline `style={}` dicts override CSS classes

**Files:** `atlasnexus_daily.py`, all `atlas_*_tabs.py` files

Dash renders Python style dicts as HTML `style=""` attributes. These have
**higher specificity than any CSS class rule**, regardless of how specific the
selector is. The design CSS's `!important` declarations cover some elements
(buttons, inputs, dropdowns) but **not** the main layout primitives:

| Python dict | Where set | What it controls | CSS coverage? |
|---|---|---|---|
| `_card_style` | `atlasnexus_daily.py` L191 | Card background `#0c2b64`, padding `14px 15px`, margin `10px 12px`, radius `6px` | ❌ No `!important` rule |
| `_card_hdr` | `atlasnexus_daily.py` L195 | Header font-size, weight, letter-spacing, color `#aab0c0` | ❌ No rule targets this |
| `alpha_content` / `beta_content` / `market_content` style | `atlasnexus_daily.py` L300–L390 | `padding: '20px'`, `margin: '10px'` on each tab pane | ❌ No override |
| `summary_subtab_style` | `atlas_styles.py` L35 | Sub-tab background, color, font-size, padding | ❌ Applied as `style=` on `dcc.Tab` |
| `summary_subtab_selected_style()` | `atlas_styles.py` L42 | Selected sub-tab border, color | ❌ Applied as `style=` on `dcc.Tab` |
| `tab_style` / `tab_selected_style` | `styles.py` L51–67 | Used in legacy layouts still imported by some tabs | ❌ Hard-coded inline |

**Fix (two options — choose one):**

**Option A — CSS `!important` additions** (lower refactor risk):
Add `!important` rules in `z_atlasnexus-design.css` that target the same
selectors the Python dicts apply to, so CSS wins even against inline styles.
This is only possible for structural layout (padding/margin/radius) — not
for per-instance color variations.

**Option B — Replace Python dicts with CSS class names** (recommended):
Define `.an-card`, `.an-card-hdr`, `.an-tab-pane`, `.an-subtab`,
`.an-subtab--selected` in CSS. Replace every `style=_card_style` with
`className="an-card"`. Remove the Python dicts. This makes the design
system the single source of truth.

The `an-card` class already exists in `atlasnexus_tabs.css` — it just isn't
being used in `atlasnexus_daily.py`.

---

### Root Cause 3 — Sub-tab components use Python dicts, not CSS classNames

**File:** `atlasnexus_daily.py` + `atlas_styles.py`

Top-level tabs correctly use `className="an-tab"` / `selected_className="an-tab--selected"`.
Sub-tabs do not — they use `style=summary_subtab_style` / `selected_style=summary_subtab_selected_style(color)`.

```python
# CURRENT — Python dict → inline style → CSS cannot override
dcc.Tab(label="Candidates", style=summary_subtab_style,
        selected_style=summary_subtab_selected_style("#3498db"))

# TARGET — className approach — CSS owns the look
dcc.Tab(label="Candidates", className="an-subtab",
        selected_className="an-subtab--selected an-subtab--blue")
```

Add to `z_atlasnexus-design.css`:
```css
.an-subtab {
  background: #112e66 !important;
  color: #aab0c0 !important;
  font-size: 12px !important;
  padding: 6px 20px !important;
  border: none !important;
}
.an-subtab--selected {
  background: #0c2b64 !important;
  border-top: 2px solid var(--book-accent, #3498db) !important;
  color: var(--book-accent, #3498db) !important;
  border-bottom: none !important;
}
```

---

### Root Cause 4 — Font family is never overridden for the app

**File:** `style.css` (loads last, currently)

`style.css` sets:
```css
body { font-family: "Open Sans", sans-serif; }
```

Neither `atlasnexus-design.css` nor `atlasnexus_tabs.css` define a
`font-family` override. The `PLOTLY_LAYOUT_DEFAULTS` sets `"Open Sans"`
too. The app will continue using Open Sans (which is fine) but if
you want to change font, **both** `body` in CSS **and** `font.family`
in `PLOTLY_LAYOUT_DEFAULTS` must be updated together.

**Fix:** If keeping Open Sans, this is fine but document it.
If changing (e.g. to "IBM Plex Sans" — a strong financial-dashboard choice):

1. Add Google Fonts import to `cover.html` and the Dash `meta_tags`:
   ```python
   html.Link(rel="stylesheet", href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&display=swap")
   ```
2. In `z_atlasnexus-design.css`:
   ```css
   body, .app__container { font-family: "IBM Plex Sans", sans-serif !important; }
   ```
3. In `atlas_styles.py` `PLOTLY_LAYOUT_DEFAULTS`:
   ```python
   "font": {"family": "IBM Plex Sans, sans-serif", "size": 12, "color": "#ffffff"},
   ```

---

## Per-Book Accent Colors

### Issue — Accent color only reaches the tab border, not charts or KPIs

**File:** `atlasnexus_daily.py` + `atlas_styles.py`

`summary_subtab_selected_style(color)` passes accent color (e.g. `"#f39c12"` for
Alpha) only to the selected tab's `borderTop`. It does **not**:
- Set a CSS variable scoped to the active book's content area
- Change the Plotly `colorway[0]` for charts inside that tab
- Color KPI numbers, card highlights, or button outlines with the book color

**Fix:** Use a CSS custom property on the active content div:

```python
# In _make_tab_switcher or a dedicated callback:
@app.callback(Output("an-main-content", "style"), Input("an-tabs", "value"))
def _set_book_accent(tab):
    accent = {
        "market": "#2e86c1",
        "beta":   "#3498db",
        "alpha":  "#f39c12",
        "risk":   "#27ae60",
        "run-center": "#8e44ad",
    }.get(tab, "#2e86c1")
    return {"--book-accent": accent}
```

Then in CSS, KPI values and card borders reference `var(--book-accent)`:
```css
.an-kpi-value    { color: var(--book-accent, #2e86c1); }
.an-card         { border-left: 3px solid var(--book-accent, #2e86c1); }
.an-subtab--selected { border-top-color: var(--book-accent, #2e86c1) !important; }
```

For **Plotly charts**, inject the accent into the figure layout inside each
tab's graph-building callback:
```python
fig.update_layout(colorway=[book_accent, ...rest_of_colorway])
```

---

## Navy Base Ramp — Tokens Defined But Not Consumed

### Issue — Two parallel `:root` blocks, hardcoded hex everywhere

Both `atlasnexus-design.css` and `atlasnexus_tabs.css` define separate
`:root` token blocks with different variable names for the same concepts:

| Concept | `atlasnexus-design.css` | `atlasnexus_tabs.css` |
|---|---|---|
| Page background | `--an-navy-900: #040f30` | `--bg-page: #061e44` |
| Card background | `--an-navy-700: #0c2b64` | `--bg-card: #0c2b64` |
| Input background | `--an-navy-600: #112e66` | `--bg-input: #112e66` |
| Muted text | `--an-muted: #aab0c0` | `--txt-sub: #aab0c0` |

Rules in each file reference their own variable set; neither references the other.
Python dicts use hardcoded hex that maps to neither.

**Fix:** Merge into a single authoritative `:root` in `z_atlasnexus-design.css`.
Use the `--an-*` naming (already more complete). Delete the duplicate block
from `atlasnexus_tabs.css`. Replace all hardcoded hex in CSS rules with tokens:

```css
/* BEFORE (scattered in both files) */
.an-card { background: #0c2b64; }

/* AFTER (single token reference) */
.an-card { background: var(--an-navy-700) !important; }
```

For Python dicts (until they're replaced with classNames per Root Cause 2):
```python
# Create a TOKENS dict in atlas_styles.py — single source of truth
TOKENS = {
    "navy_900": "#040f30", "navy_800": "#082255", "navy_700": "#0c2b64",
    "navy_600": "#112e66", "navy_500": "#1a3a6e", "navy_400": "#2a5298",
    "blue":     "#2e86c1", "cyan":     "#45b6e6",
    "green":    "#27ae60", "amber":    "#f39c12",
    "red":      "#c0392b", "muted":    "#aab0c0",
}
# Then everywhere:
_card_style = {"background": TOKENS["navy_700"], ...}
```

---

## Signal & Trade Colors

### Issue — `color_mode` is a standalone dict, not aligned with design tokens

**File:** `web/core/styles.py` L22

```python
color_mode = {1: "#F93822", 0: "#007ACE", -1: "#00B612"}
```

These are used in legacy FI tab callbacks for directional coloring.
They don't match `--an-red` / `--an-blue` / `--an-green` in the design system,
and are not documented anywhere.

**Fix:** Align with design tokens and document the convention:
```python
# web/core/styles.py
# Signal color convention: 1=SELL/short, 0=NEUTRAL, -1=BUY/long
color_mode = {
    1:  "#c0392b",  # SELL   — matches --an-red
    0:  "#2e86c1",  # NEUTRAL — matches --an-blue
   -1:  "#27ae60",  # BUY    — matches --an-green
}
```

Also align `SHAPE_COLOR` (currently `"#BD9391"` — a muted mauve) with
`--an-muted` (`#aab0c0`) for visual consistency on stat-line overlays.

---

## Z-Score Bar Chart Colors

### Issue — Named CSS colors are low-contrast on navy; blue feels "cool"

**File:** `web/core/graphs.py` L302–L308

**Current code:**
```python
spread['color'] = 'grey'          # CSS named color #808080 — grey-blue, blends into navy
spread.loc[buy,  'color'] = 'green'  # CSS named color #008000 — dark, barely visible
spread.loc[sell, 'color'] = 'red'    # CSS named color #ff0000 — saturated but inconsistent
```

The `'grey'` neutral bars render blue-grey against the navy background (the "cool" appearance),
creating poor contrast. `'green'` (#008000) and `'red'` (#ff0000) are not aligned with
the design system's `--an-green` (#27ae60) and `--an-red` (#c0392b).

**Recommended Fix — Option A: Three-bucket with proper hex (minimal, copy-paste ready):**

In `web/core/graphs.py`, find the `statistics` callback (around L302). Replace:
```python
# OLD:
spread['color'] = 'grey'
buy = spread[spread["Zscore"] >= thd].index
sell = spread[spread["Zscore"] <= -thd].index
spread.loc[buy, 'color'] = 'green'
spread.loc[sell, 'color'] = 'red'

# NEW:
spread['color'] = '#4a5568'  # neutral — visible slate gray
buy = spread[spread["Zscore"] >= thd].index
sell = spread[spread["Zscore"] <= -thd].index
spread.loc[buy,  'color'] = '#27ae60'  # buy   — matches --an-green
spread.loc[sell, 'color'] = '#c0392b'  # sell  — matches --an-red
```

**Advanced Fix — Option B: Five-bucket diverging red→green (better UX):**

Add this function to `web/core/graphs.py` at module level:
```python
def _zscore_color(z: float) -> str:
    """Map z-score to a 5-step red→neutral→green scale for better signaling."""
    if   z >=  2.0: return '#27ae60'   # strong buy   — emerald
    elif z >=  1.0: return '#82e0aa'   # mild buy     — light green
    elif z <= -2.0: return '#c0392b'   # strong sell  — crimson
    elif z <= -1.0: return '#f1948a'   # mild sell    — light red
    else:           return '#4a5568'   # neutral      — slate gray
```

Then in the `statistics` callback, replace the color assignment with:
```python
# OLD (three-bucket approach):
spread['color'] = 'grey'
spread.loc[buy,  'color'] = 'green'
spread.loc[sell, 'color'] = 'red'

# NEW (five-bucket approach):
spread['color'] = spread['Zscore'].apply(_zscore_color)
```

This gives traders an immediate directional read at five intensity levels.
The thresholds `±1σ` and `±2σ` already match `ZSCORE_ALERT_THRESHOLD = 2.0` in the code.

**Bonus — Clean up bar outlines in `getTraceStat`:**

Find the `getTraceStat` function (around L139) and update the `go.Bar` call:
```python
# OLD:
trace = go.Bar(
    x=df.index, y=df['Zscore'],
    marker=dict(color=df['color']),
    hovertext=hovertext, name='Zscore',
)

# NEW (removes visual noise from outlines):
trace = go.Bar(
    x=df.index, y=df['Zscore'],
    marker=dict(color=df['color'], line=dict(width=0)),
    hovertext=hovertext, name='Zscore',
)
```

---

## DataTable / KPI / Signals Styling

### Issue — DataTable uses Python props that CSS cannot override

**Files:** Multiple `atlas_*_tabs.py` files

`dash_table.DataTable` components set `style_header`, `style_data`,
`style_cell`, and `style_data_conditional` as Python props. These are rendered
as inline Dash-internal styles. CSS rules in `z_atlasnexus-design.css` for
`.dash-header` and `.dash-cell` apply correctly **only when** the DataTable
doesn't override them with Python props.

Current pattern (blocks CSS):
```python
dash_table.DataTable(
    style_header={"backgroundColor": "#0c2b64", "color": "#aab0c0", ...},
    style_data={"backgroundColor": "#082255", "color": "#fff", ...},
)
```

**Fix:** Remove `style_header` and `style_data` from DataTable props and let
`z_atlasnexus-design.css` handle them via `.dash-header` / `.dash-cell` rules.
Keep **only** `style_data_conditional` in Python (CSS cannot do conditional logic):

```python
dash_table.DataTable(
    # Remove style_header and style_data — CSS handles these
    style_data_conditional=[
        {"if": {"filter_query": "{signal} = 'BUY'"},  "backgroundColor": "rgba(39,174,96,0.15)"},
        {"if": {"filter_query": "{signal} = 'SELL'"}, "backgroundColor": "rgba(192,57,43,0.15)"},
    ],
    # Keep style_cell only for column widths / text alignment
    style_cell={"textAlign": "left", "minWidth": "80px"},
)
```

The existing rule in `atlasnexus-design.css`:
```css
/* Data cells — no !important on background to allow style_data_conditional */
.dash-table-container .dash-cell { color: var(--an-text) !important; ... }
```
is correctly designed for this — it just needs the Python `style_data` prop removed.

---

## CSS File Consolidation

### Issue — Four overlapping files create specificity wars

| File | Keep? | Action |
|---|---|---|
| `app.css` | Yes (partial) | Remove `html`, `body`, `h1–h6`, `button`, form, table rules — keep only the Skeleton 12-column grid and `.u-*` utilities. Add comment explaining what was removed and why. |
| `atlasnexus-design.css` | Yes → rename | Rename to `z_atlasnexus-design.css`. Merge the `atlasnexus_tabs.css` `:root` variables in. Add font-family override. Add `.an-subtab` / `.an-subtab--selected` classes. |
| `atlasnexus_tabs.css` | Merge then empty | Move unique rules (DatePicker dark theme, Dash4 dcc.Dropdown, `.dash-input-element`) into `z_atlasnexus-design.css`. Leave the file empty or with a redirect comment so existing references don't 404. |
| `style.css` | Partial keep | Keep only: `.futures__price__container`, `.graph__container`, `.graph__title`, responsive `@media` rules, `#spread-type` flex rules, `.custom-dropdown`. Remove `body`, `button`, `.app__container`, `.app__content`, `.app__header`, `.Select-*` rules — all now owned by `z_atlasnexus-design.css`. |

**Target state (4 files → 2 files doing distinct jobs):**
- `app.css` — Skeleton grid only (layout primitives)
- `z_atlasnexus-design.css` — complete AtlasNexus design system

---

## Recommended Implementation Order

Work in this sequence to see visible progress after each step:

| Step | Change | Files touched | Visible impact |
|---|---|---|---|
| **1** | Rename `atlasnexus-design.css` → `z_atlasnexus-design.css` | 1 file rename | Immediately: CSS rules start winning over `style.css` |
| **2** | Z-score bar colors → hex `#27ae60` / `#c0392b` / `#4a5568` | `graphs.py` (5 lines) | Immediately: bar chart contrast on navy |
| **3** | Align `color_mode` with design tokens | `styles.py` (3 lines) | Immediately: signal overlay colors consistent |
| **4** | Add `font-family` and `.an-subtab` CSS classes | `z_atlasnexus-design.css` | After step 1: font and sub-tab styling takes effect |
| **5** | Add TOKENS dict to `atlas_styles.py`; update Python dicts | `atlas_styles.py`, `atlasnexus_daily.py` | Consistent navy ramp across all cards |
| **6** | Remove `style_header`/`style_data` from DataTables | All `atlas_*_tabs.py` | Tables adopt CSS-driven styling |
| **7** | Replace sub-tab `style=` with `className=` | `atlasnexus_daily.py`, `atlas_styles.py` | Sub-tab typography/density from CSS |
| **8** | Add `--book-accent` CSS variable injection callback | `atlasnexus_daily.py` | Per-book accent propagates to cards, KPIs |
| **9** | Merge `atlasnexus_tabs.css` into `z_atlasnexus-design.css` | Both CSS files | Single source of truth, no conflicts |
| **10** | Clean `style.css` and `app.css` of redundant rules | Both CSS files | No more regression overrides |

Steps 1–3 are trivial (rename + ~10 lines of Python) and will produce the most
immediately visible result. Steps 4–7 are the main structural refactor.
Steps 8–10 are polish.

---

## Quick-Reference: Color Token Alignment

Single table mapping the design system color intent to the canonical values
that should be used everywhere (CSS variables, Python `TOKENS` dict, Plotly
`colorway`):

| Role | Token name | Hex | Use |
|---|---|---|---|
| Page background | `--an-navy-900` | `#040f30` | `body`, `app__container` bg |
| App shell | `--an-navy-800` | `#082255` | Header, tab bar, chart bg |
| Card | `--an-navy-700` | `#0c2b64` | Cards, dropdown menus |
| Input | `--an-navy-600` | `#112e66` | Inputs, sub-tab bar bg |
| Raised | `--an-navy-500` | `#1a3a6e` | Primary buttons, hovered rows |
| Border | `--an-navy-400` | `#2a5298` | All borders |
| Blue (accent 1) | `--an-blue` | `#2e86c1` | Market tab, links, chart line |
| Cyan (focus) | `--an-cyan` | `#45b6e6` | Focus rings, active states |
| Green (buy/ok) | `--an-green` | `#27ae60` | Buy signals, ok pills, Z-score +2 |
| Amber (warn) | `--an-amber` | `#f39c12` | Alpha tab, warn pills |
| Red (sell/error) | `--an-red` | `#c0392b` | Sell signals, error pills, Z-score -2 |
| Purple | `--an-purple` | `#8e44ad` | Run Center tab |
| Text primary | `--an-text` | `#ffffff` | Body text |
| Text muted | `--an-muted` | `#aab0c0` | Labels, captions, secondary text |
| Text faint | `--an-faint` | `#5a6478` | Disabled, placeholder, Z-score neutral |
