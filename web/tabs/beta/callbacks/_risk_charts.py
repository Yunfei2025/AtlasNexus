# -*- coding: utf-8 -*-
"""Plotly figure builders + small layout helpers for the Summary > Risk subtab.

Ported from guide/SummaryRisk.jsx — these functions consume the *real* data
already computed in risk.py::update_risk_tables (net_pos, kt_grid,
factor_risk_df, beta_rows, alpha_rows). The JSX mock arrays were used only as
a shape/visual reference, not as data source.
"""

from __future__ import annotations

import math

from dash import html
import plotly.graph_objects as go

from web.tabs.atlas_styles import PLOTLY_LAYOUT_DEFAULTS, TOKENS

_NET_BETA_ONLY = TOKENS["blue"]       # pure beta -> blue
_NET_ALPHA_LONG = TOKENS["amber"]     # pure alpha long -> amber
_NET_ALPHA_SHORT = TOKENS["red"]      # pure alpha short -> red
_NET_MIXED_LONG = "#41b078"           # mixed long -> green
_NET_MIXED_SHORT = TOKENS["red"]

_DV01_BONDS = TOKENS["blue"]
_DV01_SWAPS = TOKENS["cyan"]
_DV01_FUTURES = TOKENS["amber"]

_FACTOR_AMBER = TOKENS["amber"]
_FACTOR_GOLD = "#c8a060"
_FACTOR_SLATE = "#6b8cb8"
_FACTOR_RED = TOKENS["red"]


def _base_layout(**overrides):
    layout = dict(PLOTLY_LAYOUT_DEFAULTS)
    layout.update(overrides)
    return layout


def _net_pos_bar_color(beta: float, alpha: float, net: float) -> str:
    if beta != 0 and alpha == 0:
        return _NET_BETA_ONLY
    if beta == 0 and alpha > 0:
        return _NET_ALPHA_LONG
    if beta == 0 and alpha < 0:
        return _NET_ALPHA_SHORT
    return _NET_MIXED_LONG if net >= 0 else _NET_MIXED_SHORT


def build_net_position_fig(net_pos: dict, top_n: int = 15) -> go.Figure:
    """Diverging horizontal bar chart of net position by instrument.

    `net_pos` is the dict built in update_risk_tables: {code: {'Beta': mm, 'Alpha': mm}}.
    """
    rows = []
    for code, e in net_pos.items():
        beta, alpha = e.get("Beta", 0.0), e.get("Alpha", 0.0)
        net = round(beta + alpha, 4)
        if abs(net) < 1e-6 and abs(beta) < 1e-6 and abs(alpha) < 1e-6:
            continue
        rows.append({"inst": code, "beta": beta, "alpha": alpha, "net": net})

    rows.sort(key=lambda r: -abs(r["net"]))
    rows = rows[:top_n]
    rows.reverse()  # plot largest at top

    fig = go.Figure()
    if not rows:
        fig.update_layout(**_base_layout(height=320))
        fig.add_annotation(text="No netted positions found.", showarrow=False,
                            font={"color": TOKENS["muted"]})
        return fig

    insts = [r["inst"] for r in rows]
    nets = [r["net"] for r in rows]
    colors = [_net_pos_bar_color(r["beta"], r["alpha"], r["net"]) for r in rows]
    text = [f"{'+' if v > 0 else ''}{v:,.0f}" for v in nets]

    fig.add_trace(go.Bar(
        x=nets, y=insts, orientation="h",
        marker_color=colors, opacity=0.88,
        text=text, textposition="outside",
        textfont={"color": TOKENS["text"], "size": 10},
        hovertemplate="%{y}: %{x:+,.1f} MM<extra></extra>",
    ))

    fig.update_layout(**_base_layout(
        height=max(320, len(rows) * 26 + 60),
        bargap=0.35,
        showlegend=False,
        margin={"t": 20, "b": 30, "l": 90, "r": 40},
    ))
    fig.update_xaxes(zeroline=True, zerolinewidth=1.5, title_text="MM CNY")
    fig.update_yaxes(automargin=True)
    return fig


def build_dv01_ladder_fig(kt_grid: dict, tenor_order: list[str]) -> go.Figure:
    """Stacked vertical bar chart: DV01 (MM/bp) by tenor, split Bonds/Swaps/Futures."""
    tenors = [t for t in tenor_order if any(abs(v) > 1e-8 for v in kt_grid[t].values())]

    fig = go.Figure()
    if not tenors:
        fig.update_layout(**_base_layout(height=290))
        fig.add_annotation(text="No rate positions found.", showarrow=False,
                            font={"color": TOKENS["muted"]})
        return fig

    bonds = [kt_grid[t]["Bonds"] for t in tenors]
    swaps = [kt_grid[t]["Swaps"] for t in tenors]
    futures = [kt_grid[t]["Futures"] for t in tenors]
    totals = [round(kt_grid[t]["Bonds"] + kt_grid[t]["Swaps"] + kt_grid[t]["Futures"]
                     + kt_grid[t]["Other"], 4) for t in tenors]

    fig.add_trace(go.Bar(name="Bonds", x=tenors, y=bonds, marker_color=_DV01_BONDS, opacity=0.9))
    fig.add_trace(go.Bar(name="Swaps", x=tenors, y=swaps, marker_color=_DV01_SWAPS, opacity=0.9))
    fig.add_trace(go.Bar(name="Futures", x=tenors, y=futures, marker_color=_DV01_FUTURES, opacity=0.9))

    fig.update_layout(**_base_layout(
        height=290,
        barmode="relative",
        bargap=0.36,
        legend={**PLOTLY_LAYOUT_DEFAULTS["legend"], "orientation": "h",
                "y": -0.18, "x": 0.5, "xanchor": "center"},
        margin={"t": 30, "b": 30, "l": 44, "r": 16},
    ))
    fig.update_yaxes(title_text="MM/bp")

    for t, total in zip(tenors, totals):
        fig.add_annotation(x=t, y=total, text=f"{total:.4f}", showarrow=False,
                            yshift=12, font={"size": 10, "color": TOKENS["muted"]})
    return fig


def _factor_bar_color(delta: float) -> str:
    if delta > 10:
        return _FACTOR_AMBER
    if delta > 0:
        return _FACTOR_GOLD
    if delta > -10:
        return _FACTOR_SLATE
    return _FACTOR_RED


def build_factor_risk_fig(factor_risk_df, skip_prefixes=("SPDL", "SPSL")) -> go.Figure:
    """Horizontal bar chart of factor net exposure on a sqrt x-scale, colored by Delta RC%."""
    fig = go.Figure()
    if factor_risk_df is None or factor_risk_df.empty:
        fig.update_layout(**_base_layout(height=240))
        fig.add_annotation(text="Beta factor risk not yet computed.", showarrow=False,
                            font={"color": TOKENS["muted"]})
        return fig

    df = factor_risk_df.copy()
    if "Net Exposure" in df.columns:
        df = df[df["Net Exposure"].abs() >= 1e-8]
    df = df[~df["Risk Factor"].astype(str).str.startswith(tuple(skip_prefixes))]
    if df.empty:
        fig.update_layout(**_base_layout(height=240))
        fig.add_annotation(text="No non-zero factor exposures found.", showarrow=False,
                            font={"color": TOKENS["muted"]})
        return fig

    n = len(df)
    df = df.copy()
    df["Target RC (%)"] = round(100.0 / n, 1) if n else 0.0
    df["Delta RC (%)"] = (df["Risk Contribution (%)"] - df["Target RC (%)"]).round(1)

    df = df.sort_values("Net Exposure", ascending=True)  # largest at top after reverse below
    factors = df["Risk Factor"].astype(str).tolist()
    net_exps = df["Net Exposure"].astype(float).tolist()
    rcs = df["Risk Contribution (%)"].astype(float).tolist()
    deltas = df["Delta RC (%)"].astype(float).tolist()
    colors = [_factor_bar_color(d) for d in deltas]

    sqrt_x = [math.sqrt(abs(v)) for v in net_exps]

    fig.add_trace(go.Bar(
        x=sqrt_x, y=factors, orientation="h",
        marker_color=colors, opacity=0.85,
        customdata=list(zip(net_exps, rcs, deltas)),
        text=[f"{v:.4f}" for v in net_exps], textposition="outside",
        textfont={"size": 9},
        hovertemplate="%{y}: NetExp %{customdata[0]:.4f} | RC %{customdata[1]:.1f}%% | "
                      "ΔRC %{customdata[2]:+.1f}%%<extra></extra>",
    ))

    tick_vals_actual = [0, 0.05, 0.1, 0.25, 0.5, 1.0, 1.4]
    tick_vals_sqrt = [math.sqrt(v) for v in tick_vals_actual]

    fig.update_layout(**_base_layout(
        height=max(220, n * 32 + 60),
        showlegend=False,
        margin={"t": 20, "b": 40, "l": 90, "r": 90},
    ))
    fig.update_xaxes(
        tickmode="array", tickvals=tick_vals_sqrt,
        ticktext=[str(v) for v in tick_vals_actual],
        title_text="√ scale",
    )
    fig.update_yaxes(automargin=True)

    for y, rc, delta, color in zip(factors, rcs, deltas, colors):
        fig.add_annotation(
            x=1.0, xref="paper", xanchor="left", y=y, yref="y",
            text=f"RC {rc:.1f}   <span style='color:{color}'>{delta:+.1f}</span>",
            showarrow=False, font={"size": 9, "color": TOKENS["muted"]},
            align="left", xshift=10,
        )
    return fig


def build_kpi_cards(net_pos: dict, kt_grid: dict, tenor_order: list[str]) -> dict:
    """Compute the 4 KPI values (Total Long / Total Short / Net Exposure / Total DV01)."""
    total_long = 0.0
    total_short = 0.0
    for e in net_pos.values():
        net = round(e.get("Beta", 0.0) + e.get("Alpha", 0.0), 4)
        if net > 0:
            total_long += net
        elif net < 0:
            total_short += abs(net)
    net_exposure = total_long - total_short
    total_dv01 = sum(
        sum(kt_grid[t].values()) for t in tenor_order
    )
    return {
        "long": total_long,
        "short": total_short,
        "net": net_exposure,
        "dv01": total_dv01,
    }


def build_kpi_strip(kpis: dict) -> html.Div:
    cards = [
        ("Total Long", f"+{kpis['long'] / 1000:.1f}k", TOKENS["green"], "MM notional, net long legs"),
        ("Total Short", f"-{kpis['short'] / 1000:.1f}k", TOKENS["amber"], "MM notional, net short legs"),
        ("Net Exposure", f"{'+' if kpis['net'] >= 0 else ''}{kpis['net'] / 1000:.1f}k", TOKENS["cyan"], "Beta + Alpha combined"),
        ("Total DV01", f"{kpis['dv01']:.2f}", TOKENS["blue"], "MM/bp aggregate sensitivity"),
    ]
    return html.Div([
        html.Div([
            html.Div(label, className="risk-kpi-label"),
            html.Div(value, className="risk-kpi-value", style={"color": color}),
            html.Div(sub, style={"fontSize": "11px", "color": TOKENS["muted"]}),
        ], className="risk-kpi-card")
        for label, value, color, sub in cards
    ], className="risk-kpi-strip")


def build_inventory_summary(beta_rows: list[dict], alpha_rows: list[dict]) -> html.Div:
    """Collapsed 3-column inventory view: Beta positions | Alpha positions | Capital by Sector."""

    def _row(label: str, value: str, dim: bool = False) -> html.Div:
        return html.Div([
            html.Span(label, style={"fontFamily": "var(--font-mono)", "fontSize": "12px",
                                     "color": TOKENS["muted"] if dim else TOKENS["text"]}),
            html.Span(value, style={"fontFamily": "var(--font-mono)", "fontSize": "12px",
                                     "color": TOKENS["muted"] if dim else TOKENS["text"]}),
        ], style={"display": "flex", "justifyContent": "space-between", "padding": "3px 0",
                  "borderBottom": f"1px solid {TOKENS['navy_800']}"})

    def _cap_mm(row: dict) -> float:
        try:
            return float(str(row.get("Capital (MM)", "0")).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    sector_totals: dict[str, float] = {}
    for row in beta_rows + alpha_rows:
        sector = row.get("Sector") or row.get("Leg1") or row.get("Name", "")
        sector_totals[sector] = sector_totals.get(sector, 0.0) + _cap_mm(row)
    sorted_sectors = sorted(sector_totals.items(), key=lambda kv: -abs(kv[1]))

    return html.Div([
        html.Div([
            html.Div(f"Beta Book — {len(beta_rows)} positions", style={
                "fontSize": "11px", "letterSpacing": "0.06em", "textTransform": "uppercase",
                "color": TOKENS["blue"], "marginBottom": "8px",
            }),
            *[_row(r.get("Name", ""), f"{_cap_mm(r):+,.0f}") for r in beta_rows],
        ]),
        html.Div([
            html.Div(f"Alpha Book — {len(alpha_rows)} positions", style={
                "fontSize": "11px", "letterSpacing": "0.06em", "textTransform": "uppercase",
                "color": TOKENS["amber"], "marginBottom": "8px",
            }),
            *[_row(r.get("Name", ""), f"{_cap_mm(r):+,.0f}", dim=abs(_cap_mm(r)) < 50) for r in alpha_rows],
        ]),
        html.Div([
            html.Div("Capital by Sector", style={
                "fontSize": "11px", "letterSpacing": "0.06em", "textTransform": "uppercase",
                "color": TOKENS["muted"], "marginBottom": "8px",
            }),
            *[_row(sec, f"{tot:+,.0f}") for sec, tot in sorted_sectors],
        ]),
    ], className="risk-inventory-summary-grid")
