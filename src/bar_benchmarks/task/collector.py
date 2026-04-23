"""Merge runner verdict + overlay benchmark into results.json.

Runs as the final `alwaysRun` runnable; writes to the GCS-FUSE-mounted
results directory under `<task_index>/results.json`. The job_uid scoping
is handled by the Job's `volumes[].remote_path`.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bar_benchmarks import paths
from bar_benchmarks.types import (
    ArtifactNames,
    Result,
    RunnerVerdict,
)

INFOLOG_FILENAME = "infolog.txt"


def _load_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    return json.loads(p.read_text())


def _verdict() -> RunnerVerdict:
    data = _load_json(paths.run_dir() / "verdict.json")
    if data is None:
        now = datetime.now(UTC)
        return RunnerVerdict(
            started_at=now,
            ended_at=now,
            engine_exit=-1,
            error="runner_did_not_run",
        )
    return RunnerVerdict.model_validate(data)


def _benchmark() -> dict[str, Any]:
    data = _load_json(paths.benchmark_output_path())
    return data if data is not None else {}


def run() -> Result:
    artifacts = paths.artifacts_dir()
    manifest = json.loads((artifacts / "manifest.json").read_text())

    verdict = _verdict()
    result = Result(
        batch_id=manifest["job_uid"],
        vm_id=paths.batch_task_index(),
        instance_type=manifest["instance_type"],
        region=manifest["region"],
        artifact_names=ArtifactNames(**manifest["artifact_names"]),
        run=verdict,
        benchmark=_benchmark(),
        invalid_reason=verdict.error,
    )

    out_dir = paths.results_dir() / paths.batch_task_index()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "results.json"
    out.write_text(json.dumps(result.model_dump(mode="json"), indent=2))

    infolog = paths.data_dir() / INFOLOG_FILENAME
    if infolog.is_file():
        shutil.copy2(infolog, out_dir / INFOLOG_FILENAME)

    return result


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
