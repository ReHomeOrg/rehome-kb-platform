"""Popular-query worker entrypoint (#220).

Run: `python -m src.workers.popular_query`

Environment:
- `DATABASE_URL` — asyncpg DSN.
- `POPULAR_QUERY_WINDOW_HOURS=24` — lookback window для aggregation.
- `POPULAR_QUERY_MIN_COUNT=3` — minimum occurrences для попадания в event.
- `POPULAR_QUERY_MAX_QUERIES=50` — cap количества queries в payload.
- `POPULAR_QUERY_SCAN_INTERVAL_SECONDS=86400` — pause между сканами.
- `POPULAR_QUERY_METRICS_PORT=9102` — Prometheus pull endpoint (0 = disabled).
- `LOG_LEVEL=INFO`.
"""

import asyncio
import logging
import os
import sys

from prometheus_client import start_http_server
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.config import get_settings
from src.workers.popular_query.runner import (
    PopularQueryWorker,
    install_signal_handlers,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()

    window_hours = int(os.environ.get("POPULAR_QUERY_WINDOW_HOURS", "24"))
    min_count = int(os.environ.get("POPULAR_QUERY_MIN_COUNT", "3"))
    max_queries = int(os.environ.get("POPULAR_QUERY_MAX_QUERIES", "50"))
    interval = float(os.environ.get("POPULAR_QUERY_SCAN_INTERVAL_SECONDS", "86400"))
    metrics_port = int(os.environ.get("POPULAR_QUERY_METRICS_PORT", "9102"))

    if metrics_port > 0:
        start_http_server(metrics_port)
        logger.info("popular_query.metrics_server_started", extra={"port": metrics_port})

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    worker = PopularQueryWorker(
        session_factory=session_factory,
        window_hours=window_hours,
        min_count=min_count,
        max_queries=max_queries,
        scan_interval_seconds=interval,
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
