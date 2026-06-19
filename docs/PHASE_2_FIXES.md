# AtlasNexus — Phase 2 Fix Plan
**Date:** 2026-06-19  
**Based on:** Screenshot of live app + current `z_atlasnexus-design.css` + `atlasnexus_daily.py`

---

## What Happened and Why

Claude Code's implementation was largely correct — the CSS was renamed, Python dicts
were replaced with classNames, and TOKENS were added. However **four specific gaps**
between the plan and the implementation produced the visible regressions:

| # | Symptom (screenshot) | Root cause |
|---|---|---|
| 1 | Content fills full width — no left/right breathing room | `style.css` `.app__container { margin: 3% 5% }` was deleted (step 10), but never replaced in `z_atlasnexus-design.css` |
| 2 | Main tabs (Market / Beta Book / …) stretch equally across full width | `.an-tab` CSS has no `flex` override — Dash's internal flex layout stretches every tab to equal width |
| 3 | Sub-tabs (Data / Trend / …) appear as thin text with no background | `.an-subtab` selector isn't specific enough to beat Dash's internal `.tab` class and the `colors=` prop inline styles |
| 4 | Typography/spacing scale not applied | `font-size: 14px` hardcoded on `body`; `var(--fs-body)` and `var(--lh-body)` used in variables but not consumed by `body` |

One additional Python issue contributes to double-left-indent:

| 5 | Left content more indented than right | `_make_tab_switcher` injects `paddingLeft: 16px` inline on every tab content div, stacking on top of `.an-tab-pane`'s own `padding: 20px` |

---

## Fix 1 — Restore left/right boundaries

**File:** `web/assets/z_atlasnexus-design.css`

Find the existing `.app__container` rule:
```css
/* CURRENT */
.app__container { 
  background: var(--an-navy-900) !important;
  min-height: 100vh !important;
}
```

Replace with:
```css
/* REPLACE WITH */
.app__container { 
  background: var(--an-navy-900) !important;
  min-height: 100vh !important;
  padding: 0 3% !important;        /* ← restores the left/right boundaries from old style.css */
  box-sizing: border-box !important;
}
```

And update `.app__header` to add vertical breathing room (horizontal comes from the container padding above):
```css
/* CURRENT */
.app__header {
  background: var(--an-navy-800) !important;
  border-bottom: 1px solid var(--an-border2) !important;
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
}

/* REPLACE WITH */
.app__header {
  background: var(--an-navy-800) !important;
  border-bottom: 1px solid var(--an-border2) !important;
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  padding: 10px 0 !important;      /* ← vertical breathing room inside header */
  margin: 0 -3% !important;        /* ← break out of container padding so header is edge-to-edge */
  padding-left: 3% !important;     /* ← re-align header content with body content */
  padding-right: 3% !important;
}
```

> **Alternative (simpler):** If you want the header to also sit within the margins
> (not edge-to-edge), just add `padding: 10px 0 !important` to `.app__header` and
> skip the margin trick. Both are valid — choose the one that matches your preference.

Also add top margin to `.app__content` so the tabs don't touch the header underline:
```css
/* CURRENT */
.app__content { 
  background: var(--an-navy-900) !important;
}

/* REPLACE WITH */
.app__content { 
  background: var(--an-navy-900) !important;
  margin-top: 12px !important;
}
```

---

## Fix 2 — Stop main tabs from stretching full width

**File:** `web/assets/z_atlasnexus-design.css`

Dash renders `dcc.Tabs` as a `display: flex` container where each tab has
`flex: 1` by default, making all tabs equal-width and filling 100% of the
container. The current `.an-tab` CSS sets colors and font but not `flex`.

Find the existing `.an-tab` rule:
```css
/* CURRENT */
.an-tab {
  background: var(--an-navy-300) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  padding: 6px !important;
  border-radius: var(--an-r) !important;
}
.an-tab--selected {
  background: var(--an-navy-800) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  border-left: 3px solid var(--book-accent, var(--an-blue)) !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  padding: 6px !important;
  border-radius: var(--an-r) !important;
}
```

Replace with (add `flex`, `min-width`, `text-align`):
```css
/* REPLACE WITH */
.an-tab {
  background: var(--an-navy-300) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  padding: 8px 20px !important;
  border-radius: var(--an-r) !important;
  /* ↓ prevent Dash flex-stretch */
  flex: 0 0 auto !important;
  min-width: 110px !important;
  text-align: center !important;
  white-space: nowrap !important;
}
.an-tab--selected {
  background: var(--an-navy-800) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  border-top: 2px solid var(--book-accent, var(--an-blue)) !important;
  border-left: none !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  padding: 8px 20px !important;
  border-radius: var(--an-r) !important;
  /* ↓ prevent Dash flex-stretch */
  flex: 0 0 auto !important;
  min-width: 110px !important;
  text-align: center !important;
  white-space: nowrap !important;
}
```

Also make the tab container left-align its children (not stretch them):
```css
/* ADD this new rule after .an-tabs */
.an-tabs > div[role="tablist"],
.an-tabs > div {
  display: flex !important;
  flex-direction: row !important;
  justify-content: flex-start !important;   /* ← left-align, don't distribute */
  align-items: stretch !important;
  flex-wrap: nowrap !important;
  border-bottom: 1px solid var(--an-border2) !important;
}
```

---

## Fix 3 — Sub-tab background and selected state

**File:** `web/assets/z_atlasnexus-design.css`

The sub-tabs use `className="an-subtab"` but Dash also applies its own internal
`.tab` class. The `colors=summary_subtabs_colors` prop injects inline styles on the
tab container. Current selectors aren't specific enough to win.

Find the existing `.an-subtab` rules:
```css
/* CURRENT */
.an-subtab {
  background: var(--an-navy-600) !important;
  color: var(--an-muted) !important;
  font-size: 12px !important;
  padding: 6px 20px !important;
  border: none !important;
}
.an-subtab--selected {
  background: var(--an-navy-700) !important;
  border-top: 2px solid var(--book-accent, var(--an-blue)) !important;
  color: var(--book-accent, var(--an-blue)) !important;
  border-bottom: none !important;
}
```

Replace with more specific selectors that beat Dash internals:
```css
/* REPLACE WITH */
.tab.an-subtab,
div.tab.an-subtab {
  background: var(--an-navy-600) !important;
  color: var(--an-muted) !important;
  font-size: 12px !important;
  padding: 6px 20px !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  flex: 0 0 auto !important;
  white-space: nowrap !important;
  cursor: pointer !important;
  transition: color 0.15s ease, border-color 0.15s ease !important;
}
.tab.an-subtab:hover,
div.tab.an-subtab:hover {
  color: var(--an-text) !important;
  border-bottom-color: rgba(170,176,192,0.3) !important;
}
.tab.an-subtab--selected,
div.tab.an-subtab--selected {
  background: var(--an-navy-700) !important;
  border-bottom: 2px solid var(--book-accent, var(--an-blue)) !important;
  border-top: none !important;
  color: var(--an-text) !important;
  font-weight: 600 !important;
}
/* Accent overrides per book */
.tab.an-subtab--blue   { border-bottom-color: var(--an-blue)   !important; }
.tab.an-subtab--amber  { border-bottom-color: var(--an-amber)  !important; }
.tab.an-subtab--green  { border-bottom-color: var(--an-green)  !important; }
.tab.an-subtab--purple { border-bottom-color: var(--an-purple) !important; }

/* Color the label text to match the accent */
.tab.an-subtab--blue.an-subtab--selected   { color: var(--an-blue)   !important; }
.tab.an-subtab--amber.an-subtab--selected  { color: var(--an-amber)  !important; }
.tab.an-subtab--green.an-subtab--selected  { color: var(--an-green)  !important; }
.tab.an-subtab--purple.an-subtab--selected { color: var(--an-purple) !important; }

/* Sub-tab container: left-align, border-bottom as the track */
.tab-container.an-subtab,
div[role="tablist"]:has(> .tab.an-subtab) {
  display: flex !important;
  flex-direction: row !important;
  justify-content: flex-start !important;
  border-bottom: 1px solid var(--an-border2) !important;
  gap: 0 !important;
}
```

---

## Fix 4 — Apply typography scale to body

**File:** `web/assets/z_atlasnexus-design.css`

Find:
```css
/* CURRENT */
body, .app__container {
  font-size: 14px;
  font-family: "Open Sans", sans-serif !important;
}
```

Replace with:
```css
/* REPLACE WITH */
body, .app__container {
  font-size: var(--fs-body) !important;       /* 13px — from token */
  line-height: var(--lh-body) !important;     /* 1.55 — from token */
  font-family: "Open Sans", sans-serif !important;
  color: var(--an-text) !important;
}

/* Section headings: slightly larger */
.futures__price__container h5,
.futures__price__container h6,
.an-tab-pane h5,
.an-tab-pane h6 {
  font-size: var(--fs-section) !important;    /* 15px */
  font-weight: 600 !important;
  color: var(--an-text) !important;
  margin: 0 0 8px 0 !important;
}
```

---

## Fix 5 — Remove double left-indent from `_make_tab_switcher`

**File:** `web/apps/atlasnexus_daily.py`

The `_make_tab_switcher` function applies `paddingLeft: 16px` as an inline style
on every tab content wrapper div (e.g. `#market-div`). Since the inner content
also has `className="an-tab-pane"` with `padding: 20px`, the effective left indent
is 36px vs 20px on the right — creating an off-center appearance.

Find (around line 553):
```python
# CURRENT
def _make_tab_switcher(input_id: str, div_ids: list[str], keys: list[str]):
    """Register a show/hide callback that maps *input_id* tab value to div visibility."""
    base = {"paddingLeft": "16px", "boxSizing": "border-box"}
```

Replace with:
```python
# REPLACE WITH
def _make_tab_switcher(input_id: str, div_ids: list[str], keys: list[str]):
    """Register a show/hide callback that maps *input_id* tab value to div visibility."""
    base = {"boxSizing": "border-box"}   # removed paddingLeft — .an-tab-pane handles all padding
```

---

## Summary: All changes in one place

### `z_atlasnexus-design.css` — 4 targeted edits

| Rule | Change |
|---|---|
| `.app__container` | Add `padding: 0 3%; box-sizing: border-box` |
| `.app__header` | Add `padding: 10px 0` (+ optional edge-to-edge trick) |
| `.app__content` | Add `margin-top: 12px` |
| `.an-tab` / `.an-tab--selected` | Add `flex: 0 0 auto; min-width: 110px; text-align: center; white-space: nowrap` |
| `.an-tabs > div` | Add `justify-content: flex-start` to stop tab stretching |
| `.an-subtab` rules | Upgrade selector to `.tab.an-subtab` for higher specificity |
| `body, .app__container` | Change hardcoded `14px` → `var(--fs-body)`; add `line-height: var(--lh-body)` |

### `atlasnexus_daily.py` — 1 line change

| Location | Change |
|---|---|
| `_make_tab_switcher` `base` dict (~line 553) | Remove `"paddingLeft": "16px"` |

---

## What Was NOT Broken (no changes needed)

- ✅ Z-score color fix (`graphs.py`) — already implemented correctly
- ✅ `color_mode` token alignment (`styles.py`) — already done  
- ✅ TOKENS dict in `atlas_styles.py` — already done  
- ✅ Sub-tabs switched from `style=` to `className=` — already done  
- ✅ Cards switched to `className="an-card"` / `"an-card-hdr"` — already done  
- ✅ Tab panes switched to `className="an-tab-pane"` — already done  
- ✅ `z_atlasnexus-design.css` CSS variable tokens — correct and complete  
- ✅ CSS file load order (`z_` prefix) — confirmed correct  
