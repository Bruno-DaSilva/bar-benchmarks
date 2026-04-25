"""Attach compute-cost fields to a BatchReport.

Cost is estimated from the per-iteration `engine_wall_s` recorded by the
runner plus a flat per-VM overhead, then priced at the instance's spot
rate from `pricing`.

Per-VM framing (this is the part that's easy to misread):

- `engine_wall_s` on a `Result` is **one iteration's** wall time —
  measured by `runner._invoke_engine` around a single `spring-headless`
  invocation. Each VM (one Batch task_index) emits N results, one per
  iteration.
- The natural cost unit is per VM. A VM that runs N iterations only
  boots once, so we charge:

      per_vm_billable_s = Σ engine_wall_s of that VM's iterations + 120

  The 120s is a flat per-VM estimate for boot, artifact staging, and
  collector/teardown — it is NOT per-iteration.
- The batch total is the sum of per-VM billables across all VMs,
  equivalent to:

      total_billable_s = Σ engine_wall_s (all results) + 120 × vm_count

We deliberately ignore PENDING / queue time: GCP doesn't bill for time
the task spent waiting for a VM to be provisioned.

`apply_cached` is the counterpart for `bar-bench lookup`: a cache-hit
re-uses prior results at $0.
"""

from __future__ import annotations

from collections.abc import Iterable

from bar_benchmarks.stats.pricing import spot_usd_per_hour
from bar_benchmarks.types import BatchReport, Result

PER_VM_OVERHEAD_S: float = 120.0


def _billable_s_from_results(results: Iterable[Result], vm_count: int) -> float:
    """Sum per-iteration engine wall time + flat per-VM overhead.

    `engine_wall_s` is per-iteration; `vm_count` is the number of VMs in
    the batch (each runs ≥1 iteration). Equivalent to the per-VM
    formulation `Σ_vm (Σ_iter engine_wall_s + 120)`.
    """
    total = 0.0
    for r in results:
        wall = r.run.engine_wall_s
        if wall is not None:
            total += wall
    total += PER_VM_OVERHEAD_S * vm_count
    return total


def apply_from_results(
    report: BatchReport,
    *,
    results: Iterable[Result],
    vm_count: int,
) -> BatchReport:
    """Attach billable-seconds and cost fields to the report.

    Inputs are the per-iteration `Result` objects (already loaded by the
    caller for aggregation) and `vm_count` — the number of VMs the batch
    submitted, NOT the iteration-count. Skips silently when the report
    has no instance shape to price against.
    """
    if not report.instance_type or not report.region:
        return report

    billable_s = _billable_s_from_results(results, vm_count)
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
