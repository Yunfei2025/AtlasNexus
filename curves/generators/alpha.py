"""Compatibility shim.

`curves.generators.alpha` has moved to `curves.refreshers.alpha`.
This module re-exports the new location to keep legacy imports working.
"""

from __future__ import annotations

from curves.refreshers.alpha import *  # noqa: F401,F403


if __name__ == "__main__":
	from curves.refreshers.alpha import save_alpha_spreads_snapshot
	from settings.paths import DIR_INPUT

	out_path = save_alpha_spreads_snapshot(DIR_INPUT, rewrite=True)
	print(f"Saved alpha snapshot: {out_path}")
