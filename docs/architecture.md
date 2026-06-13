# Architecture

The application is a FastAPI service with separate layers for API routes, agent orchestration, business services, persistence models, and prompts.

```text
User / Web UI / Open WebUI
  -> FastAPI routes
  -> Legal Platform Orchestrator
  -> Specialized agents
  -> Services
  -> PostgreSQL + pgvector
  -> n8n workflows
```

The central design rule is workspace isolation. Every document chunk, opinion, search result, and audit event must be scoped to the current `workspace_id` unless it comes from the shared legal knowledge base.

## Application Layers

- `app/api`: FastAPI route handlers and HTTP-specific errors.
- `app/schemas`: Pydantic request and response contracts.
- `app/services`: Business workflows that may combine multiple models or repositories.
- `app/repositories`: Persistence-oriented database queries.
- `app/models`: SQLAlchemy ORM models and database table definitions.

Workspace operations use `WorkspaceService` over `WorkspaceRepository`. Creating a workspace also creates an owner membership, so future role checks can rely on `workspace_members` as the single membership source.
