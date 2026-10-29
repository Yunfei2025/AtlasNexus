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

from web.tabs.ui.styles import PLOTLY_LAYOUT_DEFAULTS, TOKENS

_NET_BETA_ONLY = TOKENS["blue"]       # pure beta -> blue
_NET_ALPHA_LONG = TOKENS["amber"]     # pure alpha long -> amber
_NET_ALPHA_SHORT = TOKENS["red"]      # pure alpha short -> red
_NET_MIXED_LONG = "#41b078"           # mixed long -> green
_NET_MIXED_SHORT = TOKENS["red"]

_DV01_BONDS = TOKENS["blue"]
_DV01_SWAPS = TOKENS["cyan"]
_DV01_FUTURES = TOKENS["amber"]
_DV01_LADDER_HOVER = "%{x} %{fullData.name}: %{y:+,.2f} MM/bp<extra></extra>"

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


def build_net_position_fig(net_pos: dict, top_n: int | None = None) -> go.Figure:
    """Diverging horizontal bar chart of net position by instrument.

    `net_pos` is the dict built in update_risk_tables:
    {code: {'Beta': mm, 'Alpha': mm, 'DV01': mm_per_bp}}.
    """
    rows = []
    for code, e in net_pos.items():
        beta, alpha = e.get("Beta", 0.0), e.get("Alpha", 0.0)
        net = round(beta + alpha, 4)
        dv01 = round(
            e.get("DV01", e.get("BetaDV01", 0.0) + e.get("AlphaDV01", 0.0)),
            4,
        )
        if abs(net) < 1e-6 and abs(beta) < 1e-6 and abs(alpha) < 1e-6:
            continue
        rows.append({"inst": code, "beta": beta, "alpha": alpha, "net": net, "dv01": dv01})

    # Sort instruments by name for a stable lexical scan in the dashboard.
    rows.sort(key=lambda r: str(r["inst"]).upper())
    if isinstance(top_n, int) and top_n > 0:
        rows = rows[:top_n]

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
        customdata=[[r["dv01"]] for r in rows],
        text=text, textposition="outside",
        textfont={"color": TOKENS["text"], "size": 10},
        hovertemplate="%{y}: %{x:+,.1f} MM | DV01 %{customdata[0]:+,.2f} MM/bp<extra></extra>",
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


def build_substituted_position_fig(net_pos: dict, subs: list[dict]) -> go.Figure:
    """Combined net position after short-constraint substitution.

    Each disallowed net short (``subs`` from build_short_substitutions) is
    moved to its DV01-matched substitutes; credit shorts with no substitute
    stay. Instruments the substitution changes show the strategy net as a
    faint ghost bar behind the executable bar (cyan).
    """
    strat = {str(c): (e.get("Beta", 0.0) + e.get("Alpha", 0.0),
                      e.get("BetaDV01", 0.0) + e.get("AlphaDV01", 0.0))
             for c, e in net_pos.items()}
    exe = {c: list(v) for c, v in strat.items()}
    changed: set[str] = set()
    for r in subs:
        if not r["substitutes"]:
            continue
        exe[r["code"]] = [0.0, 0.0]
        changed.add(r["code"])
        for s in r["substitutes"]:
            e = exe.setdefault(s["code"], [0.0, 0.0])
            e[0] += s["notional_mm"]
            e[1] += s["dv01"]
            changed.add(s["code"])

    rows = []
    for code, (net, dv01) in exe.items():
        s_net = strat.get(code, (0.0, 0.0))[0]
        if abs(net) < 1e-6 and abs(s_net) < 1e-6:
            continue
        beta = net_pos.get(code, {}).get("Beta", 0.0)
        rows.append({"inst": code, "net": net, "dv01": dv01, "strat": s_net,
                     "changed": code in changed,
                     "color": TOKENS["cyan"] if code in changed
                     else _net_pos_bar_color(beta, net - beta, net)})
    rows.sort(key=lambda r: str(r["inst"]).upper())

    fig = go.Figure()
    if not rows:
        fig.update_layout(**_base_layout(height=320))
        fig.add_annotation(text="No netted positions found.", showarrow=False,
                           font={"color": TOKENS["muted"]})
        return fig

    insts = [r["inst"] for r in rows]
    ghost = [r for r in rows if r["changed"]]
    fig.add_trace(go.Bar(
        x=[r["strat"] for r in ghost], y=[r["inst"] for r in ghost], orientation="h",
        name="Strategy (before substitution)",
        marker={"color": "rgba(164,182,210,0.18)", "line": {"color": TOKENS["muted"], "width": 1}},
        hovertemplate="%{y} strategy: %{x:+,.1f} MM<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=[r["net"] for r in rows], y=insts, orientation="h",
        name="Executable", marker_color=[r["color"] for r in rows], opacity=0.88,
        customdata=[[r["dv01"], r["strat"]] for r in rows],
        text=[f"{'+' if r['net'] > 0 else ''}{r['net']:,.0f}" if abs(r["net"]) > 1e-6 else "moved"
              for r in rows],
        textposition="outside", textfont={"color": TOKENS["text"], "size": 10},
        hovertemplate=("%{y}: %{x:+,.1f} MM executable | strategy %{customdata[1]:+,.1f}"
                       " | DV01 %{customdata[0]:+,.2f} MM/bp<extra></extra>"),
    ))
    fig.update_layout(**_base_layout(
        height=max(320, len(rows) * 26 + 80),
        barmode="overlay", bargap=0.35,
        showlegend=True,
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "font": {"size": 10}},
        margin={"t": 30, "b": 30, "l": 90, "r": 40},
    ))
    fig.update_xaxes(zeroline=True, zerolinewidth=1.5, title_text="MM CNY")
    fig.update_yaxes(automargin=True)
    return fig


def build_gross_position_fig(gross: dict) -> go.Figure:
    """GROSS view of the position by instrument: long and short capital kept apart, never netted.

    `gross` is {code: {'Long': mm >= 0, 'Short': mm <= 0, 'DV01Long': mm/bp, 'DV01Short': mm/bp}}.
    Long extends right, short extends left; the hover gives gross (long + |short|) and net."""
    rows = []
    for code, e in gross.items():
        lo, sh = float(e.get("Long", 0.0)), float(e.get("Short", 0.0))
        if abs(lo) < 1e-6 and abs(sh) < 1e-6:
            continue
        dv01_g = abs(float(e.get("DV01Long", 0.0))) + abs(float(e.get("DV01Short", 0.0)))
        rows.append({"inst": code, "long": lo, "short": sh, "gross": lo + abs(sh), "net": lo + sh, "dv01_g": dv01_g})
    rows.sort(key=lambda r: str(r["inst"]).upper())

    fig = go.Figure()
    if not rows:
        fig.update_layout(**_base_layout(height=320))
        fig.add_annotation(text="No positions found.", showarrow=False, font={"color": TOKENS["muted"]})
        return fig

    insts = [r["inst"] for r in rows]
    hover = [[r["gross"], r["net"], r["dv01_g"]] for r in rows]
    tmpl = "%{y}: %{x:+,.1f} MM | gross %{customdata[0]:,.1f} · net %{customdata[1]:+,.1f} | gross DV01 %{customdata[2]:.2f} MM/bp<extra></extra>"
    fig.add_trace(go.Bar(
        name="Long", x=[r["long"] for r in rows], y=insts, orientation="h", marker_color=TOKENS["green"], opacity=0.88,
        text=[f"{r['long']:+,.0f}" if abs(r["long"]) > 1e-6 else "" for r in rows], textposition="outside",
        textfont={"color": TOKENS["text"], "size": 10}, customdata=hover, hovertemplate=tmpl,
    ))
    fig.add_trace(go.Bar(
        name="Short", x=[r["short"] for r in rows], y=insts, orientation="h", marker_color=TOKENS["amber"], opacity=0.88,
        text=[f"{r['short']:+,.0f}" if abs(r["short"]) > 1e-6 else "" for r in rows], textposition="outside",
        textfont={"color": TOKENS["text"], "size": 10}, customdata=hover, hovertemplate=tmpl,
    ))
    fig.update_layout(**_base_layout(
        height=max(320, len(rows) * 26 + 60), bargap=0.35, barmode="relative", showlegend=True,
        legend={**PLOTLY_LAYOUT_DEFAULTS["legend"], "orientation": "h", "y": 1.04, "x": 0.5, "xanchor": "center"},
        margin={"t": 30, "b": 30, "l": 90, "r": 40},
    ))
    fig.update_xaxes(zeroline=True, zerolinewidth=1.5, title_text="MM CNY (long right, short left)")
    fig.update_yaxes(automargin=True)
    return fig


def build_dv01_ladder_gross_fig(kt_long: dict, kt_short: dict, tenor_order: list[str]) -> go.Figure:
    """GROSS DV01 ladder: long DV01 stacks up, short DV01 stacks down, per tenor and bucket.
    The label above each tenor shows gross (long + |short|) and net."""
    tenors = [t for t in tenor_order if t in kt_long or t in kt_short]
    fig = go.Figure()

    def side(grid, t, col):
        return float(grid.get(t, {}).get(col, 0.0))

    has_any = any(abs(side(g, t, c)) > 1e-8 for t in tenors for g in (kt_long, kt_short)
                  for c in ("Bonds", "Swaps", "Futures", "Other"))
    if not tenors or not has_any:
        fig.update_layout(**_base_layout(height=290))
        fig.add_annotation(text="No rate positions found.", showarrow=False, font={"color": TOKENS["muted"]})
        return fig

    colors = {"Bonds": _DV01_BONDS, "Swaps": _DV01_SWAPS, "Futures": _DV01_FUTURES}
    for col, color in colors.items():
        fig.add_trace(go.Bar(name=f"{col} long", legendgroup=col, x=tenors, y=[side(kt_long, t, col) for t in tenors],
                             marker_color=color, opacity=0.9, hovertemplate=_DV01_LADDER_HOVER))
        fig.add_trace(go.Bar(name=f"{col} short", legendgroup=col, x=tenors, y=[side(kt_short, t, col) for t in tenors],
                             marker_color=color, opacity=0.5, marker_pattern_shape="/",
                             hovertemplate=_DV01_LADDER_HOVER))
    fig.update_layout(**_base_layout(
        height=290, barmode="relative", bargap=0.36,
        legend={**PLOTLY_LAYOUT_DEFAULTS["legend"], "orientation": "h", "y": -0.22, "x": 0.5, "xanchor": "center"},
        margin={"t": 30, "b": 40, "l": 44, "r": 16},
    ))
    fig.update_yaxes(title_text="MM/bp (long up, short down)")
    for t in tenors:
        lo = sum(max(side(kt_long, t, c), 0.0) for c in ("Bonds", "Swaps", "Futures", "Other"))
        sh = sum(min(side(kt_short, t, c), 0.0) for c in ("Bonds", "Swaps", "Futures", "Other"))
        if abs(lo) + abs(sh) < 1e-8:
            continue
        fig.add_annotation(x=t, y=lo, text=f"gross {lo + abs(sh):.2f}<br>net {lo + sh:+.2f}", showarrow=False,
                           yshift=14, font={"size": 9, "color": TOKENS["muted"]})
    return fig


def build_dv01_ladder_fig(kt_grid: dict, tenor_order: list[str]) -> go.Figure:
    """Stacked vertical bar chart: DV01 (MM/bp) by tenor, split Bonds/Swaps/Futures."""
    tenors = [t for t in tenor_order if t in kt_grid]
    has_any_rate_position = any(
        any(abs(v) > 1e-8 for v in kt_grid[t].values())
        for t in tenors
    )

    fig = go.Figure()
    if not tenors or not has_any_rate_position:
        fig.update_layout(**_base_layout(height=290))
        fig.add_annotation(text="No rate positions found.", showarrow=False,
                            font={"color": TOKENS["muted"]})
        return fig

    bonds = [kt_grid[t]["Bonds"] for t in tenors]
    swaps = [kt_grid[t]["Swaps"] for t in tenors]
    futures = [kt_grid[t]["Futures"] for t in tenors]
    totals = [round(kt_grid[t]["Bonds"] + kt_grid[t]["Swaps"] + kt_grid[t]["Futures"]
                     + kt_grid[t]["Other"], 4) for t in tenors]

    fig.add_trace(go.Bar(name="Bonds", x=tenors, y=bonds, marker_color=_DV01_BONDS, opacity=0.9,
                         hovertemplate=_DV01_LADDER_HOVER))
    fig.add_trace(go.Bar(name="Swaps", x=tenors, y=swaps, marker_color=_DV01_SWAPS, opacity=0.9,
                         hovertemplate=_DV01_LADDER_HOVER))
    fig.add_trace(go.Bar(name="Futures", x=tenors, y=futures, marker_color=_DV01_FUTURES, opacity=0.9,
                         hovertemplate=_DV01_LADDER_HOVER))

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
        fig.add_annotation(x=t, y=total, text=f"{total:.2f}", showarrow=False,
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
        fig.add_annotation(text="No stored Beta book — Add to Portfolio on the Beta tab first.", showarrow=False,
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


def build_kpi_cards(net_pos: dict, kt_grid: dict, tenor_order: list[str], kt_split: dict | None = None) -> dict:
    """Compute the 4 KPI values (Total Long / Total Short / Net Exposure / Total DV01).
    `kt_split` ({book: {'long'|'short': {tenor: {col: dv01}}}}) adds the GROSS DV01 (long + |short|)."""
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
    out = {
        "long": total_long,
        "short": total_short,
        "net": net_exposure,
        "dv01": total_dv01,
    }
    if kt_split:
        out["gross_dv01"] = sum(abs(v) for book in kt_split.values() for sd in book.values()
                                for t in tenor_order for v in sd.get(t, {}).values())
    return out


def build_kpi_strip(kpis: dict) -> html.Div:
    cards = [
        ("Total Long", f"+{kpis['long'] / 1000:.1f}k", TOKENS["green"], "MM notional, net long legs"),
        ("Total Short", f"-{kpis['short'] / 1000:.1f}k", TOKENS["amber"], "MM notional, net short legs"),
        ("Net Exposure", f"{'+' if kpis['net'] >= 0 else ''}{kpis['net'] / 1000:.1f}k", TOKENS["cyan"], "Beta + Alpha combined"),
        ("Total DV01", f"{kpis['dv01']:.2f}", TOKENS["blue"],
         "MM/bp net" + (f" · gross {kpis['gross_dv01']:.2f}" if "gross_dv01" in kpis else " aggregate sensitivity")),
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
    """Collapsed 3-column inventory view: Beta positions | Alpha positions | Capital by Sector
    (long / short per sector, never netted)."""

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

    # Long and short per sector are kept apart - never netted: a short 10Y must not shrink the
    # capital shown for the Rates sector (only longs use capital).
    sector_totals: dict[str, list[float]] = {}
    for row in beta_rows + alpha_rows:
        sector = row.get("Sector") or row.get("Leg1") or row.get("Name", "")
        long_short = sector_totals.setdefault(sector, [0.0, 0.0])
        cap = _cap_mm(row)
        long_short[0 if cap >= 0 else 1] += cap
    sorted_sectors = sorted(sector_totals.items(), key=lambda kv: -(kv[1][0] + abs(kv[1][1])))

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
            *[_row(sec, f"{ls[0]:+,.0f}" + (f" / {ls[1]:+,.0f}" if ls[1] else "")) for sec, ls in sorted_sectors],
        ]),
    ], className="risk-inventory-summary-grid")


def build_short_substitution_panel(rows: list[dict]) -> html.Div:
    """Note + table under Position by Instrument: disallowed net shorts in the
    combined book and the DV01-matched substitutes they are executed with
    (see web/tabs/risk/short_substitution.py)."""
    mono = {"fontFamily": "var(--font-mono)", "fontSize": "12px"}
    cell = {**mono, "padding": "4px 8px", "borderBottom": f"1px solid {TOKENS['navy_800']}"}
    head = {"fontSize": "11px", "letterSpacing": "0.06em", "textTransform": "uppercase",
            "color": TOKENS["muted"], "padding": "4px 8px", "textAlign": "left"}

    note = html.Div([
        html.Span("Short constraint · ", style={"color": TOKENS["amber"], "fontWeight": "bold"}),
        html.Span("cash bonds are shorted only in CGB 5Y / 10Y / 30Y. Positions above are the strategy "
                  "as backtested; any other bond the combined book holds net short is executed as a "
                  "DV01-matched substitute (5Y+ → CGB 5/10/30, 1–3Y → pay FR007). Only the netted "
                  "residual is substituted. Backtest: alpha Sharpe 3.20 → 2.85 (2022-03 onward), "
                  "max drawdown unchanged."),
    ], style={"fontSize": "11px", "color": TOKENS["muted"], "lineHeight": "1.5", "marginBottom": "8px"})

    if not rows:
        return html.Div([note, html.Div("No disallowed net shorts — nothing to substitute.",
                                        style={"fontSize": "12px", "color": TOKENS["green"]})],
                        style={"marginTop": "12px"})

    body = []
    orders: dict[str, list[float]] = {}
    for r in rows:
        subs = r["substitutes"]
        sub_txt = " + ".join(f"{s['code']} {s['notional_mm']:+,.0f}" for s in subs) if subs else "—"
        for s in subs:
            o = orders.setdefault(s["code"], [0.0, 0.0])
            o[0] += s["notional_mm"]
            o[1] += s["dv01"]
        flag = TOKENS["red"] if not subs else TOKENS["text"]
        body.append(html.Tr([
            html.Td(r["code"], style={**cell, "color": flag}),
            html.Td(r["bond"], style={**cell, "color": TOKENS["muted"]}),
            html.Td(f"{r['net_mm']:+,.0f}", style={**cell, "textAlign": "right", "color": TOKENS["red"]}),
            html.Td(f"{r['dv01']:+.3f}", style={**cell, "textAlign": "right"}),
            html.Td(sub_txt, style={**cell, "color": TOKENS["cyan"] if subs else TOKENS["red"]}),
            html.Td(r["note"], style={**cell, "color": TOKENS["muted"]}),
        ]))

    table = html.Table([
        html.Thead(html.Tr([html.Th(h, style={**head, "textAlign": "right" if h in ("Net (MM)", "DV01") else "left"})
                            for h in ("Instrument", "Bond", "Net (MM)", "DV01", "Execute as (MM)", "")])),
        html.Tbody(body),
    ], style={"width": "100%", "borderCollapse": "collapse"})

    order_line = html.Div(
        "Substitute orders: " + " · ".join(f"{code} {n:+,.0f}MM ({d:+.3f}/bp)"
                                           for code, (n, d) in sorted(orders.items())),
        style={**mono, "color": TOKENS["cyan"], "marginTop": "8px"},
    ) if orders else None

    return html.Div([note, html.Div(table, style={"overflowX": "auto"}), order_line],
                    style={"marginTop": "12px", "paddingTop": "10px",
                           "borderTop": f"1px solid {TOKENS['navy_700']}"})
