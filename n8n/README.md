# n8n Workflows

Planned workflow templates:

- `workflows/JUR_Bot_Intake_Queue.json`
- `workflows/JUR_Document_Processing_Start.json`
- `workflows/JUR_Obsidian_Vault_Sync.json`
- `JUR_Document_Ingestion.json`
- `JUR_Legal_Update_Monitoring.json`
- `JUR_Case_Law_Indexing.json`
- `JUR_Weekly_Digest.json`

Workflows should call FastAPI webhook endpoints and preserve `workspace_id`, `user_id`, and document confidentiality metadata through every step.

The checked-in templates are inactive by default and use placeholder Telegram credentials:

- `__TELEGRAM_CREDENTIAL_ID__`
- `__TELEGRAM_CREDENTIAL_NAME__`

After import into n8n, replace those placeholders with the Telegram credential created in the target n8n project.

Required n8n environment variables:

- `JUR_API_BASE_URL`: FastAPI backend URL, for example `http://localhost:8000`.
- `JUR_N8N_WEBHOOK_BASE_URL`: public n8n webhook base URL, for example `https://n8n.example.com/webhook`.

## Bot Intake Requirements

The user may send several materials before asking the system to process them. The workflow must collect incoming items into a pending intake package and must not start document analysis until the user explicitly requests processing.

Supported incoming materials:

- Voice messages.
- Photos of documents.
- Scanned document copies.
- Word documents.
- Excel documents.
- PDF documents and other ordinary file attachments when supported by the backend.

Expected bot actions/buttons:

- `Пакетна обробка`: opens a dedicated package submenu for multi-document work.
- `Клієнти`: opens the active-client submenu.
- `Змінити системний промпт`: updates the lawyer's personal prompt/profile.

Package submenu buttons:

- `Додати фото або документ`: prompts the user to upload one or more package files.
- `Додати голосове повідомлення`: prompts the user to send package voice context or instructions.
- `Показати додані матеріали`: lists the pending files/messages in the current intake package.
- `Видалити матеріал`: lets the user remove a mistaken file before processing.
- `Очистити пакет`: clears the current pending intake package.
- `Почати обробку`: explicitly starts extraction, OCR/transcription, indexing, and legal analysis for the package.
- `Статус обробки`: shows whether extraction/indexing/analysis is queued, running, failed, or completed.
- `Скасувати обробку`: cancels a pending or queued package where possible.
- `Назад`: returns to the main menu.

Recommended workflow split:

- `JUR_Bot_Intake_Queue`: receives Telegram/bot messages and attachments, stores metadata and binaries, and updates pending package state.
- `JUR_Document_Processing_Start`: runs only after the `Почати обробку` action and sends the queued package to FastAPI.
- `JUR_Document_Ingestion`: extracts text from PDFs, DOCX, Excel files, scans, photos, and voice transcripts, then stores document metadata and chunks.

For document extraction, reuse the existing LinguistProAi internal service where possible:

- `http://linguistproai-internal-ai:8011/internal/v2/parse-document`
- `http://linguistproai-internal-ai:8011/internal/v2/segment-document`
- legacy helpers: `/internal/text-extract` and `/internal/ocr-extract`

For voice messages, reuse the existing Telegram voice pattern from LiveCalendar: Telegram download voice file -> audio transcription -> send the transcript to Jurist as extracted text.

After any OCR/text extraction/transcription step, call `POST /n8n/intake/extracted-text` with `package_id`, `external_file_id` or `item_id`, and `extracted_text`. FastAPI updates the matching intake item, creates/updates a private workspace document, rebuilds chunks, and then `Почати обробку` can include that text in the Qwen legal analysis.

`JUR_Bot_Intake_Queue` now includes the first production extraction branch:

- after `/n8n/intake/telegram` returns a `package_id`, attachment metadata is expanded into extraction jobs;
- document/photo jobs download the Telegram file, send base64 content to `http://linguistproai-internal-ai:8011/internal/v2/parse-document`, collect extracted node text, and call `/n8n/intake/extracted-text`;
- voice jobs download the Telegram voice file, transcribe audio with the existing OpenAI transcription node pattern, and call `/n8n/intake/extracted-text`;
- in package mode, this branch indexes extracted text only and legal analysis waits for explicit `Почати обробку`;
- outside package mode, a single document/photo/voice message is marked for automatic analysis after OCR or transcription.

The workflow must keep a clear package/session ID so that multiple uploads from one user can be processed together. If a user enters `Пакетна обробка`, files wait until `Почати обробку`. If a user sends a normal text question or a single file/voice message outside package mode, FastAPI creates a short-lived package and starts analysis immediately, or after extraction when the text becomes available.

## Obsidian Requirements

Obsidian can be used as a lawyer's Markdown knowledge vault. A future `JUR_Obsidian_Vault_Sync` workflow should ingest selected Markdown notes and keep them searchable alongside uploaded documents.

Expected Obsidian inputs:

- Markdown note body.
- YAML frontmatter, including `aliases`, `document_number`, `source_name`, and `source_url` when a note represents or points to a legal source.
- Tags.
- Internal links and backlinks where available.
- Folder path as workspace/context metadata.
- Attachments referenced by Markdown notes when supported.

Important rules:

- Sync only explicitly configured vault folders or notes.
- Preserve `workspace_id`, `user_id`, and source path metadata.
- Treat private vault notes as workspace-scoped private knowledge.
- Do not process or re-index a vault automatically if the user has configured manual sync mode.
- Store Obsidian chunks separately enough to identify their source as `obsidian`, while still allowing unified vector search later.

## Template Endpoints

The first workflow templates target these backend integration endpoints:

- `POST /n8n/intake/telegram`: receives normalized Telegram events and updates the pending package.
- `POST /n8n/intake/extracted-text`: attaches OCR/document/voice transcript text to a queued intake item and indexes it.
- `POST /n8n/intake/process`: starts explicit package processing after `Почати обробку`.
- `POST /n8n/obsidian/sync-note`: ingests one normalized Obsidian note into workspace-scoped search.

These endpoints are intentionally separate from the public document and agent endpoints so that bot package state, OCR/transcription, and retry metadata can evolve without changing user-facing APIs.

## Current Server Import

Imported into `https://n8n.csc-ua.tech` on 2026-06-13:

- `JUR_Bot_Intake_Queue`: `nWAfwIrKQt1kBgnJ` (`https://n8n.csc-ua.tech/workflow/nWAfwIrKQt1kBgnJ`)
- `JUR_Document_Processing_Start`: `tvcUdTGWwatqdS4e` (`https://n8n.csc-ua.tech/workflow/tvcUdTGWwatqdS4e`)
- `JUR_Obsidian_Vault_Sync`: `NGubhhjGjGp8lh57` (`https://n8n.csc-ua.tech/workflow/NGubhhjGjGp8lh57`)
- `JUR_Rada_Law_Sync_Qwen`: `idhN3BnLzF6VtTyp` (`https://n8n.csc-ua.tech/workflow/idhN3BnLzF6VtTyp`)

`JUR_Bot_Intake_Queue` uses the n8n Telegram credential `PravnykAi`. The workflows are active, but production processing still requires `JUR_API_BASE_URL` to point to a reachable FastAPI deployment.


