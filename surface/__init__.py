"""Surface visualization package.

Keep Dash app imports lazy so utility modules like `surface.retrieve`
can be imported by the engine updater without pulling in the web app.
"""

__all__ = ["app", "server", "run"]


def __getattr__(name):
	if name in {"app", "server", "run"}:
		from .app import app, server, run

		exports = {"app": app, "server": server, "run": run}
		return exports[name]
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
