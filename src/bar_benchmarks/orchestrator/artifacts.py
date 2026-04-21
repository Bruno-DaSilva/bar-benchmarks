"""Ensure the shared + per-job artifacts are in the bucket, then upload the manifest.

Bucket layout:

    gs://<artifacts-bucket>/
        engine/<name>.tar.gz                     (shared across jobs)
        bar-content/<name>.tar.gz                (shared across jobs)
        maps/<map_filename>                      (shared across jobs)
        <job_uid>/
            overlay.tar.gz
            startscript.txt
            bar_benchmarks-<ver>-py3-none-any.whl
            manifest.json

Shared keys are derived from the catalog name (not content hash) so we
can decide whether to skip a build before we have the tarball on disk.
On cache miss, we shell out to scripts/build-*.sh to materialize the
tarball locally, then upload.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bar_benchmarks.orchestrator import build
from bar_benchmarks.orchestrator.catalog import Catalog, key_from_uri
from bar_benchmarks.types import ArtifactNames, BatchConfig


@dataclass(frozen=True)
class UploadPlan:
    names: ArtifactNames
    shared_keys: dict[str, str]  # "engine" | "bar_content" | "map" -> bucket key
    map_filename: str
    wheel_filename: str
    key_prefix: str  # "<job_uid>/"
    job_uploads: dict[str, Path]  # filename under key_prefix -> local source


def build_wheel(project_root: Path) -> Path:
    """Build the current project's wheel into dist/ and return its path."""
    dist = project_root / "dist"
    for existing in dist.glob("*.whl"):
        existing.unlink()
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=project_root,
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        raise RuntimeError("uv build produced no wheel")
    return wheels[-1]


def plan(
    cfg: BatchConfig,
    job_uid: str,
    *,
    cat: Catalog,
    overlay: Path,
    wheel: Path,
) -> UploadPlan:
    engine = cat.engine(cfg.engine_name)
    bar = cat.bar_content(cfg.bar_content_name)
    mp = cat.map(cfg.map_name)

    _, engine_key = key_from_uri(engine.dest_uri)
    _, bar_key = key_from_uri(bar.dest_uri)
    _, map_key = key_from_uri(mp.dest_uri)
    map_filename = Path(map_key).name

    job_uploads = {
        "overlay.tar.gz": overlay,
        "startscript.txt": cfg.scenario_dir / "startscript.txt",
        wheel.name: wheel,
    }
    return UploadPlan(
        names=ArtifactNames(
            engine=cfg.engine_name,
            bar_content=cfg.bar_content_name,
            map=cfg.map_name,
        ),
        shared_keys={"engine": engine_key, "bar_content": bar_key, "map": map_key},
        map_filename=map_filename,
        wheel_filename=wheel.name,
        key_prefix=f"{job_uid}/",
        job_uploads=job_uploads,
    )


def manifest_bytes(cfg: BatchConfig, job_uid: str, plan_: UploadPlan) -> bytes:
    body = {
        "job_uid": job_uid,
        "region": cfg.region,
        "instance_type": cfg.machine_type,
        "map_filename": plan_.map_filename,
        "artifact_names": plan_.names.model_dump(),
        "paths": plan_.shared_keys,
        "wheel_filename": plan_.wheel_filename,
    }
    return json.dumps(body, indent=2, sort_keys=True).encode()


def ensure_and_upload(
    bucket_name: str,
    cfg: BatchConfig,
    plan_: UploadPlan,
    manifest: bytes,
    *,
    cat: Catalog,
    project: str | None = None,
    client=None,
    on_upload: Callable[[str, bool], None] | None = None,
) -> None:
    """Ensure shared blobs exist in the bucket (build+upload on miss),
    then upload per-job blobs + manifest unconditionally.

    `on_upload(uri, cached)` fires for every bucket key touched.
    """
    if client is None:
        from google.cloud import storage  # lazy import so tests don't need creds

        client = storage.Client(project=project)
    if on_upload is None:
        def on_upload(uri: str, cached: bool) -> None:
            verb = "cached" if cached else "uploading"
            print(f"[run] {verb} → {uri}", file=sys.stderr)

    bucket = client.bucket(bucket_name)

    def _ensure_shared(kind: str, ensure_local: Callable[[], Path]) -> None:
        key = plan_.shared_keys[kind]
        uri = f"gs://{bucket_name}/{key}"
        blob = bucket.blob(key)
        if blob.exists():
            on_upload(uri, True)
            return
        local = ensure_local()
        on_upload(uri, False)
        blob.upload_from_filename(str(local))

    scratch = build.workdir()
    _ensure_shared("engine", lambda: build.build_engine(cat.engine(cfg.engine_name), scratch))
    _ensure_shared(
        "bar_content",
        lambda: build.build_bar_content(cat.bar_content(cfg.bar_content_name), scratch),
    )
    _ensure_shared("map", lambda: build.fetch_map(cat.map(cfg.map_name), scratch))

    for name, src in plan_.job_uploads.items():
        key = plan_.key_prefix + name
        uri = f"gs://{bucket_name}/{key}"
        on_upload(uri, False)
        bucket.blob(key).upload_from_filename(str(src))

    manifest_key = plan_.key_prefix + "manifest.json"
    on_upload(f"gs://{bucket_name}/{manifest_key}", False)
    bucket.blob(manifest_key).upload_from_string(manifest, content_type="application/json")
