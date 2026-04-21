"""Tiny helper used by fake-runner.sh and fake-orchestrator.sh to look up
artifact URIs in scripts/artifacts.toml.

Usage: python3 _catalog.py <catalog-path> <type> <name>
Prints the gs:// URI on stdout, or exits non-zero with an error on stderr.
"""

from __future__ import annotations

import sys
import tomllib

VALID_TYPES = ("engine", "bar_content", "overlay", "map", "startscript")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        sys.stderr.write("usage: _catalog.py <catalog-path> <type> <name>\n")
        return 2

    catalog_path, type_, name = argv[1], argv[2], argv[3]

    if type_ not in VALID_TYPES:
        sys.stderr.write(f"unknown artifact type {type_!r}; expected one of {VALID_TYPES}\n")
        return 2

    with open(catalog_path, "rb") as f:
        data = tomllib.load(f)

    section = data.get(type_, {})
    if name not in section:
        sys.stderr.write(f"no entry named {name!r} in [{type_}] of {catalog_path}\n")
        return 1

    print(section[name])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
