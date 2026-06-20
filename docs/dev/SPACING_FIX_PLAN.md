# AtlasNexus Daily — Spacing & Width Fix Plan (v2)

> **Date:** 2026-06-20
> **Repo state reviewed:** `Yunfei2025/AtlasNexus@master` (commit `ad9111b`) — i.e. AFTER
> you applied the earlier `DASH_IMPROVEMENT_PLAN.md` work.
> **Scope:** the *horizontal spacing / width* gap only — content floats in a narrow band
> with big empty navy gutters on the left & right (June 19 screenshot), instead of the
> wide, near-full-width canvas in the reference design (`ui_kits/atlasnexus-daily/`).

---

## 0. What's already done (so this plan doesn't repeat it)

Reading the live repo, the earlier plan **is** applied. These are DONE — do **not** redo:

- ✅ Tab containers are CSS-flex, left-aligned: `.an-tabs > div[role="tablist"] { justify-content: flex-start }`, tabs `flex: 0 0 auto`.
- ✅ `.an-tab-pane` owns pane padding; the `_make_tab_switcher` base no longer injects `paddingLeft:16px` (it's just `{boxSizing:"border-box"}`).
- ✅ Tokens, `.an-card`, sub-tab styling, accent `--book-accent` var, CSS consolidation into `z_atlasnexus-design.css` — all in place.

So the remaining problem is **purely the width / gutters**, and it has a different root
cause than the earlier plan addressed.

---

## 1. The actual target (corrected)

The reference is **not** a narrow centered column. Per `tokens/spacing.css` and `readme.md`:

```css
--app-max-w: 2360px;   /* near-full-width canvas */
--app-pad-x: 28px;     /* small side padding */
```

`AppShell.jsx`: `maxWidth: var(--app-max-w); margin: 0 auto; padding: 26px var(--app-pad-x) 60px`.

> readme.md, verbatim: *"Content is a wide, near-full-width canvas (`--app-max-w` 2360px)
> with two-column panel grids on data screens."*

**So the design wants content to span almost the whole screen** (capped only at 2360px),
with just 28px of side padding. The Dash app currently does the opposite — a ~60–65%-wide
band centered in the navy box. That mismatch *is* the "left/right spacing too wide" complaint.

---

## 2. Root cause of the narrow band

Two independent things stack to produce the gutters:

### Cause A — the data tables don't fill their cards  🔴 primary
In `web/tabs/atlas_market_data_tab.py`, every table is built by `_dt_style(...)` with:

```python
style_table={"overflowX": "auto", "borderRadius": "4px"}   # ← no width
```

A Dash `DataTable` with no `width` **shrink-wraps to the sum of its column widths**. The
cards (`_card`) and the two flex columns (`flex: 1 1 auto` / `1.2 1 auto`) *do* stretch to
full width — but the **table inside each card stays narrow and left-anchored**, and because
the card fill (`#0c2b64`) is nearly identical to the panel bg (`#082255`), the empty card
space *reads as* a gutter. Net effect: content looks pinned to a narrow middle band.

### Cause B — no single full-width rail + the leftover card chrome  🟡 secondary
- The whole app is wrapped in `className="twelve columns futures__price__container"`, which
  `style.css` styles as a **rounded navy card with shadow** (`border-radius:.55rem; box-shadow…`).
  The reference has **no** such card — content sits directly on the gradient.
- There is **no `max-width:2360px; margin:0 auto`** rail anywhere, and `app__container` uses
  `padding: 0 3%` (proportional) instead of the design's fixed `28px`. On a wide monitor 3%
  adds another ~40–70px of gutter per side on top of Cause A.

---

## Phase A — Make tables fill their containers  🔴 P0

**File:** `web/tabs/atlas_market_data_tab.py` · **Effort:** 5 min · **Impact:** Highest

Give every DataTable a full-width table and let columns share the space:

```python
# _dt_style(...)
return dash_table.DataTable(
    ...
    style_table={"overflowX": "auto", "borderRadius": "4px",
                 "width": "100%", "minWidth": "100%"},   # ← fill the card
    style_cell={
        "textAlign": "center",
        "whiteSpace": "normal",
        "minWidth": "60px",
        # let columns grow to share full width instead of hugging content:
        # (DataTable distributes leftover width across columns when table width=100%)
    },
    ...
)
```

> If, after this, the *numbers* look too spread out, keep the table at `width:100%` but cap
> individual columns with `style_cell_conditional` widths — don't go back to shrink-wrap.

Apply the same `width:100%` to any other tab that builds tables the same way
(`atlas_*_tabs.py` using a local `_dt_style`/`DataTable`). Grep for `style_table=` and add
`"width": "100%"`.

---

## Phase B — Establish ONE full-width rail (2360 / 28px)  🔴 P0

**File:** `web/assets/z_atlasnexus-design.css` · **Effort:** 15 min · **Impact:** High

### B.1 — Add the layout tokens to `:root`
```css
:root {
  --app-max-w: 2360px;   /* match tokens/spacing.css */
  --app-pad-x: 28px;
}
```

### B.2 — Drop the proportional container padding; let the rail center
```css
.app__container {
  padding: 0 !important;          /* was 0 3% — replaced by the rail's padding */
}
```

### B.3 — Make the app wrapper the rail, and strip the card chrome
The `futures__price__container` wrapper should be a transparent, centered, near-full-width
rail — not a rounded navy card:

```css
.futures__price__container {
  background: transparent !important;   /* kill the navy card fill */
  border-radius: 0 !important;
  box-shadow: none !important;
  width: 100% !important;
  max-width: var(--app-max-w) !important;
  margin: 0 auto !important;
  padding: 0 var(--app-pad-x) !important;
  box-sizing: border-box !important;
}

/* the inner content holder must not re-introduce a card or width cap */
#an-main-content.tab__title {
  background: transparent !important;
  width: 100% !important;
}
```

### B.4 — Pane fills the rail, no extra horizontal inset
```css
.an-tab-pane {
  width: 100% !important;
  padding: 8px 0 0 0 !important;   /* rail owns the 28px side padding; pane only adds top */
  margin: 0 !important;
  box-sizing: border-box !important;
}
```

> Net result: header → tabs → sub-tabs → tables all share one 28px left edge and the content
> spans the full rail (up to 2360px), exactly like the reference.

---

## Phase C — Align the header to the same rail  🟡 P1

**File:** `web/assets/z_atlasnexus-design.css` · **Effort:** 10 min

The header currently breaks out full-bleed with `margin: 0 -3%` and its own navy bar, so its
left edge won't line up with the new 28px rail. Bring it onto the rail (the reference header
sits inside the canvas, on the gradient):

```css
.app__header {
  background: transparent !important;      /* reference: no dark bar */
  border-bottom: none !important;
  max-width: var(--app-max-w) !important;
  margin: 0 auto !important;
  padding: 26px var(--app-pad-x) 0 !important;   /* same 28px edge, was margin:0 -3% */
  box-sizing: border-box !important;
  align-items: flex-start !important;
}
```

> Keep the dark bar instead if you prefer it — but then give it `padding-left/right: 28px`
> (not `3%`) so the title still lines up with the content rail.

---

## Phase D — Verify in the browser  🟢 P2

CSS-only phases (B, C) need just a hard reload; Phase A needs a Dash restart.

1. At **1440 / 1920 / 2560** widths confirm:
   - Tables fill their cards (no inner empty band); the two-column grid spans the full rail.
   - Header, book tabs, sub-tabs, first panel share **one** 28px left edge.
   - Content is centered with even gutters only past **2360px**; below that it's near-full-width.
   - No rounded navy card wrapping the whole app.
2. **DevTools sanity check** (confirms which element was constraining width): inspect a
   panel card → walk up the tree → the first ancestor whose box is narrower than its parent
   is the culprit. After Phase A+B every ancestor from `.futures__price__container` down
   should report the full rail width. If one still shrink-wraps, add `width:100% !important`
   to that specific selector.

---

## Implementation order

| Priority | Phase | Effort | File |
|---|---|---|---|
| 🔴 P0 | A — DataTables `width:100%` | 5 min | `web/tabs/atlas_market_data_tab.py` (+ other tab builders) |
| 🔴 P0 | B — one 2360/28px transparent rail | 15 min | `web/assets/z_atlasnexus-design.css` |
| 🟡 P1 | C — header on the rail | 10 min | `web/assets/z_atlasnexus-design.css` |
| 🟢 P2 | D — verify (reload + restart) | 10 min | browser / DevTools |

**Total ≈ 40 min.** Phase A is the one that actually closes the gap; B/C make it match the
reference's near-full-width, card-free canvas.

---

## ⚠️ Correction to the earlier draft

An earlier `SPACING_FIX_PLAN.md` targeted `max-width:1600px / 24px`. That was wrong — the real
design tokens are **`--app-max-w: 2360px` / `--app-pad-x: 28px`** (`tokens/spacing.css`,
confirmed by `readme.md`). The design is a *wide* canvas, so the fix is to make Dash content
**fill** the width, not to cap it narrower. This v2 supersedes that file.

---

## Secondary differences (not spacing — track separately)

Visible in the screenshot but out of scope here; see `DASH_IMPROVEMENT_PLAN.md`:
- Bar-in-cell still fills the whole cell with green/red rather than a thin inline data bar.
- Main book tabs read as solid slate blocks vs. the reference's low-contrast fill + accent border.
- Accent/navy tokens are the older brighter set (`#2e86c1`, `#040f30`) vs. the refined palette.
