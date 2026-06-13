# n8n Workflows

Planned workflow templates:

- `JUR_Bot_Intake_Queue.json`
- `JUR_Document_Ingestion.json`
- `JUR_Document_Processing_Start.json`
- `JUR_Legal_Update_Monitoring.json`
- `JUR_Case_Law_Indexing.json`
- `JUR_Weekly_Digest.json`

Workflows should call FastAPI webhook endpoints and preserve `workspace_id`, `user_id`, and document confidentiality metadata through every step.

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

- `Додати фото або документ`: prompts the user to upload one or more files.
- `Додати голосове повідомлення`: prompts the user to send voice context or instructions.
- `Показати додані матеріали`: lists the pending files/messages in the current intake package.
- `Видалити матеріал`: lets the user remove a mistaken file before processing.
- `Очистити пакет`: clears the current pending intake package.
- `Почати обробку`: explicitly starts extraction, OCR/transcription, indexing, and legal analysis.
- `Статус обробки`: shows whether extraction/indexing/analysis is queued, running, failed, or completed.
- `Скасувати обробку`: cancels a pending or queued package where possible.

Recommended workflow split:

- `JUR_Bot_Intake_Queue`: receives Telegram/bot messages and attachments, stores metadata and binaries, and updates pending package state.
- `JUR_Document_Processing_Start`: runs only after the `Почати обробку` action and sends the queued package to FastAPI.
- `JUR_Document_Ingestion`: extracts text from PDFs, DOCX, Excel files, scans, photos, and voice transcripts, then stores document metadata and chunks.

The workflow must keep a clear package/session ID so that multiple uploads from one user can be processed together. If a user sends files without pressing `Почати обробку`, the system should acknowledge receipt and wait.
