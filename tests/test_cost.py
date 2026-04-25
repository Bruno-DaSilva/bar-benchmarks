from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bar_benchmarks.stats import cost
from bar_benchmarks.types import (
    ArtifactNames,
    BatchReport,
    Result,
    RunnerVerdict,
)


def _result(vm_id: str, engine_wall_s: float | None) -> Result:
    now = datetime.now(UTC)
    return Result(
        batch_id="job-x",
        vm_id=vm_id,
        instance_type="c2d-standard-16",
        region="us-central1",
        artifact_names=ArtifactNames(engine="e", bar_content="b", map="m"),
        run=RunnerVerdict(
            started_at=now,
            ended_at=now,
            engine_exit=0,
            engine_wall_s=engine_wall_s,
        ),
    )


def test_billable_sums_engine_wall_plus_overhead():
    # 2 VMs × 1 iter + 1 VM × 1 iter (just shape; the formula sums all
    # iteration wall times and adds 120s × vm_count regardless of how
    # iterations are distributed).
    results = [
        _result("0-0", 100.0),
        _result("0-1", 100.0),
        _result("1-0", 100.0),
    ]
    # 300s wall + 120s × 2 VMs = 540s
    assert cost._billable_s_from_results(results, vm_count=2) == pytest.approx(540.0)


def test_billable_treats_none_engine_wall_as_zero():
    # Staging blew up before the engine started → engine_wall_s is None.
    # The VM still costs the per-VM overhead.
    results = [_result("0-0", None)]
    assert cost._billable_s_from_results(results, vm_count=1) == pytest.approx(120.0)


def test_billable_zero_vms_zero_results():
    assert cost._billable_s_from_results([], vm_count=0) == 0.0


def test_apply_from_results_attaches_cost_and_rate(monkeypatch):
    report = BatchReport(
        job_uid="job-x",
        submitted=2,
        valid=2,
        invalid=0,
        instance_type="c2d-standard-16",
        region="us-central1",
    )
    results = [_result("0-0", 100.0), _result("1-0", 200.0)]
    monkeypatch.setattr(
        "bar_benchmarks.stats.cost.spot_usd_per_hour", lambda *_: 3600.0
    )
    out = cost.apply_from_results(report, results=results, vm_count=2)
    # 300s wall + 240s overhead = 540s; at $3600/hr = $540.
    assert out.total_billable_s == pytest.approx(540.0)
    assert out.price_per_vm_hour_usd == pytest.approx(3600.0)
    assert out.compute_usd == pytest.approx(540.0)


def test_apply_from_results_missing_rate_leaves_compute_none(monkeypatch):
    report = BatchReport(
        job_uid="job-x",
        submitted=1,
        valid=1,
        invalid=0,
        instance_type="some-shape",
        region="some-region",
    )
    monkeypatch.setattr(
        "bar_benchmarks.stats.cost.spot_usd_per_hour", lambda *_: None
    )
    out = cost.apply_from_results(report, results=[_result("0-0", 50.0)], vm_count=1)
    assert out.total_billable_s == pytest.approx(170.0)
    assert out.price_per_vm_hour_usd is None
    assert out.compute_usd is None


def test_apply_from_results_returns_report_unchanged_without_shape():
    # No instance_type / region → can't price; skip without computing
    # anything.
    report = BatchReport(job_uid="job-y", submitted=1, valid=1, invalid=0)
    out = cost.apply_from_results(report, results=[_result("0-0", 999.0)], vm_count=1)
    assert out == report


def test_apply_cached_zeroes_cost_fields_and_sets_flag():
    report = BatchReport(
        job_uid="job-x",
        submitted=3,
        valid=3,
        invalid=0,
        instance_type="c2d-standard-16",
        region="us-central1",
    )
    cached = cost.apply_cached(report)
    assert cached.cached is True
    assert cached.total_billable_s == 0.0
    assert cached.compute_usd == 0.0
    assert cached.price_per_vm_hour_usd is None
    # original is untouched (model_copy returns a new instance)
    assert report.cached is False
