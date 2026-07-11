# Jurist Evaluation Harness

Stage 11 starts with a local, deterministic evaluation harness for legal-answer quality checks.

The harness is intentionally offline-first:

- no secrets;
- no private Telegram messages;
- no live n8n execution by default;
- no LLM judge until the rule-based baseline is stable.

## Dataset

The seed dataset is `tests/evals/legal_questions.json`. It covers multiple legal domains, including contract law, tax, labor, construction/DBN, energy/NERC, court practice, corporate law, and consumer protection.

Each case defines:

- `question`: prompt to send to Jurist or Telegram later;
- `required_terms`: terms expected in a legally relevant answer;
- `forbidden_terms`: unsafe or overconfident claims;
- `required_sections`: expected answer form;
- `expected_official_sources`: official domains or sources that should ground the answer;
- `notes`: reviewer guidance.

## Answer File

Create a JSON object mapping case IDs to captured answers:

```json
{
  "contract_penalty_001": "Висновок: ... Джерела: https://zakon.rada.gov.ua/..."
}
```

A list format is also accepted:

```json
[
  {"id": "contract_penalty_001", "answer": "..."}
]
```

## Run

```bash
python scripts/run_legal_eval.py \
  --dataset tests/evals/legal_questions.json \
  --answers eval_reports/answers.json \
  --out-dir eval_reports \
  --fail-under 75
```

Outputs:

- `eval_reports/legal_eval_results.csv`
- `eval_reports/legal_eval_report.md`

## Scoring

The current score is rule-based and capped at 100:

- answer present: 10;
- required sections: 20;
- required terms: 25;
- forbidden claims absent: 15;
- official sources present and no blocked source hints: 20;
- answer length sanity: 10.

A case passes when its score is at least the configured threshold, currently `75` in the dataset.



## n8n/Telegram Smoke Tests

Use `scripts/run_telegram_smoke_eval.py` to send controlled evaluation questions through the Jurist n8n intake path and capture bot answers for scoring.

The runner has two modes:

- dry-run mode writes the planned questions without calling any service;
- live mode posts normalized Telegram intake events to `POST /n8n/intake/telegram` and writes captured `reply_text` values to `eval_reports/answers.json`.

Dry-run:

```bash
python scripts/run_telegram_smoke_eval.py \
  --dataset tests/evals/legal_questions.json \
  --out-dir eval_reports \
  --limit 3 \
  --dry-run
```

Live smoke environment:

- `JUR_SMOKE_API_BASE_URL` or `JUR_API_BASE_URL`;
- `JUR_SMOKE_API_KEY`, `JUR_N8N_API_KEY`, or `N8N_API_KEY` when the backend protects `/n8n/...`;
- `JUR_SMOKE_TELEGRAM_CHAT_ID`;
- `JUR_SMOKE_TELEGRAM_USER_ID`;
- `JUR_SMOKE_WORKSPACE_ID` and `JUR_SMOKE_USER_ID` for direct controlled identity, unless `--use-existing-binding` is explicitly used;
- `JUR_SMOKE_TELEGRAM_BOT_TOKEN`, optional, only when `--notify-telegram` should mirror questions and answers to a QA Telegram chat.

Live run:

```bash
python scripts/run_telegram_smoke_eval.py \
  --dataset tests/evals/legal_questions.json \
  --out-dir eval_reports \
  --limit 8 \
  --notify-telegram
```

Outputs:

- `eval_reports/answers.json`, directly consumable by `scripts/run_legal_eval.py`;
- `eval_reports/telegram_smoke_results.csv`, with package/status/error metadata;
- `eval_reports/telegram_smoke_plan.json`, dry-run only.

The live runner does not inject messages into real client conversations. It uses a controlled test identity or an explicitly selected existing Telegram binding. Telegram notification is only a QA mirror; the scoring source remains `answers.json`.

## Optional LLM Judge

The LLM judge is disabled by default. Enable it only for controlled evaluation runs after answers have been captured into an answer file.

Required environment:

- `JURIST_LLM_JUDGE_API_KEY` or `OPENAI_API_KEY`;
- `JURIST_LLM_JUDGE_MODEL` for the provider model, defaulting to `gpt-4o-mini`;
- `JURIST_LLM_JUDGE_BASE_URL` or `OPENAI_BASE_URL` for an OpenAI-compatible `/chat/completions` endpoint;
- `JURIST_LLM_JUDGE_TIMEOUT_SECONDS`, optional, default `60`.

Run:

```bash
python scripts/run_legal_eval.py \
  --dataset tests/evals/legal_questions.json \
  --answers eval_reports/answers.json \
  --out-dir eval_reports \
  --fail-under 75 \
  --llm-judge
```

Additional output:

- `eval_reports/legal_eval_llm_judge.json`

The judge returns relevance, completeness, hallucination risk, answer form, overall score, pass/fail, notes, and flags. The rule-based evaluator remains the release gate; the LLM judge is an advisory review layer until enough human-reviewed evaluation history is collected.

## Next Layers

After the local baseline is stable:

1. Add an optional LLM judge for legal relevance, completeness, hallucination risk, and answer form.
2. Add n8n/Telegram smoke tests that send controlled questions and capture answers.
3. Export reports for Kaggle-style offline analysis and charts.
4. Define release gates and lawyer-review escalation thresholds.
