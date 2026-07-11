# Tasks

## Status

- [x] MVP backend, database, document ingestion, vector search, agents, n8n templates, and documentation are complete.
- [x] Initial `JUR_` workflows were imported to `https://n8n.csc-ua.tech` and activated.
- [x] Local development knowledge base was seeded from project Markdown files.
- [x] Server FastAPI deployment is running on `markiz` and reachable from n8n as `http://agent-jurist-api:8000`.

## Stage 1: Project Skeleton

- [x] Create FastAPI project structure.
- [x] Add Docker Compose with PostgreSQL + pgvector.
- [x] Add SQLAlchemy database setup.
- [x] Add healthcheck endpoint.
- [x] Add Alembic setup and initial schema migration.
- [x] Add first tests for skeleton behavior.

## Stage 2: Database and Access Control

- [x] Create models for users, lawyer profiles, workspaces, workspace members, documents, legal sources, chunks, legal opinions, audit logs.
- [x] Add CRUD endpoints for lawyer profiles.
- [x] Add repository/service layer for workspaces.
- [x] Add role checks for owner/admin/lawyer/reviewer/viewer.
- [x] Add audit logging service.
- [x] Add tests for cross-workspace access denial.

## Stage 3: Documents

- [x] Implement upload endpoint.
- [x] Store document metadata.
- [x] Extract PDF text.
- [x] Extract DOCX text.
- [x] Add parser tests.

## Stage 4: Search and Agents

- [x] Implement chunk persistence.
- [x] Add embedding provider configuration.
- [x] Add Obsidian Markdown vault ingestion.
- [x] Implement vector search with workspace filters.
- [x] Implement Contract Review Agent.
- [x] Implement Legal Research Agent.
- [x] Implement Quality Control Agent.

## Stage 5: n8n and Docs

- [x] Add n8n workflow templates.
- [x] Add `JUR_` bot intake workflow for voice, photo, scan, Word, Excel, and PDF packages.
- [x] Add `JUR_` Obsidian vault sync workflow.
- [x] Document API endpoints.
- [x] Document deployment.
- [x] Document security model.

## Stage 6: Server Deployment and Activation

- [x] Deploy or expose FastAPI backend so n8n can reach `JUR_API_BASE_URL`.
- [x] Apply Alembic migrations on the server database.
- [x] Configure `JUR_API_BASE_URL` and `JUR_N8N_WEBHOOK_BASE_URL` in the n8n runtime.
- [x] Smoke-test `/health`, `/n8n/intake/telegram`, `/n8n/intake/process`, and `/n8n/obsidian/sync-note` from the server.
- [x] Activate imported `JUR_` workflows.
- [x] Add backend Telegram-to-workspace binding support for real bot intake.
- [x] Send a controlled Telegram test message and verify `n8n_intake_packages` / `n8n_intake_items`.

## Stage 7: Knowledge Base Expansion

- [x] Choose production legal source folders, Obsidian vaults, or document sets for ingestion.
- [x] Add legal-source ingestion script for exported NotebookLM/local law corpus files.
- [x] Add priority legal-source manifest policy for official domains, metadata, deduplication, and source freshness.
- [x] Add Verkhovna Rada catalog/daily-arrivals manifest sync for `zakon.rada.gov.ua`.
- [x] Add Rada daily sync runner that can download official HTML documents for ingestion.
- [x] Add `JUR_Rada_Law_Sync_Qwen` n8n template and API upsert endpoint for Ollama/Qwen-enriched Rada ingestion.
- [x] Ingest selected Markdown/Obsidian materials into the production workspace.
- [x] Add PDF/DOCX/XLSX/HTML bulk ingestion flow for legal source packs.
- [x] Add OCR pipeline for photos and scanned documents.
- [x] Add voice transcription pipeline for Telegram voice messages.
- [x] Add source freshness metadata for laws, court practice, and regulatory materials.
- [x] Fill the production `priority_manifest.csv` from official source exports and ingest the legal corpus. Rada catalog backfill completed control-safe with `missing_files: 0`; 18 catalog pages are preserved in `legal_sources/rada_catalog_failures.log` for retry from another IP/VPN.
- [x] Schedule daily Rada arrivals sync and ingest delta updates. Daily sync now preserves Rada validity statuses (`current`, `pending_effective`, `obsolete`, `needs_verification`).
- [x] Parse and store legal-source validity metadata from Rada updates: `effective_date`, `revision_date`, and `validity_note`.
- [x] Automatically re-embed newly ingested law chunks after daily sync via `/n8n/maintenance/reembed-missing-chunks`.

## Stage 7A: Search Performance Foundation

- [x] Install `bge-m3` on Miledy Ollama and verify `/api/embed` returns 1024-dimensional vectors.
- [x] Add Ollama embedding provider configuration for `bge-m3`.
- [x] Add migration for `document_chunks.embedding` as `vector(1024)` plus pgvector/search indexes.
- [x] Add resume-safe document chunk re-embedding script.
- [x] Move PostgreSQL vector search from Python cosine scoring to pgvector SQL ordering.
- [x] Run production pgvector migration on `jur_db`.
- [x] Re-embed all production chunks with `bge-m3` (`document_chunks.embedding` null count is 0).
- [x] Add structured Telegram/RAG timing logs.
- [x] Add Obsidian registry/aliases sync for exact legal-source routing.
- [x] Add and run Obsidian aliases backfill for existing synced notes.
- [x] Deploy Obsidian workflow frontmatter parsing for aliases and legal-source metadata.

## Stage 7B: Knowledge Corpus Completion

- [x] Continue Rada backfill until the official catalog is fully processed. Audit note: retry offsets 1844-1861 from `rada_catalog_failures.log` via VPN/Miledy IP when available.
- [x] Keep only valid/current official documents in the production manifest; obsolete/invalid sources are excluded from production RAG search and retained only as auditable source records.
- [x] Rebuild and validate `priority_manifest.csv` after corpus completion batches; current production manifest has no missing files.
- [x] Re-ingest or refresh legal corpus chunks after embedding migration when needed; current `document_chunks.embedding` null count is 0.
- [x] Keep daily Rada delta chunks searchable immediately by running automatic missing-embedding refresh after each sync.

## Stage 8: Telegram User Onboarding

- [x] Require lawyer activity direction during Telegram onboarding.
- [x] Allow Telegram users to update their personal system prompt.
- [x] Add workspace-scoped client profiles for processing context.
- [x] Include `client_profile_id` in agent/package processing requests.
- [x] Add Telegram client-profile onboarding and active client selection.
- [x] Attach active Telegram client profile to packages on `Почати обробку`.
- [x] Add Telegram client-profile submenu for selecting and editing active clients.
- [ ] Design full Telegram-to-user/workspace binding flow.
- [x] Add backend model or mapping for Telegram users and workspace access.
- [x] Apply Telegram binding migration on the server.
- [x] Create first real Telegram binding for the production workspace.
- [x] Deploy updated Telegram profile prompt buttons to the active n8n workflow.
- [x] Add bot commands for choosing active client profile.
- [x] Add bot commands for choosing workspace/case.
- [x] Add package review UX before `Почати обробку`.
- [x] Add delete-one-material and cancel-processing behavior end to end.

## Stage 9: Legal Answer Production

- [x] Add query router so contract-only questions use active document chunks, exact legal references use exact lookup, and general questions use hybrid search.
- [x] Connect package processing to document extraction, chunking, vector search, and agents for Telegram-extracted documents and voice transcripts.
- [x] Store generated answers in `legal_opinions`.
- [x] Add lawyer review/approval state for generated opinions.
- [x] Add official-source verification workflow for legislation and court practice.
- [x] Add controlled official-source web search stage for gaps and freshness checks only.
  - Restrict search to official domains such as `zakon.rada.gov.ua`, `court.gov.ua`, `supreme.court.gov.ua`, `kmu.gov.ua`, ministries, NERC, DBN/DSTU sources.
  - Trigger it only when RAG confidence is low, the answer needs current validity, or exact legal/court references must be verified.
  - Exclude news sites, private legal blogs, forums, and unofficial commentary.
- [x] Add export of final answers to DOCX/PDF.

## Stage 10: Production Hardening

- [x] Add API authentication for `/n8n/...` integration endpoints.
- [x] Add rate limits and payload-size limits for bot uploads.
- [x] Add structured logging and execution tracing.
- [x] Add backup/restore instructions for `jur_db`.
- [x] Add CI workflow for tests and migration checks.
- [x] Replace deterministic embeddings configuration with a production Ollama embedding provider.
## Stage 11: Evaluation and QA Harness

- [x] Add local legal-answer evaluation dataset across multiple domains.
- [x] Add rule-based answer quality scoring for structure, official-source grounding, required terms, and forbidden claims.
- [x] Add evaluation report output in Markdown/CSV for offline review and Kaggle-style analysis.
- [x] Add optional LLM judge for legal relevance, completeness, hallucination risk, and answer form.
- [x] Add n8n/Telegram smoke tests that send controlled questions and capture bot answers.
- [x] Define quality thresholds for release readiness and lawyer review escalation.
