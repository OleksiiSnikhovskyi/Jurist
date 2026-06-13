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
  "document_id": "optional uuid"
}
```

The MVP skeleton returns a safe placeholder and does not generate legal conclusions without checked sources.

## Lawyer Profiles

`POST /lawyer-profiles`

Creates a personal lawyer profile for an existing `users.id`. Each user can have one profile.

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
