from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.legal_source_policy import OFFICIAL_DOMAINS, has_blocked_source_hint

DEFAULT_DATASET = Path("tests/evals/legal_questions.json")
DEFAULT_REPORT_DIR = Path("eval_reports")


@dataclass(frozen=True)
class EvalCase:
    id: str
    domain: str
    question: str
    required_terms: list[str]
    forbidden_terms: list[str]
    required_sections: list[str]
    expected_official_sources: list[str]
    notes: str = ""


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    domain: str
    score: int
    passed: bool
    answer_present: bool
    sections_score: int
    required_terms_score: int
    forbidden_terms_score: int
    official_sources_score: int
    length_score: int
    missing_sections: list[str]
    missing_terms: list[str]
    forbidden_hits: list[str]
    official_source_hits: list[str]
    blocked_source_hits: list[str]


def load_dataset(path: Path) -> tuple[list[EvalCase], int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    threshold = int(raw.get("quality_threshold", 75))
    cases = [
        EvalCase(
            id=item["id"],
            domain=item["domain"],
            question=item["question"],
            required_terms=list(item.get("required_terms", [])),
            forbidden_terms=list(item.get("forbidden_terms", [])),
            required_sections=list(item.get("required_sections", [])),
            expected_official_sources=list(item.get("expected_official_sources", [])),
            notes=item.get("notes", ""),
        )
        for item in raw.get("cases", [])
    ]
    return cases, threshold


def load_answers(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        answers: dict[str, str] = {}
        for item in raw:
            answers[str(item["id"])] = str(item.get("answer", ""))
        return answers
    raise ValueError("Answers file must be a JSON object or a list of {id, answer} objects")


def evaluate_case(case: EvalCase, answer: str, threshold: int) -> EvalResult:
    normalized = normalize(answer)
    answer_present = bool(normalized.strip())
    missing_sections = [
        section for section in case.required_sections if normalize(section) not in normalized
    ]
    missing_terms = [term for term in case.required_terms if normalize(term) not in normalized]
    forbidden_hits = [term for term in case.forbidden_terms if normalize(term) in normalized]
    official_hits = official_source_hits(answer, case.expected_official_sources)
    blocked_hits = blocked_source_hits(answer)

    sections_score = proportional_score(case.required_sections, missing_sections, 20)
    required_terms_score = proportional_score(case.required_terms, missing_terms, 25)
    forbidden_terms_score = 15 if not forbidden_hits and answer_present else 0
    official_sources_score = 20 if official_hits and not blocked_hits else 0
    length_score = 10 if 250 <= len(answer.strip()) <= 6000 else (5 if answer_present else 0)
    base_score = 10 if answer_present else 0
    score = min(
        100,
        base_score
        + sections_score
        + required_terms_score
        + forbidden_terms_score
        + official_sources_score
        + length_score,
    )
    return EvalResult(
        case_id=case.id,
        domain=case.domain,
        score=score,
        passed=score >= threshold,
        answer_present=answer_present,
        sections_score=sections_score,
        required_terms_score=required_terms_score,
        forbidden_terms_score=forbidden_terms_score,
        official_sources_score=official_sources_score,
        length_score=length_score,
        missing_sections=missing_sections,
        missing_terms=missing_terms,
        forbidden_hits=forbidden_hits,
        official_source_hits=official_hits,
        blocked_source_hits=blocked_hits,
    )


def evaluate_answers(
    cases: list[EvalCase], answers: dict[str, str], threshold: int
) -> list[EvalResult]:
    return [evaluate_case(case, answers.get(case.id, ""), threshold) for case in cases]


def proportional_score(expected: list[str], missing: list[str], max_score: int) -> int:
    if not expected:
        return max_score
    present_count = len(expected) - len(missing)
    return round(max_score * present_count / len(expected))


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def official_source_hits(answer: str, expected_sources: list[str]) -> list[str]:
    domains = set(extract_domains(answer))
    expected = {normalize_domain(source) for source in expected_sources}
    allowed = {domain for domain in domains if domain in OFFICIAL_DOMAINS or domain in expected}
    return sorted(allowed)


def blocked_source_hits(answer: str) -> list[str]:
    hits = []
    for url in extract_urls(answer):
        if has_blocked_source_hint(url):
            hits.append(url)
    return sorted(set(hits))


def extract_urls(answer: str) -> list[str]:
    return re.findall(r"https?://[^\s)\]>\"']+", answer)


def extract_domains(answer: str) -> list[str]:
    domains = []
    for url in extract_urls(answer):
        domain = normalize_domain(url)
        if domain:
            domains.append(domain)
    return domains


def normalize_domain(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.netloc or parsed.path).lower().removeprefix("www.")


def write_csv(results: list[EvalResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "domain",
                "score",
                "passed",
                "missing_sections",
                "missing_terms",
                "forbidden_hits",
                "official_source_hits",
                "blocked_source_hits",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "case_id": result.case_id,
                    "domain": result.domain,
                    "score": result.score,
                    "passed": result.passed,
                    "missing_sections": "; ".join(result.missing_sections),
                    "missing_terms": "; ".join(result.missing_terms),
                    "forbidden_hits": "; ".join(result.forbidden_hits),
                    "official_source_hits": "; ".join(result.official_source_hits),
                    "blocked_source_hits": "; ".join(result.blocked_source_hits),
                }
            )


def write_markdown(results: list[EvalResult], path: Path, threshold: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    average = round(sum(result.score for result in results) / len(results), 2) if results else 0
    passed_count = sum(1 for result in results if result.passed)
    lines = [
        "# Jurist Evaluation Report",
        "",
        f"Quality threshold: `{threshold}`",
        f"Average score: `{average}`",
        f"Passed: `{passed_count}/{len(results)}`",
        "",
        "| Case | Domain | Score | Passed | Issues |",
        "|---|---|---:|:---:|---|",
    ]
    for result in results:
        issues = []
        if result.missing_sections:
            issues.append("missing sections: " + ", ".join(result.missing_sections))
        if result.missing_terms:
            issues.append("missing terms: " + ", ".join(result.missing_terms))
        if result.forbidden_hits:
            issues.append("forbidden: " + ", ".join(result.forbidden_hits))
        if result.blocked_source_hits:
            issues.append("blocked sources")
        if not result.official_source_hits:
            issues.append("no official source")
        lines.append(
            f"| `{result.case_id}` | {result.domain} | {result.score} | "
            f"{'yes' if result.passed else 'no'} | {'; '.join(issues) or 'ok'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Jurist legal answers with rule-based checks."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--answers", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--fail-under", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases, dataset_threshold = load_dataset(args.dataset)
    threshold = args.fail_under if args.fail_under is not None else dataset_threshold
    answers = load_answers(args.answers)
    results = evaluate_answers(cases, answers, threshold)
    write_csv(results, args.out_dir / "legal_eval_results.csv")
    write_markdown(results, args.out_dir / "legal_eval_report.md", threshold)
    if results and min(result.score for result in results) < threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
