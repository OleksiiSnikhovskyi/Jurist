# Database Schema

Initial tables:

- `users`
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

Run migrations with:

```bash
alembic upgrade head
```

The migration enables PostgreSQL `vector` extension for future pgvector search.

The application database is `jur_db`; the technical PostgreSQL role is `jur_user`. These are infrastructure credentials and are separate from application users, lawyers, and future client records.
