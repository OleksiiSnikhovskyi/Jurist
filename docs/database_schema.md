# Database Schema

Initial tables:

- `users`
- `client_profiles`
- `workspaces`
- `workspace_members`
- `lawyer_profiles`
- `documents`
- `legal_sources`
- `document_chunks`
- `legal_opinions`
- `audit_logs`
- `n8n_intake_packages`
- `n8n_intake_items`
- `n8n_telegram_bindings`

Run migrations with:

```bash
alembic upgrade head
```

The migrations enable PostgreSQL `vector` and `pg_trgm` extensions. Production document chunk embeddings use `vector(1024)` for Ollama `bge-m3`, with pgvector HNSW indexing for cosine search.

The application database is `jur_db`; the technical PostgreSQL role is `jur_user`. These are infrastructure credentials and are separate from application users, lawyers, and future client records.
