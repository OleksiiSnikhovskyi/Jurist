# Specification

Authoritative technical assignment: [TOR/Технічне завдання.md](TOR/Технічне%20завдання.md).

## Product Goal

Create a local or semi-local Ukrainian legal AI assistant platform for lawyers and legal professionals. The system must analyze legal documents, search source-aware Ukrainian legal materials, check source freshness, support private workspaces, and store knowledge in PostgreSQL/pgvector.

## Architecture

The platform is organized as:

- FastAPI backend.
- Legal Platform Orchestrator.
- Workspace access control.
- Personal lawyer profiles with system prompt, specialization, work context, represented interests, and communication preferences.
- Legal research, contract review, case law, drafting, regulatory monitoring, and quality control agents.
- PostgreSQL + pgvector.
- n8n workflow automation for ingestion, monitoring, indexing, and reporting.
- Obsidian vault ingestion for Markdown notes, legal templates, personal knowledge bases, case notes, tags, and backlinks.

## MVP

- Docker Compose.
- PostgreSQL + pgvector.
- FastAPI backend.
- Users and workspaces.
- Lawyer profile for each legal professional.
- Document upload.
- PDF/DOCX/XLSX text extraction.
- Bot intake for voice messages, document photos, scanned copies, Word files, Excel files, and PDFs, with processing started only after an explicit user command.
- Chunking and embeddings.
- Obsidian Markdown vault indexing.
- Vector search.
- Basic orchestrator.
- Contract Review Agent.
- Legal Research Agent.
- Quality Control Agent.
- Stored legal opinions.
- Workspace isolation.
- Tests and documentation.

## Legal Safety

The system must not invent legislation, cases, citations, document details, or definitive legal conclusions. Every legal answer that depends on current law must be checked against available sources or clearly marked as requiring verification.
