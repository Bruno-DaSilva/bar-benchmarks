from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from bar_benchmarks.stats import cost
from bar_benchmarks.types import BatchReport


# ---- fake Batch API objects --------------------------------------------------
# Mirror just the slice of batch_v1.Task that `cost._billable_s_from_tasks`
# reads: task.status.status_events[*].{task_state.name, event_time.timestamp()}.


@dataclass
class _FakeEventTime:
    _ts: float

    def timestamp(self) -> float:
        return self._ts


@dataclass
class _FakeTaskState:
    name: str


@dataclass
class _FakeEvent:
    task_state: _FakeTaskState
    event_time: _FakeEventTime


@dataclass
class _FakeStatus:
    status_events: list[_FakeEvent] = field(default_factory=list)


@dataclass
class _FakeTask:
    status: _FakeStatus

    @classmethod
    def make(cls, transitions: list[tuple[str, float]]) -> "_FakeTask":
        events = [
            _FakeEvent(task_state=_FakeTaskState(name=s), event_time=_FakeEventTime(ts))
            for s, ts in transitions
        ]
        return cls(status=_FakeStatus(status_events=events))


# ---- tests -------------------------------------------------------------------


def test_billable_sums_pending_to_succeeded_per_task():
    tasks = [
        _FakeTask.make([
            ("PENDING", 100.0),
            ("ASSIGNED", 150.0),
            ("RUNNING", 150.5),
            ("SUCCEEDED", 400.0),
        ]),
        _FakeTask.make([
            ("PENDING", 200.0),
            ("ASSIGNED", 250.0),
            ("RUNNING", 251.0),
            ("SUCCEEDED", 600.0),
        ]),
    ]
    # (400 - 100) + (600 - 200) = 300 + 400 = 700
    assert cost._billable_s_from_tasks(tasks) == pytest.approx(700.0)


def test_billable_counts_failed_as_final():
    # A preempted/failed task still burned VM time until the FAILED event.
    tasks = [
        _FakeTask.make([
            ("PENDING", 10.0),
            ("ASSIGNED", 60.0),
            ("RUNNING", 60.5),
            ("FAILED", 200.0),
        ]),
    ]
    assert cost._billable_s_from_tasks(tasks) == pytest.approx(190.0)


def test_billable_skips_tasks_missing_pending_or_final():
    # No PENDING event — don't contribute.
    tasks = [
        _FakeTask.make([("RUNNING", 50.0), ("SUCCEEDED", 100.0)]),
        # No terminal event — don't contribute.
        _FakeTask.make([("PENDING", 10.0), ("RUNNING", 60.0)]),
    ]
    assert cost._billable_s_from_tasks(tasks) == 0.0


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


def test_apply_from_batch_api_returns_report_unchanged_without_shape(monkeypatch):
    # Missing instance_type means we can't price — short-circuit without
    # touching the Batch API (which would fail in tests).
    report = BatchReport(job_uid="job-y", submitted=1, valid=1, invalid=0)
    called = False

    def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("should not have called Batch API")

    monkeypatch.setattr("google.cloud.batch_v1.BatchServiceClient", boom, raising=False)
    out = cost.apply_from_batch_api(report, project="p")
    assert out == report
    assert not called
