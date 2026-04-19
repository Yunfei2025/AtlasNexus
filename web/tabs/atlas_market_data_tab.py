# -*- coding: utf-8 -*-
"""
Market Data tab — daily snapshot of money-market rates, bond futures,
reference bonds and IRS forward rates for the MARKET > DATA subtab.

Data sources
------------
* Money-market rates             : IRS-InstrumentInfo.pkl (CLOSE column)
* Bond futures & CTD             : futures-InstrumentInfo.pkl (key Def)
* Bond futures Zscore            : TBond-spdsrt.pkl (key BondCurve, col Zscore)
* Reference bonds     (F33:H42)  : TBond-cvref.pkl + CBond-cvref.pkl
* IRS forward rates              : IRS-forward.pkl  (Term/Date/R7D_Forward/S3M_Forward)
                                   written by curves/refreshers/irs.py compute_stats()
"""
from __future__ import annotations

import re
import traceback
from typing import Any

import pandas as pd
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output

from settings.paths import DIR_INPUT

# ── Theme ────────────────────────────────────────────────────────────────────
THEME = {
    "bg_main":       "#082255",
    "bg_card":       "#0c2b64",
    "bg_input":      "#112e66",
    "text_main":     "#ffffff",
    "text_sub":      "#aab0c0",
    "accent":        "#3498db",
    "accent_light":  "#5dade2",
    "table_header":  "#061E44",
    "positive":      "#27ae60",
    "negative":      "#e74c3c",
}

_ROW_KEY_COL = "__row_key"


def _with_row_keys_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with a stable hidden row key column."""
    if _ROW_KEY_COL in df.columns:
        return df
    keyed_df = df.copy()
    keyed_df[_ROW_KEY_COL] = [str(i) for i in range(len(keyed_df))]
    return keyed_df


def _with_row_keys_records(data: list[dict]) -> list[dict]:
    """Attach hidden stable row keys to table records when needed."""
    keyed_records: list[dict] = []
    for idx, row in enumerate(data):
        keyed_row = dict(row)
        keyed_row.setdefault(_ROW_KEY_COL, str(idx))
        keyed_records.append(keyed_row)
    return keyed_records


def _style_row_filter(row_key: object, col: str) -> dict[str, dict[str, str]]:
    """Build a DataTable style filter tied to one logical row."""
    safe_row_key = str(row_key).replace("\\", "\\\\").replace('"', '\\"')
    return {"if": {"filter_query": f'{{{_ROW_KEY_COL}}} = "{safe_row_key}"', "column_id": col}}

# ── Bar-in-cell helpers ───────────────────────────────────────────────────────

def _bar_styles_gradient(
    df: pd.DataFrame,
    col: str,
    vmin: float,
    vmax: float,
    color: str = "rgba(52,152,219,0.50)",
    bg: str = "transparent",
) -> list[dict]:
    """Return style_data_conditional entries painting a left-anchored bar per cell."""
    styles: list[dict] = []
    span = vmax - vmin
    if span <= 0:
        return styles
    keyed_df = _with_row_keys_df(df)
    for row_key, val in zip(keyed_df[_ROW_KEY_COL], keyed_df[col]):
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
    max_abs: float = 5.0,
) -> list[dict]:
    """Center-anchored bar: positive (green, right) / negative (red, left)."""
    styles: list[dict] = []
    pos_color = "rgba(39,174,96,0.55)"
    neg_color = "rgba(231,76,60,0.55)"
    keyed_df = _with_row_keys_df(df)
    for row_key, val in zip(keyed_df[_ROW_KEY_COL], keyed_df[col]):
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        norm = max(-1.0, min(1.0, v / max_abs))  # clamp to [-1, 1]
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


# ── Shared table style helpers ────────────────────────────────────────────────
def _dt_style(
    id_: str,
    columns: list[dict],
    data: list[dict],
    extra_styles: list[dict] | None = None,
) -> dash_table.DataTable:
    keyed_data = _with_row_keys_records(data)
    keyed_columns = list(columns)
    hidden_columns: list[str] = []
    if keyed_data and all(col.get("id") != _ROW_KEY_COL for col in keyed_columns):
        keyed_columns.append({"name": _ROW_KEY_COL, "id": _ROW_KEY_COL})
        hidden_columns.append(_ROW_KEY_COL)
    cond_styles = [{"if": {"row_index": "odd"}, "backgroundColor": THEME["bg_input"]}]
    if extra_styles:
        cond_styles.extend(extra_styles)
    return dash_table.DataTable(
        id=id_,
        columns=keyed_columns,
        data=keyed_data,
        hidden_columns=hidden_columns,
        css=[
            {"selector": ".show-hide", "rule": "display: none;"},
            {"selector": ".dash-spreadsheet-menu", "rule": "display: none;"},
        ],
        style_table={"overflowX": "auto", "borderRadius": "4px"},
        style_header={
            "backgroundColor": THEME["table_header"],
            "color": THEME["text_main"],
            "fontWeight": "bold",
            "fontSize": "12px",
            "border": "1px solid #1a3a7a",
            "textAlign": "center",
            "padding": "6px 8px",
        },
        style_cell={
            "backgroundColor": THEME["bg_card"],
            "color": THEME["text_main"],
            "fontSize": "12px",
            "border": "1px solid #142c5e",
            "padding": "5px 8px",
            "textAlign": "center",
            "whiteSpace": "normal",
            "minWidth": "60px",
        },
        style_data_conditional=cond_styles,
    )


def _card(title: str, content: Any) -> html.Div:
    return html.Div(
        [
            html.Div(
                title,
                style={
                    "color": THEME["accent"],
                    "fontWeight": "bold",
                    "fontSize": "13px",
                    "marginBottom": "8px",
                    "paddingBottom": "6px",
                    "borderBottom": f'1px solid {THEME["table_header"]}',
                    "letterSpacing": "0.05em",
                },
            ),
            content,
        ],
        style={
            "backgroundColor": THEME["bg_card"],
            "border": f'1px solid {THEME["table_header"]}',
            "borderRadius": "6px",
            "padding": "14px 16px",
        },
    )


# ── Data loaders ──────────────────────────────────────────────────────────────

# Instruments to show in the money-market panel (in order)
_REPO_INSTRUMENTS = ["FR001.IR", "FR007.IR", "SHIBOR3M.IR"]
_SWAP_INSTRUMENTS = [
    "FR007S1Y.IR", "FR007S5Y.IR",
    "SHI3MS1Y.IR", "SHI3MS5Y.IR",
]
_MM_INSTRUMENTS   = _REPO_INSTRUMENTS + _SWAP_INSTRUMENTS


def _load_money_market() -> pd.DataFrame:
    """Money-market snapshot.

    Close       – daily fixing/close:
        • Repo rates (FR001/FR007/SHIBOR3M): database-px.pkl['IRS'] last valid row
        • IRS swaps:                          IRS-cvpx.pkl['ytm_act'] last row
    Quote       – real-time / mid:
        • Repo rates: same as Close (published fixings, no bid/ofr available)
        • IRS swaps:  IRS-spdsrt.pkl['swaps']['Quote'] (market-quoted mid)
    Chg (bp)    – (Quote − Close) × 100
    CR (3m, bp) – Carry(3m,bp) + Roll(3m,bp) from IRS-spdsrt.pkl['swaps']
    """
    rows: list[dict] = []

    # ── Repo / fixing rates ───────────────────────────────────────────────────
    try:
        db_irs: pd.DataFrame = pd.read_pickle(str(DIR_INPUT / "database-px.pkl"))["IRS"]
    except Exception:
        db_irs = pd.DataFrame()

    for inst in _REPO_INSTRUMENTS:
        try:
            val = db_irs[inst].dropna().iloc[-1] if (not db_irs.empty and inst in db_irs.columns) else None
        except Exception:
            val = None
        v = round(float(val), 4) if val is not None and pd.notna(val) else "—"
        rows.append({
            "Reference": inst,
            "Close (%)": v,
            "Quote (%)": v,
            "Chg (bp)": 0.00 if v != "—" else "—",
            "CR (3m, bp)": "—",
        })

    # ── IRS swaps ─────────────────────────────────────────────────────────────
    try:
        ytm_act_last: pd.Series = pd.read_pickle(str(DIR_INPUT / "IRS-cvpx.pkl"))["ytm_act"].iloc[-1]
    except Exception:
        ytm_act_last = pd.Series(dtype=float)

    try:
        swaps_df: pd.DataFrame = pd.read_pickle(str(DIR_INPUT / "IRS-spdsrt.pkl"))["swaps"]
    except Exception:
        swaps_df = pd.DataFrame()

    for inst in _SWAP_INSTRUMENTS:
        c = ytm_act_last.get(inst)
        if not swaps_df.empty and inst in swaps_df.index:
            q     = swaps_df.loc[inst, "Quote"]
            carry = swaps_df.loc[inst, "Carry(3m,bp)"]
            roll  = swaps_df.loc[inst, "Roll(3m,bp)"]
        else:
            q = carry = roll = None

        c_val = round(float(c), 4) if c is not None and pd.notna(c) else "—"
        q_val = round(float(q), 4) if q is not None and pd.notna(q) else "—"

        if c_val != "—" and q_val != "—":
            chg = round((float(q_val) - float(c_val)) * 100, 2)
        else:
            chg = "—"

        if carry is not None and roll is not None and pd.notna(carry) and pd.notna(roll):
            cr = round(float(carry) + float(roll), 2)
        else:
            cr = "—"

        rows.append({
            "Reference": inst,
            "Close (%)": c_val,
            "Quote (%)": q_val,
            "Chg (bp)": chg,
            "CR (3m, bp)": cr,
        })

    return pd.DataFrame(rows)


def _load_bond_futures() -> pd.DataFrame:
    """Front-month T/TL/TF/TS futures with CTD, IRR, and Zscore from pickles."""
    try:
        inst = pd.read_pickle(str(DIR_INPUT / "futures-InstrumentInfo.pkl"))
        defs: pd.DataFrame = inst.get("Def", pd.DataFrame())
        if defs.empty:
            return pd.DataFrame()

        defs = defs.copy()
        # Extract the alphabetic contract-type prefix (T, TL, TF, TS)
        defs["_type"] = [
            m.group(1) if (m := re.match(r"^([A-Z]+)\d", idx.replace(".CFE", ""))) else ""
            for idx in defs.index
        ]

        CONTRACT_ORDER = ["TS", "TF", "T", "TL"]  # 2Y → 5Y → 10Y → 30Y
        rows: list[dict] = []
        for ct in CONTRACT_ORDER:
            subset = defs[defs["_type"] == ct]
            if subset.empty:
                continue
            front = subset.sort_values("LASTTRADE_DATE").iloc[0]
            ctd_id = front["TBF_CTD02"] if pd.notna(front.get("TBF_CTD02")) else None
            irr_val = front.get("TBF_IRR02")
            rows.append({
                "Contract": str(front.name).replace(".CFE", ""),
                "Close":    round(float(front["CLOSE"]), 3),
                "CTD":      ctd_id if ctd_id else "—",
                "IRR":      round(float(irr_val), 4) if pd.notna(irr_val) else "—",
                "_ctd_id":  ctd_id,
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Zscore from TBond-spdsrt.pkl BondCurve indexed by bond ID
        try:
            spdsrt = pd.read_pickle(str(DIR_INPUT / "TBond-spdsrt.pkl"))
            bond_curve: pd.DataFrame = spdsrt.get("BondCurve", pd.DataFrame())

            def _get_zscore(ctd_id):
                if ctd_id and ctd_id in bond_curve.index:
                    z = bond_curve.loc[ctd_id, "Zscore"]
                    return round(float(str(z)), 3) if pd.notna(z) else "—"
                return "—"

            df["Zscore"] = df["_ctd_id"].apply(_get_zscore)
        except Exception:
            df["Zscore"] = "—"

        return df.drop(columns=["_ctd_id"])

    except Exception:
        return pd.DataFrame()


def _load_reference_bonds() -> pd.DataFrame:
    """On-the-run CGB/CDB reference bonds with CR(3m,bp) from spdsrt pickles."""
    tenors = ["0.3Y", "0.5Y", "0.7Y", "1Y", "1.5Y", "2Y", "3Y", "5Y", "10Y"]
    tenor_cols = [f"Term near {t}" for t in tenors]

    rows = []
    try:
        cgb_ref  = pd.read_pickle(str(DIR_INPUT / "TBond-cvref.pkl"))
        cgb_last = cgb_ref.get("RefBond", pd.DataFrame()).iloc[-1] if isinstance(cgb_ref, dict) else pd.Series()
    except Exception:
        cgb_last = pd.Series()

    try:
        cdb_ref  = pd.read_pickle(str(DIR_INPUT / "CBond-cvref.pkl"))
        cdb_last = cdb_ref.get("RefBond", pd.DataFrame()).iloc[-1] if isinstance(cdb_ref, dict) else pd.Series()
    except Exception:
        cdb_last = pd.Series()

    try:
        cgb_bc = pd.read_pickle(str(DIR_INPUT / "TBond-spdsrt.pkl")).get("BondCurve", pd.DataFrame())
    except Exception:
        cgb_bc = pd.DataFrame()

    try:
        cdb_bc = pd.read_pickle(str(DIR_INPUT / "CBond-spdsrt.pkl")).get("BondCurve", pd.DataFrame())
    except Exception:
        cdb_bc = pd.DataFrame()

    def _cr(bc: pd.DataFrame, bond_id: Any) -> Any:
        """Return Carry(3m,bp) + Roll(3m,bp) for bond_id in BondCurve, else '—'."""
        if not isinstance(bond_id, str) or bc.empty or bond_id not in bc.index:
            return "—"
        row = bc.loc[bond_id]
        carry = row.get("Carry(3m,bp)")
        roll  = row.get("Roll(3m,bp)")
        if pd.notna(carry) and pd.notna(roll):
            return round(float(carry) + float(roll), 2)
        return "—"

    for tenor, col in zip(tenors, tenor_cols):
        cgb_id = cgb_last.get(col, "—")
        cdb_id = cdb_last.get(col, "—")
        rows.append({
            "Tenor":   tenor,
            "CGB":     cgb_id,
            "CGB_CR":  _cr(cgb_bc, cgb_id),
            "CDB":     cdb_id,
            "CDB_CR":  _cr(cdb_bc, cdb_id),
        })
    return pd.DataFrame(rows)


def _load_irs_forward() -> pd.DataFrame:
    """IRS forward rates from IRS-forward.pkl (Term/Date/R7D_Forward/S3M_Forward).

    The pkl is written by curves/refreshers/irs.py compute_stats() and contains
    the same columns as time_based_clean (reset_index of time_based_df).
    """
    pkl_path = DIR_INPUT / "IRS-forward.pkl"
    if not pkl_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_pickle(str(pkl_path))
        if isinstance(df, pd.DataFrame):
            df = df.reset_index()  # restore Term as a regular column
            # Keep only the columns written by Python (not Excel-formula columns)
            keep = [c for c in ["Term", "Date", "R7D_Forward", "S3M_Forward"] if c in df.columns]
            df = df[keep]
            for col in df.columns:
                if col not in ("Term", "Date"):
                    df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
            return df
    except Exception:
        pass
    return pd.DataFrame()


# ── Layout builder ────────────────────────────────────────────────────────────

def build_market_data_layout() -> html.Div:
    return html.Div(
        [
            # Refresh button row
            html.Div(
                [
                    html.Span(
                        "Market Data Snapshot",
                        style={"color": THEME["text_main"], "fontWeight": "bold",
                               "fontSize": "15px"},
                    ),
                    html.Button(
                        "↻ Refresh",
                        id="market-data-refresh-btn",
                        n_clicks=0,
                        style={
                            "marginLeft": "20px",
                            "backgroundColor": THEME["bg_input"],
                            "color": THEME["accent"],
                            "border": f'1px solid {THEME["accent"]}',
                            "borderRadius": "4px",
                            "padding": "4px 14px",
                            "fontSize": "12px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Span(
                        id="market-data-timestamp",
                        style={"color": THEME["text_sub"], "fontSize": "11px",
                               "marginLeft": "16px"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center",
                       "marginBottom": "16px"},
            ),

            # Row 1: Money Market + Bond Futures
            html.Div(
                [
                    html.Div(
                        _card("MONEY MARKET RATES",
                              html.Div(id="mkt-data-rates-table")),
                        style={"flex": "1", "minWidth": "0"},
                    ),
                    html.Div(
                        _card("BOND FUTURES & CTD",
                              html.Div(id="mkt-data-futures-table")),
                        style={"flex": "1", "minWidth": "0"},
                    ),
                ],
                style={"display": "flex", "gap": "14px", "marginBottom": "14px"},
            ),

            # Row 2: Reference Bonds + IRS Forward Rates
            html.Div(
                [
                    html.Div(
                        _card("REFERENCE BONDS",
                              html.Div(id="mkt-data-refbond-table")),
                        style={"flex": "1 1 auto", "minWidth": "450px"},
                    ),
                    html.Div(
                        _card("IRS FORWARD RATES",
                              html.Div(id="mkt-data-irs-table")),
                        style={"flex": "1.2 1 auto", "minWidth": "0"},
                    ),
                ],
                style={"display": "flex", "gap": "14px"},
            ),
        ],
        style={"padding": "16px", "backgroundColor": THEME["bg_main"]},
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

def register_market_data_callbacks(app) -> None:

    @app.callback(
        [
            Output("mkt-data-rates-table",   "children"),
            Output("mkt-data-futures-table", "children"),
            Output("mkt-data-refbond-table", "children"),
            Output("mkt-data-irs-table",     "children"),
            Output("market-data-timestamp",  "children"),
        ],
        Input("market-data-refresh-btn", "n_clicks"),
    )
    def _refresh_market_data(n_clicks):
        from datetime import datetime
        ts = datetime.now().strftime("Updated %H:%M:%S")

        # ── Money Market ──────────────────────────────────────────────────
        df_mm = _load_money_market()
        if df_mm.empty:
            tbl_mm = html.Span("Data unavailable", style={"color": THEME["text_sub"], "fontSize": "12px"})
        else:
            cols_mm = [{"name": c, "id": c} for c in df_mm.columns]
            mm_styles: list[dict] = []
            for bar_col in ["Chg (bp)", "CR (3m, bp)"]:
                if bar_col in df_mm.columns:
                    bar_vals = pd.to_numeric(df_mm[bar_col], errors="coerce").dropna()
                    if len(bar_vals):
                        max_abs = max(abs(bar_vals).max(), 0.1)
                        mm_styles += _bar_styles_zscore(df_mm, bar_col, max_abs=max_abs)
            tbl_mm = _dt_style("mkt-dt-rates", cols_mm, df_mm.to_dict("records"),
                               extra_styles=mm_styles)

        # ── Bond Futures ──────────────────────────────────────────────────
        df_fut = _load_bond_futures()
        if df_fut.empty:
            tbl_fut = html.Span("Data unavailable", style={"color": THEME["text_sub"], "fontSize": "12px"})
        else:
            cols_fut = [{"name": c, "id": c} for c in df_fut.columns]
            # Compute z-score bar range from actual values
            fut_styles: list[dict] = []
            if "Zscore" in df_fut.columns:
                z_vals = pd.to_numeric(df_fut["Zscore"], errors="coerce").dropna()
                z_max = max(abs(z_vals.max()), abs(z_vals.min()), 1.0)
                fut_styles = _bar_styles_zscore(df_fut, "Zscore", max_abs=z_max)
            tbl_fut = _dt_style("mkt-dt-futures", cols_fut, df_fut.to_dict("records"),
                                extra_styles=fut_styles)

        # ── Reference Bonds ───────────────────────────────────────────────
        df_ref = _load_reference_bonds()
        if df_ref.empty:
            tbl_ref = html.Span("Data unavailable", style={"color": THEME["text_sub"], "fontSize": "12px"})
        else:
            _ref_labels = {"Tenor": "Tenor", "CGB": "CGB", "CGB_CR": "CR,3m",
                           "CDB": "CDB", "CDB_CR": "CR,3m"}
            cols_ref = [{"name": _ref_labels.get(c, c), "id": c} for c in df_ref.columns]
            ref_styles: list[dict] = []
            for cr_col in ["CGB_CR", "CDB_CR"]:
                if cr_col in df_ref.columns:
                    cr_vals = pd.to_numeric(df_ref[cr_col], errors="coerce").dropna()
                    if len(cr_vals):
                        max_abs = max(abs(cr_vals).max(), 0.1)
                        ref_styles += _bar_styles_zscore(df_ref, cr_col, max_abs=max_abs)
            tbl_ref = _dt_style("mkt-dt-refbond", cols_ref, df_ref.to_dict("records"),
                                extra_styles=ref_styles)

        # ── IRS Forward Rates ─────────────────────────────────────────────
        df_irs = _load_irs_forward()
        if df_irs.empty:
            tbl_irs = html.Span("IRS-forward.pkl not yet generated — run today's IRS refresh.",
                                style={"color": THEME["text_sub"], "fontSize": "12px"})
        else:
            col_labels = {"Term": "Term", "Date": "Date",
                          "R7D_Forward": "R7D Fwd", "S3M_Forward": "S3M Fwd"}
            cols_irs = [{"name": col_labels.get(c, c), "id": c} for c in df_irs.columns]
            # Build gradient bars for both forward-rate columns
            irs_styles: list[dict] = []
            for fwd_col in ["R7D_Forward", "S3M_Forward"]:
                if fwd_col in df_irs.columns:
                    vals = pd.to_numeric(df_irs[fwd_col], errors="coerce").dropna()
                    if len(vals):
                        irs_styles += _bar_styles_gradient(
                            df_irs, fwd_col, vals.min(), vals.max(),
                            color="rgba(52,152,219,0.45)",
                            bg=THEME["bg_card"],
                        )
            tbl_irs = _dt_style("mkt-dt-irs", cols_irs, df_irs.to_dict("records"),
                                extra_styles=irs_styles)

        return tbl_mm, tbl_fut, tbl_ref, tbl_irs, ts
