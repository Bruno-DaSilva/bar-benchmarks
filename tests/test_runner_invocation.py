from __future__ import annotations

import json

from bar_benchmarks.task import runner


def test_runner_happy_path(task_env, tiny_artifacts):
    verdict = runner.run()
    assert verdict.engine_exit == 0
    assert verdict.error is None
    assert verdict.benchmark_output_path is not None
    assert verdict.timings["engine_wall_s"] >= 0

    # benchmark-results.json written by stub engine
    bench = json.loads((task_env["data"] / "benchmark-results.json").read_text())
    assert bench == {"frames": 10, "fps": 60}

    # verdict.json written to run dir
    on_disk = json.loads((task_env["run"] / "verdict.json").read_text())
    assert on_disk["engine_exit"] == 0
    assert on_disk["error"] is None


def _replace_engine(task_env, tiny_artifacts, stub: bytes) -> None:
    import tarfile
    from io import BytesIO

    engine_tar = task_env["bucket"] / tiny_artifacts["paths"]["engine"]
    engine_tar.unlink()
    with tarfile.open(engine_tar, "w:gz") as tf:
        info = tarfile.TarInfo(name="spring-headless")
        info.size = len(stub)
        info.mode = 0o755
        tf.addfile(info, BytesIO(stub))


def test_runner_overlay_output_missing(task_env, tiny_artifacts):
    # Replace engine with a stub that exits 0 but writes no benchmark file.
    _replace_engine(task_env, tiny_artifacts, b"#!/bin/sh\nexit 0\n")

    verdict = runner.run()
    assert verdict.engine_exit == 0
    assert verdict.error == "overlay_output_missing"


def test_runner_engine_crash(task_env, tiny_artifacts):
    _replace_engine(task_env, tiny_artifacts, b"#!/bin/sh\nexit 42\n")

    verdict = runner.run()
    assert verdict.engine_exit == 42
    assert verdict.error == "engine_crash"
