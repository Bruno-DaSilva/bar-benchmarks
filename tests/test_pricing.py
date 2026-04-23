from __future__ import annotations

from bar_benchmarks.stats.pricing import spot_usd_per_hour


def test_spot_rate_known_shape():
    assert spot_usd_per_hour("c2d-standard-16", "us-central1") == 0.174304


def test_spot_rate_unknown_shape_is_none():
    assert spot_usd_per_hour("c2d-standard-16", "europe-west1") is None
    assert spot_usd_per_hour("n1-standard-8", "us-central1") is None
