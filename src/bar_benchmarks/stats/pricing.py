"""Spot pricing table.

Deliberately narrow — only the shape + region we actually run. Missing
entries return None so the report skips cost rather than guessing.
"""

from __future__ import annotations

_SPOT_USD_PER_HOUR: dict[tuple[str, str], float] = {
    ("c2d-standard-16", "us-central1"): 0.174304,
}


def spot_usd_per_hour(instance_type: str, region: str) -> float | None:
    return _SPOT_USD_PER_HOUR.get((instance_type, region))
