#!/usr/bin/env python3
"""Standalone Dash app for running factor-model backtests interactively."""
from __future__ import annotations

import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from factors.config import config_manager
from factors.engine.factor_engine import run_analysis
from factors.processing.loader import getDailyTS

SUPPORTED_TICKERS: list[dict[str, Any]] = [
    {"label": "T.CFE (10Y Treasury Future)", "value": "T.CFE"},
    {"label": "TF.CFE (5Y Treasury Future)", "value": "TF.CFE"},
    {"label": "TS.CFE (2Y Treasury Future)", "value": "TS.CFE"},
    {"label": "TL.CFE (30Y Treasury Future)", "value": "TL.CFE"},
    {"label": "Pair: T.CFE - TS.CFE", "value": "Pair:T.CFE-TS.CFE"},
    {"label": "Fly: TS.CFE - TF.CFE - T.CFE", "value": "Fly:TS.CFE-TF.CFE-T.CFE"},
]

THEME = {
    "bg": "#0f172a",
    "panel": "#111827",
    "panel_alt": "#1f2937",
    "border": "#334155",
    "text": "#e5e7eb",
    "muted": "#94a3b8",
    "accent": "#38bdf8",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
}

JOB_LOCK = threading.Lock()
JOB_STATE: dict[str, dict[str, Any]] = {}

app = Dash(__name__, title="Factor Backtest Dashboard")
server = app.server


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
            JOB_STATE[job_id]["message"] = "Running factor backtest..."
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
    fig.update_xaxes(gridcolor="#1e293b")
    fig.update_yaxes(gridcolor="#1e293b")
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
            factors += " ..."
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

    return html.Div(
        [
            html.H4("Period Results", style={"color": THEME["text"], "marginBottom": "12px"}),
            html.Table(
                [
                    html.Thead(
                        html.Tr([
                            html.Th("Period"),
                            html.Th("Status"),
                            html.Th("# Factors"),
                            html.Th("Selected Factors"),
                            html.Th("Error"),
                        ])
                    ),
                    html.Tbody(rows or [html.Tr([html.Td("No period results", colSpan=5)])]),
                ],
                style={
                    "width": "100%",
                    "borderCollapse": "collapse",
                    "color": THEME["text"],
                },
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


def _build_results_layout(results: Any, ticker: str, start_date: str, end_date: str) -> html.Div:
    metrics = getattr(results, "backtest_metrics", None)
    backtest_data = getattr(results, "backtest_data", None)

    metric_cards = html.Div(
        [
            _metric_card("Ticker", ticker),
            _metric_card("Period", f"{start_date} → {end_date}"),
            _metric_card("Total Return", _format_pct(getattr(metrics, "total_return", None))),
            _metric_card("Sharpe", _format_num(getattr(metrics, "sharpe_ratio", None))),
            _metric_card("Volatility", _format_pct(getattr(metrics, "volatility", None))),
            _metric_card("Max Drawdown", _format_pct(getattr(metrics, "max_drawdown", None))),
        ],
        style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "18px"},
    )

    cumulative_returns = _to_series(getattr(backtest_data, "cumulative_returns", None))
    strategy_returns = _to_series(getattr(backtest_data, "strategy_returns", None))
    predictions = _to_series(getattr(backtest_data, "predictions", None))
    positions = _to_series(getattr(backtest_data, "positions", None))

    figures = html.Div(
        [
            html.Div(dcc.Graph(figure=_make_line_figure(cumulative_returns, "Cumulative Returns", THEME["accent"]))),
            html.Div(dcc.Graph(figure=_make_line_figure(strategy_returns, "Strategy Returns", THEME["success"]))),
            html.Div(dcc.Graph(figure=_make_line_figure(predictions, "Predictions", THEME["warning"]))),
            html.Div(dcc.Graph(figure=_make_line_figure(positions, "Positions", THEME["danger"]))),
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(380px, 1fr))",
            "gap": "16px",
        },
    )

    return html.Div([metric_cards, figures, _build_period_table(results)])


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


start_date_default, end_date_default = _default_dates()

app.layout = html.Div(
    [
        dcc.Store(id="factor-job-store", storage_type="session"),
        dcc.Interval(id="factor-job-poll", interval=1500, n_intervals=0, disabled=True),
        html.H2("Factor Model Backtest Dashboard", style={"color": THEME["text"], "marginBottom": "8px"}),
        html.P(
            "Set the backtest period and instrument, then run the factor model backtest from the dashboard.",
            style={"color": THEME["muted"], "marginBottom": "20px"},
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Label("Ticker", style={"display": "block", "marginBottom": "8px", "color": THEME["text"]}),
                        dcc.Dropdown(
                            id="factor-ticker-dropdown",
                            options=cast(Any, SUPPORTED_TICKERS),
                            value=config_manager.model_config.ticker,
                            clearable=False,
                        ),
                    ],
                    style={"minWidth": "280px", "flex": "1"},
                ),
                html.Div(
                    [
                        html.Label("Backtest Period", style={"display": "block", "marginBottom": "8px", "color": THEME["text"]}),
                        dcc.DatePickerRange(
                            id="factor-date-range",
                            start_date=start_date_default,
                            end_date=end_date_default,
                            display_format="YYYY-MM-DD",
                            minimum_nights=0,
                            style={"backgroundColor": THEME["panel_alt"]},
                        ),
                    ],
                    style={"minWidth": "320px", "flex": "1"},
                ),
                html.Div(
                    [
                        html.Label("Action", style={"display": "block", "marginBottom": "8px", "color": THEME["text"]}),
                        html.Button(
                            "Run Backtest",
                            id="factor-run-button",
                            n_clicks=0,
                            style={
                                "backgroundColor": THEME["accent"],
                                "color": "#082f49",
                                "border": "none",
                                "padding": "12px 20px",
                                "borderRadius": "8px",
                                "fontWeight": "700",
                                "cursor": "pointer",
                            },
                        ),
                    ],
                    style={"minWidth": "180px"},
                ),
            ],
            style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "18px"},
        ),
        html.Div(id="factor-status-container", children=_status_block(None)),
        dcc.Loading(
            type="default",
            color=THEME["accent"],
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
    style={
        "backgroundColor": THEME["bg"],
        "minHeight": "100vh",
        "padding": "24px",
        "fontFamily": "Segoe UI, Arial, sans-serif",
    },
)


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
def trigger_backtest(n_clicks: int, start_date: str, end_date: str, ticker: str):
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
def poll_job(_n_intervals: int, job_store: dict[str, Any] | None):
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
        _build_results_layout(result, job.get("ticker", "-"), job.get("start_date", "-"), job.get("end_date", "-")),
        True,
        False,
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8051)
