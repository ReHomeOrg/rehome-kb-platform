"""Webhooks module — E5 эпик.

E5.1 — foundation (model + CRUD endpoints).
E5.2 — outbox + delivery worker (in-process asyncio).
E5.4 — event integration с articles/chat triggers.

Architecture (Architect decisions 2026-05-13):
- Delivery: in-process asyncio worker, без новых deps (Dramatiq+Redis
  в backlog при scaling).
- SSRF защита: блокировать RFC1918 internal IPs.
- Signing: HMAC-SHA256 over raw body (Stripe-like).
"""
