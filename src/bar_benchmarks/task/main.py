"""Task-side entrypoint: invoke the runner."""

from __future__ import annotations

from bar_benchmarks.task import runner


def main() -> int:
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
