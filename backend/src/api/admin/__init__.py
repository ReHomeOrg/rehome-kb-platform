"""Admin endpoints (#227+).

OpenAPI 04 `/api/v1/admin/*` — 16 endpoints для admin UI. Модуль
landing'ится incremental по мере merge'а PR'ов:
- #227: GET /admin/stats
- #228: GET /admin/llm/providers
- #229: GET /admin/system-config
- #230: kb_users CRUD (5 endpoints)
- #231: security_incidents CRUD (list/get/update)
- #232: personal_data_requests CRUD (list/get/process)

Backlog (отдельные PR'ы):
- PATCH /admin/system-config (runtime config storage)
- PUT /admin/llm/active + /admin/llm/eval-runs
- /admin/cache + reindex + tasks/{id}
- /admin/audit-log + export (alias /api/v1/audit-log)
"""
