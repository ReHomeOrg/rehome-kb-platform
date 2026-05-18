"""Admin endpoints (#232+).

OpenAPI 04 `/api/v1/admin/*` — 16 endpoints для admin UI. Этот модуль
landing'ит incremental:
- #232: personal_data_requests CRUD (этот PR)

Backlog (отдельные PR'ы):
- /admin/stats / /admin/users / /admin/security-incidents
- /admin/llm/providers + active + eval-runs
- /admin/system-config (GET + PATCH)
- /admin/audit-log + export
- /admin/cache + reindex + tasks/{id}
"""
