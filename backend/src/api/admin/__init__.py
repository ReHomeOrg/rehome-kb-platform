"""Admin endpoints (#231+).

OpenAPI 04 `/api/v1/admin/*` — 16 endpoints для admin UI. Этот модуль
landing'ит incremental:
- #231: security_incidents CRUD (этот PR)

Backlog (отдельные PR'ы):
- /admin/stats
- /admin/users (kb_users CRUD)
- /admin/llm/providers + active + eval-runs
- /admin/system-config (GET + PATCH)
- /admin/audit-log + export
- /admin/personal-data/requests
- /admin/cache + reindex + tasks/{id}
"""
