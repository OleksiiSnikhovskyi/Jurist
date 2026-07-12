from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_legal_eval import EvalCase, load_dataset

DEFAULT_DATASET = Path("tests/evals/legal_questions.json")
DEFAULT_OUT_DIR = Path("eval_reports")


@dataclass(frozen=True)
class TelegramSmokeConfig:
    api_base_url: str
    api_key: str | None
    chat_id: str
    telegram_user_id: str
    workspace_id: str | None
    user_id: str | None
    username: str = "jurist_eval_smoke"
    requested_agent: str = "orchestrator"
    timeout_seconds: int = 120
    use_existing_binding: bool = False
    notify_telegram: bool = False
    telegram_bot_token: str | None = None
    telegram_notify_chat_id: str | None = None


@dataclass(frozen=True)
class TelegramSmokeResult:
    case_id: str
    domain: str
    question: str
    ok: bool
    status: str | None
    package_id: str | None
    reply_text: str
    error: str | None = None


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def config_from_env(*, use_existing_binding: bool, notify_telegram: bool) -> TelegramSmokeConfig:
    api_base_url = os.getenv("JUR_SMOKE_API_BASE_URL") or os.getenv("JUR_API_BASE_URL")
    if not api_base_url:
        raise RuntimeError("Set JUR_SMOKE_API_BASE_URL or JUR_API_BASE_URL for live smoke runs.")

    chat_id = os.getenv("JUR_SMOKE_TELEGRAM_CHAT_ID")
    telegram_user_id = os.getenv("JUR_SMOKE_TELEGRAM_USER_ID")
    if not chat_id or not telegram_user_id:
        raise RuntimeError("Set JUR_SMOKE_TELEGRAM_CHAT_ID and JUR_SMOKE_TELEGRAM_USER_ID.")

    workspace_id = os.getenv("JUR_SMOKE_WORKSPACE_ID")
    user_id = os.getenv("JUR_SMOKE_USER_ID")
    if not use_existing_binding and (not workspace_id or not user_id):
        raise RuntimeError(
            "Set JUR_SMOKE_WORKSPACE_ID and JUR_SMOKE_USER_ID, or pass --use-existing-binding."
        )

    bot_token = os.getenv("JUR_SMOKE_TELEGRAM_BOT_TOKEN")
    notify_chat_id = os.getenv("JUR_SMOKE_TELEGRAM_NOTIFY_CHAT_ID") or chat_id
    if notify_telegram and not bot_token:
        raise RuntimeError("Set JUR_SMOKE_TELEGRAM_BOT_TOKEN before using --notify-telegram.")

    return TelegramSmokeConfig(
        api_base_url=api_base_url,
        api_key=os.getenv("JUR_SMOKE_API_KEY")
        or os.getenv("JUR_N8N_API_KEY")
        or os.getenv("N8N_API_KEY"),
        chat_id=chat_id,
        telegram_user_id=telegram_user_id,
        workspace_id=workspace_id,
        user_id=user_id,
        username=os.getenv("JUR_SMOKE_TELEGRAM_USERNAME", "jurist_eval_smoke"),
        requested_agent=os.getenv("JUR_SMOKE_REQUESTED_AGENT", "orchestrator"),
        timeout_seconds=int(os.getenv("JUR_SMOKE_TIMEOUT_SECONDS", "120")),
        use_existing_binding=use_existing_binding,
        notify_telegram=notify_telegram,
        telegram_bot_token=bot_token,
        telegram_notify_chat_id=notify_chat_id,
    )


def select_cases(cases: list[EvalCase], case_ids: list[str], limit: int | None) -> list[EvalCase]:
    if case_ids:
        wanted = set(case_ids)
        selected = [case for case in cases if case.id in wanted]
        missing = sorted(wanted - {case.id for case in selected})
        if missing:
            raise ValueError(f"Unknown evaluation case IDs: {', '.join(missing)}")
    else:
        selected = cases
    return selected[:limit] if limit is not None else selected


def build_telegram_event(case: EvalCase, config: TelegramSmokeConfig, index: int) -> dict[str, Any]:
    event: dict[str, Any] = {
        "telegram_update_id": 910000 + index,
        "chat_id": config.chat_id,
        "telegram_user_id": config.telegram_user_id,
        "username": config.username,
        "message_id": 920000 + index,
        "text": case.question,
        "action": "free_text",
        "attachments": [],
        "has_attachments": False,
        "requested_agent": config.requested_agent,
        "question": case.question,
        "received_at": datetime.now(UTC).isoformat(),
    }
    if config.workspace_id:
        event["workspace_id"] = config.workspace_id
    if config.user_id:
        event["user_id"] = config.user_id
    return event


def run_live_smoke(cases: list[EvalCase], config: TelegramSmokeConfig) -> list[TelegramSmokeResult]:
    results = []
    for index, case in enumerate(cases, start=1):
        event = build_telegram_event(case, config, index)
        if config.notify_telegram:
            notify_telegram_chat(
                config,
                f"[Jurist smoke] Question {index}/{len(cases)} `{case.id}`\n\n{case.question}",
            )
        try:
            payload = post_json(
                join_url(config.api_base_url, "/n8n/intake/telegram"),
                event,
                api_key=config.api_key,
                timeout_seconds=config.timeout_seconds,
            )
            result = TelegramSmokeResult(
                case_id=case.id,
                domain=case.domain,
                question=case.question,
                ok=bool(payload.get("ok")),
                status=payload.get("status"),
                package_id=payload.get("package_id"),
                reply_text=str(payload.get("reply_text", "")),
            )
        except RuntimeError as exc:
            result = TelegramSmokeResult(
                case_id=case.id,
                domain=case.domain,
                question=case.question,
                ok=False,
                status=None,
                package_id=None,
                reply_text="",
                error=str(exc),
            )
        if config.notify_telegram:
            answer = result.reply_text or f"ERROR: {result.error}"
            notify_telegram_chat(config, f"[Jurist smoke] Answer `{case.id}`\n\n{answer}")
        results.append(result)
    return results


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-JUR-N8N-API-KEY"] = api_key
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request to {url} failed: {exc}") from exc
    return json.loads(raw)


def notify_telegram_chat(config: TelegramSmokeConfig, text: str) -> None:
    if not config.telegram_bot_token or not config.telegram_notify_chat_id:
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_notify_chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    post_json(url, payload, timeout_seconds=config.timeout_seconds)


def join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def write_answers_json(results: list[TelegramSmokeResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    answers = {result.case_id: result.reply_text for result in results if result.reply_text}
    path.write_text(json.dumps(answers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_results_csv(results: list[TelegramSmokeResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "domain", "ok", "status", "package_id", "error"],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "case_id": result.case_id,
                    "domain": result.domain,
                    "ok": result.ok,
                    "status": result.status,
                    "package_id": result.package_id,
                    "error": result.error or "",
                }
            )


def write_dry_run_plan(cases: list[EvalCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "case_id": case.id,
            "domain": case.domain,
            "question": case.question,
            "expected_official_sources": case.expected_official_sources,
        }
        for case in cases
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run controlled Jurist Telegram/n8n smoke questions and capture answers."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--use-existing-binding", action="store_true")
    parser.add_argument("--notify-telegram", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_file:
        try:
            load_env_file(args.env_file)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    cases, _threshold = load_dataset(args.dataset)
    selected = select_cases(cases, args.case_id, args.limit)
    if args.dry_run:
        write_dry_run_plan(selected, args.out_dir / "telegram_smoke_plan.json")
        return 0

    try:
        config = config_from_env(
            use_existing_binding=args.use_existing_binding,
            notify_telegram=args.notify_telegram,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    results = run_live_smoke(selected, config)
    write_answers_json(results, args.out_dir / "answers.json")
    write_results_csv(results, args.out_dir / "telegram_smoke_results.csv")
    return 1 if any(not result.ok or result.error for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
