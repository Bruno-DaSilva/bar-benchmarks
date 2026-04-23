"""Attach compute-cost fields to a BatchReport.

Ground truth comes from the Batch API: each task exposes
`status_events` with PENDING / ASSIGNED / RUNNING / SUCCEEDED|FAILED
timestamps, and the PENDING→final window is the closest proxy to the
per-VM billable time. Sum across tasks, multiply by the spot rate from
`pricing`, and write the numbers onto the report.

`apply_cached` is the counterpart for `bar-bench lookup`: a cache-hit
re-uses prior results at $0.
"""

from __future__ import annotations

import sys
from typing import Any

from bar_benchmarks.stats.pricing import spot_usd_per_hour
from bar_benchmarks.types import BatchReport


def _billable_s_from_tasks(tasks: list[Any]) -> float:
    """Sum PENDING→SUCCEEDED|FAILED windows across tasks, in seconds."""
    total = 0.0
    for t in tasks:
        pending_ts: float | None = None
        final_ts: float | None = None
        for ev in t.status.status_events:
            state = ev.task_state.name
            ts = ev.event_time.timestamp()
            if state == "PENDING" and pending_ts is None:
                pending_ts = ts
            elif state in ("SUCCEEDED", "FAILED"):
                final_ts = ts
        if pending_ts is not None and final_ts is not None:
            total += final_ts - pending_ts
    return total


def apply_from_batch_api(
    report: BatchReport,
    *,
    project: str,
) -> BatchReport:
    """Fetch task timings from the Batch API and attach cost to the report.

    On any API failure (job GC'd, permission, network) the report is
    returned unchanged — cost stays None and `print_report` skips the
    line. Uses the report's own `region` (and implicitly `group0` task
    group, which `batch_submitter.build_job` hardcodes).
    """
    if not report.instance_type or not report.region:
        return report
    try:
        from google.cloud import batch_v1

        client = batch_v1.BatchServiceClient()
        parent = (
            f"projects/{project}/locations/{report.region}/jobs/"
            f"{report.job_uid}/taskGroups/group0"
        )
        tasks = list(client.list_tasks(parent=parent))
    except Exception as exc:  # noqa: BLE001 — any failure → skip cost
        print(
            f"[cost] batch api unavailable ({type(exc).__name__}: {exc}); "
            f"no cost attached to report",
            file=sys.stderr,
        )
        return report

    billable_s = _billable_s_from_tasks(tasks)
    rate = spot_usd_per_hour(report.instance_type, report.region)
    compute_usd = billable_s / 3600 * rate if rate is not None else None
    return report.model_copy(
        update={
            "total_billable_s": billable_s,
            "price_per_vm_hour_usd": rate,
            "compute_usd": compute_usd,
        }
    )


def apply_cached(report: BatchReport) -> BatchReport:
    """Flag a cache-hit run as free and zero out cost fields."""
    return report.model_copy(
        update={
            "cached": True,
            "total_billable_s": 0.0,
            "price_per_vm_hour_usd": None,
            "compute_usd": 0.0,
        }
    )
