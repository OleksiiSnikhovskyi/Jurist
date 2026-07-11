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

## Next Layers

After the local baseline is stable:

1. Add an optional LLM judge for legal relevance, completeness, hallucination risk, and answer form.
2. Add n8n/Telegram smoke tests that send controlled questions and capture answers.
3. Export reports for Kaggle-style offline analysis and charts.
4. Define release gates and lawyer-review escalation thresholds.
