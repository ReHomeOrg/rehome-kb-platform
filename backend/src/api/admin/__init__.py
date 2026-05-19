"""Admin endpoints (#227+).

OpenAPI 04 `/api/v1/admin/*` — 16 endpoints для admin UI. Этот модуль
landing'ит incremental:
- #230: kb_users CRUD (этот PR)

Backlog (отдельные PR'ы):
- /admin/stats
- /admin/llm/providers + active
- /admin/system-config (GET + PATCH)
- /admin/audit-log + export
- /admin/security-incidents
- /admin/personal-data/requests
- /admin/cache + reindex + tasks/{id}
"""
