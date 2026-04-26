# -*- coding: utf-8 -*-
"""AtlasNexus Intraday Console.

A separate Dash app for higher-frequency monitoring and intraday strategy operation.

Port: 8081
"""

from __future__ import annotations

import pathlib
import Path
from dash import dcc, html
from dash.dependencies import Input, Output, State

# Add project root to Python path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from web.tabs.atlas_styles import tab_style, tabs_styles, tab_selected_style
from web.services.artifacts import find_latest_run, format_run_meta
from web.services.jobs import start_engine_job, tail_log

from dash import Dash as _Dash


project_root = pathlib.Path(__file__).resolve().parents[2]
assets_folder = str(project_root / "web" / "assets")

app = _Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    assets_folder=assets_folder,
)

app.title = "AtlasNexus Intraday Console"


def build_header():
    return html.Div(
        [
            html.Div(
                [
                    html.H4("AtlasNexus · Intraday", className="app__header__title"), #资产汇策
                    html.P(id="ani-refresh-time", className="app__header__title--grey"),
                    html.P(id="ani-latest-run", className="app__header__title--grey"),
                ],
                className="app__header__desc",
            ),
            html.Div(
                [
                    dcc.Store(id="ani-job-id", storage_type="memory"),
                    html.A(html.Button("Run Intraday Snapshot", id="ani-btn-run", n_clicks=0)),
                    html.A(html.Button("Run Intraday (+update)", id="ani-btn-run-update", n_clicks=0)),
                    html.Div(id="ani-job-status", children="No job running."),
                ],
                className="app__dropdown",
            ),
        ],
        className="app__header",
    )


def build_tabs_panel():
    return html.Div(
        [
            html.Div(
                [
                    dcc.Tabs(
                        id="ani-tabs",
                        value="session",
                        children=[
                            dcc.Tab(label="Session", value="session", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Signals", value="signals", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Risk", value="risk", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Tickets", value="tickets", style=tab_style, selected_style=tab_selected_style),
                        ],
                        style=tabs_styles,
                    ),
                    html.Div(id="ani-tabs-content"),
                    dcc.Interval(id="ani-interval", interval=3_000, n_intervals=0),
                ],
                className="tab__title",
            ),
        ],
        className="twelve columns futures__price__container",
    )


def create_layout():
    return html.Div(
        [
            build_header(),
            html.Div([build_tabs_panel()], className="app__content"),
        ],
        className="app__container",
    )


app.layout = create_layout()


@app.callback(
    Output("ani-refresh-time", "children"),
    Output("ani-latest-run", "children"),
    Input("ani-interval", "n_intervals"),
)
def _tick(n):
    meta = find_latest_run(mode="intraday")
    return (
        f"Refresh tick: {n}",
        f"Latest intraday run: {format_run_meta(meta)}",
    )


@app.callback(
    Output("ani-job-id", "data"),
    Output("ani-job-status", "children"),
    Input("ani-btn-run", "n_clicks"),
    Input("ani-btn-run-update", "n_clicks"),
    prevent_initial_call=True,
)
def _start_jobs(n_run, n_run_update):
    ctx = __import__("dash").callback_context
    if not ctx.triggered:
        raise __import__("dash").exceptions.PreventUpdate

    trig = ctx.triggered[0]["prop_id"].split(".")[0]

    if trig == "ani-btn-run":
        job = start_engine_job(argv=["intraday"])
        return job.job_id, f"Started job {job.job_id}: intraday"

    if trig == "ani-btn-run-update":
        job = start_engine_job(argv=["intraday", "--update-data"])
        return job.job_id, f"Started job {job.job_id}: intraday --update-data"

    raise __import__("dash").exceptions.PreventUpdate


@app.callback(
    Output("ani-tabs-content", "children"),
    Input("ani-tabs", "value"),
    State("ani-job-id", "data"),
    Input("ani-interval", "n_intervals"),
)
def _render_tab(tab, job_id, n):
    if tab == "session":
        log = tail_log(job_id, max_lines=80) if job_id else ""
        meta = find_latest_run(mode="intraday")
        return html.Div(
            [
                html.H5("Session"),
                html.P("Use the buttons in the header to run intraday snapshot jobs."),
                html.P(f"Latest intraday run: {format_run_meta(meta)}"),
                html.Hr(),
                html.H6("Job log (tail)"),
                html.Pre(log, style={"whiteSpace": "pre-wrap", "maxHeight": "320px", "overflowY": "auto"}),
            ]
        )

    if tab == "signals":
        return html.Div([
            html.H5("Signals"),
            html.P("Planned: load latest intraday signals artifact and render tables/plots."),
        ])

    if tab == "risk":
        return html.Div([
            html.H5("Risk"),
            html.P("Planned: intraday exposure + session limits + alerts."),
        ])

    if tab == "tickets":
        return html.Div([
            html.H5("Tickets"),
            html.P("Planned: open/close suggestions and ticket export."),
        ])

    return html.Div([html.P(f"Unknown tab: {tab}")])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8081, debug=False, use_reloader=False)
