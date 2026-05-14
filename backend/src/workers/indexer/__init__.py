"""RAG indexer worker (#149).

Polling-based: каждые `INDEXER_POLL_INTERVAL_SECONDS` фетчит PUBLISHED
articles без embeddings под текущим `EMBEDDING_PROVIDER`'s model_id,
индексирует batch. Blue-green re-embedding автоматически срабатывает
при смене model_id.

Run: `python -m src.workers.indexer`
Docker: `backend/Dockerfile.indexer` (heavy RAG deps).
"""

from src.workers.indexer.runner import (
    IndexerWorker,
    install_signal_handlers,
    make_default_indexer,
)

__all__ = ["IndexerWorker", "install_signal_handlers", "make_default_indexer"]
