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
- [ ] Add tests for cross-workspace access denial.

## Stage 3: Documents

- [ ] Implement upload endpoint.
- [ ] Store document metadata.
- [ ] Extract PDF text.
- [ ] Extract DOCX text.
- [ ] Add parser tests.

## Stage 4: Search and Agents

- [ ] Implement chunk persistence.
- [ ] Add embedding provider configuration.
- [ ] Implement vector search with workspace filters.
- [ ] Implement Contract Review Agent.
- [ ] Implement Legal Research Agent.
- [ ] Implement Quality Control Agent.

## Stage 5: n8n and Docs

- [ ] Add n8n workflow templates.
- [ ] Document API endpoints.
- [ ] Document deployment.
- [ ] Document security model.
