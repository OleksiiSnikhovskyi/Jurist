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
  "document_id": "optional uuid",
  "client_profile_id": "optional uuid"
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
Telegram onboarding also relies on this profile: after Telegram binding, the bot asks `Який напрямок Вашої діяльності?` before collecting work materials if the bound user has no profile yet. The profile can later be updated through `PATCH /lawyer-profiles/{profile_id}` or through the Telegram action `Змінити системний промпт`.

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

## Client Profiles

`POST /client-profiles`

Creates a workspace-scoped client profile. This profile represents the client, their role in the matter, interests, risk preferences, communication preferences, and factual context.

```json
{
  "workspace_id": "uuid",
  "created_by": "uuid",
  "display_name": "ТОВ Приклад",
  "client_type": "business",
  "matter_role": "позивач",
  "interests": "Стягнути заборгованість і зберегти договірні відносини",
  "risk_preferences": "Уникати надмірно агресивної позиції",
  "communication_preferences": "Стислий executive summary",
  "factual_context": "Постачання виконано, оплата прострочена"
}
```

`GET /client-profiles/by-workspace/{workspace_id}?user_id={user_id}`

Lists client profiles visible to a workspace member.

`GET /client-profiles/{profile_id}?user_id={user_id}`

Returns one client profile after workspace access validation.

`PATCH /client-profiles/{profile_id}?user_id={user_id}`

Updates any subset of client profile fields.

`DELETE /client-profiles/{profile_id}?user_id={user_id}`

Deletes a client profile. Agent requests can include `client_profile_id`; the selected profile is then added to retrieval context and to the generated answer.

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

Receives normalized Telegram events from `JUR_Bot_Intake_Queue`. If `workspace_id` and `user_id` are provided, or if `telegram_user_id` has an active binding, the endpoint creates or updates the active pending intake package for the Telegram chat and stores text/file metadata. If the Telegram user is not yet linked to a workspace user, the endpoint returns `ok=false` with a bot-safe reply message.

If the bound user has no lawyer profile yet, this endpoint asks `Який напрямок Вашої діяльності?` and stores the next free-text answer as the first profile/system-prompt basis instead of adding it to a document package. The `Змінити системний промпт` bot action lets the user replace the profile prompt later.

Telegram client-profile actions:

- `Створити профіль клієнта`: starts a step-by-step client profile dialog.
- `Обрати клієнта`: lists recent workspace client profiles and waits for the exact client name.
- `Показати активного клієнта`: shows the currently selected client context.
- `Змінити профіль клієнта`: starts a replacement client-profile dialog.

The selected client profile is stored in Telegram binding metadata as `active_client_profile_id`. When the user presses `Почати обробку`, this ID is copied to the intake package metadata as `client_profile_id`.

`POST /n8n/telegram/bindings`

Creates or updates the active mapping between a Telegram account and an application workspace user. The target `user_id` must already have `write_documents` permission in the target `workspace_id`.

```json
{
  "telegram_user_id": "123456789",
  "telegram_chat_id": "123456789",
  "username": "lawyer",
  "workspace_id": "uuid",
  "user_id": "uuid",
  "is_active": true
}
```

`POST /n8n/intake/process`

Starts explicit package processing after the user presses `Почати обробку`. The endpoint marks the package as `processing_requested` and records the requested agent/question for the next processing step.
It can also store `client_profile_id` in the package metadata so the downstream processing step can include the client context in agent requests.

`POST /n8n/obsidian/sync-note`

Receives a normalized Obsidian Markdown note from `JUR_Obsidian_Vault_Sync`, stores it as an `obsidian_markdown` document, chunks it, and makes it available to workspace-scoped vector search.
