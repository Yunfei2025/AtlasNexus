"""Dash callbacks for yield surface dashboard."""

from __future__ import annotations

import numpy as np
from dash import Dash
from dash.dependencies import Input, Output, State

try:
    from settings.general import app_color
except ImportError:
    app_color = {"graph_bg": "#082255", "graph_line": "#007ACE"}

from .config import UPS, CENTERS, EYES, TEXTS, COLORSCALE
from .data import genCurveData


def register_callbacks(app: Dash) -> None:
    
    @app.callback(
        Output("surface-graph", "figure"),
        Input("surface-slider", "value"),
        Input("surface-date-picker-range", "start_date"),
        Input("surface-date-picker-range", "end_date"),
        Input("surface-country-selection", "value"),
    )
    def make_surface_graph(value, start_date, end_date, country):
        curve_data = genCurveData(start_date, end_date, country)
        xlist = curve_data["plist"]["x"]
        ylist = curve_data["plist"]["y"]
        zlist = curve_data["plist"]["z"]
        points = curve_data["points"]
        
        if value is None:
            value = 0

        if value in [0, 2, 3]:
            z_secondary_beginning = [z[1] for z in zlist if z[0] == "None"]
            z_secondary_end = [z[0] for z in zlist if z[0] != "None"]
            z_secondary = z_secondary_beginning + z_secondary_end
            x_secondary = ["3-month"] * len(z_secondary_beginning) + ["1-month"] * len(z_secondary_end)
            y_secondary = ylist
            opacity = 0.7
        elif value == 1:
            x_secondary = xlist
            y_secondary = [ylist[-1] for i in xlist]
            z_secondary = zlist[-1]
            opacity = 0.7
        elif value == 4:
            z_secondary = [z[8] for z in zlist]
            x_secondary = ["10-year" for i in z_secondary]
            y_secondary = ylist
            opacity = 0.25

        if value in range(0, 5):
            trace1 = dict(type="surface", x=xlist, y=ylist, z=zlist, hoverinfo="x+y+z",
                lighting={"ambient": 0.95, "diffuse": 0.99, "fresnel": 0.01, "roughness": 0.01, "specular": 0.01},
                colorscale=COLORSCALE, opacity=opacity, showscale=False, zmax=9.18, zmin=0, scene="scene")
            trace2 = dict(type="scatter3d", mode="lines", x=x_secondary, y=y_secondary, z=z_secondary,
                hoverinfo="x+y+z", line=dict(color="#444444"))
            data = [trace1, trace2]
        else:
            trace1 = dict(type="contour", x=ylist, y=xlist, z=np.array(zlist).T, colorscale=COLORSCALE,
                showscale=False, zmax=9.18, zmin=0, line=dict(smoothing=1, color="rgba(40,40,40,0.15)"),
                contours=dict(coloring="heatmap"))
            data = [trace1]

        layout = dict(
            autosize=True, font=dict(size=12, color="#E0E0E0"),
            margin=dict(t=5, l=5, b=5, r=5), showlegend=False, hovermode="closest",
            paper_bgcolor=app_color["graph_bg"], plot_bgcolor=app_color["graph_bg"],
            scene=dict(
                aspectmode="manual", aspectratio=dict(x=2, y=5, z=1.5),
                camera=dict(up=UPS[value], center=CENTERS[value], eye=EYES[value]),
                bgcolor=app_color["graph_bg"],
                annotations=[
                    dict(showarrow=False, y=points["P-Short"]["y"], x=points["P-Short"]["x"], z=points["P-Short"]["z"],
                        text="Today\'s " + points["P-Short"]["x"], xanchor="left", xshift=10, opacity=0.7, font=dict(color="#E0E0E0")),
                    dict(y=points["P-Long"]["y"], x=points["P-Long"]["x"], z=points["P-Long"]["z"],
                        text="Today\'s " + points["P-Long"]["x"], textangle=0, ax=0, ay=-75,
                        font=dict(color="#E0E0E0", size=12), arrowcolor="#E0E0E0", arrowsize=3, arrowwidth=1, arrowhead=1),
                ],
                xaxis={"showgrid": True, "gridcolor": "rgba(255,255,255,0.1)", "gridwidth": 1, "title": "",
                    "type": "category", "zeroline": False, "categoryorder": "array",
                    "categoryarray": list(reversed(xlist)), "backgroundcolor": app_color["graph_bg"], "color": "#E0E0E0"},
                yaxis={"showgrid": True, "gridcolor": "rgba(255,255,255,0.1)", "gridwidth": 1, "title": "",
                    "type": "date", "zeroline": False, "backgroundcolor": app_color["graph_bg"], "color": "#E0E0E0"},
                zaxis={"showgrid": True, "gridcolor": "rgba(255,255,255,0.1)", "gridwidth": 1, "title": "",
                    "zeroline": False, "backgroundcolor": app_color["graph_bg"], "color": "#E0E0E0"},
            ),
        )
        return dict(data=data, layout=layout)

    @app.callback(Output("surface-text", "children"), [Input("surface-slider", "value")])
    def make_surface_text(value):
        if value is None:
            value = 0
        return TEXTS[value]

    @app.callback(
        [Output("surface-slider", "value"), Output("surface-click-output", "data")],
        [Input("surface-back", "n_clicks"), Input("surface-next", "n_clicks")],
        [State("surface-slider", "value"), State("surface-click-output", "data")],
    )
    def advance_surface_slider(back, nxt, slider, last_history):
        if last_history is None:
            last_history = {"back": 0, "next": 0}
        if slider is None:
            slider = 0
        try:
            if back > last_history["back"]:
                last_history["back"] = back
                return max(0, slider - 1), last_history
            if nxt > last_history["next"]:
                last_history["next"] = nxt
                return min(5, slider + 1), last_history
        except Exception:
            last_history = {"back": 0, "next": 0}
        return slider, last_history
