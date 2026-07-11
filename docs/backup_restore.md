# jur_db Backup and Restore

This document describes operational backup and restore procedures for the Jurist PostgreSQL database `jur_db`.

The database contains private workspace documents, legal-source chunks, Telegram intake metadata, legal opinions, audit events, and export metadata. Treat every backup as confidential production data.

## Principles

- Never commit database dumps, `.env` files, or restore logs containing secrets.
- Prefer PostgreSQL custom-format dumps (`pg_dump -Fc`) so restores can be selective and verified.
- Store backups outside the repository in an encrypted server directory or an encrypted object store.
- Keep at least one recent restore-tested backup before applying migrations.
- Restore into a temporary database first; replace production only after validation.

## Environment

Set connection details through environment variables or the server shell profile:

```bash
export PGHOST=127.0.0.1
export PGPORT=5433
export PGDATABASE=jur_db
export PGUSER=jur_user
export PGPASSWORD='<secret-from-secure-env>'
export BACKUP_DIR=/srv/backups/jurist
```

When running inside Docker, execute the same `pg_dump` / `pg_restore` commands from a container that can reach the Postgres service. Do not paste secrets into shell history on shared machines.

## Create a Backup

```bash
mkdir -p "$BACKUP_DIR"
backup_file="$BACKUP_DIR/jur_db_$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --compress=9 --no-owner --no-acl --file="$backup_file" "$PGDATABASE"
sha256sum "$backup_file" > "$backup_file.sha256"
ls -lh "$backup_file" "$backup_file.sha256"
```

Record the current migration version beside the dump:

```bash
psql "$PGDATABASE" -Atc "select version_num from alembic_version" > "$backup_file.alembic_version"
```

## Verify a Backup Without Touching Production

Restore into a disposable database name first:

```bash
verify_db="jur_restore_verify_$(date -u +%Y%m%dT%H%M%SZ)"
createdb "$verify_db"
pg_restore --dbname="$verify_db" --no-owner --no-acl "$backup_file"
psql "$verify_db" -Atc "select version_num from alembic_version"
psql "$verify_db" -Atc "select count(*) from users"
dropdb "$verify_db"
```

The Alembic version should match the `.alembic_version` sidecar unless you intentionally restored an older point-in-time backup.

## Restore Procedure

Use a maintenance window. Stop FastAPI and n8n workflows that write into Jurist before restoring.

Recommended safe restore flow:

1. Create a fresh backup of the current production database.
2. Restore the target dump into a temporary database and verify it.
3. Stop writers: FastAPI container and active `JUR_` n8n workflows.
4. Rename the current production database out of the way.
5. Create a new `jur_db` and restore the verified dump.
6. Run `alembic upgrade head` from the matching application revision.
7. Start FastAPI, run `/health`, then reactivate workflows.

Example commands:

```bash
createdb jur_db_restore_candidate
pg_restore --dbname=jur_db_restore_candidate --no-owner --no-acl "$backup_file"
psql jur_db_restore_candidate -Atc "select version_num from alembic_version"

# During maintenance only:
# dropdb/rename commands are intentionally not scripted here. Perform them manually
# after confirming the candidate restore and retaining the pre-restore backup.
```

## Post-Restore Checks

```bash
psql jur_db -Atc "select version_num from alembic_version"
psql jur_db -Atc "select count(*) from users"
psql jur_db -Atc "select count(*) from workspaces"
psql jur_db -Atc "select count(*) from documents"
curl http://127.0.0.1:8020/health
```

Then run one controlled n8n smoke test with a non-confidential Telegram message and confirm a new row appears in `n8n_intake_packages`.

## Retention

A conservative starting point:

- hourly backups for 24 hours;
- daily backups for 14 days;
- weekly backups for 8 weeks;
- monthly backups for 12 months.

Adjust retention to storage cost, confidentiality policy, and client requirements. Periodically test restores; an untested backup is only a hope with a timestamp.
