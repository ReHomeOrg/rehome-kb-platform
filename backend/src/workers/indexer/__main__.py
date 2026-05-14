"""Indexer worker entrypoint (#149).

Run: `python -m src.workers.indexer`

Environment:
- `DATABASE_URL` — asyncpg DSN (см. config.py)
- `EMBEDDING_PROVIDER=hf` для production (mock для CI / dev)
- `EMBEDDING_MODEL=intfloat/multilingual-e5-large`
- `INDEXER_BATCH_SIZE=10`
- `INDEXER_POLL_INTERVAL_SECONDS=30`
- `INDEXER_METRICS_PORT=9100` (#152, 0 = disabled)
"""

import asyncio
import logging
import os
import sys

from prometheus_client import start_http_server
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.config import get_settings
from src.api.search.retrieval import _build_provider
from src.workers.indexer.runner import (
    IndexerWorker,
    install_signal_handlers,
    make_default_indexer,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()

    if not settings.rag_enabled:
        logger.warning("indexer_worker.rag_disabled — set RAG_ENABLED=true to enable")

    batch_size = int(os.environ.get("INDEXER_BATCH_SIZE", "10"))
    poll_interval = float(os.environ.get("INDEXER_POLL_INTERVAL_SECONDS", "30"))
    metrics_port = int(os.environ.get("INDEXER_METRICS_PORT", "9100"))

    # Prometheus pull endpoint (#152). 0 = disabled (CI / dev без
    # Prometheus). По умолчанию слушает 0.0.0.0:9100 — Anti-DoS
    # invariant: внутренний port, scope'ить через k8s NetworkPolicy
    # или nginx upstream только для Prometheus pod'а.
    if metrics_port > 0:
        start_http_server(metrics_port)
        logger.info("indexer_worker.metrics_started", extra={"port": metrics_port})

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Provider — singleton (model load expensive, ~30s + 2.3GB RAM).
    # Reused across batches; rebuilt не нужно.
    provider = _build_provider(settings)
    make_indexer = make_default_indexer(provider)

    worker = IndexerWorker(
        session_factory=session_factory,
        make_indexer=make_indexer,
        batch_size=batch_size,
        poll_interval_seconds=poll_interval,
    )

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop, worker)

    try:
        await worker.run_forever()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
