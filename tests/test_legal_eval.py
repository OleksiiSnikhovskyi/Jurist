import json
from pathlib import Path

from scripts.run_legal_eval import (
    build_llm_judge_prompt,
    evaluate_case,
    load_dataset,
    main,
    parse_llm_judge_response,
    write_csv,
    write_llm_judge_json,
    write_markdown,
)


def test_eval_dataset_covers_multiple_domains() -> None:
    cases, threshold = load_dataset(Path("tests/evals/legal_questions.json"))

    assert threshold == 75
    assert len(cases) >= 8
    assert len({case.domain for case in cases}) >= 6
    assert all(case.required_terms for case in cases)
    assert all(case.expected_official_sources for case in cases)


def test_rule_based_eval_scores_grounded_answer() -> None:
    case = load_dataset(Path("tests/evals/legal_questions.json"))[0][0]
    answer = """
    Висновок: пеня, 3% річних та інфляційні втрати можуть аналізуватися окремо.
    Аналіз: прострочення грошового зобов'язання треба довести договором і датами оплати.
    Джерела: https://zakon.rada.gov.ua/laws/show/435-15
    Ризики: суд може зменшити пеню, а 3% річних і інфляційні втрати потребують розрахунку.
    """

    result = evaluate_case(case, answer, threshold=75)

    assert result.passed is True
    assert result.score >= 90
    assert result.official_source_hits == ["zakon.rada.gov.ua"]
    assert result.forbidden_hits == []


def test_rule_based_eval_flags_missing_shape_and_unofficial_sources() -> None:
    case = load_dataset(Path("tests/evals/legal_questions.json"))[0][0]
    answer = "Пеня стягується автоматично без доказів. Див. https://legal-blog.test/comment"

    result = evaluate_case(case, answer, threshold=75)

    assert result.passed is False
    assert result.score < 75
    assert "автоматично без доказів" in result.forbidden_hits
    assert result.blocked_source_hits == ["https://legal-blog.test/comment"]
    assert result.missing_sections


def test_eval_report_writers_create_markdown_and_csv(tmp_path: Path) -> None:
    case = load_dataset(Path("tests/evals/legal_questions.json"))[0][0]
    result = evaluate_case(
        case,
        "Висновок Аналіз Джерела Ризики пеня 3% річних інфляційні втрати прострочення "
        "https://zakon.rada.gov.ua/laws/show/435-15 " + "детальний текст " * 25,
        threshold=75,
    )

    csv_path = tmp_path / "results.csv"
    md_path = tmp_path / "report.md"
    write_csv([result], csv_path)
    write_markdown([result], md_path, threshold=75)

    assert "case_id,domain,score" in csv_path.read_text(encoding="utf-8")
    report = md_path.read_text(encoding="utf-8")
    assert "Jurist Evaluation Report" in report
    assert "contract_penalty_001" in report


def test_eval_cli_writes_reports_and_fails_under_threshold(tmp_path: Path, monkeypatch) -> None:
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(
        json.dumps({"contract_penalty_001": "занадто коротко"}), encoding="utf-8"
    )
    out_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_legal_eval.py",
            "--dataset",
            "tests/evals/legal_questions.json",
            "--answers",
            str(answers_path),
            "--out-dir",
            str(out_dir),
            "--fail-under",
            "75",
        ],
    )

    exit_code = main()

    assert exit_code == 1
    assert (out_dir / "legal_eval_results.csv").exists()
    assert (out_dir / "legal_eval_report.md").exists()


def test_llm_judge_prompt_includes_case_and_rule_context() -> None:
    case = load_dataset(Path("tests/evals/legal_questions.json"))[0][0]
    answer = "Висновок: тестова відповідь"
    rule_result = evaluate_case(case, answer, threshold=75)

    prompt = build_llm_judge_prompt(case, answer, rule_result)

    assert case.id in prompt
    assert case.question in prompt
    assert "Rule score" in prompt
    assert "strict JSON" in prompt


def test_parse_llm_judge_response_bounds_scores() -> None:
    result = parse_llm_judge_response(
        "case-1",
        json.dumps(
            {
                "relevance": 7,
                "completeness": 4,
                "hallucination_risk": -2,
                "answer_form": 5,
                "overall_score": 120,
                "passed": True,
                "notes": "grounded enough",
                "flags": ["check freshness"],
            }
        ),
    )

    assert result.case_id == "case-1"
    assert result.relevance == 5
    assert result.hallucination_risk == 0
    assert result.overall_score == 100
    assert result.flags == ["check freshness"]


def test_write_llm_judge_json(tmp_path: Path) -> None:
    result = parse_llm_judge_response(
        "case-1",
        json.dumps(
            {
                "relevance": 5,
                "completeness": 4,
                "hallucination_risk": 1,
                "answer_form": 5,
                "overall_score": 88,
                "passed": True,
                "notes": "ok",
                "flags": [],
            }
        ),
    )

    output = tmp_path / "judge.json"
    write_llm_judge_json([result], output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload[0]["case_id"] == "case-1"
    assert payload[0]["overall_score"] == 88


def test_eval_cli_llm_judge_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(json.dumps({}), encoding="utf-8")
    out_dir = tmp_path / "reports"
    monkeypatch.delenv("JURIST_LLM_JUDGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_legal_eval.py",
            "--dataset",
            "tests/evals/legal_questions.json",
            "--answers",
            str(answers_path),
            "--out-dir",
            str(out_dir),
            "--llm-judge",
        ],
    )

    exit_code = main()

    assert exit_code == 2
    assert (out_dir / "legal_eval_results.csv").exists()
    assert not (out_dir / "legal_eval_llm_judge.json").exists()
