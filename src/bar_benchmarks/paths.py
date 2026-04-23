from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


def artifacts_dir() -> Path:
    """GCS FUSE mount scoped to `<artifacts-bucket>/<job_uid>/` — per-job
    artifacts (overlay, startscript, wheel, manifest). Read-only on the VM."""
    return _env_path("BAR_ARTIFACTS_DIR", "/mnt/artifacts")


def artifacts_bucket_dir() -> Path:
    """GCS FUSE mount scoped to the artifacts bucket root — shared,
    content-addressed artifacts (engine, bar-content, map). Read-only on
    the VM. Runner resolves keys from manifest["paths"] against this."""
    return _env_path("BAR_ARTIFACTS_BUCKET_DIR", "/mnt/artifacts-bucket")


def results_dir() -> Path:
    """GCS FUSE mount the collector writes results.json into, scoped per job."""
    return _env_path("BAR_RESULTS_DIR", "/mnt/results")


def data_dir() -> Path:
    """Local --write-dir for spring-headless; holds games/, maps/, benchmark-results.json."""
    return _env_path("BAR_DATA_DIR", "/var/bar-data")


def run_dir() -> Path:
    """Local task scratch for verdict.json."""
    return _env_path("BAR_RUN_DIR", "/var/bar-run")


def engine_dir() -> Path:
    """Local extraction target for engine.tar.gz."""
    return _env_path("BAR_ENGINE_DIR", "/opt/recoil")


def benchmark_output_path() -> Path:
    """Absolute path of the overlay's benchmark JSON, relative to data_dir()."""
    rel = os.environ.get("BAR_BENCHMARK_OUTPUT_PATH", "benchmark-results.json")
    return data_dir() / rel


def batch_task_index() -> str:
    """Injected by Batch on the VM; defaults to '0' for dev smoke runs."""
    return os.environ.get("BATCH_TASK_INDEX", "0")
