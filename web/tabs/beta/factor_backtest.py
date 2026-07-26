"""Factor Model Backtest tab for embedding in AtlasNexus Beta Book.

Adapts factors/dashboard.py content to the Atlas dark-blue theme and
provides build_factor_model_backtest_layout() + register_factor_backtest_callbacks(app).
"""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

from factors.config import config_manager
from factors.engine.factor_engine import run_analysis
from factors.processing.loader import getDailyTS

# ── Theme (Atlas dark-blue palette) ─────────────────────────────────────────
THEME = {
    "bg": "#082255",
    "panel": "#0c2b64",
    "panel_alt": "#112e66",
    "border": "#1a3a7a",
    "text": "#ffffff",
    "muted": "#aab0c0",
    "accent": "#3498db",
    "success": "#00cc96",
    "warning": "#f39c12",
    "danger": "#ef553b",
    "chart_template": "plotly_dark",
}

SUPPORTED_TICKERS: list[dict[str, Any]] = [
    {"label": "T.CFE (10Y Treasury Future)", "value": "T.CFE"},
    {"label": "TF.CFE (5Y Treasury Future)", "value": "TF.CFE"},
    {"label": "TS.CFE (2Y Treasury Future)", "value": "TS.CFE"},
    {"label": "TL.CFE (30Y Treasury Future)", "value": "TL.CFE"},
    {"label": "Pair: T.CFE - TS.CFE", "value": "Pair:T.CFE-TS.CFE"},
    {"label": "Fly: TS.CFE - TF.CFE - T.CFE", "value": "Fly:TS.CFE-TF.CFE-T.CFE"},
]

# ── Job Management ──────────────────────────────────────────────────────────
JOB_LOCK = threading.Lock()
JOB_STATE: dict[str, dict[str, Any]] = {}


def _default_dates() -> tuple[str, str]:
    date_config = config_manager.date_config
    end_date = date_config.day_data_end_date
    try:
        ticker = config_manager.model_config.ticker
        data = getDailyTS(ticker)
        if data is not None and not data.empty:
            end_date = pd.Timestamp(data.index.max()).strftime("%Y-%m-%d")
    except Exception:
        pass
    return date_config.day_data_start_date, end_date


def _start_job(start_date: str, end_date: str, ticker: str) -> str:
    job_id = uuid.uuid4().hex
    with JOB_LOCK:
        JOB_STATE[job_id] = {
            "status": "queued",
            "message": "Queued",
            "submitted_at": datetime.now(),
            "start_date": start_date,
            "end_date": end_date,
            "ticker": ticker,
            "result": None,
            "error": None,
        }

    def _worker() -> None:
        with JOB_LOCK:
            JOB_STATE[job_id]["status"] = "running"
            JOB_STATE[job_id]["message"] = "Running factor backtest…"
            JOB_STATE[job_id]["started_at"] = datetime.now()
        try:
            result = run_analysis(
                start_date=start_date,
                end_date=end_date,
                ticker=ticker,
                num_cores=1,
            )
            with JOB_LOCK:
                if result is None or getattr(result, "status", "failed") != "completed":
                    JOB_STATE[job_id]["status"] = "failed"
                    JOB_STATE[job_id]["message"] = "Backtest failed"
                    JOB_STATE[job_id]["error"] = "Factor engine returned no completed result."
                else:
                    JOB_STATE[job_id]["status"] = "completed"
                    JOB_STATE[job_id]["message"] = "Backtest completed"
                    JOB_STATE[job_id]["result"] = result
                JOB_STATE[job_id]["finished_at"] = datetime.now()
        except Exception as exc:
            with JOB_LOCK:
                JOB_STATE[job_id]["status"] = "failed"
                JOB_STATE[job_id]["message"] = "Backtest failed"
                JOB_STATE[job_id]["error"] = f"{exc}\n\n{traceback.format_exc()}"
                JOB_STATE[job_id]["finished_at"] = datetime.now()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return job_id


# ── Helper formatters ───────────────────────────────────────────────────────

def _format_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "N/A"


def _format_num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "N/A"


def _to_series(values: Any) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    if isinstance(values, pd.DataFrame):
        if values.empty:
            return pd.Series(dtype=float)
        if values.shape[1] == 1:
            series = values.iloc[:, 0]
        else:
            series = values.sum(axis=1)
        return pd.to_numeric(series, errors="coerce").dropna()
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce").dropna()
    try:
        series = pd.Series(values)
        return pd.to_numeric(series, errors="coerce").dropna()
    except Exception:
        return pd.Series(dtype=float)


# ── Chart / card builders (Atlas-themed) ────────────────────────────────────

def _make_line_figure(series: pd.Series, title: str, color: str) -> go.Figure:
    fig = go.Figure()
    if not series.empty:
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                line={"color": color, "width": 2},
                name=title,
            )
        )
    fig.update_layout(
        title=title,
        paper_bgcolor=THEME["panel"],
        plot_bgcolor=THEME["panel"],
        font={"color": THEME["text"]},
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
        height=300,
    )
    fig.update_xaxes(gridcolor=THEME["border"])
    fig.update_yaxes(gridcolor=THEME["border"])
    return fig


def _metric_card(label: str, value: str) -> html.Div:
    return html.Div(
        [
            html.Div(label, style={"fontSize": "12px", "color": THEME["muted"], "marginBottom": "6px"}),
            html.Div(value, style={"fontSize": "22px", "fontWeight": "700", "color": THEME["text"]}),
        ],
        style={
            "backgroundColor": THEME["panel_alt"],
            "border": f"1px solid {THEME['border']}",
            "borderRadius": "10px",
            "padding": "14px 16px",
            "minWidth": "160px",
            "flex": "1",
        },
    )


def _build_period_table(results: Any) -> html.Div:
    rows = []
    for period in getattr(results, "period_results", []):
        factors = ", ".join((period.selected_factors or [])[:5])
        if period.selected_factors and len(period.selected_factors) > 5:
            factors += " …"
        rows.append(
            html.Tr(
                [
                    html.Td(period.month),
                    html.Td(period.status),
                    html.Td(len(period.selected_factors or [])),
                    html.Td(factors or "-"),
                    html.Td((period.error or "")[:120]),
                ]
            )
        )

    td_style = {"padding": "6px 10px", "borderBottom": f"1px solid {THEME['border']}"}
    th_style = {**td_style, "fontWeight": "600", "backgroundColor": THEME["panel_alt"]}

    return html.Div(
        [
            html.H4("Period Results", style={"color": THEME["text"], "marginBottom": "12px"}),
            html.Table(
                [
                    html.Thead(
                        html.Tr([
                            html.Th("Period", style=th_style),
                            html.Th("Status", style=th_style),
                            html.Th("# Factors", style=th_style),
                            html.Th("Selected Factors", style=th_style),
                            html.Th("Error", style=th_style),
                        ])
                    ),
                    html.Tbody(rows or [html.Tr([html.Td("No period results", colSpan=5, style=td_style)])]),
                ],
                style={"width": "100%", "borderCollapse": "collapse", "color": THEME["text"]},
            ),
        ],
        style={
            "backgroundColor": THEME["panel"],
            "border": f"1px solid {THEME['border']}",
            "borderRadius": "12px",
            "padding": "16px",
            "marginTop": "18px",
            "overflowX": "auto",
        },
    )


def _build_top_alpha_features(results: Any) -> html.Div | None:
    """Build a 'Top Driving Signals' panel from feature frequency across walk-forward periods."""
    from collections import Counter
    counter: Counter = Counter()
    for period in getattr(results, "period_results", []):
        for feat in (getattr(period, "selected_factors", None) or []):
            counter[feat] += 1
    if not counter:
        return None

    top = counter.most_common(8)
    n_periods = sum(1 for p in getattr(results, "period_results", [])
                    if getattr(p, "status", "") == "success")
    n_periods = max(n_periods, 1)

    _td = {"padding": "6px 12px", "fontSize": "12px", "color": THEME["text"]}
    _th = {**_td, "color": THEME["muted"], "fontWeight": "600",
           "borderBottom": f"1px solid {THEME['border']}"}

    rows = []
    for rank, (feat, cnt) in enumerate(top, 1):
        pct = cnt / n_periods
        bar_w = f"{max(4, int(pct * 100))}%"
        rows.append(html.Tr([
            html.Td(str(rank), style={**_td, "color": THEME["muted"]}),
            html.Td(feat, style={**_td, "fontFamily": "monospace", "color": THEME["accent"]}),
            html.Td(str(cnt), style=_td),
            html.Td(
                html.Div(
                    html.Div(style={"height": "8px", "width": bar_w,
                                    "backgroundColor": THEME["accent"],
                                    "borderRadius": "3px"}),
                    style={"width": "120px"}
                ),
                style=_td,
            ),
            html.Td(f"{pct:.0%}", style=_td),
        ]))

    return html.Div([
        html.H5("Top Driving Signals",
                style={"color": THEME["accent"], "marginBottom": "6px", "fontSize": "14px"}),
        html.P(
            "Indicators most frequently selected by the walk-forward model to predict returns "
            "(selection frequency across successful periods ≈ indicator consistency).",
            style={"color": THEME["muted"], "fontSize": "11px", "marginBottom": "10px",
                   "fontStyle": "italic"},
        ),
        html.Table([
            html.Thead(html.Tr([
                html.Th("#",           style=_th),
                html.Th("Indicator",   style=_th),
                html.Th("Count",       style=_th),
                html.Th("Consistency", style=_th),
                html.Th("%",           style=_th),
            ])),
            html.Tbody(rows),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
    ], style={
        "backgroundColor": THEME["panel"],
        "border": f"1px solid {THEME['border']}",
        "borderRadius": "10px",
        "padding": "14px 16px",
        "marginBottom": "16px",
    })


def _build_results_layout(results: Any, ticker: str, start_date: str, end_date: str) -> html.Div:
    metrics       = getattr(results, "backtest_metrics", None)
    backtest_data = getattr(results, "backtest_data",   None)

    cumulative_returns = _to_series(getattr(backtest_data, "cumulative_returns", None))
    strategy_returns   = _to_series(getattr(backtest_data, "strategy_returns",   None))
    predictions        = _to_series(getattr(backtest_data, "predictions",        None))
    positions          = _to_series(getattr(backtest_data, "positions",          None))

    # ── Compute IC statistics & current signal state ─────────────────────────
    mean_ic = ic_std = icir = ic_hit = ic_tstat = 0.0
    z_score = scalar = 0.0
    last_signal = 0
    ic_rolling = pd.Series(dtype=float)

    if not predictions.empty and not strategy_returns.empty:
        # IC = rolling 60-day corr(prediction_t, actual_return_{t+1})
        # 60-day (≈3 months) is the practitioner-standard window: reduces noise
        # without sacrificing signal timeliness.
        actual_fwd = strategy_returns.shift(-1).reindex(predictions.index)
        ic_rolling = predictions.rolling(60).corr(actual_fwd).dropna()
        if len(ic_rolling) > 0:
            mean_ic  = float(ic_rolling.mean())
            ic_std   = float(ic_rolling.std()) if len(ic_rolling) > 1 else 1.0
            icir     = mean_ic / (ic_std + 1e-8)
            ic_hit   = float((ic_rolling > 0).mean())
            n_ic     = len(ic_rolling)
            ic_tstat = mean_ic / (ic_std / (n_ic ** 0.5) + 1e-8) if n_ic > 1 else 0.0

        last_pred_val = float(predictions.iloc[-1])
        pred_hist     = predictions.tail(252)
        z_score = ((last_pred_val - pred_hist.mean()) / (pred_hist.std() + 1e-8)
                   if len(pred_hist) > 5 else 0.0)
        scalar = max(0.5, min(2.0, abs(z_score)))

    if not positions.empty:
        last_signal = int(round(float(positions.iloc[-1])))

    if   last_signal ==  1: dir_label, dir_color = "⬆ LONG",    THEME["success"]
    elif last_signal == -1: dir_label, dir_color = "⬇ SHORT",   THEME["danger"]
    else:                   dir_label, dir_color = "⏸ NEUTRAL", THEME["muted"]

    if   abs(icir) >= 0.50: conf, conf_color = "HIGH",   THEME["success"]
    elif abs(icir) >= 0.25: conf, conf_color = "MEDIUM", THEME["warning"]
    else:                   conf, conf_color = "LOW",     THEME["danger"]

    # ── Section 1: Summary cards + Current Signal State ──────────────────────
    signal_card = html.Div([
        html.Div("Current Signal",
                 style={"fontSize": "11px", "color": THEME["muted"], "marginBottom": "6px",
                        "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div(dir_label,
                 style={"fontSize": "20px", "fontWeight": "800", "color": dir_color,
                        "marginBottom": "8px"}),
        html.Div([
            html.Span("Z  ",     style={"color": THEME["muted"], "fontSize": "11px"}),
            html.Span(f"{z_score:+.2f}",
                      style={"color": THEME["text"], "fontSize": "12px", "fontWeight": "600"}),
        ], style={"marginBottom": "3px"}),
        html.Div([
            html.Span("Scale  ", style={"color": THEME["muted"], "fontSize": "11px"}),
            html.Span(f"{scalar:.1f}×",
                      style={"color": THEME["accent"], "fontSize": "12px", "fontWeight": "600"}),
        ], style={"marginBottom": "3px"}),
        html.Div([
            html.Span("ICIR  ",  style={"color": THEME["muted"], "fontSize": "11px"}),
            html.Span(f"{icir:.2f}",
                      style={"color": conf_color, "fontSize": "12px", "fontWeight": "600"}),
        ], style={"marginBottom": "3px"}),
        html.Div(f"Conf: {conf}",
                 style={"fontSize": "11px", "color": conf_color, "fontWeight": "700",
                        "marginTop": "4px"}),
    ], style={
        "backgroundColor": THEME["panel"],
        "border":          f"2px solid {dir_color}",
        "borderRadius":    "10px",
        "padding":         "14px 16px",
        "minWidth":        "160px",
        "flex":            "1",
    })

    metric_cards = html.Div(
        [
            _metric_card("Ticker",       ticker),
            _metric_card("Period",       f"{start_date} → {end_date}"),
            _metric_card("Total Return", _format_pct(getattr(metrics, "total_return", None))),
            _metric_card("Sharpe",       _format_num(getattr(metrics, "sharpe_ratio", None))),
            _metric_card("Volatility",   _format_pct(getattr(metrics, "volatility",   None))),
            _metric_card("Max Drawdown", _format_pct(getattr(metrics, "max_drawdown", None))),
            signal_card,
        ],
        style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "18px"},
    )

    # ── Section 2: IC & Signal Statistics table ───────────────────────────────
    _td = {"padding": "7px 14px", "textAlign": "center", "fontSize": "12px",
           "color": THEME["text"]}
    _th = {**_td, "color": THEME["muted"], "fontWeight": "600",
           "borderBottom": f"1px solid {THEME['border']}"}

    ic_table_div = html.Div([
        html.H5("IC & Signal Statistics",
                style={"color": THEME["accent"], "marginBottom": "10px", "fontSize": "14px"}),
        html.Table([
            html.Thead(html.Tr([
                html.Th("Mean IC",   style=_th),
                html.Th("IC Std",    style=_th),
                html.Th("ICIR",      style=_th),
                html.Th("IC t-stat", style=_th),
                html.Th("IC Hit%",   style=_th),
                html.Th("Win Rate",  style=_th),
            ])),
            html.Tbody(html.Tr([
                html.Td(f"{mean_ic:.4f}",  style=_td),
                html.Td(f"{ic_std:.4f}",   style=_td),
                html.Td(f"{icir:.2f}",
                        style={**_td, "color": conf_color, "fontWeight": "700"}),
                html.Td(f"{ic_tstat:.2f}", style=_td),
                html.Td(f"{ic_hit:.1%}",   style=_td),
                html.Td(_format_pct(getattr(metrics, "win_rate", None)), style=_td),
            ])),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
    ], style={
        "backgroundColor": THEME["panel"],
        "border":          f"1px solid {THEME['border']}",
        "borderRadius":    "10px",
        "padding":         "14px 16px",
        "marginBottom":    "16px",
    })

    # ── Section 3: Cumulative PnL + Rolling IC (side by side) ────────────────
    _common = dict(
        paper_bgcolor=THEME["panel"], plot_bgcolor=THEME["panel"],
        font={"color": THEME["text"]}, hovermode="x unified",
        margin={"l": 44, "r": 20, "t": 45, "b": 40},
        xaxis=dict(gridcolor=THEME["border"]),
        yaxis=dict(gridcolor=THEME["border"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font={"color": THEME["text"]}),
    )

    pnl_fig = go.Figure()
    if not cumulative_returns.empty:
        pnl_fig.add_trace(go.Scatter(
            x=cumulative_returns.index, y=cumulative_returns.values,
            mode="lines", line={"color": THEME["accent"], "width": 2},
            name="Cumulative PnL",
        ))
    pnl_fig.update_layout(title="Cumulative PnL", height=310, **_common)

    ic_fig = go.Figure()
    if not ic_rolling.empty:
        ic_fig.add_trace(go.Scatter(
            x=ic_rolling.index, y=ic_rolling.values,
            mode="lines", line={"color": THEME["warning"], "width": 1, "dash": "dot"},
            name="Rolling 60d IC", opacity=0.55,
        ))
        # EWMA(20) of the rolling IC — smoothes out high-frequency flips
        ic_ewma = ic_rolling.ewm(span=20, min_periods=10).mean()
        ic_fig.add_trace(go.Scatter(
            x=ic_ewma.index, y=ic_ewma.values,
            mode="lines", line={"color": THEME["warning"], "width": 2},
            name="IC EWMA(20)",
        ))
        ic_fig.add_trace(go.Scatter(
            x=[ic_rolling.index.min(), ic_rolling.index.max()], y=[0.0, 0.0],
            mode="lines", line={"color": "gray", "dash": "dash", "width": 1},
            showlegend=False,
        ))
    ic_fig.update_layout(title="Rolling 60-day IC  (dotted = raw, solid = EWMA-20)", height=310, **_common)

    charts_row = html.Div([
        html.Div(dcc.Graph(figure=pnl_fig), style={"flex": "1", "minWidth": "0"}),
        html.Div(dcc.Graph(figure=ic_fig),  style={"flex": "1", "minWidth": "0"}),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "16px"})

    # ── Section 4: Signal History bar chart (colour-coded) ────────────────────
    _sig_c = {1: THEME["success"], -1: THEME["danger"], 0: THEME["muted"]}
    bar_colors = [_sig_c.get(int(round(float(v))), THEME["muted"])
                  for v in positions.values] if not positions.empty else []

    sig_fig = go.Figure()
    if not positions.empty:
        sig_fig.add_trace(go.Bar(
            x=positions.index, y=positions.values,
            marker_color=bar_colors,
            name="Signal",
        ))
    sig_fig.update_layout(
        title="Signal History  (+1 Long / −1 Short / 0 Neutral)",
        height=200, bargap=0, showlegend=False,
        **_common,
    )

    # ── Q3 footnote: signal convention for bond futures ────────────────────────
    ir_note = html.Div(
        "ℹ  Signal direction is in futures PRICE space.  "
        "Macro features (IRDL/IRSL/IRCV) are stored as yield levels — the model "
        "is trained on price returns (−D·Δy), so ⬆ LONG already means long bond/futures "
        "(rate expected to fall).  No manual sign flip is required.",
        style={"color": THEME["muted"], "fontSize": "11px", "fontStyle": "italic",
               "padding": "8px 12px", "backgroundColor": THEME["panel_alt"],
               "borderRadius": "6px", "marginBottom": "14px",
               "borderLeft": f"3px solid {THEME['accent']}"},
    )

    # ── Top Driving Signals panel ─────────────────────────────────────────────────
    top_alpha_div = _build_top_alpha_features(results)

    children = [
        ir_note,
        metric_cards,
        ic_table_div,
        charts_row,
        html.H5("Signal History",
                style={"color": THEME["accent"], "marginBottom": "8px", "fontSize": "14px"}),
        dcc.Graph(figure=sig_fig),
    ]
    if top_alpha_div is not None:
        children.append(top_alpha_div)
    children.append(_build_period_table(results))

    return html.Div(children)


def _status_block(job: dict[str, Any] | None) -> html.Div:
    if not job:
        color = THEME["muted"]
        text = "Ready"
        details = "Pick a ticker and date range, then click Run Backtest."
    else:
        status = job.get("status", "unknown")
        color_map = {
            "queued": THEME["warning"],
            "running": THEME["accent"],
            "completed": THEME["success"],
            "failed": THEME["danger"],
        }
        color = color_map.get(status, THEME["muted"])
        text = job.get("message", status.title())
        submitted_at = job.get("submitted_at")
        submitted_str = submitted_at.strftime("%Y-%m-%d %H:%M:%S") if submitted_at else ""
        details = f"Ticker: {job.get('ticker', '-')} | Period: {job.get('start_date', '-')} → {job.get('end_date', '-')}"
        if submitted_str:
            details += f" | Submitted: {submitted_str}"

    return html.Div(
        [
            html.Div(text, style={"fontSize": "16px", "fontWeight": "700", "color": color}),
            html.Div(details, style={"fontSize": "12px", "color": THEME["muted"], "marginTop": "6px"}),
        ],
        style={
            "backgroundColor": THEME["panel"],
            "border": f"1px solid {THEME['border']}",
            "borderLeft": f"4px solid {color}",
            "borderRadius": "10px",
            "padding": "14px 16px",
            "marginBottom": "16px",
        },
    )


# ── Public API ──────────────────────────────────────────────────────────────

def build_factor_model_backtest_layout() -> html.Div:
    """Return the Factor Model Backtest panel for embedding inside Beta Book."""
    start_date_default, end_date_default = _default_dates()

    return html.Div(
        [
            dcc.Store(id="factor-job-store", storage_type="session"),
            dcc.Interval(id="factor-job-poll", interval=1500, n_intervals=0, disabled=True),

            html.H4(
                "Alpha Factor Backtest",
                style={"color": THEME["text"], "marginBottom": "4px"},
            ),
            html.P(
                "Walk-forward ML model trained on alpha signals (momentum, carry, vol, macro) "
                "to predict bond futures price returns.  "
                "Risk factors (IRDL/IRSL/FX/CMD) enter as predictive features, not as the traded asset.",
                style={"color": THEME["muted"], "marginBottom": "20px", "fontSize": "12px",
                       "fontStyle": "italic"},
            ),

            # ── Controls row ────────────────────────────────────────────
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Ticker", style={"display": "block", "marginBottom": "8px", "color": THEME["text"], "fontSize": "13px"}),
                            dcc.Dropdown(
                                id="factor-ticker-dropdown",
                                options=cast(Any, SUPPORTED_TICKERS),
                                value=config_manager.model_config.ticker,
                                clearable=False,
                                style={"color": "#000"},
                            ),
                        ],
                        style={"minWidth": "260px", "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.Label("Backtest Period", style={"display": "block", "marginBottom": "8px", "color": THEME["text"], "fontSize": "13px"}),
                            dcc.DatePickerRange(
                                id="factor-date-range",
                                start_date=start_date_default,
                                end_date=end_date_default,
                                display_format="YYYY-MM-DD",
                                minimum_nights=0,
                            ),
                        ],
                        style={"minWidth": "300px", "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.Label("Action", style={"display": "block", "marginBottom": "8px", "color": THEME["text"], "fontSize": "13px"}),
                            html.Button(
                                "Run Backtest",
                                id="factor-run-button",
                                n_clicks=0,
                                style={
                                    "backgroundColor": THEME["accent"],
                                    "color": "#fff",
                                    "border": "none",
                                    "padding": "10px 18px",
                                    "borderRadius": "6px",
                                    "fontWeight": "700",
                                    "cursor": "pointer",
                                },
                            ),
                        ],
                        style={"minWidth": "160px"},
                    ),
                ],
                style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "18px"},
            ),

            # ── Status & results ────────────────────────────────────────
            html.Div(id="factor-status-container", children=_status_block(None)),
            dcc.Loading(
                type="circle",
                color=THEME["accent"],
                style={"minHeight": "80px"},
                children=html.Div(
                    id="factor-results-container",
                    children=html.Div(
                        "No backtest has been run yet.",
                        style={
                            "color": THEME["muted"],
                            "backgroundColor": THEME["panel"],
                            "border": f"1px solid {THEME['border']}",
                            "borderRadius": "12px",
                            "padding": "18px",
                        },
                    ),
                ),
            ),
        ],
        style={"padding": "6px 0"},
    )


def register_factor_backtest_callbacks(app) -> None:
    """Register the two callbacks (trigger + poll) on the given Dash app."""

    @app.callback(
        Output("factor-job-store", "data"),
        Output("factor-job-poll", "disabled"),
        Output("factor-run-button", "disabled"),
        Input("factor-run-button", "n_clicks"),
        State("factor-date-range", "start_date"),
        State("factor-date-range", "end_date"),
        State("factor-ticker-dropdown", "value"),
        prevent_initial_call=True,
    )
    def _trigger_backtest(n_clicks: int, start_date: str, end_date: str, ticker: str):
        if not n_clicks:
            raise PreventUpdate
        if not start_date or not end_date or not ticker:
            raise PreventUpdate
        if pd.Timestamp(start_date) > pd.Timestamp(end_date):
            raise PreventUpdate
        job_id = _start_job(start_date, end_date, ticker)
        return {"job_id": job_id}, False, True

    @app.callback(
        Output("factor-status-container", "children"),
        Output("factor-results-container", "children"),
        Output("factor-job-poll", "disabled", allow_duplicate=True),
        Output("factor-run-button", "disabled", allow_duplicate=True),
        Input("factor-job-poll", "n_intervals"),
        State("factor-job-store", "data"),
        prevent_initial_call=True,
    )
    def _poll_job(_n_intervals: int, job_store: dict[str, Any] | None):
        if not job_store or "job_id" not in job_store:
            raise PreventUpdate

        job_id = job_store["job_id"]
        with JOB_LOCK:
            job = JOB_STATE.get(job_id)

        if not job:
            return _status_block(None), no_update, True, False

        status_component = _status_block(job)
        status = job.get("status")

        if status in {"queued", "running"}:
            return status_component, no_update, False, True

        if status == "failed":
            error_text = job.get("error") or "Unknown error"
            return (
                status_component,
                html.Div(
                    [
                        html.H4("Backtest failed", style={"color": THEME["danger"], "marginBottom": "12px"}),
                        html.Pre(
                            error_text,
                            style={
                                "whiteSpace": "pre-wrap",
                                "color": THEME["text"],
                                "backgroundColor": THEME["panel"],
                                "padding": "16px",
                                "borderRadius": "10px",
                                "border": f"1px solid {THEME['border']}",
                            },
                        ),
                    ]
                ),
                True,
                False,
            )

        result = job.get("result")
        return (
            status_component,
            _build_results_layout(
                result,
                job.get("ticker", "-"),
                job.get("start_date", "-"),
                job.get("end_date", "-"),
            ),
            True,
            False,
        )
