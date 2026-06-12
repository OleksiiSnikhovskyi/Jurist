# n8n Workflows

Planned workflow templates:

- `document_ingestion.json`
- `legal_update_monitoring.json`
- `case_law_indexing.json`
- `weekly_digest.json`

Workflows should call FastAPI webhook endpoints and preserve `workspace_id`, `user_id`, and document confidentiality metadata through every step.
