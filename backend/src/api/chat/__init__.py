"""Chat module — foundation E3.1 (Issue #61).

ChatSession + ChatMessage data layer для AI-чата. HTTP роутеры — E3.2.
LLMProvider abstraction (vLLM) — E3.7.

Authorization model:
- ChatSession принадлежит **либо** authenticated user (`user_id` = JWT sub),
  **либо** anonymous client (`session_token` = opaque UUID, выдаётся при
  create и хранится клиентом в cookie/header).
- На каждый access (get/list/delete) repository проверяет ownership через
  `get_session_by_owner`. Без хотя бы одного identifier — return None.
"""
