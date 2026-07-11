from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse


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


@dataclass(frozen=True)
class LLMJudgeConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60


@dataclass(frozen=True)
class LLMJudgeResult:
    case_id: str
    relevance: int
    completeness: int
    hallucination_risk: int
    answer_form: int
    overall_score: int
    passed: bool
    notes: str
    flags: list[str]


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


def build_llm_judge_prompt(case: EvalCase, answer: str, rule_result: EvalResult) -> str:
    return "\n".join(
        [
            "You are a legal QA judge for a Ukrainian legal assistant.",
            "Evaluate only the answer quality. Do not provide legal advice.",
            "Return strict JSON with these keys only:",
            "relevance, completeness, hallucination_risk, answer_form, overall_score, passed, notes, flags.",
            "Scores relevance/completeness/answer_form are integers 0-5.",
            "hallucination_risk is 0 for low risk and 5 for high risk.",
            "overall_score is 0-100. passed is boolean.",
            "Flag unsupported exact claims, missing official sources, poor structure, or overconfident wording.",
            "",
            f"Case ID: {case.id}",
            f"Domain: {case.domain}",
            f"Question: {case.question}",
            f"Required sections: {', '.join(case.required_sections)}",
            f"Required terms: {', '.join(case.required_terms)}",
            f"Expected official sources: {', '.join(case.expected_official_sources)}",
            f"Rule score: {rule_result.score}",
            f"Rule missing terms: {', '.join(rule_result.missing_terms) or 'none'}",
            f"Rule blocked sources: {', '.join(rule_result.blocked_source_hits) or 'none'}",
            "",
            "Answer:",
            answer,
        ]
    )


def llm_judge_config_from_env() -> LLMJudgeConfig:
    api_key = os.getenv("JURIST_LLM_JUDGE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set JURIST_LLM_JUDGE_API_KEY or OPENAI_API_KEY before using --llm-judge."
        )
    model = os.getenv("JURIST_LLM_JUDGE_MODEL", "gpt-4o-mini")
    base_url = os.getenv("JURIST_LLM_JUDGE_BASE_URL") or os.getenv(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"
    )
    timeout = int(os.getenv("JURIST_LLM_JUDGE_TIMEOUT_SECONDS", "60"))
    return LLMJudgeConfig(api_key=api_key, model=model, base_url=base_url, timeout_seconds=timeout)


def request_llm_judge(
    case: EvalCase,
    answer: str,
    rule_result: EvalResult,
    config: LLMJudgeConfig,
) -> LLMJudgeResult:
    endpoint = urljoin(config.base_url.rstrip("/") + "/", "chat/completions")
    payload = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You are a strict legal-answer evaluation judge. Return JSON only.",
            },
            {
                "role": "user",
                "content": build_llm_judge_prompt(case, answer, rule_result),
            },
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM judge request failed: {exc}") from exc
    content = raw["choices"][0]["message"]["content"]
    return parse_llm_judge_response(case.id, content)


def parse_llm_judge_response(case_id: str, content: str) -> LLMJudgeResult:
    raw = json.loads(content)
    return LLMJudgeResult(
        case_id=case_id,
        relevance=bounded_int(raw.get("relevance"), 0, 5),
        completeness=bounded_int(raw.get("completeness"), 0, 5),
        hallucination_risk=bounded_int(raw.get("hallucination_risk"), 0, 5),
        answer_form=bounded_int(raw.get("answer_form"), 0, 5),
        overall_score=bounded_int(raw.get("overall_score"), 0, 100),
        passed=bool(raw.get("passed", False)),
        notes=str(raw.get("notes", "")),
        flags=[str(flag) for flag in raw.get("flags", [])],
    )


def bounded_int(value: object, lower: int, upper: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return lower
    return max(lower, min(upper, number))


def judge_answers_with_llm(
    cases: list[EvalCase],
    answers: dict[str, str],
    rule_results: list[EvalResult],
    config: LLMJudgeConfig,
) -> list[LLMJudgeResult]:
    cases_by_id = {case.id: case for case in cases}
    judge_results = []
    for rule_result in rule_results:
        case = cases_by_id[rule_result.case_id]
        judge_results.append(request_llm_judge(case, answers.get(case.id, ""), rule_result, config))
    return judge_results


def write_llm_judge_json(results: list[LLMJudgeResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "case_id": result.case_id,
            "relevance": result.relevance,
            "completeness": result.completeness,
            "hallucination_risk": result.hallucination_risk,
            "answer_form": result.answer_form,
            "overall_score": result.overall_score,
            "passed": result.passed,
            "notes": result.notes,
            "flags": result.flags,
        }
        for result in results
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    parser.add_argument("--llm-judge", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases, dataset_threshold = load_dataset(args.dataset)
    threshold = args.fail_under if args.fail_under is not None else dataset_threshold
    answers = load_answers(args.answers)
    results = evaluate_answers(cases, answers, threshold)
    write_csv(results, args.out_dir / "legal_eval_results.csv")
    write_markdown(results, args.out_dir / "legal_eval_report.md", threshold)
    if args.llm_judge:
        try:
            judge_results = judge_answers_with_llm(
                cases, answers, results, llm_judge_config_from_env()
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        write_llm_judge_json(judge_results, args.out_dir / "legal_eval_llm_judge.json")
    if results and min(result.score for result in results) < threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
