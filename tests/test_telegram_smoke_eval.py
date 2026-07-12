import json
from pathlib import Path

from scripts.run_telegram_smoke_eval import (
    TelegramSmokeConfig,
    TelegramSmokeResult,
    build_telegram_event,
    config_from_env,
    load_env_file,
    main,
    select_cases,
    write_answers_json,
    write_results_csv,
)
from scripts.run_legal_eval import load_dataset


def test_select_cases_by_id_and_limit() -> None:
    cases, _threshold = load_dataset(Path("tests/evals/legal_questions.json"))

    selected = select_cases(cases, ["tax_vat_001", "consumer_001"], limit=1)

    assert [case.id for case in selected] == ["tax_vat_001"]


def test_build_telegram_event_uses_controlled_identity() -> None:
    case = load_dataset(Path("tests/evals/legal_questions.json"))[0][0]
    config = TelegramSmokeConfig(
        api_base_url="https://jurist.example.test",
        api_key="secret",
        chat_id="100",
        telegram_user_id="200",
        workspace_id="workspace-1",
        user_id="user-1",
    )

    event = build_telegram_event(case, config, index=3)

    assert event["chat_id"] == "100"
    assert event["telegram_user_id"] == "200"
    assert event["workspace_id"] == "workspace-1"
    assert event["user_id"] == "user-1"
    assert event["action"] == "free_text"
    assert event["question"] == case.question
    assert event["attachments"] == []


def test_config_requires_identity_unless_binding_mode(monkeypatch) -> None:
    monkeypatch.setenv("JUR_SMOKE_API_BASE_URL", "https://jurist.example.test")
    monkeypatch.setenv("JUR_SMOKE_TELEGRAM_CHAT_ID", "100")
    monkeypatch.setenv("JUR_SMOKE_TELEGRAM_USER_ID", "200")
    monkeypatch.delenv("JUR_SMOKE_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("JUR_SMOKE_USER_ID", raising=False)

    try:
        config_from_env(use_existing_binding=False, notify_telegram=False)
    except RuntimeError as exc:
        assert "JUR_SMOKE_WORKSPACE_ID" in str(exc)
    else:
        raise AssertionError("config_from_env should require direct smoke identity")

    config = config_from_env(use_existing_binding=True, notify_telegram=False)
    assert config.use_existing_binding is True
    assert config.workspace_id is None


def test_write_answers_and_results(tmp_path: Path) -> None:
    results = [
        TelegramSmokeResult(
            case_id="case-1",
            domain="contract_law",
            question="Q",
            ok=True,
            status="processed",
            package_id="pkg-1",
            reply_text="A",
        )
    ]

    answers_path = tmp_path / "answers.json"
    csv_path = tmp_path / "results.csv"
    write_answers_json(results, answers_path)
    write_results_csv(results, csv_path)

    assert json.loads(answers_path.read_text(encoding="utf-8")) == {"case-1": "A"}
    assert "case_id,domain,ok" in csv_path.read_text(encoding="utf-8")


def test_dry_run_cli_writes_plan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_telegram_smoke_eval.py",
            "--dataset",
            "tests/evals/legal_questions.json",
            "--out-dir",
            str(tmp_path),
            "--limit",
            "2",
            "--dry-run",
        ],
    )

    exit_code = main()

    assert exit_code == 0
    plan = json.loads((tmp_path / "telegram_smoke_plan.json").read_text(encoding="utf-8"))
    assert len(plan) == 2
    assert {"case_id", "domain", "question", "expected_official_sources"} <= set(plan[0])


def test_load_env_file_sets_missing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "smoke.env"
    env_file.write_text(
        "JUR_SMOKE_API_BASE_URL=https://jurist.example.test\n"
        "JUR_SMOKE_TELEGRAM_CHAT_ID=100\n"
        "JUR_SMOKE_TELEGRAM_USER_ID='200'\n"
        "JUR_SMOKE_WORKSPACE_ID=workspace-1\n"
        'JUR_SMOKE_USER_ID="user-1"\n',
        encoding="utf-8",
    )
    for name in [
        "JUR_SMOKE_API_BASE_URL",
        "JUR_SMOKE_TELEGRAM_CHAT_ID",
        "JUR_SMOKE_TELEGRAM_USER_ID",
        "JUR_SMOKE_WORKSPACE_ID",
        "JUR_SMOKE_USER_ID",
    ]:
        monkeypatch.delenv(name, raising=False)

    load_env_file(env_file)
    config = config_from_env(use_existing_binding=False, notify_telegram=False)

    assert config.api_base_url == "https://jurist.example.test"
    assert config.telegram_user_id == "200"
    assert config.user_id == "user-1"


def test_dry_run_cli_accepts_env_file(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "smoke.env"
    env_file.write_text("JUR_SMOKE_API_BASE_URL=https://jurist.example.test\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_telegram_smoke_eval.py",
            "--dataset",
            "tests/evals/legal_questions.json",
            "--out-dir",
            str(tmp_path / "reports"),
            "--limit",
            "1",
            "--dry-run",
            "--env-file",
            str(env_file),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert (tmp_path / "reports" / "telegram_smoke_plan.json").exists()


def test_live_cli_loads_env_file_before_config(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "smoke.env"
    env_file.write_text(
        "JUR_SMOKE_API_BASE_URL=https://jurist.example.test\n"
        "JUR_SMOKE_TELEGRAM_CHAT_ID=100\n"
        "JUR_SMOKE_TELEGRAM_USER_ID=200\n"
        "JUR_SMOKE_WORKSPACE_ID=workspace-1\n"
        "JUR_SMOKE_USER_ID=user-1\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "reports"
    for name in [
        "JUR_SMOKE_API_BASE_URL",
        "JUR_SMOKE_TELEGRAM_CHAT_ID",
        "JUR_SMOKE_TELEGRAM_USER_ID",
        "JUR_SMOKE_WORKSPACE_ID",
        "JUR_SMOKE_USER_ID",
    ]:
        monkeypatch.delenv(name, raising=False)

    def fake_run_live_smoke(cases, config):
        assert config.api_base_url == "https://jurist.example.test"
        assert config.workspace_id == "workspace-1"
        return [
            TelegramSmokeResult(
                case_id=cases[0].id,
                domain=cases[0].domain,
                question=cases[0].question,
                ok=True,
                status="processed",
                package_id="pkg-1",
                reply_text="Висновок: тестова відповідь",
            )
        ]

    monkeypatch.setattr("scripts.run_telegram_smoke_eval.run_live_smoke", fake_run_live_smoke)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_telegram_smoke_eval.py",
            "--dataset",
            "tests/evals/legal_questions.json",
            "--out-dir",
            str(out_dir),
            "--limit",
            "1",
            "--env-file",
            str(env_file),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert (out_dir / "answers.json").exists()
    assert (out_dir / "telegram_smoke_results.csv").exists()
