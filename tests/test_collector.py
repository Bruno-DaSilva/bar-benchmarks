from __future__ import annotations

import json
from datetime import UTC, datetime

from bar_benchmarks.task import collector
from bar_benchmarks.types import RunnerVerdict


def _write_inputs(task_env, *, error=None, has_bench=True):
    run = task_env["run"]
    data = task_env["data"]

    verdict = RunnerVerdict(
        started_at=datetime(2026, 4, 20, tzinfo=UTC),
        ended_at=datetime(2026, 4, 20, 0, 0, 30, tzinfo=UTC),
        engine_exit=0 if error is None else 1,
        engine_wall_s=30.0,
        benchmark_output_path=str(data / "benchmark-results.json"),
        error=error,
    )
    (run / "verdict.json").write_text(json.dumps(verdict.model_dump(mode="json")))
    if has_bench:
        (data / "benchmark-results.json").write_text(json.dumps({"frames": 10, "fps": 60}))


def test_collector_happy_path(task_env, tiny_artifacts):
    _write_inputs(task_env)
    result = collector.run()

    out = task_env["results"] / "0" / "results.json"
    assert out.is_file()
    on_disk = json.loads(out.read_text())
    assert result.valid is True
    assert result.invalid_reason is None
    assert on_disk["benchmark"] == {"frames": 10, "fps": 60}
    assert on_disk["batch_id"] == "job-test"
    assert on_disk["instance_type"] == "n1-standard-8"
    assert on_disk["artifact_names"]["engine"] == "recoil-test"


def test_collector_engine_crash_marks_invalid(task_env, tiny_artifacts):
    _write_inputs(task_env, error="engine_crash")
    result = collector.run()
    assert result.valid is False
    assert result.invalid_reason == "engine_crash"


def test_collector_uploads_infolog_when_present(task_env, tiny_artifacts):
    _write_inputs(task_env)
    (task_env["data"] / "infolog.txt").write_text("engine log contents\n")

    collector.run()

    uploaded = task_env["results"] / "0" / "infolog.txt"
    assert uploaded.is_file()
    assert uploaded.read_text() == "engine log contents\n"


def test_collector_skips_infolog_when_absent(task_env, tiny_artifacts):
    _write_inputs(task_env)

    collector.run()

    assert not (task_env["results"] / "0" / "infolog.txt").exists()


def test_collector_missing_verdict(task_env, tiny_artifacts):
    result = collector.run()
    assert result.valid is False
    assert result.invalid_reason == "runner_did_not_run"
