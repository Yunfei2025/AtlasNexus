# -*- coding: utf-8 -*-
"""Stats-table renderers for the Seasonal Pattern card: episode-bucket
stats (BondNewIssue / OTR-OFR ladder promotions), TermBasis roll-cycle
stats, and the plain monthly seasonal stats table. Split out of the
~400-line _update_seasonal callback so each stats table is independently
readable and testable."""

from __future__ import annotations

from dash import html


def episode_bucket_stats_panel(bucket_stats) -> "html.Div":
    """Render an episode_bucket_stats() DataFrame as the Seasonal Pattern
    card's stats panel -- shared by every event-time (day-since-X) overlay
    branch of _update_seasonal (BondNewIssue, OFR-ladder RV, ...)."""
    if bucket_stats is None or bucket_stats.empty:
        return html.Div()
    _arrow = {"up": "↑", "down": "↓", "neutral": "—"}
    _dir_color = {"up": "#00cc96", "down": "#ef553b", "neutral": "#aab0c0"}
    header = html.Div([
        html.Span("Day",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
        html.Span("Dir",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
        html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
        html.Span("AvgΔ (bp)", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
        html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
        html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
    ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
               "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})
    rows = []
    for day, row in bucket_stats.iterrows():
        p = row["p_value"]
        sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
        dir_c = _dir_color[row["direction"]]
        rows.append(html.Div([
            html.Span(f"D+{day}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}),
            html.Span(f"{_arrow[row['direction']]}",
                      style={"fontSize": "11px", "color": dir_c, "minWidth": "16px"}),
            html.Span(f"{row['consistency']*100:.0f}%{sig}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
            html.Span(f"{row['avg_chg_bp']:+.2f}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
            html.Span(f"n={row['n_episodes']}", style={"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}),
            html.Span(f"p={p:.2f}", style={"fontSize": "11px", "color": "#aab0c0"}),
        ], style={"display": "flex", "gap": "12px", "padding": "2px 6px"}))
    note = html.Div(
        "* p<0.10  ** p<0.05  (one-sided binomial; no FDR correction applied)",
        style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
    )
    return html.Div([header] + rows + [note],
                     style={"background": "transparent", "borderRadius": "4px",
                            "padding": "6px 0", "marginBottom": "8px"})


def term_basis_roll_cycle_stats_panel(bucket_stats) -> "html.Div":
    """Render the TermBasis roll_cycle_bucket_stats() DataFrame, including
    the near-maturity convergence verdict banner."""
    if bucket_stats is None or bucket_stats.empty:
        return html.Div()
    try:
        _arrow = {"up": "↑", "down": "↓", "neutral": "—", "flat": "—", "n/a": "·"}
        _dir_color = {"up": "#00cc96", "down": "#ef553b", "neutral": "#aab0c0",
                      "flat": "#aab0c0", "n/a": "#aab0c0"}

        # Convergence verdict: does the near-maturity end (DTM<=45)
        # show a significant, directionally consistent pattern, or
        # is it noise? FYTM basis should converge toward 0 as the
        # front contract's remaining carry period shrinks -- but
        # this signal is duration-dependent (clean for T/TL,
        # frequently insignificant for TF/TS) and this badge makes
        # that visible per-ticker instead of requiring a read of
        # every row's p-value.
        _near_mat = bucket_stats[bucket_stats.index <= 45]
        _sig_near = _near_mat[_near_mat["p_value"] < 0.10]
        if _near_mat.empty:
            _verdict_text, _verdict_color = "Insufficient data near maturity", "#aab0c0"
        elif not _sig_near.empty:
            _verdict_text = f"Significant convergence near maturity (n={len(_sig_near)} bucket(s) p<0.10)"
            _verdict_color = "#00cc96"
        else:
            _verdict_text = "No significant convergence near maturity — treat as noise for this contract"
            _verdict_color = "#ef553b"
        verdict_banner = html.Div(
            _verdict_text,
            style={"fontSize": "10px", "color": _verdict_color, "fontWeight": "600",
                   "padding": "2px 6px 6px 6px"},
        )

        header = html.Div([
            html.Span("DTM",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
            html.Span("Sign",  style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
            html.Span("Trend", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
            html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
            html.Span("AvgLvl",style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
            html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
            html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
        ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
                   "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})
        rows = []
        for dtm_val, row in bucket_stats.iterrows():
            p = row["p_value"]
            sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
            sign_c = _dir_color[row["sign"]]
            trend_c = _dir_color[row["trend"]]
            rows.append(html.Div([
                html.Span(f"{dtm_val}d", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}),
                html.Span(f"{_arrow[row['sign']]}",
                          style={"fontSize": "11px", "color": sign_c, "minWidth": "16px"}),
                html.Span(f"{_arrow[row['trend']]}",
                          style={"fontSize": "11px", "color": trend_c, "minWidth": "16px"}),
                html.Span(f"{row['consistency']*100:.0f}%{sig}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
                html.Span(f"{row['avg_level']:+.2f}", style={"fontSize": "11px", "color": "#ffffff", "minWidth": "44px"}),
                html.Span(f"n={row['n_cycles']}", style={"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}),
                html.Span(f"p={p:.2f}", style={"fontSize": "11px", "color": "#aab0c0"}),
            ], style={"display": "flex", "gap": "12px", "padding": "2px 6px"}))
        note = html.Div(
            "Sign = avg level vs. 0 at this DTM.  Trend = change vs. the prior "
            "(farther-from-maturity) row, i.e. is it converging into the roll.  "
            "* p<0.10  ** p<0.05 (Sign only; one-sided binomial, no FDR correction).",
            style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
        )
        return html.Div([verdict_banner, header] + rows + [note],
                          style={"background": "transparent", "borderRadius": "4px",
                                 "padding": "6px 0", "marginBottom": "8px"})
    except Exception as e:
        print(f"[seasonal] TermBasis roll-cycle stats error: {e}")
        return html.Div()


def monthly_seasonal_stats_panel(stats, highlight_month) -> "html.Div":
    """Render the plain monthly_seasonal_stats() DataFrame used by every
    calendar-year overlay (non-episode, non-roll-cycle) spread type."""
    if stats is None or stats.empty:
        return html.Div()
    try:
        _arrow = {"up": "↑", "down": "↓", "neutral": "—"}
        _dir_color = {
            "up":      "#00cc96",
            "down":    "#ef553b",
            "neutral": "#aab0c0",
        }
        rows = []
        for month, row in stats.iterrows():
            p = row["p_value"]
            sig = "**" if p < 0.05 else ("*" if p < 0.10 else "")
            is_hl = (highlight_month and int(month) == int(highlight_month))
            row_style = {
                "background": "#1a3a7a" if is_hl else "transparent",
                "display": "flex",
                "gap": "12px",
                "padding": "2px 6px",
                "borderRadius": "3px",
            }
            cell_style = {"fontSize": "11px", "color": "#ffffff", "minWidth": "34px"}
            sub_style  = {"fontSize": "11px", "color": "#aab0c0", "minWidth": "34px"}
            dir_c = _dir_color[row["direction"]]
            rows.append(html.Div([
                html.Span(row["month_name"], style={**cell_style, "minWidth": "28px"}),
                html.Span(
                    f"{_arrow[row['direction']]}",
                    style={**cell_style, "color": dir_c, "minWidth": "16px"}
                ),
                html.Span(f"{row['consistency']*100:.0f}%{sig}", style={**cell_style, "minWidth": "44px"}),
                html.Span(f"{row['avg_chg_bp']:+.1f}", style={**cell_style, "minWidth": "44px"}),
                html.Span(f"n={row['n_years']}", style={**sub_style}),
                html.Span(f"p={p:.2f}", style={**sub_style}),
            ], style=row_style))

        header = html.Div([
            html.Span("Month", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "28px"}),
            html.Span("Dir",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "16px"}),
            html.Span("Cons%", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
            html.Span("AvgΔ (bp)", style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "44px"}),
            html.Span("Obs",   style={"fontSize": "10px", "color": "#8fb3d9", "minWidth": "34px"}),
            html.Span("p-val", style={"fontSize": "10px", "color": "#8fb3d9"}),
        ], style={"display": "flex", "gap": "12px", "padding": "2px 6px",
                   "borderBottom": "1px solid #1a3a7a", "marginBottom": "2px"})

        note = html.Div(
            "* p<0.10  ** p<0.05  (one-sided binomial; no FDR correction applied)",
            style={"fontSize": "9px", "color": "#8fb3d9", "marginTop": "4px", "padding": "0 6px"},
        )
        return html.Div([header] + rows + [note],
                          style={"background": "transparent", "borderRadius": "4px",
                                 "padding": "6px 0", "marginBottom": "8px"})
    except Exception as e:
        print(f"[seasonal] stats table error: {e}")
        return html.Div()
