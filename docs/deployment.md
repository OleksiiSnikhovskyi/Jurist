# Deployment

Local development:

```bash
cp .env.example .env
docker compose up -d
alembic upgrade head
uvicorn app.main:app --reload
```

The backend expects PostgreSQL at `DATABASE_URL`. For Codespaces, update `.env` if port forwarding or service names differ.

Default local database settings:

- database: `jur_db`
- database user: `jur_user`
- local development password: `jur_password`

If an existing PostgreSQL volume was initialized before these names were added, create them manually:

```bash
psql -U postgres -f scripts/create_jur_db.sql
```
