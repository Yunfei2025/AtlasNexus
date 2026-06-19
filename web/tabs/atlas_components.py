"""
atlas_components.py — AtlasNexus Dash Component Helpers
========================================================
DROP THIS FILE into  web/tabs/  (or web/) in your codebase.

Usage:
    from web.tabs.atlas_components import button, card, badge, label_field

These are thin wrappers around html.* / dcc.* that apply consistent
AtlasNexus styles, matching the colours in atlas_styles.py exactly.
All kwargs are forwarded to the underlying Dash component so you keep
full control (id, n_clicks, disabled, style overrides, className, etc.)

BEFORE:
    html.Button("Run EOD", id="an-btn-eod", n_clicks=0, style={
        'background':'#1a3a6e','color':'#ffffff','border':'1px solid #2a5298',
        'borderRadius':'4px','padding':'6px 14px','cursor':'pointer','fontSize':'13px',
    })

AFTER:
    button("Run EOD", id="an-btn-eod", n_clicks=0)
"""

from __future__ import annotations
from typing import Any

from dash import html, dcc

# ── Colour / style constants (mirror atlas_styles.py) ─────────────────────────

_NAVY_800   = "#082255"
_NAVY_700   = "#0c2b64"
_NAVY_600   = "#112e66"
_NAVY_500   = "#1a3a6e"
_BORDER     = "#2a5298"
_BLUE       = "#2e86c1"
_GREEN      = "#27ae60"
_AMBER      = "#f39c12"
_RED        = "#c0392b"
_PURPLE     = "#8e44ad"
_CYAN       = "#45b6e6"
_TEXT       = "#ffffff"
_MUTED      = "#aab0c0"

# Button variant → (background, border-color)
_BTN_VARIANTS: dict[str, tuple[str, str]] = {
    "primary":   (_NAVY_500, _BORDER),
    "secondary": ("#1a5276", "#2e86c1"),
    "success":   ("#1a4731", "#27ae60"),
    "danger":    ("#6e1a1a", "#c0392b"),
    "warning":   ("#6e4b00", "#f39c12"),
}

_BASE_BTN: dict[str, Any] = {
    "color":        _TEXT,
    "borderRadius": "4px",
    "padding":      "6px 14px",
    "cursor":       "pointer",
    "fontSize":     "13px",
    "fontWeight":   "500",
    "lineHeight":   "1",
    "whiteSpace":   "nowrap",
}

_BASE_LABEL: dict[str, Any] = {
    "color":        _MUTED,
    "fontSize":     "11px",
    "marginBottom": "4px",
    "display":      "block",
    "letterSpacing": "0.06em",
    "textTransform": "uppercase",
}

_BASE_INPUT: dict[str, Any] = {
    "background":   _NAVY_600,
    "color":        _TEXT,
    "border":       f"1px solid {_BORDER}",
    "borderRadius": "4px",
    "padding":      "5px 8px",
    "width":        "100%",
    "fontSize":     "13px",
}

_BASE_CARD: dict[str, Any] = {
    "padding":      "14px 15px",
    "background":   _NAVY_700,
    "margin":       "10px 12px",
    "borderRadius": "6px",
    "border":       f"1px solid rgba(42,82,152,0.3)",
}

_BASE_CARD_HDR: dict[str, Any] = {
    "color":         _MUTED,
    "fontSize":      "11px",
    "fontWeight":    "600",
    "letterSpacing": "0.08em",
    "textTransform": "uppercase",
    "marginBottom":  "10px",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def button(
    label: str,
    *,
    variant: str = "primary",
    style_overrides: dict | None = None,
    **kwargs,
) -> html.Button:
    """Themed html.Button.

    Args:
        label:           Button text.
        variant:         One of "primary" | "secondary" | "success" | "danger" | "warning".
        style_overrides: Dict merged on top of the base style (e.g. marginRight="10px").
        **kwargs:        Forwarded to html.Button (id, n_clicks, disabled, …).

    Example:
        button("Run EOD", id="an-btn-eod", n_clicks=0)
        button("Delete", id="btn-del", variant="danger")
        button("Save",   id="btn-save", variant="success", style_overrides={"marginLeft": "8px"})
    """
    bg, border = _BTN_VARIANTS.get(variant, _BTN_VARIANTS["primary"])
    style: dict[str, Any] = {
        **_BASE_BTN,
        "background": bg,
        "border":     f"1px solid {border}",
        **(style_overrides or {}),
    }
    return html.Button(label, style=style, **kwargs)


def lbl(text: str, **kwargs) -> html.Label:
    """Small all-caps muted label, matching _LBL_STYLE."""
    style = {**_BASE_LABEL, **(kwargs.pop("style", {}) or {})}
    return html.Label(text, style=style, **kwargs)


def card(
    title: str,
    children: Any,
    *,
    style_overrides: dict | None = None,
    **kwargs,
) -> html.Div:
    """Titled card panel (_card_style + _card_hdr pattern).

    Example:
        card("DAILY PIPELINE", html.Div([...]))
    """
    card_style = {**_BASE_CARD, **(style_overrides or {})}
    return html.Div(
        [
            html.Div(title, style=_BASE_CARD_HDR),
            children,
        ],
        style=card_style,
        **kwargs,
    )


def badge(
    text: str,
    *,
    status: str = "idle",
    **kwargs,
) -> html.Span:
    """Inline status badge pill (mirrors the an-status-pill CSS class).

    status: "ok" | "warn" | "error" | "idle"
    
    Example:
        badge("FINISHED", status="ok")
        badge("RUNNING",  status="warn")
        badge("FAILED",   status="error")
    """
    _STATUS: dict[str, tuple[str, str]] = {
        "ok":    ("#1a4731", _GREEN),
        "warn":  ("#6e4b00", _AMBER),
        "error": ("#6e1a1a", _RED),
        "idle":  ("#1c2540", _MUTED),
    }
    bg, fg = _STATUS.get(status, _STATUS["idle"])
    style = {
        "background":   bg,
        "color":        fg,
        "border":       f"1px solid {fg}",
        "borderRadius": "3px",
        "padding":      "1px 6px",
        "fontSize":     "11px",
        "fontWeight":   "600",
        "whiteSpace":   "nowrap",
        **(kwargs.pop("style", {}) or {}),
    }
    return html.Span(text, style=style, className="an-status-pill", **kwargs)


def label_field(
    label_text: str,
    input_component: Any,
    *,
    min_width: str = "140px",
    flex: str = "0 0 auto",
    z_index: int | None = None,
    **kwargs,
) -> html.Div:
    """Label stacked above an input (dropdown, date picker, etc.).

    Example:
        label_field("As Of Date", dcc.DatePickerSingle(id="asof", ...))
        label_field("Instrument", dcc.Dropdown(id="btype", options=[...], value="IRS"))
    """
    wrapper_style: dict[str, Any] = {
        "display":   "flex",
        "flexDirection": "column",
        "minWidth":  min_width,
        "flex":      flex,
    }
    if z_index is not None:
        wrapper_style["position"] = "relative"
        wrapper_style["zIndex"]   = str(z_index)
    wrapper_style.update(kwargs.pop("style", {}) or {})
    return html.Div(
        [lbl(label_text), input_component],
        style=wrapper_style,
        **kwargs,
    )


def button_row(*buttons: Any, gap: str = "8px") -> html.Div:
    """Flex row of buttons with consistent gap.

    Example:
        button_row(
            button("Update Data",  id="btn-update"),
            button("Run EOD",      id="btn-eod"),
            button("Run EOD+Data", id="btn-eod-update"),
        )
    """
    return html.Div(
        list(buttons),
        style={
            "display":    "flex",
            "flexDirection": "row",
            "alignItems": "center",
            "flexWrap":   "wrap",
            "gap":        gap,
        },
    )


def section_header(text: str, **kwargs) -> html.Div:
    """Bold all-caps section heading, same style as _card_hdr."""
    style = {**_BASE_CARD_HDR, **(kwargs.pop("style", {}) or {})}
    return html.Div(text, style=style, **kwargs)


def stat(
    label_text: str,
    value: str,
    *,
    value_color: str = _TEXT,
    **kwargs,
) -> html.Div:
    """Small labelled stat (KPI cell).

    Example:
        stat("Latest EOD", "2026-06-17")
        stat("Status",     "completed", value_color="#27ae60")
    """
    return html.Div(
        [
            html.Div(label_text, style={**_BASE_LABEL, "marginBottom": "2px"}),
            html.Div(value, style={"color": value_color, "fontSize": "14px", "fontWeight": "600"}),
        ],
        style={"display": "flex", "flexDirection": "column", **(kwargs.pop("style", {}) or {})},
        **kwargs,
    )


def dropdown(
    *,
    style_overrides: dict | None = None,
    theme_overrides: dict | None = None,
    **kwargs,
) -> dcc.Dropdown:
    """dcc.Dropdown pre-wired with AtlasNexus style + optionHeight=30.

    Example:
        dropdown(id="btype", options=[...], value="IRS", clearable=False)
    """
    style  = {"fontSize": "13px", **(style_overrides or {})}
    return dcc.Dropdown(style=style, optionHeight=30, **kwargs)


def input_number(
    *,
    style_overrides: dict | None = None,
    **kwargs,
) -> dcc.Input:
    """dcc.Input[type=number] with AtlasNexus styling.

    Example:
        input_number(id="workers", value=4, min=1, max=32, step=1)
    """
    style = {**_BASE_INPUT, **(style_overrides or {})}
    return dcc.Input(type="number", style=style, **kwargs)
