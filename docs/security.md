# Security Model

Core requirements:

- Enforce workspace isolation on all private documents.
- Check user role before document access.
- Log access-sensitive actions into `audit_logs`.
- Do not log full confidential document text.
- Keep secrets in `.env`, not in git.
- Mark legal answers as unverified when source freshness is unknown.
- Never use private documents from another workspace in retrieval or agent responses.
