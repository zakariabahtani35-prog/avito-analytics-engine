import pytest

from src.validation.data_quality_checks import QualityResult, assert_quality_results


def test_assert_quality_results_passes_when_all_checks_pass() -> None:
    results = [QualityResult("check", True, 0, "ok")]

    assert_quality_results(results)


def test_assert_quality_results_raises_with_failure_summary() -> None:
    results = [
        QualityResult("positive_price", False, 2, "bad price"),
        QualityResult("ml_count_equals_clean_count", True, 0, "ok"),
    ]

    with pytest.raises(AssertionError, match="positive_price=2"):
        assert_quality_results(results)
