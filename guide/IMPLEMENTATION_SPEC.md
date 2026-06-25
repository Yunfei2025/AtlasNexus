# AtlasNexus Daily — UI Implementation Spec
> Reference for porting the HTML/JSX prototype to production (Dash / Python).
> Read alongside the JSX source files in this folder — they are the ground truth for layout and data.

---

## 1. Design System Rules (applies everywhere)

### Fonts
- **UI / labels / headings**: `IBM Plex Sans` — use `var(--font-sans)`
- **All numeric / tabular data, IDs, metadata**: `IBM Plex Mono` — use `var(--font-mono)`
- SVG chart text must explicitly set `fontFamily` — SVGs do not inherit CSS font vars automatically
- Never hardcode `"monospace"` or `"sans-serif"` — always reference the token

### Cards / Panels
- Use the `Panel` component (or equivalent) for every section container
- Required tokens: `--surface-panel`, `--border-default`, `--radius-md` (8px), `--shadow-panel`
- **No square corners** — all cards use `--radius-md`
- Header: eyebrow label (uppercase mono, accent color) + optional actions row
- Body padding: `var(--panel-pad)` (22px) unless overridden to `padding="0"` for flush tables

### Spacing
- Gap between panels: `16–20px`
- Use `--panel-pad` (22px) for internal panel padding
- Dense 4px grid: `--space-1` (2px) → `--space-10` (40px)

---

## 2. Summary → Risk Subtab

### Reference file
`ui_kits/atlasnexus-daily/SummaryRisk.jsx`

### Layout (top → bottom)

```
┌─────────────────────────────────────────────────────────┐
│  KPI Strip: 4 cards (Total Long / Short / Net Exp / DV01) │
└─────────────────────────────────────────────────────────┘
┌──────────────────────────┬──────────────────────────────┐
│                          │  DV01 Duration Ladder        │
│  Net Position by         │  (stacked bar, 6 tenors)     │
│  Instrument              ├──────────────────────────────┤
│  (horizontal bar chart)  │  Factor Risk Attribution     │
│                          │  (horizontal bar, sqrt scale)│
└──────────────────────────┴──────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  Position Inventory (collapsible)                        │
│  Collapsed: Beta positions | Alpha positions | By Sector │
│  Expanded: full DataTable                                │
└─────────────────────────────────────────────────────────┘
```

### Grid columns
- Left (Net Position): `1fr` — always ≥50% of page width
- Right (DV01 + Factor Risk stacked): `440px` fixed

### KPI Cards
| Label | Value | Accent |
|---|---|---|
| Total Long | sum of net > 0 positions (MM) | green |
| Total Short | sum of abs(net < 0) positions (MM) | amber |
| Net Exposure | Long − Short (MM) | cyan |
| Total DV01 | sum all DV01 (MM/bp) | blue |

### Net Position Chart
- Horizontal bar chart, one bar per instrument
- Color by book/direction: Beta=blue, Alpha long=amber, Alpha short=red, Mixed long=green
- Show value label at end of each bar (+/− MM)
- SVG: `viewBox="0 0 560 420"` `width="100%"`

### DV01 Duration Ladder
- Stacked vertical bar chart, tenors: 1Y 2Y 5Y 10Y 20Y 30Y
- Stacks: Bonds (blue `#3d8bd4`), Swaps (cyan `#45b6e6`), Futures (amber `#e0a23c`)
- SVG: fixed `width=400 height=290`, NOT `width="100%"` (renders 1:1, fonts stay true size)
- Tenor totals strip below chart

### Factor Risk Attribution
- Horizontal bar chart, one bar per factor (6 factors)
- **Use √ (square root) scale** — IRDL.CN (1.18 net exp) otherwise dwarfs commodity factors (0.025)
- Bar color = Δ RC %: amber (>10), gold (0–10), slate (0 to −10), red (<−10)
- Right annotations: RC % and Δ RC % per factor
- SVG: `viewBox="0 0 400 188"` `width="100%"` (matches ~440px column → ~1:1 font rendering)
- Label x-axis as "√ scale"

### Position Inventory (collapsed default)
- 3-column grid: Beta positions | Alpha positions | Capital by Sector
- Both Beta and Alpha show **capital (MM)**, not DV01
- Expand toggle reveals full DataTable with: Book badge, Name, Instrument, Sector, Capital, DV01, Direction badge

---

## 3. Run Center Tab

### Reference file
`ui_kits/atlasnexus-daily/RunCenter.jsx`

### Layout
```
┌──────────────────────┬────────────────────────────────────┐
│  LEFT COLUMN (320px) │  RIGHT COLUMN (flex 1)             │
│                      │                                    │
│  Daily Pipeline      │  Status bar (run_id, mode, asof,  │
│  ─ As Of Date        │  status pill, elapsed)             │
│  ─ Run EOD           │                                    │
│  ─ Run Intraday      │  Log viewer (scrolling, monospace) │
│  ─ Reprocess         │  480px height, auto-scroll         │
│  ─ Force Recalc      │  Color-coded by level:             │
│                      │    INFO=slate, WARN=amber,         │
│  Data Backfill       │    ERROR=red, SUCCESS=green,       │
│  ─ Instrument type   │    DEBUG=muted                     │
│  ─ Update steps      │  Timestamp | Level | Message       │
│  ─ Date range        │                                    │
│  ─ Run Backfill      │                                    │
└──────────────────────┴────────────────────────────────────┘
```

### Design intent
- Utilitarian / control-focused — no decorative elements
- Controls are independent (Daily Pipeline and Backfill are separate workflows)
- Log viewer auto-scrolls to bottom on new entries
- Status bar always visible above the log
- Font for log lines: `IBM Plex Mono`, `13px`
- Log level badge: inline colored text, not a pill badge

### Controls (left panel)
- `Input` — As Of Date (text/date)
- `Button variant="primary"` — Run EOD / Run Backfill (primary action per section)
- `Button variant="outline"` — secondary actions (Reprocess, Force Recalc)
- `Select` — Instrument type, Update steps
- Date range: two `Input` fields (From / To)

### Status bar fields
| Field | Source |
|---|---|
| run_id | last pipeline execution ID |
| mode | eod / intraday / backfill |
| asof | date of last run |
| status | IDLE / RUNNING / COMPLETE / ERROR |
| elapsed | duration of last run |

---

## 4. Implementation Approach

### Option A — Port JSX → Dash components (recommended)
Point Claude Code at the JSX files directly:
```
"Port SummaryRisk.jsx and RunCenter.jsx to Dash/Plotly. 
Use the existing component structure in web/apps/atlasnexus_daily.py.
Match layout, color tokens, and data exactly from the JSX."
```
The JSX is the spec — Claude Code can read it and translate layout/styles to `html.Div` + `dcc.Graph` + `className` patterns.

### Option B — Embed JSX prototype as iframe
If the Dash app allows iframes, serve the HTML prototype as a static asset and embed it. Zero migration cost, but loses Dash reactivity.

### Option C — Copy token values directly
All color/spacing/font tokens are in `tokens/` at the design system root. Import `styles.css` in your Dash app's assets folder and all `var(--...)` tokens resolve automatically — no need to hardcode any values.

---

## 5. Token Quick Reference

| Token | Value | Use |
|---|---|---|
| `--font-sans` | IBM Plex Sans | UI text |
| `--font-mono` | IBM Plex Mono | Data / numbers |
| `--radius-md` | 8px | Panel/card corners |
| `--panel-pad` | 22px | Panel inner padding |
| `--shadow-panel` | layered navy shadow | Panel elevation |
| `--surface-panel` | navy-700 | Panel background |
| `--border-default` | 1px navy border | Panel outline |
| `--text-primary` | bright white | Primary text |
| `--text-secondary` | mid-brightness | Secondary labels |
| `--text-muted` | dim blue-grey | Metadata / hints |
| `--border-subtle` | very faint border | Row separators |
