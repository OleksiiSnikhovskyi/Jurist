import json
from pathlib import Path

from scripts.run_legal_eval import (
    evaluate_case,
    load_dataset,
    main,
    write_csv,
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
