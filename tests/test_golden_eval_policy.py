from pathlib import Path

from scripts.golden_eval_policy import (
    BLOCKING_TEST_IDS,
    GOLDEN_TOTAL_MAX_SCORE,
    case_blocks_release,
    case_requires_lawyer_review,
    classify_golden_run,
    summarize_golden_dataset,
    validate_golden_dataset,
)

DATASET = Path("tests/evaluation/legal_agent_golden_dataset_uk.md")


def test_golden_dataset_structure_is_valid() -> None:
    summary = summarize_golden_dataset(DATASET)

    assert validate_golden_dataset(DATASET) == []
    assert len(summary.test_ids) == 30
    assert summary.test_ids[0] == "TEST-001"
    assert summary.test_ids[-1] == "TEST-030"
    assert summary.max_score == GOLDEN_TOTAL_MAX_SCORE == 120
    assert set(summary.blocking_test_ids) == BLOCKING_TEST_IDS


def test_golden_run_classification_release_gate() -> None:
    result = classify_golden_run(108)

    assert result.status == "pilot_ready_with_lawyer_control"
    assert result.release_ready is True
    assert result.lawyer_review_required is True


def test_golden_run_blocks_on_critical_scenario_even_with_high_score() -> None:
    result = classify_golden_run(118, failed_blocking_test_ids={"TEST-021"})

    assert result.status == "blocked_critical"
    assert result.release_ready is False
    assert result.failed_blocking_test_ids == ["TEST-021"]


def test_golden_run_lower_bands_require_remediation() -> None:
    assert classify_golden_run(100).status == "targeted_fixes_required"
    assert classify_golden_run(80).status == "unstable_deep_review_required"
    assert classify_golden_run(71).status == "not_usable_for_legal_practice"


def test_case_level_lawyer_review_and_release_blocking() -> None:
    assert case_requires_lawyer_review(4) is False
    assert case_requires_lawyer_review(3) is True
    assert case_requires_lawyer_review(4, critical_error=True) is True
    assert case_blocks_release("TEST-014", 3) is True
    assert case_blocks_release("TEST-001", 3) is False
    assert case_blocks_release("TEST-001", 4, critical_error=True) is True
