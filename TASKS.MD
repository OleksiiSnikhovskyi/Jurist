# Tasks

## Status

- [x] MVP backend, database, document ingestion, vector search, agents, n8n templates, and documentation are complete.
- [x] Initial `JUR_` workflows were imported to `https://n8n.csc-ua.tech` and left inactive.
- [x] Local development knowledge base was seeded from project Markdown files.

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

- [ ] Deploy or expose FastAPI backend so n8n can reach `JUR_API_BASE_URL`.
- [ ] Apply Alembic migrations on the server database.
- [ ] Configure `JUR_API_BASE_URL` and `JUR_N8N_WEBHOOK_BASE_URL` in the n8n runtime.
- [ ] Smoke-test `/health`, `/n8n/intake/telegram`, `/n8n/intake/process`, and `/n8n/obsidian/sync-note` from the server.
- [ ] Activate imported `JUR_` workflows after endpoint checks pass.
- [ ] Send a controlled Telegram test message and verify `n8n_intake_packages` / `n8n_intake_items`.

## Stage 7: Knowledge Base Expansion

- [ ] Choose production legal source folders, Obsidian vaults, or document sets for ingestion.
- [ ] Ingest selected Markdown/Obsidian materials into the production workspace.
- [ ] Add PDF/DOCX/XLSX bulk ingestion flow for legal source packs.
- [ ] Add OCR pipeline for photos and scanned documents.
- [ ] Add voice transcription pipeline for Telegram voice messages.
- [ ] Add source freshness metadata for laws, court practice, and regulatory materials.

## Stage 8: Telegram User Onboarding

- [ ] Design Telegram-to-user/workspace binding flow.
- [ ] Add backend model or mapping for Telegram users and workspace access.
- [ ] Add bot commands for choosing workspace/case.
- [ ] Add package review UX before `Почати обробку`.
- [ ] Add delete-one-material and cancel-processing behavior end to end.

## Stage 9: Legal Answer Production

- [ ] Connect package processing to document extraction, chunking, vector search, and agents.
- [ ] Store generated answers in `legal_opinions`.
- [ ] Add lawyer review/approval state for generated opinions.
- [ ] Add official-source verification workflow for legislation and court practice.
- [ ] Add export of final answers to DOCX/PDF.

## Stage 10: Production Hardening

- [ ] Add API authentication for `/n8n/...` integration endpoints.
- [ ] Add rate limits and payload-size limits for bot uploads.
- [ ] Add structured logging and execution tracing.
- [ ] Add backup/restore instructions for `jur_db`.
- [ ] Add CI workflow for tests and migration checks.
- [ ] Replace deterministic embeddings with a production embedding provider.
