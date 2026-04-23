from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bar_benchmarks.types import (
    ArtifactNames,
    Result,
    RunnerVerdict,
)


def _result_kwargs():
    return dict(
        batch_id="job-1",
        vm_id="task-0",
        instance_type="n1-standard-8",
        region="us-west4",
        artifact_names=ArtifactNames(
            engine="recoil-abc1234",
            bar_content="bar-test-29871-90f4bc1",
            map="hellas-basin-v1.4",
        ),
        run=RunnerVerdict(
            started_at=datetime(2026, 4, 20, tzinfo=UTC),
            ended_at=datetime(2026, 4, 20, 0, 1, tzinfo=UTC),
            engine_exit=0,
        ),
        benchmark={"frames": 1234},
        valid=True,
    )


def test_result_roundtrip():
    r = Result(**_result_kwargs())
    dumped = r.model_dump(mode="json")
    assert dumped["valid"] is True
    assert dumped["artifact_names"]["engine"] == "recoil-abc1234"
    reloaded = Result.model_validate(dumped)
    assert reloaded == r


def test_result_rejects_extra_fields():
    kw = _result_kwargs()
    with pytest.raises(ValidationError):
        Result(**kw, stray="nope")


def test_invalid_reason_default_none():
    r = Result(**_result_kwargs())
    assert r.invalid_reason is None
