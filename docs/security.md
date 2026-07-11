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

Client profiles are also workspace-scoped private context. Agents may use a `client_profile_id` only when the profile belongs to the requested `workspace_id` and the requesting user has workspace read permission. A client profile from another workspace must never be added to retrieval queries or generated answers.

## Audit Logging

Access-sensitive actions are written to `audit_logs` through `AuditLogService`. Audit metadata is intentionally limited: keys such as `document_text`, `full_text`, `prompt`, `system_prompt`, and `raw_text` are removed, and long strings are truncated. Store identifiers, source names, risk flags, and operational context in audit metadata, not confidential document bodies.

## Cross-Workspace Denial

Document access must validate both the user's membership and the document's own `workspace_id`. A valid `document_id` is not sufficient: if the caller provides `workspace_id=A` and the document belongs to `workspace_id=B`, access is denied before any document body or chunk text is returned.

## n8n Integration Security

n8n integration endpoints are implementation endpoints for trusted workflows, not public client APIs. They still enforce workspace access when `workspace_id` and `user_id` are provided:

- `POST /n8n/intake/telegram` requires `write_documents` before storing Telegram materials in a workspace package.
- `POST /n8n/telegram/bindings` requires `write_documents` for the target workspace user before creating or updating a Telegram binding.
- `POST /n8n/intake/process` requires `run_agents` before marking a package ready for processing.
- `POST /n8n/obsidian/sync-note` requires `write_documents` before creating searchable Obsidian documents and chunks.

If a Telegram event has no `workspace_id` or `user_id`, the backend first resolves `telegram_user_id` through `n8n_telegram_bindings`. If no active binding exists, it returns a safe response asking for account/workspace binding and does not store private materials. This keeps future client onboarding separate from the technical PostgreSQL role and from Telegram credentials.

Workflow names must start with `JUR_` so they are identifiable in n8n and easier to audit. Checked-in workflow templates are inactive by default and contain placeholder credential IDs. Real Telegram credentials must live in n8n credentials, not in repository JSON or `.env.example`.

## Telegram and Uploaded Materials

Telegram file IDs, filenames, MIME types, message IDs, and chat/user IDs are stored as operational metadata in `n8n_intake_items`. Raw binary files, OCR output, and voice transcripts should be stored only through controlled ingestion steps and should remain workspace-scoped. The system must not start OCR, transcription, indexing, or legal analysis until the user explicitly chooses `Почати обробку`.

After Telegram binding, a lawyer profile is required before materials are collected. If no profile exists, the bot asks `Який напрямок Вашої діяльності?` and stores the answer as the initial profile context. The user must always be able to replace their system prompt later; the Telegram action `Змінити системний промпт` updates only the profile prompt and does not add that text as case material.

Telegram client-profile onboarding stores only structured profile fields and the active `client_profile_id` in binding/package metadata. The active client profile is workspace-scoped and is copied into package metadata only when the user explicitly chooses `Почати обробку`.

## Obsidian Vault Security

Obsidian notes are treated as private workspace knowledge. Sync only explicitly configured notes or folders, preserve source paths as metadata, and never index an entire vault automatically unless the lawyer has configured that behavior. Synced notes become `obsidian_markdown` documents and are subject to the same workspace-scoped vector search rules as uploaded documents.

## Agent Output Safety

Specialized agents return source references and warnings. Contract review, legal research, and quality control responses are preliminary and must remain framed as lawyer-review workflows. When source freshness is unknown, responses must warn that current legislation and court practice require verification in official sources.
Bot upload rate and payload limits are enforced before intake storage for `/n8n/intake/telegram` and `/n8n/intake/extracted-text`. Oversized payloads return `413`; enabled rate limits return `429` with `Retry-After`, reducing accidental retry storms and overly large OCR/transcription submissions.
