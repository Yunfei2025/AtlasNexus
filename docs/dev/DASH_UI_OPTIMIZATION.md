# AtlasNexus Daily — UI Optimization Implementation Guide

> **Companion to:** `web/Dash_UI_Optimization.html` (visual preview)
> **Generated:** 2026-06-20
> **Applies to:** Dash app under `web/` — specifically `tabs/market_*.py` layout files

---

## Table of Contents

1. [Q1-A — White Table Borders (Priority: Critical)](#1-white-table-borders)
2. [Q1-B — Tab Width Recommendation](#2-tab-width)
3. [Screen 2 — Surface Tab](#3-surface-tab)
4. [Screen 3 — Pricer Tab](#4-pricer-tab)
5. [Screen 4 — Trend Tab](#5-trend-tab)
6. [Screen 5 — Curves Tab](#6-curves-tab)
7. [Global CSS Belt-and-Suspenders](#7-css-fixes)

---

## 1. White Table Borders

### Root Cause

`dash_table.DataTable` renders each `<td>` with an **inline style**:
```
border: 1px solid rgb(211, 211, 211)
```
This is applied from Python via the component's internal defaults. The CSS file
`web/assets/atlasnexus-design.css` currently only sets `border-bottom` and
`border-right` on `.dash-cell` — so `border-top` and `border-left` remain the
Dash default grey-white. CSS `!important` cannot override Dash DataTable inline
styles because those are applied at the Python component level, not the
stylesheet level.

### Fix — Python side (required in EVERY `dash_table.DataTable` call)

Locate every `dash_table.DataTable(...)` across all tab files and add:

```python
dash_table.DataTable(
    # ... existing props ...

    # ── ADD THESE THREE STYLE PROPS ──────────────────────────────
    style_cell={
        'border':          '1px solid #061E44',  # --an-border2
        'borderBottom':    '1px solid #0d2040',
        'backgroundColor': '#0e1d3a',            # --an-navy-800
        'color':           '#e9eef8',            # --an-text
        'fontFamily':      'inherit',
        'fontSize':        '12px',
        'padding':         '5px 10px',
        'whiteSpace':      'normal',
    },
    style_header={
        'border':          '1px solid #061E44',
        'borderBottom':    '1px solid #2a5298',  # --an-border (stronger)
        'backgroundColor': '#17345c',            # --an-navy-600
        'color':           '#6f83a3',            # --an-muted
        'fontWeight':      '600',
        'fontSize':        '11px',
        'letterSpacing':   '0.07em',
        'textTransform':   'uppercase',
        'padding':         '7px 10px',
    },
    style_data={
        'border':          '1px solid #061E44',
        'backgroundColor': '#0e1d3a',
    },
    style_data_conditional=[
        # Row hover
        {
            'if': {'state': 'active'},
            'backgroundColor': 'rgba(61,139,212,0.12)',
            'border':          '1px solid #2a517f',
        },
        {
            'if': {'row_index': 'odd'},
            'backgroundColor': 'rgba(255,255,255,0.018)',
        },
    ],
    # Remove default table outline; use a wrapper div for border-radius instead
    style_table={'border': 'none', 'overflowX': 'auto'},
)
```

### Wrap each DataTable for border-radius

```python
html.Div(
    dash_table.DataTable(...),
    style={
        'border':       '1px solid #1e3a5f',
        'borderRadius': '5px',
        'overflow':     'hidden',
    }
)
```

### Files to edit

Search for `dash_table.DataTable` across:
- `web/tabs/market_data.py` (Data tab — Money Market, Reference Bonds, On-The-Run, IRS)
- `web/tabs/market_pricer.py` (Pricer tab — Bond Pricer table)
- `web/tabs/beta_book.py`, `alpha_book.py`, `summary.py` (if they contain tables)

Quick search command:
```bash
grep -rn "dash_table.DataTable" web/
```

---

## 2. Tab Width

### Recommendation: Use wider tabs (design system version)

**Why:** The compact tabs (~`padding: 8px 10px`) look like Dash defaults. The
wider version (`padding: 10px 20px`) signals intentional design, improves
readability of multi-word labels ("Beta Book", "Alpha Book"), and gives the
active underline accent proper visual weight.

### Locate the main tab styles

Find the `tabs_styles` / `tab_style` dictionaries (likely in
`web/apps/atlasnexus_daily.py` or `web/core/layout.py`):

```python
# BEFORE (compact)
tab_style = {
    'padding': '8px 10px',
    # ...
}

# AFTER (wider — matches design system)
tab_style = {
    'padding': '10px 20px',
    'fontSize': '13px',
    'fontWeight': '500',
    'letterSpacing': '0.01em',
    # keep existing color/background props
}
```

Also ensure the active tab uses:
```python
selected_style = {
    'padding': '10px 20px',
    'borderBottom': '2px solid #45b6e6',  # --an-cyan
    'color': '#e9eef8',                   # --an-text
    # ...
}
```

---

## 3. Surface Tab

**File:** `web/tabs/market_surface.py`

### 3.1 — Fix panel width (currently auto / ~22% of page)

The control panel uses an auto-width container. Fix it to 280px:

```python
# In the layout return — find the outer html.Div wrapping the controls:

html.Div(
    [controls_panel, chart_div],
    style={'display': 'flex', 'height': '100%'}
)

# Change the controls panel div to:
html.Div(
    [...controls...],
    style={
        'width':      '280px',
        'minWidth':   '280px',
        'flexShrink': '0',
        'background': '#102544',      # --an-navy-750
        'borderRight': '1px solid #1e3a5f',
        'padding':    '16px',
        'overflowY':  'auto',
    }
)

# And the chart div to:
html.Div(
    [...chart...],
    style={'flex': '1', 'display': 'flex', 'flexDirection': 'column'}
)
```

### 3.2 — Replace View Mode radio+label row with chip buttons

The current View Mode uses `dcc.RadioItems` with floating labels below each
radio. Replace with a button-group pattern:

```python
# BEFORE (current broken layout)
dcc.RadioItems(
    id='surface-view-mode',
    options=[{'label': m, 'value': m} for m in ['3D','Today','Position','Short','Long','Above']],
    value='3D',
    inline=True,
    # radio dots + labels below = bad layout
)

# AFTER — chip-button group
html.Div([
    html.Label('VIEW MODE', style={
        'display': 'block', 'fontSize': '10px', 'fontWeight': '700',
        'color': '#4a5d7c', 'letterSpacing': '0.08em',
        'textTransform': 'uppercase', 'marginBottom': '5px',
    }),
    dcc.RadioItems(
        id='surface-view-mode',
        options=[{'label': m, 'value': m}
                 for m in ['3D', 'Today', 'Position', 'Short', 'Long', 'Above']],
        value='3D',
        inline=True,
        inputStyle={'display': 'none'},   # hide the radio dot
        labelStyle={
            'display':      'inline-block',
            'padding':      '3px 10px',
            'marginRight':  '4px',
            'marginBottom': '4px',
            'fontSize':     '11px',
            'border':       '1px solid #1e3a5f',
            'borderRadius': '3px',
            'color':        '#6f83a3',
            'background':   '#17345c',
            'cursor':       'pointer',
        },
        # Active chip styling via CSS class (add to atlasnexus-design.css):
        # .surface-mode-chips .form-check-input:checked + label { color: #45b6e6; ... }
        className='surface-mode-chips',
    ),
])
```

Add to `web/assets/atlasnexus-design.css`:
```css
/* View Mode chips — active state */
.surface-mode-chips label { transition: background 0.12s, color 0.12s, border-color 0.12s; }
.surface-mode-chips input[type="radio"]:checked + label {
    background:   rgba(61,139,212,0.20) !important;
    border-color: #3d8bd4 !important;
    color:        #45b6e6 !important;
}
.surface-mode-chips label:hover {
    background:   #21426e !important;
    color:        #e9eef8 !important;
}
```

### 3.3 — Style Back/Next buttons

```python
# BEFORE
html.Button('< Back', id='surface-back'),
html.Button('Next >', id='surface-next'),

# AFTER — use atlas_components
from web.tabs.atlas_components import button, input_number

html.Div([
    button('← Back', id='surface-back', variant='primary'),
    button('Next →', id='surface-next', variant='secondary'),
    input_number(id='surface-step', value=0, min=0, step=1,
                 style_overrides={'width': '54px', 'textAlign': 'center'}),
], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center'})
```

### 3.4 — Add chart context strip

Insert a thin header above the `dcc.Graph`:

```python
html.Div([
    html.Div([
        html.Span('3D Yield Surface', style={
            'fontSize': '12px', 'fontWeight': '600', 'color': '#e9eef8'
        }),
        html.Span(' · ', style={'color': '#2e547f', 'margin': '0 6px'}),
        html.Span(id='surface-chart-context',  # updated by callback
                  style={'fontSize': '11px', 'color': '#4a5d7c'}),
    ], style={'display': 'flex', 'alignItems': 'center',
              'padding': '9px 16px', 'borderBottom': '1px solid rgba(255,255,255,0.06)'}),
    dcc.Graph(id='surface-graph', style={'flex': '1'}),
], style={'flex': '1', 'display': 'flex', 'flexDirection': 'column'})
```

---

## 4. Pricer Tab

**File:** `web/tabs/market_pricer.py`

### 4.1 — DataTable border fix

See [Section 1](#1-white-table-borders) — apply all three style props to the
Pricer DataTable. No other structural changes required; the filter row controls
are already well-formed.

### 4.2 — Wrap table for border-radius

```python
html.Div(
    dash_table.DataTable(id='pricer-table', ...),
    style={
        'border':       '1px solid #1e3a5f',
        'borderRadius': '5px',
        'overflow':     'hidden',
        'marginTop':    '10px',
    }
)
```

---

## 5. Trend Tab

**File:** `web/tabs/market_trend.py`

### 5.1 — Widen the sidebar

Find the container div for the sidebar (left column with SERIES + QUICK SELECT):

```python
# BEFORE
html.Div([...], style={'width': '120px', ...})   # or minWidth / flex-based

# AFTER
html.Div([...], style={
    'width':       '172px',
    'minWidth':    '172px',
    'flexShrink':  '0',
    'background':  '#122a4c',       # --an-navy-700
    'borderRight': '1px solid #1e3a5f',
    'padding':     '12px',
    'overflowY':   'auto',
})
```

### 5.2 — Style Quick Select items as chips

The quick-select items are likely rendered as `html.Div` or `html.A` elements
inside the sidebar. Apply interactive chip styles:

```python
def quick_select_item(label, series_id, active=False):
    base = {
        'display':      'block',
        'padding':      '5px 9px',
        'borderRadius': '3px',
        'fontSize':     '12px',
        'marginBottom': '1px',
        'cursor':       'pointer',
        'transition':   'background 0.1s, color 0.1s',
    }
    if active:
        base.update({
            'background': 'rgba(69,182,230,0.10)',
            'color':      '#45b6e6',
        })
    else:
        base.update({
            'color':      '#a4b6d2',
            'background': 'transparent',
        })
    return html.Div(label, id={'type': 'qs-item', 'index': series_id},
                    style=base, n_clicks=0)
```

Wire hover via CSS (add to `atlasnexus-design.css`):
```css
.qs-chip:hover { background: #21426e !important; color: #e9eef8 !important; }
```
Add `className='qs-chip'` to each item.

### 5.3 — Frame the mini charts

Wrap each `dcc.Graph` mini-chart in a card:

```python
def mini_chart_card(series_label, graph_id):
    return html.Div([
        html.Div(series_label, style={
            'padding':       '5px 10px',
            'fontSize':      '10px',
            'color':         '#4a5d7c',
            'letterSpacing': '0.07em',
            'textTransform': 'uppercase',
            'borderBottom':  '1px solid rgba(255,255,255,0.06)',
        }),
        dcc.Graph(id=graph_id,
                  config={'displayModeBar': False},
                  style={'height': '80px'}),
    ], style={
        'background':   '#122a4c',
        'border':       '1px solid #1e3a5f',
        'borderRadius': '4px',
        'overflow':     'hidden',
    })
```

Replace bare `dcc.Graph` calls for FR001.IR, FR007.IR, SHIBOR3M.IR with
`mini_chart_card(label, id)`.

---

## 6. Curves Tab

**File:** `web/tabs/market_curves.py`

### 6.1 — Widen control panel to 260px

```python
# BEFORE
html.Div([...], style={'width': '230px', ...})   # or auto / smaller

# AFTER
html.Div([...], style={
    'width':       '260px',
    'minWidth':    '260px',
    'flexShrink':  '0',
    'background':  '#102544',
    'borderRight': '1px solid #1e3a5f',
    'padding':     '14px 16px',
    'overflowY':   'auto',
})
```

### 6.2 — Populate Reference Bonds list

The "Reference Bonds" section is currently a collapsed or placeholder `html.Div`.
Populate it from the same on-the-run data used elsewhere:

```python
def reference_bonds_list(bonds_df):
    """bonds_df: DataFrame with columns [ticker, tenor, yield_pct]"""
    items = []
    for _, row in bonds_df.iterrows():
        yield_str = f"{row['tenor']} · {row['yield_pct']:.3f}%" \
                    if row['yield_pct'] else f"{row['tenor']} · —"
        opacity = '1.0' if row['yield_pct'] else '0.5'
        items.append(html.Div([
            html.Span(row['ticker'], style={
                'fontSize': '11px', 'color': '#a4b6d2',
                'fontFamily': 'monospace',
            }),
            html.Span(yield_str, style={
                'fontSize': '11px',
                'color': '#45b6e6' if row['yield_pct'] else '#6f83a3',
            }),
        ], style={
            'display':         'flex',
            'justifyContent':  'space-between',
            'alignItems':      'center',
            'padding':         '5px 9px',
            'background':      '#122a4c',
            'border':          '1px solid rgba(255,255,255,0.06)',
            'borderRadius':    '3px',
            'marginBottom':    '2px',
            'opacity':         opacity,
            'cursor':          'pointer',
        }, id={'type': 'ref-bond-row', 'index': row['ticker']}, n_clicks=0))
    return html.Div(items)
```

Call from a callback that fires when `curve-type-dropdown` value changes.

### 6.3 — Move "Real Time Bond Curves" header inside chart container

```python
# BEFORE — heading floats above the graph as a separate html.Div
html.Div('Real Time Bond Curves', style={'fontSize': '14px', ...}),
dcc.Graph(id='curves-graph', ...),

# AFTER — wrap in a flex-column, header strip + chart
html.Div([
    html.Div([
        html.Div([
            html.Span('Real Time Bond Curves', style={
                'fontSize': '12px', 'fontWeight': '600', 'color': '#e9eef8',
            }),
            html.Span(' · ', style={'color': '#2e547f', 'margin': '0 8px'}),
            html.Span(id='curves-chart-subtitle',
                      style={'fontSize': '11px', 'color': '#4a5d7c'}),
        ]),
        # Optional Spot/Forward toggles
        html.Div([
            html.Button('Spot',    id='toggle-spot',    n_clicks=0,
                        style=_CHIP_ACTIVE_STYLE),
            html.Button('Forward', id='toggle-forward', n_clicks=0,
                        style=_CHIP_ACTIVE_STYLE),
        ], style={'display': 'flex', 'gap': '6px'}),
    ], style={
        'display':         'flex',
        'alignItems':      'center',
        'justifyContent':  'space-between',
        'padding':         '9px 16px',
        'borderBottom':    '1px solid rgba(255,255,255,0.06)',
    }),
    dcc.Graph(id='curves-graph', style={'flex': '1'}),
], style={'flex': '1', 'display': 'flex', 'flexDirection': 'column'})
```

---

## 7. Global CSS Fixes

Add/update these rules in `web/assets/atlasnexus-design.css`:

```css
/* ── DataTable — belt-and-suspenders (Python props take priority) ── */
.dash-table-container .dash-cell,
.dash-table-container .dash-header {
  border:        1px solid #061E44 !important;  /* was only bottom/right */
  border-bottom: 1px solid #061E44 !important;
  border-right:  1px solid #061E44 !important;
}
.dash-table-container .dash-header {
  border-bottom: 1px solid #2a5298 !important;  /* stronger header separator */
}

/* ── Quick select chip hover ───────────────────────────────────── */
.qs-chip { transition: background 0.1s, color 0.1s; }
.qs-chip:hover { background: #21426e !important; color: #e9eef8 !important; }

/* ── Surface view-mode chip active ────────────────────────────── */
.surface-mode-chips label {
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.surface-mode-chips input[type="radio"]:checked + label {
  background:   rgba(61,139,212,0.20) !important;
  border-color: #3d8bd4 !important;
  color:        #45b6e6 !important;
}
.surface-mode-chips label:hover {
  background: #21426e !important;
  color:      #e9eef8 !important;
}
```

---

## Summary — Priority Order

| Priority | Issue | File(s) | Effort |
|----------|-------|---------|--------|
| 🔴 Critical | White table borders (`style_cell`) | All tab files with DataTable | ~30 min |
| 🟠 High | Tab width (padding) | `atlasnexus_daily.py` or layout.py | ~5 min |
| 🟠 High | Surface panel width (280px) | `market_surface.py` | ~10 min |
| 🟡 Medium | Trend sidebar width (172px) | `market_trend.py` | ~5 min |
| 🟡 Medium | Curves panel width (260px) | `market_curves.py` | ~5 min |
| 🟡 Medium | Curves header relocation | `market_curves.py` | ~15 min |
| 🟢 Refinement | View Mode chips | `market_surface.py` + CSS | ~20 min |
| 🟢 Refinement | Quick Select chips | `market_trend.py` + CSS | ~20 min |
| 🟢 Refinement | Mini chart cards | `market_trend.py` | ~15 min |
| 🟢 Refinement | Reference Bonds list | `market_curves.py` | ~30 min |
