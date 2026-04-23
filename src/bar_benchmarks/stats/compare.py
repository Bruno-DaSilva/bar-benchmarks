"""Welch's t-test comparison of two BatchReports.

The sample unit is per-VM sim frame-time mean (``PerVmSim.mean_ms``): each
VM contributes one independent observation. We emit a Welch two-sided CI
on the mean difference (candidate − baseline), rescaled to percent of the
baseline mean. Uses scipy for the t-distribution numerics.
"""

from __future__ import annotations

import math
import statistics

from scipy import stats as scipy_stats

from bar_benchmarks.types import BatchReport, ComparisonReport


def compare(
    cand_report: BatchReport,
    base_report: BatchReport,
    *,
    alpha: float = 0.05,
) -> ComparisonReport:
    """Compare candidate vs baseline BatchReports, returning a Welch CI."""
    cand = [p.mean_ms for p in cand_report.per_vm]
    base = [p.mean_ms for p in base_report.per_vm]
    return _build(
        cand_job_uid=cand_report.job_uid,
        base_job_uid=base_report.job_uid,
        cand=cand,
        base=base,
        alpha=alpha,
    )


def _build(
    *,
    cand_job_uid: str,
    base_job_uid: str,
    cand: list[float],
    base: list[float],
    alpha: float,
) -> ComparisonReport:
    n_c, n_b = len(cand), len(base)
    mean_c = statistics.fmean(cand) if cand else None
    mean_b = statistics.fmean(base) if base else None

    # Need n >= 2 on both sides for an unbiased variance and a usable CI.
    if n_c < 2 or n_b < 2 or mean_c is None or mean_b is None:
        return ComparisonReport(
            cand_job_uid=cand_job_uid,
            base_job_uid=base_job_uid,
            n_cand=n_c,
            n_base=n_b,
            cand_mean_ms=mean_c,
            base_mean_ms=mean_b,
            alpha=alpha,
        )

    var_c = statistics.variance(cand)
    var_b = statistics.variance(base)
    se_sq = var_c / n_c + var_b / n_b
    se = math.sqrt(se_sq)
    delta = mean_c - mean_b

    # Welch-Satterthwaite df. Degenerates when both variances are zero;
    # in that case the CI collapses to the point estimate.
    if se == 0.0:
        t_stat = 0.0 if delta == 0.0 else math.copysign(math.inf, delta)
        df = float("inf")
        low = high = delta
    else:
        df_num = se_sq * se_sq
        df_den = (var_c / n_c) ** 2 / (n_c - 1) + (var_b / n_b) ** 2 / (n_b - 1)
        df = df_num / df_den if df_den > 0 else float("inf")
        t_crit = float(scipy_stats.t.ppf(1.0 - alpha / 2.0, df))
        t_stat = delta / se
        low = delta - t_crit * se
        high = delta + t_crit * se

    if mean_b != 0:
        delta_pct = delta / mean_b * 100.0
        pct_low = low / mean_b * 100.0
        pct_high = high / mean_b * 100.0
    else:
        delta_pct = pct_low = pct_high = None

    significant = low > 0 or high < 0

    return ComparisonReport(
        cand_job_uid=cand_job_uid,
        base_job_uid=base_job_uid,
        n_cand=n_c,
        n_base=n_b,
        cand_mean_ms=mean_c,
        base_mean_ms=mean_b,
        delta_ms=delta,
        delta_ms_low=low,
        delta_ms_high=high,
        delta_pct=delta_pct,
        delta_pct_low=pct_low,
        delta_pct_high=pct_high,
        t_stat=t_stat,
        df=df,
        alpha=alpha,
        significant=significant,
    )


def print_comparison(cmp: ComparisonReport) -> None:
    """Human-readable comparison output, mirroring aggregate.print_report."""
    print(f"\n=== Compare {cmp.cand_job_uid} vs {cmp.base_job_uid} ===")
    print(f"candidate: mean= {_fmt(cmp.cand_mean_ms)}ms  (n={cmp.n_cand})")
    print(f"baseline:  mean= {_fmt(cmp.base_mean_ms)}ms  (n={cmp.n_base})")
    if cmp.delta_ms is None:
        print("insufficient samples for Welch CI (need n ≥ 2 per side)")
        return
    print(
        f"Δ = {cmp.delta_ms:+.3f}ms  "
        f"95% CI [{cmp.delta_ms_low:+.3f}, {cmp.delta_ms_high:+.3f}]ms"
    )
    if cmp.delta_pct is not None:
        print(
            f"Δ = {cmp.delta_pct:+.2f}%  "
            f"95% CI [{cmp.delta_pct_low:+.2f}%, {cmp.delta_pct_high:+.2f}%]  "
            f"{'SIGNIFICANT' if cmp.significant else 'not significant'}"
        )
    print(f"t={cmp.t_stat:.3f}  df={cmp.df:.2f}  alpha={cmp.alpha}")


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"
