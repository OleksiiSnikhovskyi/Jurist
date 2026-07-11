from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GOLDEN_DATASET_PATH = Path("tests/evaluation/legal_agent_golden_dataset_uk.md")
GOLDEN_TEST_COUNT = 30
GOLDEN_CASE_MAX_SCORE = 4
GOLDEN_TOTAL_MAX_SCORE = GOLDEN_TEST_COUNT * GOLDEN_CASE_MAX_SCORE
PILOT_READY_MIN_SCORE = 108
TARGETED_FIXES_MIN_SCORE = 90
UNSTABLE_MIN_SCORE = 72
BLOCKING_TEST_IDS = frozenset({"TEST-014", "TEST-016", "TEST-020", "TEST-021", "TEST-022"})


@dataclass(frozen=True)
class GoldenDatasetSummary:
    path: Path
    test_ids: list[str]
    blocking_test_ids: list[str]
    max_score: int
    pilot_ready_min_score: int
    targeted_fixes_min_score: int
    unstable_min_score: int


@dataclass(frozen=True)
class GoldenRunClassification:
    total_score: int
    max_score: int
    status: str
    release_ready: bool
    lawyer_review_required: bool
    failed_blocking_test_ids: list[str]
    notes: str


def summarize_golden_dataset(path: Path = GOLDEN_DATASET_PATH) -> GoldenDatasetSummary:
    text = path.read_text(encoding="utf-8")
    test_ids = extract_test_ids(text)
    blocking_ids = sorted(BLOCKING_TEST_IDS.intersection(test_ids))
    return GoldenDatasetSummary(
        path=path,
        test_ids=test_ids,
        blocking_test_ids=blocking_ids,
        max_score=len(test_ids) * GOLDEN_CASE_MAX_SCORE,
        pilot_ready_min_score=PILOT_READY_MIN_SCORE,
        targeted_fixes_min_score=TARGETED_FIXES_MIN_SCORE,
        unstable_min_score=UNSTABLE_MIN_SCORE,
    )


def extract_test_ids(markdown: str) -> list[str]:
    return re.findall(r"^###\s+(TEST-\d{3})\b", markdown, flags=re.MULTILINE)


def classify_golden_run(
    total_score: int,
    *,
    failed_blocking_test_ids: set[str] | None = None,
    max_score: int = GOLDEN_TOTAL_MAX_SCORE,
) -> GoldenRunClassification:
    failed_blocking = sorted((failed_blocking_test_ids or set()).intersection(BLOCKING_TEST_IDS))
    if failed_blocking:
        return GoldenRunClassification(
            total_score=total_score,
            max_score=max_score,
            status="blocked_critical",
            release_ready=False,
            lawyer_review_required=True,
            failed_blocking_test_ids=failed_blocking,
            notes="Release blocked by a critical golden-dataset scenario.",
        )
    if total_score >= PILOT_READY_MIN_SCORE:
        return GoldenRunClassification(
            total_score=total_score,
            max_score=max_score,
            status="pilot_ready_with_lawyer_control",
            release_ready=True,
            lawyer_review_required=True,
            failed_blocking_test_ids=[],
            notes="Eligible for pilot use only under lawyer supervision.",
        )
    if total_score >= TARGETED_FIXES_MIN_SCORE:
        return GoldenRunClassification(
            total_score=total_score,
            max_score=max_score,
            status="targeted_fixes_required",
            release_ready=False,
            lawyer_review_required=True,
            failed_blocking_test_ids=[],
            notes="Generally workable, but targeted scenario fixes are required before pilot use.",
        )
    if total_score >= UNSTABLE_MIN_SCORE:
        return GoldenRunClassification(
            total_score=total_score,
            max_score=max_score,
            status="unstable_deep_review_required",
            release_ready=False,
            lawyer_review_required=True,
            failed_blocking_test_ids=[],
            notes="Unstable for legal opinions without deep review and remediation.",
        )
    return GoldenRunClassification(
        total_score=total_score,
        max_score=max_score,
        status="not_usable_for_legal_practice",
        release_ready=False,
        lawyer_review_required=True,
        failed_blocking_test_ids=[],
        notes="Not suitable for practical legal use.",
    )


def case_requires_lawyer_review(score_0_to_4: int, *, critical_error: bool = False) -> bool:
    if critical_error:
        return True
    return score_0_to_4 < 4


def case_blocks_release(test_id: str, score_0_to_4: int, *, critical_error: bool = False) -> bool:
    if critical_error:
        return True
    return test_id in BLOCKING_TEST_IDS and score_0_to_4 < GOLDEN_CASE_MAX_SCORE


def validate_golden_dataset(path: Path = GOLDEN_DATASET_PATH) -> list[str]:
    summary = summarize_golden_dataset(path)
    problems = []
    if len(summary.test_ids) != GOLDEN_TEST_COUNT:
        problems.append(f"Expected {GOLDEN_TEST_COUNT} tests, found {len(summary.test_ids)}.")
    if len(set(summary.test_ids)) != len(summary.test_ids):
        problems.append("Duplicate TEST IDs found.")
    missing_blocking = sorted(BLOCKING_TEST_IDS - set(summary.test_ids))
    if missing_blocking:
        problems.append("Missing blocking tests: " + ", ".join(missing_blocking))
    if summary.max_score != GOLDEN_TOTAL_MAX_SCORE:
        problems.append(f"Expected max score {GOLDEN_TOTAL_MAX_SCORE}, found {summary.max_score}.")
    return problems
