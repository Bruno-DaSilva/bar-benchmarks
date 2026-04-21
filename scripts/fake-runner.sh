#!/usr/bin/env bash
# Run the task-side pipeline (preflight + runner from src/bar_benchmarks/task/)
# locally against real artifacts pulled from GCS, with a persistent on-disk
# cache so re-runs skip the download. Mirrors the on-VM environment: lays out
# the same dirs that paths.py expects, sets the same BAR_* env vars that
# orchestrator/batch_submitter.py:18-25 sets in production, then invokes
# `python -m bar_benchmarks.task.main`.
#
# Pick artifacts by name from scripts/artifacts.toml (the artifact catalog).
# Each name resolves to a gs:// URI and is independent of any job submission,
# so the same engine can be paired with different content versions and vice
# versa. Use scripts/fake-orchestrator.sh to publish a new artifact under a
# name in the catalog.

set -euo pipefail

DEFAULT_CATALOG="scripts/artifacts.toml"
DEFAULT_WORKDIR=".smoke/fake-runner"

usage() {
  cat >&2 <<'EOF'
Usage:
  fake-runner.sh --engine NAME --bar-content NAME --overlay NAME \
                 --map NAME --startscript NAME
                 [--catalog scripts/artifacts.toml]
                 [--workdir .smoke/fake-runner]
                 [--clean-cache]

Names refer to entries in the catalog (default scripts/artifacts.toml).
Downloaded artifacts are cached under <workdir>/cache/<bucket>/<key> so
subsequent runs skip the network. The runner's working tree
(<workdir>/{artifacts,data,run,engine,results}) is wiped at the start of
each run to give the runner a fresh-VM look.
EOF
  exit 2
}

# ---- arg parsing ----

engine_name=""
bar_content_name=""
overlay_name=""
map_name=""
startscript_name=""
catalog="$DEFAULT_CATALOG"
workdir="$DEFAULT_WORKDIR"
clean_cache=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --engine) engine_name="$2"; shift 2 ;;
    --bar-content) bar_content_name="$2"; shift 2 ;;
    --overlay) overlay_name="$2"; shift 2 ;;
    --map) map_name="$2"; shift 2 ;;
    --startscript) startscript_name="$2"; shift 2 ;;
    --catalog) catalog="$2"; shift 2 ;;
    --workdir) workdir="$2"; shift 2 ;;
    --clean-cache) clean_cache=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

for var in engine_name bar_content_name overlay_name map_name startscript_name; do
  if [[ -z "${!var}" ]]; then
    echo "missing required flag: --${var%_name}" >&2
    usage
  fi
done

# ---- pre-flight tooling ----

command -v gcloud  >/dev/null || { echo "gcloud not found on PATH" >&2; exit 1; }
command -v uv      >/dev/null || { echo "uv not found on PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2; exit 1; }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
script_dir="$(cd "$(dirname "$0")" && pwd)"

# Resolve paths (workdir + catalog) relative to the repo root if given as relative.
case "$workdir" in
  /*) ;;
  *)  workdir="$repo_root/$workdir" ;;
esac
case "$catalog" in
  /*) ;;
  *)  catalog="$repo_root/$catalog" ;;
esac

if [[ ! -f "$catalog" ]]; then
  echo "catalog not found: $catalog" >&2
  exit 1
fi

cache_dir="$workdir/cache"
artifacts_dir="$workdir/artifacts"
data_dir="$workdir/data"
run_dir="$workdir/run"
engine_dir="$workdir/engine"
results_dir="$workdir/results"

# ---- resolve artifact URIs from the catalog ----

lookup() {
  python3 "$script_dir/_catalog.py" "$catalog" "$1" "$2"
}

engine_uri="$(lookup engine "$engine_name")"             || exit 1
bar_content_uri="$(lookup bar_content "$bar_content_name")" || exit 1
overlay_uri="$(lookup overlay "$overlay_name")"          || exit 1
map_uri="$(lookup map "$map_name")"                      || exit 1
startscript_uri="$(lookup startscript "$startscript_name")" || exit 1
map_basename="$(basename "$map_uri")"

# ---- cache layout: <cache_dir>/<bucket>/<key> ----

# Convert "gs://bucket/path/to/blob" -> "<cache>/bucket/path/to/blob"
cache_path_for() {
  local uri="$1"
  local stripped="${uri#gs://}"
  printf '%s/%s' "$cache_dir" "$stripped"
}

if [[ $clean_cache -eq 1 ]]; then
  echo "[fake-runner] --clean-cache: wiping $cache_dir" >&2
  rm -rf "$cache_dir"
fi

mkdir -p "$cache_dir"

fetch() {
  # Note: callers consume our stdout via $(), and `set -e` does NOT fire on a
  # failed assignment-from-substitution. So callers must use `|| exit 1`
  # explicitly. We `return 1` here on failure (exit would only kill the
  # subshell, not the parent).
  local uri="$1"
  local dest
  dest="$(cache_path_for "$uri")"
  if [[ -f "$dest" ]]; then
    echo "[fake-runner] cache hit: $uri" >&2
  else
    echo "[fake-runner] downloading: $uri" >&2
    mkdir -p "$(dirname "$dest")"
    if ! gcloud storage cp "$uri" "$dest" >&2; then
      echo "[fake-runner] download failed: $uri" >&2
      return 1
    fi
  fi
  printf '%s' "$dest"
}

engine_local="$(fetch "$engine_uri")"             || exit 1
bar_content_local="$(fetch "$bar_content_uri")"   || exit 1
overlay_local="$(fetch "$overlay_uri")"           || exit 1
startscript_local="$(fetch "$startscript_uri")"   || exit 1
map_local="$(fetch "$map_uri")"                   || exit 1

# ---- wipe + re-stage runtime dirs ----

echo "[fake-runner] staging working tree at $workdir" >&2
rm -rf "$artifacts_dir" "$data_dir" "$run_dir" "$engine_dir" "$results_dir"
mkdir -p "$artifacts_dir" "$data_dir" "$run_dir" "$engine_dir" "$results_dir"

# Symlink cached files into the staged artifacts dir under the canonical
# names runner.py expects (constants in src/bar_benchmarks/task/runner.py:22-27).
ln -s "$engine_local"      "$artifacts_dir/engine.tar.gz"
ln -s "$bar_content_local" "$artifacts_dir/bar-content.tar.gz"
ln -s "$overlay_local"     "$artifacts_dir/overlay.tar.gz"
ln -s "$startscript_local" "$artifacts_dir/startscript.txt"
ln -s "$map_local"         "$artifacts_dir/$map_basename"

# Synthesize a manifest: only map_filename is read by the runner
# (runner.py:79); the other fields are here so the collector won't choke if
# we later wire it in. Hash placeholders match the convention in
# tests/conftest.py:80-95.
cat >"$artifacts_dir/manifest.json" <<EOF
{
  "job_uid": "fake-runner-local",
  "region": "local",
  "instance_type": "local",
  "map_filename": "$map_basename",
  "artifact_hashes": {
    "engine": "$(printf '0%.0s' {1..64})",
    "bar_content": "$(printf '1%.0s' {1..64})",
    "overlay": "$(printf '2%.0s' {1..64})",
    "map": "$(printf '3%.0s' {1..64})",
    "startscript": "$(printf '4%.0s' {1..64})"
  },
  "wheel_filename": "bar_benchmarks-0.0.0-local.whl"
}
EOF

# ---- env mirror of orchestrator/batch_submitter.py:18-25 ----

export BAR_ARTIFACTS_DIR="$artifacts_dir"
export BAR_RESULTS_DIR="$results_dir"
export BAR_DATA_DIR="$data_dir"
export BAR_RUN_DIR="$run_dir"
export BAR_ENGINE_DIR="$engine_dir"
export BAR_BENCHMARK_OUTPUT_PATH="benchmark-results.json"
export BATCH_JOB_UID="fake-runner-local"
export BATCH_TASK_INDEX="0"

echo "[fake-runner] invoking python -m bar_benchmarks.task.main" >&2
set +e
(cd "$repo_root" && uv run python -m bar_benchmarks.task.main)
rc=$?
set -e

# ---- summary ----

verdict="$run_dir/verdict.json"
bench_out="$data_dir/benchmark-results.json"
bar_sdd="$data_dir/games/BAR.sdd"

echo >&2
echo "[fake-runner] task exit: $rc" >&2
echo "[fake-runner] verdict:        $verdict $( [[ -f $verdict ]] && echo '(present)' || echo '(missing)')" >&2
echo "[fake-runner] benchmark out:  $bench_out $( [[ -f $bench_out ]] && echo '(present)' || echo '(missing)')" >&2
echo "[fake-runner] BAR.sdd:        $bar_sdd $( [[ -d $bar_sdd ]] && echo '(present)' || echo '(missing)')" >&2

exit "$rc"
