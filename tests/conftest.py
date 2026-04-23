from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def task_env(monkeypatch, tmp_path):
    """Point all BAR_* paths at a tmp tree and return the layout."""
    bucket = tmp_path / "mnt-artifacts-bucket"
    artifacts = bucket / "job-test"
    results = tmp_path / "mnt-results"
    data = tmp_path / "var-bar-data"
    run = tmp_path / "var-bar-run"
    engine = tmp_path / "opt-recoil"
    for d in (bucket, artifacts, results, data, run, engine):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("BAR_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("BAR_ARTIFACTS_BUCKET_DIR", str(bucket))
    monkeypatch.setenv("BAR_RESULTS_DIR", str(results))
    monkeypatch.setenv("BAR_DATA_DIR", str(data))
    monkeypatch.setenv("BAR_RUN_DIR", str(run))
    monkeypatch.setenv("BAR_ENGINE_DIR", str(engine))
    monkeypatch.setenv("BAR_BENCHMARK_OUTPUT_PATH", "benchmark-results.json")
    monkeypatch.setenv("BATCH_JOB_UID", "job-test")
    monkeypatch.setenv("BATCH_TASK_INDEX", "0")

    return {
        "bucket": bucket,
        "artifacts": artifacts,
        "results": results,
        "data": data,
        "run": run,
        "engine": engine,
    }


def _make_tarball(out: Path, files: dict[str, str], *, mode: dict[str, int] | None = None) -> None:
    mode = mode or {}
    with tarfile.open(out, "w:gz") as tf:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = mode.get(name, 0o644)
            from io import BytesIO

            tf.addfile(info, BytesIO(data))


@pytest.fixture
def tiny_artifacts(task_env):
    """Populate the tmp bucket + per-job dir with tiny fixture tarballs
    and a manifest. Engine stub writes benchmark JSON. Layout mirrors
    the real artifacts bucket: engine/bar-content/map at bucket root
    under catalog-derived names, overlay/startscript/manifest under
    the per-job dir."""
    bucket = task_env["bucket"]
    artifacts = task_env["artifacts"]
    data = task_env["data"]
    map_filename = "tiny.smf"

    engine_name = "recoil-test"
    bar_content_name = "bar-test"
    map_name = "tiny"

    engine_key = f"engine/{engine_name}.tar.gz"
    bar_content_key = f"bar-content/{bar_content_name}.tar.gz"
    map_key = f"maps/{map_filename}"

    for sub in ("engine", "bar-content", "maps"):
        (bucket / sub).mkdir(parents=True, exist_ok=True)

    stub_script = (
        "#!/bin/sh\n"
        f'echo "{{\\"frames\\": 10, \\"fps\\": 60}}" > "{data}/benchmark-results.json"\n'
        "exit 0\n"
    )
    _make_tarball(
        bucket / engine_key,
        {"spring-headless": stub_script},
        mode={"spring-headless": 0o755},
    )
    _make_tarball(
        bucket / bar_content_key,
        {"VERSION": "1.2.3\n", "shared.lua": "-- base"},
    )
    (bucket / map_key).write_bytes(b"map-bytes")

    # Overlay mirrors /var/bar-data/: files under games/BAR.sdd/ override
    # bar-content, and top-level files are bar-data extras.
    _make_tarball(
        artifacts / "overlay.tar.gz",
        {
            "games/BAR.sdd/shared.lua": "-- overlay wins\n",
            "games/BAR.sdd/extra.lua": "-- added",
            "benchmark_snapshot.lua": "-- extra drop at bar-data root",
        },
    )
    (artifacts / "startscript.txt").write_text("[GAME] { ... }\n")

    manifest = {
        "job_uid": "job-test",
        "region": "us-west4",
        "instance_type": "n1-standard-8",
        "map_filename": map_filename,
        "artifact_names": {
            "engine": engine_name,
            "bar_content": bar_content_name,
            "map": map_name,
        },
        "paths": {
            "engine": engine_key,
            "bar_content": bar_content_key,
            "map": map_key,
        },
    }
    (artifacts / "manifest.json").write_text(json.dumps(manifest))
    return manifest
