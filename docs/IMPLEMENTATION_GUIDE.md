# AtlasNexus Design System — Implementation Guide

## What you have

The design system was created in this project with:
- **Design tokens** (colors, spacing, typography) in `tokens/*.css`
- **Component specs** in `components/core/*.jsx` + `.d.ts`
- **Dash integration CSS** in `atlasnexus-design.css`

But your Python Dash app in GitHub uses **inline styles** (Python dicts), so the CSS never applied.

---

## 3-Step Fix

### Step 1: Drop the Fixed CSS ✅ (Immediate 85% fix)

1. Download `atlasnexus-design-FIXED.css` from this project
2. Rename it to `z_atlasnexus-design.css` (the `z_` prefix ensures it loads last)
3. Drop it into `web/assets/`
4. **Delete or rename** the old `atlasnexus-design.css` to avoid conflicts
5. Restart the app

**Result:** Colors, borders, spacing all apply. Red/green bars return. Navigation, inputs, tables styled.

**What still needs Python tweaks:** Interactive states (focus rings, hover effects on tabs) are partially driven by Python component logic and won't be 100% smooth without the next step.

---

### Step 2: (Optional, but Recommended) Migrate Python Styles to CSS ✅ (Polish to 100%)

This takes ~10 minutes. Three files need small edits:

#### File 1: `web/tabs/atlas_styles.py`

Remove the inline style dicts that conflict with CSS. Replace:

```python
# OLD — inline styles (conflict with CSS)
tab_style: Dict[str, Any] = {
    "background": "#425476",
    "color": "white",
    ...
}
tab_selected_style: Dict[str, Any] = {
    "background": "#082255",
    ...
}
```

With:

```python
# NEW — just reference CSS classes
# All styling is now in z_atlasnexus-design.css
# If you need fine-grained control, keep only layout/positioning here,
# not colors/borders.
```

Then in the app code where these are used:

```python
# OLD
dcc.Tabs(style=tabs_styles, ...)
dcc.Tab(style=tab_style, ...)
dcc.Tab(style=tab_selected_style, ...)

# NEW
dcc.Tabs(className="an-tabs", ...)
dcc.Tab(className="an-tab", ...)
dcc.Tab(className="an-tab--selected", ...)
```

**Add to `z_atlasnexus-design.css`:**

```css
/* Tabs */
.an-tabs {
  z-index: 99 !important;
  border-radius: 4px !important;
}
.an-tab {
  background: var(--an-navy-300) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  padding: 6px !important;
  border-radius: 4px !important;
}
.an-tab--selected {
  background: var(--an-navy-800) !important;
  color: var(--an-text) !important;
  border: 1px solid var(--an-border2) !important;
  border-left: 3px solid var(--an-blue) !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  padding: 6px !important;
  border-radius: 4px !important;
}
```

#### File 2: `web/tabs/atlas_components.py`

This file is already well-structured with `atlas_components.button()` etc. No changes needed — it already uses inline styles strategically but is flexible.

**If you want to bind buttons to CSS:**

```python
# In button() function, add optional className:
def button(
    label: str,
    *,
    variant: str = "primary",
    className: str = "",  # NEW
    style_overrides: dict | None = None,
    **kwargs,
) -> html.Button:
    bg, border = _BTN_VARIANTS.get(variant, _BTN_VARIANTS["primary"])
    style: dict[str, Any] = {
        **_BASE_BTN,
        "background": bg,
        "border": f"1px solid {border}",
        **(style_overrides or {}),
    }
    # If className provided, use it instead of inline styles
    if className:
        return html.Button(label, className=className, **kwargs)
    return html.Button(label, style=style, **kwargs)
```

#### File 3: `web/core/styles.py`

This is a large file with Plotly figure configurations. **No changes needed** — Plotly uses JSON config, not CSS. The CSS file already handles the wrapper containers.

---

### Step 3: (Final Polish) Test & Iterate

After dropping the CSS:
1. Open the app at `http://localhost:8080`
2. Check:
   - [ ] Red/green bars in table cells visible
   - [ ] Tabs styled correctly (navy background, cyan active underline)
   - [ ] Buttons look cohesive
   - [ ] Dropdowns dark navy
   - [ ] Inputs have proper focus states
   - [ ] Overall navy terminal aesthetic consistent

If anything looks off:
- Open browser DevTools (`F12`)
- Inspect the element
- Check if CSS rule is being applied (green checkmark = yes)
- If `app.css` or `style.css` is overriding, remove those files or prefix them with `a_` so they load before `z_`

---

## File Inventory

| File | Purpose | Action |
|---|---|---|
| `z_atlasnexus-design.css` | Design tokens + component CSS | ✅ Drop into `web/assets/` |
| `atlasnexus-design.css` | Old conflicting file | ❌ Delete from `web/assets/` |
| `web/tabs/atlas_styles.py` | Python style dicts | Optional: migrate to className |
| `web/tabs/atlas_components.py` | Component helpers | Keep as-is (already good) |
| `web/core/styles.py` | Plotly config | Keep as-is |
| `web/assets/app.css` | Skeleton framework | Optional: can remove if using only `z_` |
| `web/assets/style.css` | Old inline styles | Optional: archive after `z_` proven |

---

## Why This Works

**CSS Cascade:**
- `app.css` loads first (Skeleton framework)
- `style.css` loads second (old inline)
- `atlasnexus-design.css` loads third (conflicts)
- **`z_atlasnexus-design.css` loads last** ← wins all conflicts via `!important`

**What `!important` does:**
- It says "ignore browser cascade, use this rule"
- Necessary because Python inline `style=` attributes are naturally highest priority
- Only NOT used on `.dash-cell background` so `style_data_conditional` (your red/green bars) can inject their own background colors per-cell

---

## Next: Claude Code in VS Code

If you want the full polish (step 2), hand this guide + the original repo to Claude Code. It can:
1. Search/replace `tab_style` → `className="an-tab"` across all files
2. Add the CSS class rules
3. Test & iterate

**But step 1 alone (just the CSS) gets you 85% of the way.**

---

## Troubleshooting

**"Red/green bars still missing"**
- Check DevTools. Is `.dash-cell` showing `background: var(--an-navy-800) !important`?
- If yes, you used the old CSS. Replace with `z_atlasnexus-design.css`.
- If no, the conditional styling in Python is broken. Check `style_data_conditional` in the tab code.

**"Colors are still old"**
- Did you rename to `z_atlasnexus-design.css`? (Or place it alphabetically last?)
- Do a hard refresh: `Ctrl+Shift+R` (Windows) or `Cmd+Shift+R` (Mac)
- Check DevTools Network tab: is the CSS file loading at all?

**"Font sizes are huge / tiny"**
- That's the `app.css` font-size hack. The fixed CSS resets it. Verify `html { font-size: 10px; }` is in your CSS file.

---

## Questions?

The key insight: **Python inline styles beat regular CSS**, so we use `!important` to win. Cleaner long-term is to migrate to `className=` + pure CSS, but the fixed CSS alone gets you there without touching Python.
