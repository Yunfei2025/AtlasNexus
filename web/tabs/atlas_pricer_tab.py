# -*- coding: utf-8 -*-
"""PRICER subtab for the MARKET section.

Shows bid/offer price tables for:
  - Bonds: TBond, CBond, LBond, GBond  (filtered by term range)
  - Swaps: FR007 IRS, Repo Pairs, Shi3M Pairs, Box, Repo Butterflies, Shi3M Butterflies

Data sources
------------
  Bond table  : {Type}-spdsrt.pkl  (BondCurve key for TBond/CBond; top-level for others)
                {Type}-rtquo.pkl   (Quote sub-df for Bid / Ofr per bond)
                {Type}-InstrumentInfo.pkl  (coupon, ptmyear, yield_cnbd)
  Swap table  : IRS-spdsrt.pkl  (keys: 'swaps', 'spreads')

Columns
-------
  Bonds : Ticker | Coupon | PtmYear | Yield_CNBD | Z-Score | Stationary
          Halflife | VolRatio | Close | Bid | Ofr | Mid | dYld (bp)
          Carry (3m,bp) | Roll (3m,bp) | C+R (3m,bp)
  Swaps : Ticker | Close | Bid | Ofr | Mid | dYld (bp)
          Carry (3m,bp) | Roll (3m,bp) | C+R (3m,bp)
"""

from __future__ import annotations

import re

import pandas as pd
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output

from settings.fixed_income import IRSConfig
from settings.paths import DIR_INPUT

# ── Shared theme ──────────────────────────────────────────────────────────────
THEME = {
    "bg_main":      "#082255",
    "bg_card":      "#0c2b64",
    "bg_input":     "#112e66",
    "text_main":    "#ffffff",
    "text_sub":     "#aab0c0",
    "accent":       "#3498db",
    "accent_light": "#5dade2",
    "table_header": "#061E44",
    "positive":     "#27ae60",
    "negative":     "#e74c3c",
}

# ── Dropdown options ──────────────────────────────────────────────────────────
_L1_OPTIONS = [
    {"label": "TBond (Treasury)",          "value": "TBond"},
    {"label": "CBond (Policy Bank)",       "value": "CBond"},
    {"label": "LBond (Local Gov't)",       "value": "LBond"},
    {"label": "GBond (Green Bond)",        "value": "GBond"},
    {"label": "Swap",                      "value": "Swap"},
]

_BOND_TERM_OPTIONS = [
    {"label": "1 – 3 Y",  "value": "1-3Y"},
    {"label": "3 – 5 Y",  "value": "3-5Y"},
    {"label": "5 – 7 Y",  "value": "5-7Y"},
    {"label": "7 – 10 Y", "value": "7-10Y"},
]

_SWAP_TERM_OPTIONS = [
    {"label": "Swaps",             "value": "Swaps"},
    {"label": "Repo Pairs",        "value": "RepoPairs"},
    {"label": "Shi3M Pairs",       "value": "Shi3MPairs"},
    {"label": "Box",               "value": "Box"},
    {"label": "Repo Butterflies",  "value": "RepoButterflies"},
    {"label": "Shi3M Butterflies", "value": "Shi3MButterflies"},
]

# Term range → (lo_exclusive, hi_inclusive) in years
_TERM_RANGE: dict[str, tuple[float, float]] = {
    "1-3Y":  (1.0,  3.0),
    "3-5Y":  (3.0,  5.0),
    "5-7Y":  (5.0,  7.0),
    "7-10Y": (7.0, 10.0),
}

# ── Instrument name patterns for swap sub-categories ─────────────────────────
_BUTTERFLY_RE   = re.compile(r"^(?:Repo|Shi3M)-(?:\d+[my]){3,}$", re.IGNORECASE)
_PAIR_REPO_RE   = re.compile(r"^Repo-(?:\d+[my]){2}$", re.IGNORECASE)
_PAIR_SHI3M_RE  = re.compile(r"^Shi3M-(?:\d+[my]){2}$", re.IGNORECASE)
_BOX_RE         = re.compile(r"^(?:Repo|Shi3M)-(?:\d+[my]){4,}$|^Box-", re.IGNORECASE)
_IRS_ORDER      = {ticker: rank for rank, ticker in enumerate(IRSConfig.IRS_LIST)}
_ROW_KEY_COL    = "__row_key"


def _swap_category(name: str) -> str:
    """Map an IRS spread instrument name to its UI sub-category."""
    n = str(name)
    if n.lower().startswith("basis"):
        return "Box"
    if _BUTTERFLY_RE.match(n):
        return "RepoButterflies" if n.lower().startswith("repo") else "Shi3MButterflies"
    if _PAIR_REPO_RE.match(n):
        return "RepoPairs"
    if _PAIR_SHI3M_RE.match(n):
        return "Shi3MPairs"
    if _BOX_RE.match(n):
        return "Box"
    return "Swaps"


def _sort_swap_tickers(tickers: list[str], subtype: str) -> list[str]:
    """Return PRICER swap tickers in the intended UI order."""
    if subtype != "Swaps":
        return tickers

    return sorted(
        tickers,
        key=lambda ticker: (_IRS_ORDER.get(str(ticker), len(_IRS_ORDER)), str(ticker)),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────
def _safe_round(v, n: int = 4) -> float | str:
    try:
        f = float(v)
        if f != f:          # NaN check
            return "—"
        return round(f, n)
    except Exception:
        return "—"


def _row_val(row: pd.Series, *keys) -> object:
    """Return first non-null value found in *keys* from a Series row."""
    for k in keys:
        if k in row.index:
            val = row[k]
            try:
                if pd.notna(val):
                    return val
            except Exception:
                if val is not None:
                    return val
        # case-insensitive fallback
        kl = k.lower()
        for idx in row.index:
            if str(idx).lower() == kl:
                val2 = row[idx]
                try:
                    if pd.notna(val2):
                        return val2
                except Exception:
                    if val2 is not None:
                        return val2
    return None


def _with_row_keys(rows: list[dict]) -> list[dict]:
    """Attach a hidden stable row key so style rules survive client-side sorting."""
    keyed_rows: list[dict] = []
    for idx, row in enumerate(rows):
        keyed = dict(row)
        keyed[_ROW_KEY_COL] = str(idx)
        keyed_rows.append(keyed)
    return keyed_rows


def _style_row_filter(row_key: object, col: str) -> dict[str, dict[str, str]]:
    """Return a Dash DataTable filter binding a style rule to one logical row."""
    safe_row_key = str(row_key).replace("\\", "\\\\").replace('"', '\\"')
    return {"if": {"filter_query": f'{{{_ROW_KEY_COL}}} = "{safe_row_key}"', "column_id": col}}


# ── Bar / highlight style helpers ────────────────────────────────────────────

def _bar_styles_gradient(
    df: pd.DataFrame,
    col: str,
    vmin: float,
    vmax: float,
    color: str = "rgba(52,152,219,0.45)",
    bg: str = "transparent",
) -> list[dict]:
    """Left-anchored proportional bar per cell (used for Carry / Roll / C+R)."""
    styles: list[dict] = []
    span = vmax - vmin
    if span <= 0:
        return styles
    if _ROW_KEY_COL not in df.columns:
        return styles
    for row_key, val in zip(df[_ROW_KEY_COL], df[col]):
        try:
            pct = max(0.0, min(100.0, (float(val) - vmin) / span * 100))
        except (TypeError, ValueError):
            continue
        styles.append({
            **_style_row_filter(row_key, col),
            "background": (
                f"linear-gradient(to right, {color} {pct:.1f}%, {bg} {pct:.1f}%)"
            ),
        })
    return styles


def _bar_styles_zscore(
    df: pd.DataFrame,
    col: str,
    max_abs: float = 3.0,
) -> list[dict]:
    """Center-anchored bar: positive = green (right), negative = red (left)."""
    styles: list[dict] = []
    pos_color = "rgba(39,174,96,0.60)"
    neg_color = "rgba(231,76,60,0.60)"
    if _ROW_KEY_COL not in df.columns:
        return styles
    for row_key, val in zip(df[_ROW_KEY_COL], df[col]):
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        norm = max(-1.0, min(1.0, v / max_abs))
        half = abs(norm) * 50
        if norm >= 0:
            grad = (
                f"transparent 50%, "
                f"{pos_color} 50%, {pos_color} {50 + half:.1f}%, "
                f"transparent {50 + half:.1f}%"
            )
        else:
            grad = (
                f"transparent {50 - half:.1f}%, "
                f"{neg_color} {50 - half:.1f}%, {neg_color} 50%, "
                f"transparent 50%"
            )
        styles.append({
            **_style_row_filter(row_key, col),
            "background": f"linear-gradient(to right, {grad})",
        })
    return styles


def _compute_pricer_styles(rows: list[dict], include_zscore: bool = True) -> list[dict]:
    """Build the full style_data_conditional list for a pricer table."""
    styles: list[dict] = []
    if not rows:
        return styles

    df = pd.DataFrame(_with_row_keys(rows))

    # Odd-row stripe
    styles.append({"if": {"row_index": "odd"}, "backgroundColor": THEME["bg_input"]})

    # Z-Score: center-anchored green/red bar
    if include_zscore and "Z-Score" in df.columns:
        z_vals = pd.to_numeric(df["Z-Score"], errors="coerce").dropna()
        max_abs = max(abs(z_vals).max(), 0.1) if len(z_vals) else 3.0
        styles += _bar_styles_zscore(df, "Z-Score", max_abs)

    # dYld (bp): center-anchored green/red bar
    if "dYld (bp)" in df.columns:
        d_vals = pd.to_numeric(df["dYld (bp)"], errors="coerce").dropna()
        max_abs_d = max(abs(d_vals).max(), 0.1) if len(d_vals) else 10.0
        styles += _bar_styles_zscore(df, "dYld (bp)", max_abs_d)

    # Carry / Roll / C+R: center-anchored green/red bar
    for col in ["Carry (3m,bp)", "Roll (3m,bp)", "C+R (3m,bp)"]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(vals):
                max_abs = max(abs(vals).max(), 0.1)
                styles += _bar_styles_zscore(df, col, max_abs)

    # Bid / Ofr / Mid: distinct background to separate quote columns from stats
    for col in ["Bid", "Ofr", "Mid"]:
        if col in df.columns:
            styles.append({
                "if": {"column_id": col},
                "backgroundColor": "#0d3355",
                "border": "1px solid #1e4a80",
            })

    return styles


def _make_table(
    id_: str,
    rows: list[dict],
    extra_styles: list[dict] | None = None,
) -> dash_table.DataTable:
    keyed_rows = _with_row_keys(rows)
    cols = []
    hidden_cols: list[str] = []
    if keyed_rows:
        for col in keyed_rows[0].keys():
            cols.append({"name": col, "id": col})
            if str(col).startswith("__"):
                hidden_cols.append(col)
    cond: list[dict] = extra_styles if extra_styles is not None else [
        {"if": {"row_index": "odd"}, "backgroundColor": THEME["bg_input"]}
    ]
    return dash_table.DataTable(
        id=id_,
        columns=cols,
        data=keyed_rows,
        hidden_columns=hidden_cols,
        sort_action="native",
        page_size=50,
        style_table={"overflowX": "auto", "borderRadius": "4px"},
        css=[{"selector": ".show-hide", "rule": "display: none;"}],
        style_header={
            "backgroundColor": THEME["table_header"],
            "color":           THEME["text_main"],
            "fontWeight":      "bold",
            "fontSize":        "11px",
            "border":          "1px solid #1a3a7a",
            "textAlign":       "center",
            "padding":         "5px 7px",
        },
        style_cell={
            "backgroundColor": THEME["bg_card"],
            "color":           THEME["text_main"],
            "fontSize":        "11px",
            "border":          "1px solid #142c5e",
            "padding":         "4px 7px",
            "textAlign":       "center",
            "whiteSpace":      "normal",
            "minWidth":        "55px",
        },
        style_data_conditional=cond,
    )


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_bond_spdsrt(btype: str) -> pd.DataFrame:
    """Load the BondCurve StatInfo DataFrame from {btype}-spdsrt.pkl."""
    try:
        data = pd.read_pickle(str(DIR_INPUT / f"{btype}-spdsrt.pkl"))
        if isinstance(data, dict):
            # TBond / CBond: dict with 'BondCurve', 'BondSwap' keys
            bc = data.get("BondCurve")
            if isinstance(bc, pd.DataFrame) and not bc.empty:
                return bc
            # Other bond types stored under '{btype}Spread'
            bc2 = data.get(f"{btype}Spread")
            if isinstance(bc2, dict):
                si = bc2.get("StatInfo")
                if isinstance(si, pd.DataFrame):
                    return si
            # Fallback: first DataFrame in dict
            for v in data.values():
                if isinstance(v, pd.DataFrame) and not v.empty:
                    return v
        if isinstance(data, pd.DataFrame) and not data.empty:
            return data
    except Exception:
        pass
    return pd.DataFrame()


def _load_rtquo_bid_ofr(btype: str) -> pd.DataFrame:
    """Return a DataFrame indexed by bond ID with 'Bid' and 'Ofr' columns."""
    try:
        pxrt = pd.read_pickle(str(DIR_INPUT / f"{btype}-rtquo.pkl"))
        if isinstance(pxrt, dict):
            quote = pxrt.get("Quote")
            if isinstance(quote, pd.DataFrame):
                if "ID" in quote.columns:
                    q = quote[["ID", "Bid", "Ofr"]].dropna(how="all").set_index("ID")
                    return q
                # Sometimes Quote is already indexed by bond ID
                if "Bid" in quote.columns and "Ofr" in quote.columns:
                    return quote[["Bid", "Ofr"]]
    except Exception:
        pass
    return pd.DataFrame()


def _load_instrument_def(btype: str) -> pd.DataFrame:
    """Return the instrument definition DataFrame with coupon, ptmyear, etc."""
    try:
        raw = pd.read_pickle(str(DIR_INPUT / f"{btype}-InstrumentInfo.pkl"))
        if isinstance(raw, dict):
            df = raw.get("Def", pd.DataFrame())
        else:
            df = raw
        if isinstance(df, pd.DataFrame):
            return df
    except Exception:
        pass
    return pd.DataFrame()


# ── Bond table builder ────────────────────────────────────────────────────────

def _build_bond_rows(btype: str, term_range: str) -> list[dict]:
    bc    = _load_bond_spdsrt(btype)
    rtquo = _load_rtquo_bid_ofr(btype)
    ddef  = _load_instrument_def(btype)

    if bc.empty:
        return []

    # Filter by term (years to maturity)
    lo, hi = _TERM_RANGE.get(term_range, (0.0, 100.0))
    ttm_col = next((c for c in ["ttm", "PTMYEAR", "ptmyear", "剩余期限"] if c in bc.columns), None)
    if ttm_col:
        ttm = pd.to_numeric(bc[ttm_col], errors="coerce")
        bc  = bc[(ttm > lo) & (ttm <= hi)]

    if bc.empty:
        return []

    rows: list[dict] = []
    for bond_id in bc.index:
        row_bc = bc.loc[bond_id]

        # ── Instrument attributes ──────────────────────────────────────────
        coupon     = "—"
        ptmyear    = "—"
        yield_cnbd = "—"
        if not ddef.empty and bond_id in ddef.index:
            row_def    = ddef.loc[bond_id]
            coupon     = _safe_round(_row_val(row_def, "COUPONRATE", "couponrate", "票面利率:%"), 3)
            ptmyear    = _safe_round(_row_val(row_def, "PTMYEAR",    "ptmyear",    "剩余期限"),  3)
            yield_cnbd = _safe_round(_row_val(row_def, "YIELD_CNBD", "yield_cnbd", "估价收益率:%(中债)"), 4)

        # ── Spread stats (from spdsrt BondCurve) ──────────────────────────
        def _v(key: str, n: int = 4):
            val = _row_val(row_bc, key)
            return _safe_round(val, n) if val is not None else "—"

        zscore     = _safe_round(_row_val(row_bc, "Zscore"), 2)
        stationary = _row_val(row_bc, "stationary") or "—"
        halflife   = _safe_round(_row_val(row_bc, "halflife"), 1)
        vol_ratio  = _safe_round(_row_val(row_bc, "vol_ratio"), 2)
        close      = _v("close", 4)

        # ── Bid / Ofr from rtquo ───────────────────────────────────────────
        bid = "—"
        ofr = "—"
        if not rtquo.empty and bond_id in rtquo.index:
            row_q = rtquo.loc[bond_id]
            bid = _safe_round(_row_val(row_q, "Bid", "bid"), 4)
            ofr = _safe_round(_row_val(row_q, "Ofr", "ofr"), 4)

        # Mid = (bid + ofr) / 2; fallback to CurveYield
        if bid != "—" and ofr != "—":
            try:
                mid = round((float(bid) + float(ofr)) / 2, 4)
            except Exception:
                mid = "—"
        else:
            mid = _v("CurveYield", 4)

        # dYld = (mid − yield_cnbd) × 100  [in basis points]
        if mid != "—" and yield_cnbd != "—":
            try:
                dyld = round((float(mid) - float(yield_cnbd)) * 100, 2)
            except Exception:
                dyld = "—"
        else:
            dyld = "—"

        # Carry / Roll
        carry = _safe_round(_row_val(row_bc, "Carry(3m,bp)"), 2)
        roll  = _safe_round(_row_val(row_bc, "Roll(3m,bp)"),  2)
        if carry != "—" and roll != "—":
            try:
                cr = round(float(carry) + float(roll), 2)
            except Exception:
                cr = "—"
        else:
            cr = "—"

        rows.append({
            "Ticker":        bond_id,
            "Coupon":        coupon,
            "PtmYear":       ptmyear,
            "Yield_CNBD":    yield_cnbd,
            "Z-Score":       zscore,
            "Stationary":    stationary,
            "Halflife":      halflife,
            "VolRatio":      vol_ratio,
            "Close":         close,
            "Bid":           bid,
            "Ofr":           ofr,
            "Mid":           mid,
            "dYld (bp)":     dyld,
            "Carry (3m,bp)": carry,
            "Roll (3m,bp)":  roll,
            "C+R (3m,bp)":   cr,
        })

    return rows


# ── Swap table builder ────────────────────────────────────────────────────────

def _build_swap_rows(subtype: str) -> list[dict]:
    try:
        irs_rt = pd.read_pickle(str(DIR_INPUT / "IRS-spdsrt.pkl"))
    except Exception:
        return []

    if not isinstance(irs_rt, dict):
        return []

    # Both swaps and spread subtypes are stored in the 'spreads' StatInfo DataFrame
    # (which has CvPx, QtPx, Carry(3m,bp), Roll(3m,bp) for all instruments).
    # irs_rt['swaps'] only holds contracts['value'] with FixRate — not used here.
    df = irs_rt.get("spreads", pd.DataFrame())

    if not isinstance(df, pd.DataFrame) or df.empty:
        return []

    # Filter by category (works for both "Swaps" and all spread subtypes)
    mask = [_swap_category(str(idx)) == subtype for idx in df.index]
    df = df[mask]
    if df.empty:
        return []

    rows: list[dict] = []
    for ticker in _sort_swap_tickers([str(idx) for idx in df.index], subtype):
        row = df.loc[ticker]

        def _v(key: str, n: int = 4):
            val = _row_val(row, key)
            return _safe_round(val, n) if val is not None else "—"

        # Close = curve/model price (CvPx)
        close = _v("CvPx", 4)

        # Mid = quoted/market price (QtPx or Quote)
        mid = _v("QtPx", 4)
        if mid == "—":
            mid = _v("Quote", 4)

        # IRS typically has no separate bid/ofr — leave as "—" unless present
        bid = _v("Bid", 4)
        ofr = _v("Ofr", 4)

        # dYld (bp) = (mid − close) × 100
        if mid != "—" and close != "—":
            try:
                dyld = round((float(mid) - float(close)) * 100, 2)
            except Exception:
                dyld = "—"
        else:
            # Fallback: use pre-computed spread column
            sp = _v("spread", 4)
            dyld = round(float(sp) * 100, 2) if sp != "—" else "—"

        carry = _safe_round(_row_val(row, "Carry(3m,bp)"), 2)
        roll  = _safe_round(_row_val(row, "Roll(3m,bp)"),  2)
        if carry != "—" and roll != "—":
            try:
                cr = round(float(carry) + float(roll), 2)
            except Exception:
                cr = "—"
        else:
            cr = "—"

        rows.append({
            "Ticker":        ticker,
            "Close":         close,
            "Bid":           bid,
            "Ofr":           ofr,
            "Mid":           mid,
            "dYld (bp)":     dyld,
            "Carry (3m,bp)": carry,
            "Roll (3m,bp)":  roll,
            "C+R (3m,bp)":   cr,
        })

    return rows


# ── Layout ────────────────────────────────────────────────────────────────────

def build_pricer_layout() -> html.Div:
    """Return the PRICER subtab content for the MARKET section."""
    _lbl = {"color": THEME["text_sub"], "fontSize": "11px", "marginBottom": "4px", "display": "block"}

    return html.Div(
        [
            # ── Controls row ─────────────────────────────────────────────────
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Instrument Type", style=_lbl),
                            dcc.Dropdown(
                                id="pricer-l1-dd",
                                options=_L1_OPTIONS,
                                value="TBond",
                                clearable=False,
                                style={"fontSize": "13px"},
                            ),
                        ],
                        style={"width": "200px", "minWidth": "160px"},
                    ),
                    html.Div(
                        [
                            html.Label("Sub-type / Term", style=_lbl),
                            dcc.Dropdown(
                                id="pricer-l2-dd",
                                options=_BOND_TERM_OPTIONS,
                                value="1-3Y",
                                clearable=False,
                                style={"fontSize": "13px"},
                            ),
                        ],
                        style={"width": "200px", "minWidth": "160px"},
                    ),
                    html.Div(
                        [
                            html.Label("\u00a0", style={**_lbl, "marginBottom": "0"}),
                            html.Button(
                                "↻  Refresh",
                                id="pricer-refresh-btn",
                                n_clicks=0,
                                style={
                                    "backgroundColor": THEME["bg_input"],
                                    "color":           THEME["accent"],
                                    "border":          f'1px solid {THEME["accent"]}',
                                    "borderRadius":    "4px",
                                    "padding":         "5px 14px",
                                    "fontSize":        "12px",
                                    "cursor":          "pointer",
                                },
                            ),
                        ],
                    ),
                    html.Span(
                        id="pricer-timestamp",
                        style={"color": THEME["text_sub"], "fontSize": "11px",
                               "alignSelf": "flex-end", "paddingBottom": "4px"},
                    ),
                ],
                style={
                    "display":    "flex",
                    "gap":        "16px",
                    "alignItems": "flex-end",
                    "flexWrap":   "wrap",
                    "marginBottom": "16px",
                },
            ),
            # ── Table area ────────────────────────────────────────────────────
            html.Div(id="pricer-table-container"),
        ],
        style={
            "backgroundColor": THEME["bg_main"],
            "padding":         "16px",
            "borderRadius":    "5px",
            "margin":          "10px",
        },
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

def register_pricer_callbacks(app) -> None:
    """Register PRICER subtab callbacks onto *app*."""

    @app.callback(
        Output("pricer-l2-dd", "options"),
        Output("pricer-l2-dd", "value"),
        Input("pricer-l1-dd", "value"),
    )
    def _sync_l2_options(l1: str):
        if l1 == "Swap":
            return _SWAP_TERM_OPTIONS, "Swaps"
        return _BOND_TERM_OPTIONS, "1-3Y"

    @app.callback(
        Output("pricer-table-container", "children"),
        Output("pricer-timestamp",       "children"),
        Input("pricer-refresh-btn",      "n_clicks"),
        Input("data-refresh",            "n_intervals"),
        Input("pricer-l1-dd",            "value"),
        Input("pricer-l2-dd",            "value"),
    )
    def _refresh_pricer(n_clicks, n_intervals, l1: str, l2: str):
        from datetime import datetime
        ts = datetime.now().strftime("Updated %H:%M:%S")
        _na = html.Span(
            "—",
            style={"color": THEME["text_sub"], "fontSize": "12px", "fontStyle": "italic"},
        )
        if not l1 or not l2:
            return _na, ts

        # ── Bond table ────────────────────────────────────────────────────
        if l1 != "Swap":
            label = next((o["label"] for o in _L1_OPTIONS if o["value"] == l1), l1)
            rows  = _build_bond_rows(l1, l2)
            if not rows:
                msg = (
                    f"No bond data for {l1} / {l2}. "
                    f"Run EOD to populate {l1}-spdsrt.pkl and {l1}-rtquo.pkl."
                )
                return html.Span(msg, style={"color": THEME["text_sub"], "fontSize": "12px",
                                              "fontStyle": "italic"}), ts
            styles = _compute_pricer_styles(rows, include_zscore=True)
            return html.Div([
                html.Div(
                    f"BOND PRICER  —  {label}  ·  {l2}",
                    style={"color": THEME["accent"], "fontWeight": "bold",
                           "fontSize": "13px", "marginBottom": "10px"},
                ),
                _make_table("pricer-bond-tbl", rows, extra_styles=styles),
            ]), ts

        # ── Swap table ────────────────────────────────────────────────────
        label = next((o["label"] for o in _SWAP_TERM_OPTIONS if o["value"] == l2), l2)
        rows  = _build_swap_rows(l2)
        if not rows:
            msg = (
                f"No swap data for {l2}. "
                "Run EOD to populate IRS-spdsrt.pkl."
            )
            return html.Span(msg, style={"color": THEME["text_sub"], "fontSize": "12px",
                                          "fontStyle": "italic"}), ts
        styles = _compute_pricer_styles(rows, include_zscore=False)
        return html.Div([
            html.Div(
                f"SWAP PRICER  —  {label}",
                style={"color": THEME["accent"], "fontWeight": "bold",
                       "fontSize": "13px", "marginBottom": "10px"},
            ),
            _make_table("pricer-swap-tbl", rows, extra_styles=styles),
        ]), ts
