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

- `Клієнти`: opens the client-profile submenu and shows the active client if one is selected. Free text in this menu is ignored until a client action button is chosen.
- `Новий клієнт` / `Створити профіль клієнта`: starts a step-by-step client profile dialog.
- `Обрати клієнта`: lists recent workspace client profiles as `1. Назва клієнта` and waits for the numeric choice.
- `Показати активного клієнта`: shows the currently selected client context.
- `Налаштування клієнта` / `Змінити профіль клієнта`: shows the active client profile and starts an edit dialog for that same profile.
- `Видалити клієнта`: lists profiles as `1. Назва клієнта` and waits for the numeric choice to delete. If the deleted profile was active, the active selection is cleared.
- `Назад`: returns to the main menu and cancels an incomplete client-profile dialog.

The selected client profile is stored in Telegram binding metadata as `active_client_profile_id`. When the user presses `Почати обробку`, or when `/n8n/intake/process` starts without an explicit `client_profile_id`, this ID is copied to the intake package metadata as `client_profile_id`.

Telegram package-processing actions:

- `Пакетна обробка`: switches Telegram binding metadata to package mode and returns the package submenu.
- `Додати фото або документ` / `Додати голосове повідомлення`: in package mode, adds material to the current package and waits for `Почати обробку`.
- `Показати додані матеріали`, `Очистити пакет`, `Статус обробки`, `Почати обробку`: operate on the current package.
- `Назад`: returns to the main menu and leaves package mode.

Outside package mode, a normal text question is analyzed immediately. A single photo/document/voice message outside package mode is marked with `auto_process_after_extraction`; after OCR, parsing, or transcription calls `/n8n/intake/extracted-text`, FastAPI starts legal analysis automatically with the active client profile.

`POST /n8n/intake/extracted-text`

Attaches OCR/document extraction or voice transcription output to a pending Telegram intake item and indexes it as a private workspace document. This is the integration point for LinguistProAi extraction workflows and existing Telegram voice transcription workflows.

```json
{
  "package_id": "uuid",
  "external_file_id": "telegram-file-id",
  "extracted_text": "Recognized document or voice transcript text",
  "file_name": "contract.pdf",
  "mime_type": "application/pdf",
  "extraction_method": "linguistproai.ocr_extract",
  "document_type": "telegram_pdf"
}
```

`item_id` may be sent instead of `external_file_id` when n8n already knows the database item ID. The endpoint updates the matching intake item, creates or updates a `telegram://...` document, rebuilds chunks, and leaves the package ready for explicit `Почати обробку`. If package metadata contains `auto_process_after_extraction=true`, the endpoint starts analysis immediately after indexing and may return `status` and `answer`.

### `POST /n8n/legal-sources/upsert`

Stores or updates one official legal source from `zakon.rada.gov.ua`, creates/updates the corresponding workspace document, and rebuilds chunks for later pgvector search.

Expected fields:

- `workspace_id`, `user_id`
- `source_name`, `source_type`, `source_url`
- `document_number`, `adoption_date`, `effective_date`, `validity_status`
- `last_checked_at`, `topic_tags`, `summary`
- `full_text`
- optional `file_path`, `jurisdiction`, `chunk_size`, `overlap`

This endpoint accepts only official `zakon.rada.gov.ua` URLs. Local LLM output may be passed in `summary`, `topic_tags`, and `source_type`, but official metadata and `full_text` should come from the Rada source page.


`POST /n8n/legal-sources/verification-candidates`

Returns stale official legal-source URLs that should be checked by n8n. The endpoint requires `workspace_id` and `user_id` for access control, accepts `limit` and `max_age_days`, and returns only allowlisted official domains that are not obsolete.

`POST /n8n/legal-sources/verify-official-sources`

Stores official-source verification metadata for legislation and court-practice references. It records URL/domain, allowlist status, verification status, HTTP status, confidence, checked timestamp, and compact evidence payloads in `legal_source_verifications`. It does not store fetched page text.


`POST /n8n/official-source-search/plan`

Builds a controlled official-source web-search plan. The endpoint does not fetch pages itself. It records metadata in `official_source_search_runs`, returns allowlisted `site:` queries, and classifies candidate URLs as accepted or rejected.

Search is allowed only when at least one controlled trigger is present:

- `trigger_reason` is `low_rag_confidence`, `current_validity_required`, or `exact_reference_verification`;
- `rag_confidence` is below the backend threshold;
- `requires_current_validity=true`;
- `exact_references` contains one or more legal/court references.

```json
{
  "workspace_id": "uuid",
  "user_id": "uuid",
  "query": "стаття 625 ЦК України",
  "trigger_reason": "low_rag_confidence",
  "rag_confidence": 0.2,
  "requires_current_validity": false,
  "exact_references": ["ЦК України ст. 625"],
  "candidate_urls": ["https://zakon.rada.gov.ua/laws/show/435-15"]
}
```

Allowed domains include `zakon.rada.gov.ua`, `court.gov.ua`, `supreme.court.gov.ua`, `kmu.gov.ua`, ministries, NERC, DBN/DSTU-related official sources. News sites, private legal blogs, forums, and unofficial commentary are rejected.

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

Starts explicit package processing after the user presses `Почати обробку`. The endpoint records the requested agent/question and can store `client_profile_id` in package metadata so the processing step includes client context.

When `JUR_OLLAMA_BASE_URL` is configured, FastAPI sends extracted text messages, the lawyer system prompt, the active client profile, and workspace-scoped retrieval fragments to local Ollama/Qwen and returns the answer in `answer`. The package status becomes `processed` on success, `llm_error` on Ollama failure, or `waiting_for_text_extraction` when the package contains only files/media without extracted text.

`POST /n8n/obsidian/sync-note`

Receives a normalized Obsidian Markdown note from `JUR_Obsidian_Vault_Sync`, stores it as an `obsidian_markdown` document, chunks it, and makes it available to workspace-scoped vector search.

## Legal Opinions

`GET /legal-opinions/by-workspace/{workspace_id}?user_id={user_id}`

Lists legal opinions visible to the workspace member.

`GET /legal-opinions/{opinion_id}?user_id={user_id}`

Returns one legal opinion when the user has workspace read permission.

`PATCH /legal-opinions/{opinion_id}/review`

Updates review status and review notes. The caller must have review permission.

`POST /legal-opinions/{opinion_id}/export`

Exports a final answer to DOCX or PDF and stores export metadata in `legal_opinion_exports`.

```json
{
  "user_id": "uuid",
  "export_format": "docx"
}
```

`export_format` may be `docx` or `pdf`. DOCX export uses `python-docx`; PDF export converts the generated DOCX through LibreOffice/soffice. Files are written below `EXPORT_DIR/legal_opinions`.
