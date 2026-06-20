# AtlasNexus Daily — Dash Implementation Improvement Plan

> **Goal:** Close the visual and structural gap between the current `web/` Dash app
> (screenshot, June 19 2026) and the reference design in `ui_kits/atlasnexus-daily/`.  
> All changes are in `web/assets/z_atlasnexus-design.css` (CSS-only where possible)
> and targeted edits to `web/apps/atlasnexus_daily.py` and the relevant
> `web/tabs/atlas_*_tab.py` files.

---

## Diagnostic Summary

| # | Area | Current state | Design target | Root cause |
|---|------|--------------|---------------|------------|
| 1 | Color tokens | `#040f30` navy base, `#0c2b64` panels | `#0a1428` / `#122a4c` — bluer, more refined | `--an-*` variables don't match `tokens/colors.css` |
| 2 | Page background | Flat `#040f30` solid | Fixed vertical gradient navy-950 → navy-850 | Missing `background: linear-gradient(…)` on `body` |
| 3 | App header | Fixed top bar, H4 title, tight padding | Inline in scroll flow, display-weight title, 26px top pad | Structural: Dash `app__header` div is a layout bar, not a content heading |
| 4 | Main tabs | Heavy slate fill inactive, left-border selected accent | Low-contrast inactive fill, **bottom**-border selected accent | `.an-tab` background + `.an-tab--selected border-left` → should be `border-bottom` |
| 5 | Sub-tabs | Filled blocks (`navy-600` bg), border-top on selected | Underline style — transparent bg, border-bottom on selected | `.an-subtab` background should be `transparent`, `border-top` → `border-bottom` |
| 6 | Panel/card | Left accent bar (`border-left: 3px`), no top border | All-side `1px` border, **eyebrow** label inside card | `.an-card` pattern vs. design's `Panel eyebrow` pattern |
| 7 | Section titles | Float outside the card as standalone divs | Part of panel interior (eyebrow) | Python layout: title div + table div are siblings, not nested |
| 8 | DataTable bar cells | Full-cell background fill (whole cell coloured) | Narrow inline data bar behind the number, value text on top | `style_data_conditional` can only fill background; needs `style_cell_conditional` + absolute bar trick |
| 9 | IRS Forward Rates | Shift inputs sit above/outside the table | Shift inputs inline with the panel header (`actions` pattern) | Layout: inputs are in a separate row above the Dash DataTable |
| 10 | Typography | H4 / explicit px sizes, no scale | `var(--type-display)`, `var(--type-h1)`, `var(--type-meta)` tokens | Missing token bridging from design system to Dash CSS |
| 11 | Accent colors | `--an-blue: #2e86c1` | `--accent-blue: #3d8bd4` (design token) | Token name and value mismatch |
| 12 | Status pill | Plain text span "• Wind —" | Proper pill border + dot (`an-status-pill.idle`) | Already implemented in CSS; the HTML span needs the class applied |

---

## Phase 1 — Token Alignment (CSS-only, `z_atlasnexus-design.css`)

**Effort:** ~30 min · **Risk:** Low · **Impact:** High (everything downstream benefits)

The design system (`tokens/colors.css`) and the Dash stylesheet use two parallel but
divergent token sets. Bridge them by adding aliases in `:root` so both names work.

### 1.1 Update `:root` navy ramp

Replace the current `--an-navy-*` block with values that match `tokens/colors.css`,
and add semantic aliases matching the design kit's names:

```css
:root {
  /* — Ramp (match tokens/colors.css exactly) — */
  --an-navy-950: #060d1c;   /* was #020d22 */
  --an-navy-900: #0a1428;   /* was #040f30 — page bg */
  --an-navy-850: #0c1830;   /* NEW gradient stop */
  --an-navy-800: #0e1d3a;   /* was #082255 — working bg */
  --an-navy-750: #102544;   /* NEW raised panel */
  --an-navy-700: #122a4c;   /* was #0c2b64 — card surface */
  --an-navy-600: #17345c;   /* was #112e66 — inputs */
  --an-navy-500: #21426e;   /* was #1a3a6e — buttons */
  --an-navy-400: #2e547f;   /* was #2a5298 — border */
  --an-navy-300: #3a4d6e;   /* was #425476 — inactive tab */

  /* — Accents (match tokens/colors.css) — */
  --an-blue:   #3d8bd4;   /* was #2e86c1 */
  --an-cyan:   #45b6e6;   /* unchanged */
  --an-green:  #2f9d6b;   /* was #27ae60 */
  --an-amber:  #e0a23c;   /* was #f39c12 */
  --an-red:    #d56b6b;   /* was #c0392b */
  --an-purple: #7c70d6;   /* was #8e44ad */
  --an-teal:   #36a6b8;   /* NEW — Run Center */

  /* — Text ramp (match tokens/colors.css) — */
  --an-text:   #e9eef8;   /* was #ffffff */
  --an-muted:  #a4b6d2;   /* was #aab0c0 */
  --an-faint:  #4a5d7c;   /* was #5a6478 */

  /* — Borders (match tokens/colors.css) — */
  --an-border:  #2a517f;   /* was #2a5298 */
  --an-border2: #1e3a5f;   /* was #061E44 */

  /* — Semantic aliases (so design-kit token names work in Python inline styles too) — */
  --surface-panel:  var(--an-navy-700);
  --surface-raised: var(--an-navy-750);
  --surface-input:  var(--an-navy-600);
  --text-primary:   var(--an-text);
  --text-secondary: var(--an-muted);
  --text-muted:     #6f83a3;
  --text-faint:     var(--an-faint);
  --border-default: var(--an-border2);
  --border-strong:  var(--an-border);

  /* — Signal (for bar cells) — */
  --positive-bar:  #2c6e4d;
  --negative-bar:  #8a3a3a;
  --neutral-bar:   #1f3a5e;
}
```

### 1.2 Update `TOKENS` dict in `atlas_styles.py`

Mirror the same value changes in the Python dict so any code that reads
`TOKENS["navy_900"]` etc. stays in sync with the CSS:

```python
TOKENS: Dict[str, str] = {
    "navy_950": "#060d1c", "navy_900": "#0a1428", "navy_850": "#0c1830",
    "navy_800": "#0e1d3a", "navy_750": "#102544", "navy_700": "#122a4c",
    "navy_600": "#17345c", "navy_500": "#21426e", "navy_400": "#2e547f",
    "navy_300": "#3a4d6e",
    "blue":   "#3d8bd4", "cyan":   "#45b6e6",
    "green":  "#2f9d6b", "amber":  "#e0a23c",
    "red":    "#d56b6b", "purple": "#7c70d6", "teal": "#36a6b8",
    "text":   "#e9eef8", "muted":  "#a4b6d2", "faint": "#4a5d7c",
}
```

---

## Phase 2 — Background & Body Gradient

**Effort:** 5 min · **Risk:** Low · **Impact:** Medium

The design uses a fixed vertical gradient (`navy-950 → navy-900 → navy-850`) giving
depth. The current flat fill makes the UI feel flatter than the design.

In `z_atlasnexus-design.css`, update:

```css
body, .app__container {
  background: linear-gradient(
    180deg,
    var(--an-navy-950) 0%,
    var(--an-navy-900) 18%,
    var(--an-navy-850) 100%
  ) !important;
  background-attachment: fixed !important;
  min-height: 100vh !important;
}
```

---

## Phase 3 — App Header

**Effort:** 45 min · **Risk:** Medium · **Impact:** High

The design's header is part of the scroll flow (not a fixed top bar) and uses
display-weight typography. The current Dash `app__header` is structurally a fixed bar.
Two approaches — choose one:

### Option A (CSS-only, lower risk): Restyle the existing bar

Keep the Dash `app__header` div but make it look like the design:

```css
.app__header {
  background: transparent !important;      /* no bar fill */
  border-bottom: none !important;
  padding: 26px 24px 0 24px !important;
  align-items: flex-start !important;
}

/* Display-weight app title */
.app__header__title {
  font-size: 26px !important;
  font-weight: 300 !important;
  letter-spacing: 0.04em !important;
  color: var(--an-text) !important;
  line-height: 1.2 !important;
}

/* Separator dot between "AtlasNexus" and "Daily" */
.app__header__title .sep {
  color: var(--an-faint) !important;
  margin: 0 6px !important;
}

/* Timestamp / metadata lines */
.app__header__title--grey {
  font-size: 11px !important;
  color: var(--an-muted) !important;
  margin-top: 8px !important;
  letter-spacing: 0 !important;
}
```

Also update `build_header()` in `atlasnexus_daily.py` to wrap "AtlasNexus" and
"Daily" in the title so the separator dot can be styled separately:

```python
html.H4([
    "AtlasNexus ",
    html.Span("·", className="sep"),
    " Daily"
], className="app__header__title"),
```

### Option B (structural, higher fidelity): Inline header

Move the header HTML inside the scrolling content area so it has the same left
padding as the tab panels. Remove the `.app__header` wrapper, add the title block
as the first child of `build_tabs_panel()`. This matches the design exactly but
requires touching more Python code.

---

## Phase 4 — Main Tab Bar

**Effort:** 15 min · **Risk:** Low · **Impact:** High

**Current:** Selected tab has `border-left: 3px solid` (left accent bar).  
**Design:** Selected tab has **bottom** border underline accent.

Also: inactive tabs use a heavy slate background; design uses a much lighter fill.

```css
/* Inactive tab — lighter fill, no heavy block */
.an-tab {
  background: linear-gradient(
    180deg,
    var(--an-navy-300) 0%,   /* slate-tab */
    #2b3b58 100%              /* slate-tab-dim */
  ) !important;
  color: var(--an-muted) !important;
  border: 1px solid var(--an-border2) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  padding: 8px 18px !important;
  border-radius: 4px 4px 0 0 !important;
  border-bottom: none !important;
  transition: background 0.15s, color 0.15s !important;
}
.an-tab:hover {
  background: var(--an-navy-500) !important;
  color: var(--an-text) !important;
}

/* Selected tab — bottom accent line, not left */
.an-tab--selected {
  background: var(--an-navy-800) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  border-bottom: 2px solid var(--book-accent, var(--an-blue)) !important;
  border-left: none !important;           /* remove the current left accent */
  border-radius: 4px 4px 0 0 !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  padding: 8px 18px !important;
}
```

---

## Phase 5 — Sub-tabs

**Effort:** 15 min · **Risk:** Low · **Impact:** High

**Current:** Filled blocks with `background: navy-600`.  
**Design:** Underline style — transparent background, `border-bottom` on selected.

```css
/* Inactive sub-tab — transparent, muted text */
.an-subtab {
  background: transparent !important;
  color: var(--an-muted) !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  padding: 8px 20px !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  letter-spacing: 0.03em !important;
  transition: color 0.15s, border-color 0.15s !important;
}
.an-subtab:hover {
  color: var(--an-text) !important;
}

/* Selected sub-tab — accent bottom border, accent text */
.an-subtab--selected {
  background: transparent !important;
  border-bottom: 2px solid var(--book-accent, var(--an-blue)) !important;
  border-top: none !important;            /* remove current border-top */
  color: var(--book-accent, var(--an-blue)) !important;
  font-weight: 600 !important;
}

/* Book-specific overrides (keep these) */
.an-subtab--blue   { border-bottom-color: var(--an-blue)   !important; color: var(--an-blue)   !important; }
.an-subtab--amber  { border-bottom-color: var(--an-amber)  !important; color: var(--an-amber)  !important; }
.an-subtab--green  { border-bottom-color: var(--an-green)  !important; color: var(--an-green)  !important; }
.an-subtab--purple { border-bottom-color: var(--an-purple) !important; color: var(--an-purple) !important; }
```

The `dcc.Tabs` container holding sub-tabs should also have a bottom border to
ground the underlines:

```css
/* Sub-tab row underline track */
.an-tab-pane > .dash-tabs {
  border-bottom: 1px solid var(--an-border2) !important;
  margin-bottom: 20px !important;
}
```

---

## Phase 6 — Panel / Card System

**Effort:** 60 min · **Risk:** Medium · **Impact:** Very High

This is the largest visual gap. The design uses a **Panel with eyebrow** pattern;
the current code uses free-floating section titles above plain DataTables.

### 6.1 CSS: Replace left-bar card with full-border card + eyebrow

```css
.an-card {
  background: var(--surface-panel) !important;   /* navy-700 */
  border: 1px solid var(--an-border2) !important; /* all sides */
  border-left: none !important;                   /* remove accent left bar */
  border-top: 2px solid var(--book-accent, var(--an-blue)) !important; /* top accent */
  border-radius: 0 0 6px 6px !important;
  padding: 0 !important;                          /* tables sit flush */
  margin: 0 0 20px 0 !important;                  /* use gap instead of margin */
  overflow: hidden !important;
}

/* Eyebrow header inside the card */
.an-card-hdr {
  padding: 12px 14px 10px !important;
  color: var(--an-muted) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  border-bottom: 1px solid var(--an-border2) !important;
  margin-bottom: 0 !important;
}

/* Card actions row (for IRS shift inputs, refresh buttons, etc.) */
.an-card-actions {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  padding: 10px 14px !important;
  border-bottom: 1px solid var(--an-border2) !important;
  gap: 16px !important;
}
```

### 6.2 Python: Move section titles inside the card

In every tab builder that currently renders a pattern like:

```python
# CURRENT (title floating outside):
html.Div("MONEY MARKET RATES", className="an-section-title"),
html.Div([dash_table.DataTable(...)], className="an-card"),
```

Change to the eyebrow-inside pattern:

```python
# TARGET (title as card eyebrow):
html.Div([
    html.Div("MONEY MARKET RATES", className="an-card-hdr"),
    dash_table.DataTable(...),
], className="an-card"),
```

Files to update:
- `web/tabs/atlas_market_data_tab.py` — Money Market Rates, Reference Bonds, On-the-run Bonds, IRS Forward Rates
- `web/tabs/atlas_fi_tabs.py` — all section panels
- `web/tabs/atlas_alpha_tabs.py`
- `web/tabs/atlas_multiasset_tabs.py`

### 6.3 Two-column grid layout for Market Data

The 2-column panel layout currently uses Skeleton's `six columns` divs.
Replace with a CSS grid to match the design:

```python
# In atlas_market_data_tab.py, wrap the 4 panels in:
html.Div([
    # Left column
    html.Div([money_market_card, reference_bonds_card], style={
        "display": "flex", "flexDirection": "column", "gap": "20px"
    }),
    # Right column
    html.Div([on_the_run_card, irs_fwd_card], style={
        "display": "flex", "flexDirection": "column", "gap": "20px"
    }),
], style={
    "display": "grid",
    "gridTemplateColumns": "1fr 1fr",
    "gap": "20px",
    "alignItems": "start",
})
```

---

## Phase 7 — DataTable Bar Cells

**Effort:** 45 min · **Risk:** Medium · **Impact:** High

**Current:** `style_data_conditional` paints the entire cell background green/red.  
**Design:** A narrow bar sits *behind* the number, proportional to the value magnitude.

Dash's DataTable cannot render arbitrary HTML in cells, so the closest approximation
is to combine `style_data_conditional` with carefully sized widths and a text overlay:

### 7.1 Inline data-bar via `style_data_conditional`

The trick: set `background-image: linear-gradient(…)` instead of `background-color`,
which lets you control the bar width as a percentage:

```python
def make_bar_conditional(col: str, max_val: float, pos_color: str, neg_color: str):
    """Generate style_data_conditional entries for an inline data bar."""
    rules = []
    steps = 20
    for i in range(1, steps + 1):
        pct = (i / steps) * 100
        threshold = (i / steps) * max_val
        # Positive bar
        rules.append({
            "if": {"filter_query": f"{{{col}}} >= {threshold - max_val/steps} && {{{col}}} < {threshold}",
                   "column_id": col},
            "background": (
                f"linear-gradient(to right, {pos_color} {pct:.0f}%, "
                f"transparent {pct:.0f}%)"
            ),
            "color": "#e9eef8",
        })
        # Negative bar (right-aligned, reversed)
        rules.append({
            "if": {"filter_query": f"{{{col}}} > {-threshold} && {{{col}}} <= {-(threshold - max_val/steps)}",
                   "column_id": col},
            "background": (
                f"linear-gradient(to left, {neg_color} {pct:.0f}%, "
                f"transparent {pct:.0f}%)"
            ),
            "color": "#e9eef8",
        })
    return rules
```

Use `pos_color="#2c6e4d"` (design's `--positive-bar`) and `neg_color="#8a3a3a"`
(`--negative-bar`) instead of the current bright green/red.

### 7.2 Text alignment in bar columns

Bar columns should right-align text so the bar grows from the left (positive)
or right (negative):

```python
style_cell_conditional=[
    {"if": {"column_id": bar_cols}, "textAlign": "right"},
]
```

### 7.3 IRS Forward Rates — neutral blue bars

The FWD columns use `--neutral-bar: #1f3a5e`. Apply a simpler gradient:

```python
# One rule per value range, using the neutral bar color
{"background": "linear-gradient(to right, #1f3a5e {pct}%, transparent {pct}%)"}
```

---

## Phase 8 — IRS Forward Rates Panel: Actions Row

**Effort:** 30 min · **Risk:** Low · **Impact:** Medium

The R7D / S3M shift inputs should be inside the panel header alongside the panel
title, not in a separate row above the table.

In `atlas_market_data_tab.py`, restructure the IRS panel:

```python
html.Div([
    # Card header row with eyebrow + inline shift inputs
    html.Div([
        html.Div("IRS FORWARD RATES", className="an-card-hdr",
                 style={"border": "none", "padding": "0", "flex": "1"}),
        html.Div([
            html.Label("R7D shift (bp)", style=_LBL_STYLE),
            dcc.Input(id="irs-r7d-shift", type="number", value=0,
                      style={**_INPUT_STYLE, "width": "60px"}),
        ], style={"display": "flex", "flexDirection": "column"}),
        html.Div([
            html.Label("S3M shift (bp)", style=_LBL_STYLE),
            dcc.Input(id="irs-s3m-shift", type="number", value=0,
                      style={**_INPUT_STYLE, "width": "60px"}),
        ], style={"display": "flex", "flexDirection": "column"}),
    ], className="an-card-actions"),
    # Table
    dash_table.DataTable(...),
], className="an-card"),
```

---

## Phase 9 — Typography Bridge

**Effort:** 20 min · **Risk:** Low · **Impact:** Medium

Add design token typography variables to `z_atlasnexus-design.css` so Python inline
style strings referencing `var(--type-*)` work in the Dash context:

```css
:root {
  /* Typography tokens (mirrors tokens/typography.css for Dash context) */
  --type-display: 300 26px/1.2 "Open Sans", sans-serif;
  --type-h1:      600 18px/1.3 "Open Sans", sans-serif;
  --type-h2:      600 15px/1.4 "Open Sans", sans-serif;
  --type-h3:      600 13px/1.4 "Open Sans", sans-serif;
  --type-body:    400 13px/1.55 "Open Sans", sans-serif;
  --type-meta:    400 11px/1.5 "Open Sans", sans-serif;
  --type-th:      600 11px/1.4 "Open Sans", sans-serif;
  --ls-display:   0.04em;
  --ls-label:     0.07em;
  --ls-caps:      0.06em;
  --app-max-w:    1600px;
  --app-pad-x:    24px;
}
```

Apply `var(--type-display)` to `.app__header__title` and
`var(--type-meta)` to `.app__header__title--grey`.

---

## Phase 10 — Run Center Card Polish

**Effort:** 20 min · **Risk:** Low · **Impact:** Low-Medium

Match the Run Center's clean `Panel padding="22px"` look from the design:

- Each card (`DAILY PIPELINE`, `DATA BACKFILL`, `STATUS & LOGS`) should use the
  `.an-card` + `.an-card-hdr` pattern (see Phase 6).
- Button row inside cards: use `display: flex; gap: 14px; align-items: flex-end;
  flex-wrap: wrap` — matches the design's `RunCenter.jsx` exactly.
- The `Generate Factor Series` button should use `--accent-green` border color
  (already done in Python but update to use `--an-teal` per design's `accent="teal"` intent).

---

## Phase 11 — Status Pill in Header

**Effort:** 10 min · **Risk:** Low · **Impact:** Low

The design's `StatusPill label="Wind" value="—" status="live"` renders as:

```
● Wind —
```
in a rounded pill with `border: 1px solid rgba(69,182,230,0.3)` and
`background: rgba(69,182,230,0.08)`.

Current Python code already emits `.an-status-pill.idle` correctly — the CSS
`border: 1px solid transparent` means it's invisible. Fix:

```css
.an-status-pill.idle {
  background: rgba(100,115,140,.08) !important;
  color: var(--an-muted) !important;
  border-color: rgba(100,115,140,.25) !important;  /* make border visible */
}
```

---

## Phase 12 — Spacing & Container Cleanup

**Effort:** 20 min · **Risk:** Low · **Impact:** Medium

1. **Tab pane padding:** `.an-tab-pane { padding: 24px !important; }` — currently
   `padding: 20px; margin: 10px` which creates inconsistent offsets.

2. **Remove double margin:** Individual `.an-card` items have `margin: 10px 12px`.
   Once panels are in a flex column with `gap: 20px`, zero out the card margin:
   `margin: 0 !important;`

3. **Content max-width:** Wrap `#an-main-content` in a max-width container matching
   the design's `--app-max-w: 1600px`:

   ```css
   #an-main-content {
     max-width: var(--app-max-w) !important;
     margin: 0 auto !important;
     padding: 0 var(--app-pad-x) !important;
   }
   ```

---

## Implementation Order

| Priority | Phase | Effort | Files |
|----------|-------|--------|-------|
| 🔴 P0 | 1 — Token alignment | 30 min | `z_atlasnexus-design.css`, `atlas_styles.py` |
| 🔴 P0 | 4 — Main tab bar | 15 min | `z_atlasnexus-design.css` |
| 🔴 P0 | 5 — Sub-tabs | 15 min | `z_atlasnexus-design.css` |
| 🔴 P0 | 6 — Panel/card + eyebrow | 60 min | `z_atlasnexus-design.css`, market/fi/alpha/multiasset tab files |
| 🟡 P1 | 2 — Background gradient | 5 min | `z_atlasnexus-design.css` |
| 🟡 P1 | 3 — Header typography | 45 min | `z_atlasnexus-design.css`, `atlasnexus_daily.py` |
| 🟡 P1 | 7 — Bar cells | 45 min | all `atlas_*_tab.py` files |
| 🟡 P1 | 9 — Typography bridge | 20 min | `z_atlasnexus-design.css` |
| 🟢 P2 | 8 — IRS actions row | 30 min | `atlas_market_data_tab.py` |
| 🟢 P2 | 10 — Run Center | 20 min | `atlasnexus_daily.py` |
| 🟢 P2 | 11 — Status pill | 10 min | `z_atlasnexus-design.css` |
| 🟢 P2 | 12 — Spacing | 20 min | `z_atlasnexus-design.css` |

**Estimated total:** ~6 hours of focused work, all in existing files. No new
dependencies. CSS phases (1, 2, 4, 5, 9, 11, 12) can be verified by reloading the
browser without restarting the Dash server.

---

## What the Design Does NOT Require

- Changing any data logic, callback signatures, or Dash IDs
- Adding new Python packages
- Restructuring the multi-tab keep-alive DOM pattern
- Touching `app.css` (Skeleton base) — the `z_` prefix CSS loads last and wins
