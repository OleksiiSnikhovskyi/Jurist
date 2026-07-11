# Database Schema

Initial tables:

- `users`
- `client_profiles`
- `workspaces`
- `workspace_members`
- `lawyer_profiles`
- `documents`
- `legal_sources`
- `legal_source_verifications`
- `document_chunks`
- `legal_opinions`
- `legal_opinion_exports`
- `official_source_search_runs`
- `audit_logs`
- `n8n_intake_packages`
- `n8n_intake_items`
- `n8n_telegram_bindings`

Run migrations with:

```bash
alembic upgrade head
```

The migrations enable PostgreSQL `vector` and `pg_trgm` extensions. Production document chunk embeddings use `vector(1024)` for Ollama `bge-m3`, with pgvector HNSW indexing for cosine search.

Official-source verification metadata is stored in `legal_source_verifications`; fetched source page text is not duplicated there. The application database is `jur_db`; the technical PostgreSQL role is `jur_user`. These are infrastructure credentials and are separate from application users, lawyers, and future client records.
Controlled official-source search plans are stored in `official_source_search_runs`. The table records trigger metadata, generated official-domain site queries, accepted/rejected candidate URLs, and compact audit metadata only; fetched page text is not stored there.

Final answer exports are stored in `legal_opinion_exports`. The table records the legal opinion, workspace, requester, format, path, content type, file size, and review/source metadata for generated DOCX/PDF files.

Backup and restore procedures for jur_db are documented in docs/backup_restore.md.
