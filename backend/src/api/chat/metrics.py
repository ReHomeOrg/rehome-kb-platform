"""Prometheus metrics для chat module (#179).

In-process: метрики через общий `/metrics` endpoint.

Metrics:
- `kb_chat_sessions_created_total{scope}` — counter сессий, label
  scope ∈ AccessLevel enum values (~5: guest/tenant/staff/legal/etc).
- `kb_chat_messages_total{scope}` — counter messages sent (user
  POST к /sessions/{id}/messages).
- `kb_chat_message_duration_seconds` — histogram end-to-end длительности
  send-message handler'а (включая retrieval + LLM response).

Cardinality: scope ~5 values; safe.
"""

from typing import Final

from prometheus_client import Counter, Histogram

# Chat message — RAG retrieval (~100ms) + LLM streaming response
# (~2-30s typical). Outliers до timeout (~60s).
_MESSAGE_DURATION_BUCKETS: Final = (
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    30.0,
    60.0,
)


SESSIONS_CREATED_TOTAL: Final = Counter(
    "kb_chat_sessions_created_total",
    "Total chat sessions created, labelled by initiator scope.",
    labelnames=("scope",),
)

MESSAGES_TOTAL: Final = Counter(
    "kb_chat_messages_total",
    "Total chat user messages sent, labelled by session scope.",
    labelnames=("scope",),
)

MESSAGE_DURATION_SECONDS: Final = Histogram(
    "kb_chat_message_duration_seconds",
    "End-to-end chat message handler duration (retrieval + LLM response).",
    buckets=_MESSAGE_DURATION_BUCKETS,
)

# C23: срабатывания жёсткого retrieval-gate — сколько ответов вернули детерминированный
# no-answer (нет уверенного контекста) вместо вызова LLM. Сигнал «content gap» + доля
# запросов без уверенной базы (калибровка порога / приоритет наполнения KB).
RAG_HARD_GATE_TOTAL: Final = Counter(
    "kb_chat_rag_hard_gate_total",
    "Chat responses short-circuited to a deterministic no-answer by the C23 hard "
    "retrieval-gate (no confident context, LLM not called).",
)


__all__ = [
    "MESSAGES_TOTAL",
    "MESSAGE_DURATION_SECONDS",
    "RAG_HARD_GATE_TOTAL",
    "SESSIONS_CREATED_TOTAL",
]
