#!/usr/bin/env bash
# Publish a single local artifact to its gs:// URI as defined in the artifact
# catalog (scripts/artifacts.toml). Pairs with scripts/fake-runner.sh, which
# downloads named artifacts from the same catalog.
#
# Workflow: add an entry to the catalog (e.g. `[engine] recoil-2025-05 =
# "gs://bar-experiments-bench-artifacts/engine/recoil-2025-05.tar.gz"`),
# then run this script with the local file you want to publish under that
# name. The script uploads to the URI the catalog points at; it does not
# mutate the catalog.

set -euo pipefail

DEFAULT_CATALOG="scripts/artifacts.toml"

usage() {
  cat >&2 <<'EOF'
Usage: fake-orchestrator.sh ( --engine NAME
                            | --bar-content NAME
                            | --overlay NAME
                            | --map NAME
                            | --startscript NAME )
                            FILE
                            [--catalog scripts/artifacts.toml]
                            [--dry-run]

Exactly one of the artifact-type flags is required, naming the catalog entry
to publish. FILE is the local file whose bytes will be uploaded to the
gs:// URI that the catalog assigns to that name. Add the catalog entry by
hand first; this script will not register new names.
EOF
  exit 2
}

# ---- arg parsing ----

art_type=""
art_name=""
catalog="$DEFAULT_CATALOG"
file=""
dry_run=0

set_type() {
  if [[ -n "$art_type" ]]; then
    echo "only one artifact-type flag may be set (got --${art_type//_/-} and --$1)" >&2
    usage
  fi
  art_type="$2"
  art_name="$3"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --engine)       set_type engine engine "$2"; shift 2 ;;
    --bar-content)  set_type bar-content bar_content "$2"; shift 2 ;;
    --overlay)      set_type overlay overlay "$2"; shift 2 ;;
    --map)          set_type map map "$2"; shift 2 ;;
    --startscript)  set_type startscript startscript "$2"; shift 2 ;;
    --catalog)      catalog="$2"; shift 2 ;;
    --dry-run)      dry_run=1; shift ;;
    -h|--help)      usage ;;
    --)             shift; break ;;
    -*)             echo "unknown arg: $1" >&2; usage ;;
    *)
      if [[ -n "$file" ]]; then
        echo "extra positional arg: $1 (FILE already set to $file)" >&2
        usage
      fi
      file="$1"; shift ;;
  esac
done

# Anything remaining after `--` is the file.
if [[ -z "$file" && $# -gt 0 ]]; then
  file="$1"; shift
fi

if [[ -z "$art_type" ]]; then
  echo "must set one of --engine|--bar-content|--overlay|--map|--startscript" >&2
  usage
fi
if [[ -z "$file" ]]; then
  echo "missing FILE positional arg" >&2
  usage
fi
if [[ ! -f "$file" || ! -r "$file" ]]; then
  echo "not a readable file: $file" >&2
  exit 1
fi

# ---- pre-flight tooling ----

command -v gcloud  >/dev/null || { echo "gcloud not found on PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2; exit 1; }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
script_dir="$(cd "$(dirname "$0")" && pwd)"

case "$catalog" in
  /*) ;;
  *)  catalog="$repo_root/$catalog" ;;
esac

if [[ ! -f "$catalog" ]]; then
  echo "catalog not found: $catalog" >&2
  exit 1
fi

# ---- resolve URI from catalog ----

uri="$(python3 "$script_dir/_catalog.py" "$catalog" "$art_type" "$art_name")" || exit 1

# Sanity-check map filename consistency: the runner takes the on-disk filename
# from the URI's basename (see fake-runner.sh staging step), so a map entry
# whose URI ends in "tiny.smf" published from a local "small.smf" would silently
# rename the file. Warn but don't block.
if [[ "$art_type" == "map" ]]; then
  uri_base="$(basename "$uri")"
  file_base="$(basename "$file")"
  if [[ "$uri_base" != "$file_base" ]]; then
    echo "[fake-orch] note: local map filename ($file_base) differs from catalog URI basename ($uri_base); the URI basename wins" >&2
  fi
fi

echo "[fake-orch] type=$art_type  name=$art_name" >&2
echo "[fake-orch] file=$file" >&2
echo "[fake-orch] dest=$uri" >&2

if [[ $dry_run -eq 1 ]]; then
  echo "[fake-orch] --dry-run, skipping upload" >&2
  exit 0
fi

gcloud storage cp "$file" "$uri"
echo "[fake-orch] uploaded" >&2
