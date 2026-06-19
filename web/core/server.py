"""Dash server instance shared across FI Engine web applications."""

from __future__ import annotations
import pathlib

from dash import Dash
import os
import time
import logging
from flask import g, request, jsonify
from flask import send_file, abort

# Get the project root and assets directory
project_root = pathlib.Path(__file__).parent.parent.parent
assets_folder = str(project_root / "web" / "assets")

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width"}],
    assets_folder=assets_folder,
)
server = app.server

# Configure server to handle Windows socket issues
if hasattr(server, "config"):
    server.config["SOCKET_TIMEOUT"] = 60
    server.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max file size

# Optional per-request timing logs to diagnose stalls
if os.environ.get("WEB_LOG_TIMINGS", "0") == "1":
    _logger = logging.getLogger(__name__)

    @server.before_request
    def _before_request():  # type: ignore
        g._req_start = time.time()

    @server.after_request
    def _after_request(response):  # type: ignore
        try:
            start = getattr(g, "_req_start", None)
            if start is not None:
                elapsed = (time.time() - start) * 1000.0
                _logger.info("%s %s -> %s in %.1fms", request.method, request.path, response.status_code, elapsed)
        except Exception:
            pass
        return response

# Simple health endpoint to confirm the server is responding
@server.route("/healthz")
def _healthz():  # type: ignore
    return jsonify({"status": "ok"})


# Serve the cover page (AtlasNexus landing page)
@server.route("/")
def _serve_cover():  # type: ignore
    try:
        cover_file = project_root / "web" / "assets" / "cover.html"
        if cover_file.exists():
            return send_file(str(cover_file))
        else:
            abort(404)
    except Exception:
        abort(500)


# Serve the pairs regression plots HTML as a static-like endpoint so iframes
# or direct links can access it from the Dash app. This reads the file from
# the project 'pairs' folder and returns it with appropriate content-type.
@server.route("/pairs/regression_plots.html")
def _serve_pairs_regression():  # type: ignore
    try:
        pairs_file = project_root / "pairs" / "regression_plots.html"
        if pairs_file.exists():
            return send_file(str(pairs_file))
        else:
            abort(404)
    except Exception:
        abort(500)
