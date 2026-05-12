"""Documents module — metadata-only (E2.8 #56).

Document model для kb-files. ВАЖНО: эта реализация НЕ включает MinIO
+ signed URL для скачивания файлов. Эндпоинт `/{id}/files/{format}`
возвращает HTTP 501 (architect approved deviation от OpenAPI 04 —
download будет реализован в kb-files эпике).

Access control: `confidentiality` enum (PUBLIC/INTERNAL/RESTRICTED) —
отличается от articles' `access_level`. Маппинг — в `access.py`.
"""
