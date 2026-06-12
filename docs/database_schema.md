# Database Schema

Initial tables:

- `users`
- `workspaces`
- `workspace_members`
- `documents`
- `legal_sources`
- `document_chunks`
- `legal_opinions`
- `audit_logs`

Run migrations with:

```bash
alembic upgrade head
```

The migration enables PostgreSQL `vector` extension for future pgvector search.
