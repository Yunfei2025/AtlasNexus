"""Helpers for resolving backfill instrument-type aliases."""


def expand_backfill_btypes(btype: str) -> list[str]:
    """Expand backfill aliases to the concrete instrument types they should run."""
    if btype == "OBond":
        return ["LBond", "BBond", "GBond", "MNote"]
    return [btype]
