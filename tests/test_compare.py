from __future__ import annotations

import math

import pytest

from bar_benchmarks.stats import compare as compare_mod
from bar_benchmarks.types import BatchReport, PerVmSim


def _report(job_uid: str, means: list[float]) -> BatchReport:
    return BatchReport(
        job_uid=job_uid,
        submitted=len(means),
        valid=len(means),
        invalid=0,
        per_vm=[PerVmSim(vm_id=f"vm-{i}", mean_ms=m) for i, m in enumerate(means)],
    )


def test_welch_ci_matches_scipy_reference() -> None:
    # Reference computed via scipy.stats.ttest_ind(..., equal_var=False)
    # .confidence_interval(0.95) — candidate is ~1% slower, significant.
    cand = [22.1, 22.3, 22.0, 22.5, 22.2, 22.4, 22.1, 22.3, 22.2, 22.4]
    base = [22.0, 21.9, 22.1, 22.2, 22.0, 21.8, 22.1, 22.0, 22.1, 22.0]
    cmp = compare_mod.compare(_report("cand", cand), _report("base", base))

    assert cmp.delta_ms == pytest.approx(0.23, abs=1e-9)
    assert cmp.delta_ms_low == pytest.approx(0.099726, abs=1e-5)
    assert cmp.delta_ms_high == pytest.approx(0.360274, abs=1e-5)
    assert cmp.t_stat == pytest.approx(3.736559, abs=1e-5)
    assert cmp.df == pytest.approx(16.331346, abs=1e-5)
    assert cmp.significant is True
    # baseline mean = 22.02 → percent CI is ~[0.45%, 1.64%]
    assert cmp.delta_pct_low == pytest.approx(0.099726 / 22.02 * 100, abs=1e-5)
    assert cmp.delta_pct_high == pytest.approx(0.360274 / 22.02 * 100, abs=1e-5)


def test_identical_samples_ci_spans_zero() -> None:
    samples = [10.0, 11.0, 12.0, 13.0, 14.0]
    cmp = compare_mod.compare(_report("c", samples), _report("b", samples))

    assert cmp.delta_ms == 0.0
    assert cmp.t_stat == 0.0
    assert cmp.df == pytest.approx(8.0, abs=1e-9)
    # scipy reference: CI = [-2.306004, 2.306004]
    assert cmp.delta_ms_low == pytest.approx(-2.306004, abs=1e-5)
    assert cmp.delta_ms_high == pytest.approx(2.306004, abs=1e-5)
    assert cmp.significant is False


def test_zero_variance_both_sides() -> None:
    cmp = compare_mod.compare(_report("c", [5.0, 5.0]), _report("b", [4.0, 4.0]))
    assert cmp.delta_ms == pytest.approx(1.0)
    assert cmp.delta_ms_low == pytest.approx(1.0)
    assert cmp.delta_ms_high == pytest.approx(1.0)
    # delta != 0 with SE=0 → infinite t; flagged significant.
    assert math.isinf(cmp.t_stat)
    assert cmp.significant is True


def test_insufficient_samples_returns_null_ci() -> None:
    cmp = compare_mod.compare(_report("c", [5.0]), _report("b", [4.0, 4.2, 4.1]))
    assert cmp.n_cand == 1
    assert cmp.n_base == 3
    assert cmp.delta_ms is None
    assert cmp.t_stat is None
    assert cmp.df is None
    assert cmp.significant is False
    # Means are still populated when available.
    assert cmp.cand_mean_ms == pytest.approx(5.0)
    assert cmp.base_mean_ms == pytest.approx(4.1)


def test_empty_report() -> None:
    cmp = compare_mod.compare(_report("c", []), _report("b", [1.0, 2.0]))
    assert cmp.n_cand == 0
    assert cmp.cand_mean_ms is None
    assert cmp.delta_ms is None


def test_alpha_passthrough_widens_ci() -> None:
    samples_c = [10.0, 10.5, 11.0, 10.8, 10.2]
    samples_b = [9.8, 10.0, 10.1, 9.9, 10.0]
    cmp95 = compare_mod.compare(_report("c", samples_c), _report("b", samples_b), alpha=0.05)
    cmp99 = compare_mod.compare(_report("c", samples_c), _report("b", samples_b), alpha=0.01)

    width_95 = cmp95.delta_ms_high - cmp95.delta_ms_low
    width_99 = cmp99.delta_ms_high - cmp99.delta_ms_low
    assert width_99 > width_95
    assert cmp99.alpha == 0.01
    assert cmp95.alpha == 0.05
