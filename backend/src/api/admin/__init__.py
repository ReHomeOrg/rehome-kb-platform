"""Admin endpoints (#227+).

OpenAPI 04 `/api/v1/admin/*` — 16 endpoints для admin UI. Модуль
landing'ится incremental по мере merge'а PR'ов:
- #227: GET /admin/stats
- #228: GET /admin/llm/providers
- #229: GET /admin/system-config
- #230: kb_users CRUD (5 endpoints)
- #231: security_incidents CRUD (list/get/update)
- #232: personal_data_requests CRUD (list/get/process)
- #237: GET /admin/audit-log (alias surface для /audit-log с
  OpenAPI-compliant param names)
- #238: DELETE /admin/cache + POST /admin/reindex + GET /admin/tasks/{id}
  (operational triad + admin_tasks foundation; reindex — honest stub)
- #239: POST /admin/audit-log/export (admin_tasks-backed task с
  result_url → existing /audit-log/export.csv)
- #244: POST/GET /admin/llm/eval-runs (mock + smoke MVP; results
  inline в admin_task.params per ADR-0013)
- #264: PATCH /admin/system-config + PUT /admin/llm/active per
  ADR-0019 (writable runtime config storage, JSONB single row +
  Settings overlay).
- #336: Keycloak step-up MFA validation (X-MFA-Token JWT verified
  via Keycloak JWKS + acr claim check; replaces #264 honest stub).

Backlog (отдельные PR'ы):
- Real provider support в eval-runs (нужны env credentials)
- Real async worker для admin_tasks (#268 landed asyncio MVP;
  Dramatiq+Redis при scale)
"""
