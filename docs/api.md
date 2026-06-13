# API

## Health

`GET /health`

Returns service status.

## Agents

`POST /agents/orchestrator/query`

Initial request shape:

```json
{
  "user_id": "uuid",
  "workspace_id": "uuid",
  "question": "Analyze this contract",
  "document_id": "optional uuid"
}
```

The MVP skeleton returns a safe placeholder and does not generate legal conclusions without checked sources.

`POST /agents/contract-review/query`

Runs a workspace-scoped contract review over indexed document chunks. The response includes warnings, source chunk references, and a conservative confidence score. It does not replace human legal review.

`POST /agents/legal-research/query`

Runs a workspace-scoped legal research pass over indexed chunks. The response summarizes relevant facts from the workspace, flags possible legal issues, lists source chunk references, and warns that laws and court practice must be checked in official sources before use.

`POST /agents/quality-control/query`

Runs a workspace-scoped quality control pass over a draft answer or legal opinion text supplied in `question`. The response flags missing sources, overconfident wording, weak factual grounding, missing risk blocks, and returns source chunk references for manual review.

## Lawyer Profiles

`POST /lawyer-profiles`

Creates a personal lawyer profile for an existing `users.id`. Each user can have one profile.

```json
{
  "user_id": "uuid",
  "display_name": "Oleksii S.",
  "system_prompt": "Act as a Ukrainian civil litigation lawyer...",
  "specialization": "Civil litigation and contract disputes",
  "jurisdictions": ["Ukraine"],
  "workplace_context": "Private legal practice",
  "represented_interests": "Represents small businesses and individual clients",
  "communication_style": "Precise, source-aware, practical",
  "extra_context": {
    "preferred_language": "uk"
  }
}
```

`GET /lawyer-profiles/{profile_id}`

Returns a lawyer profile by profile ID.

`GET /lawyer-profiles/by-user/{user_id}`

Returns a lawyer profile by user ID.

`PATCH /lawyer-profiles/{profile_id}`

Updates any subset of profile fields.

`DELETE /lawyer-profiles/{profile_id}`

Deletes a lawyer profile.

## Documents

`POST /documents/upload`

Uploads a file into a workspace and stores document metadata. The caller must be a workspace member with `write_documents` permission.

Multipart form fields:

- `workspace_id`: target workspace ID.
- `user_id`: uploading user ID.
- `file`: binary file.
- `document_type`: optional content/type override.
- `confidentiality_level`: optional, defaults to `private`.

The endpoint stores the file in `UPLOAD_DIR`, creates a `documents` record, extracts text from supported PDF/DOCX files into `documents.extracted_text`, and writes a `document.uploaded` audit log entry. Chunking is handled in later ingestion steps.

## n8n Integration

`POST /n8n/intake/telegram`

Receives normalized Telegram events from `JUR_Bot_Intake_Queue`. If `workspace_id` and `user_id` are provided, the endpoint creates or updates the active pending intake package for the Telegram chat and stores text/file metadata. If the Telegram user is not yet linked to a workspace user, the endpoint returns `ok=false` with a bot-safe reply message.

`POST /n8n/intake/process`

Starts explicit package processing after the user presses `Почати обробку`. The endpoint marks the package as `processing_requested` and records the requested agent/question for the next processing step.

`POST /n8n/obsidian/sync-note`

Receives a normalized Obsidian Markdown note from `JUR_Obsidian_Vault_Sync`, stores it as an `obsidian_markdown` document, chunks it, and makes it available to workspace-scoped vector search.
