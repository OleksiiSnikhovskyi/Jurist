# Security Model

Core requirements:

- Enforce workspace isolation on all private documents.
- Check user role before document access.
- Log access-sensitive actions into `audit_logs`.
- Do not log full confidential document text.
- Keep secrets in `.env`, not in git.
- Mark legal answers as unverified when source freshness is unknown.
- Never use private documents from another workspace in retrieval or agent responses.

## Workspace Roles

Workspace membership is stored in `workspace_members`. The application recognizes these roles:

- `owner`: all workspace permissions.
- `admin`: reads, writes, runs agents, manages members, manages workspace settings.
- `lawyer`: reads, writes documents, reviews documents, runs agents.
- `reviewer`: reads and reviews documents.
- `viewer`: reads only.

All private document access, vector search, legal opinions, and future n8n workflows must check workspace membership before reading or writing workspace-scoped data.

## Audit Logging

Access-sensitive actions are written to `audit_logs` through `AuditLogService`. Audit metadata is intentionally limited: keys such as `document_text`, `full_text`, `prompt`, `system_prompt`, and `raw_text` are removed, and long strings are truncated. Store identifiers, source names, risk flags, and operational context in audit metadata, not confidential document bodies.

## Cross-Workspace Denial

Document access must validate both the user's membership and the document's own `workspace_id`. A valid `document_id` is not sufficient: if the caller provides `workspace_id=A` and the document belongs to `workspace_id=B`, access is denied before any document body or chunk text is returned.
