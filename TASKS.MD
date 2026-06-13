# Tasks

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
- [ ] Add Obsidian Markdown vault ingestion.
- [ ] Implement vector search with workspace filters.
- [ ] Implement Contract Review Agent.
- [ ] Implement Legal Research Agent.
- [ ] Implement Quality Control Agent.

## Stage 5: n8n and Docs

- [ ] Add n8n workflow templates.
- [ ] Add `JUR_` bot intake workflow for voice, photo, scan, Word, Excel, and PDF packages.
- [ ] Add `JUR_` Obsidian vault sync workflow.
- [ ] Document API endpoints.
- [ ] Document deployment.
- [ ] Document security model.
