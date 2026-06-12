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
