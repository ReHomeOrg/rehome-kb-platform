"""Vault rotation reminders worker entrypoint (#167).

Run: `python -m src.workers.vault_reminders`

Environment:
- `DATABASE_URL` — asyncpg DSN.
- `VAULT_REMINDER_WINDOW_DAYS=7` — за сколько дней до expiry начинать
  напоминания.
- `VAULT_REMINDER_SCAN_INTERVAL_SECONDS=86400` — pause между сканами
  (default 24 hours).
- `VAULT_REMINDER_METRICS_PORT=9101` — Prometheus pull endpoint
  (#176, 0 = disabled).
- `LOG_LEVEL=INFO`.
"""

import asyncio
import logging
import os
import sys

from prometheus_client import start_http_server
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.config import get_settings
from src.workers.vault_reminders.runner import (
    VaultReminderWorker,
    install_signal_handlers,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()

    window_days = int(os.environ.get("VAULT_REMINDER_WINDOW_DAYS", "7"))
    interval = float(os.environ.get("VAULT_REMINDER_SCAN_INTERVAL_SECONDS", "86400"))
    metrics_port = int(os.environ.get("VAULT_REMINDER_METRICS_PORT", "9101"))

    # Prometheus pull endpoint (#176). 0 = disabled (CI / dev без
    # Prometheus). Default port 9101 (indexer держит 9100). Anti-DoS
    # invariant: scope'ить через k8s NetworkPolicy.
    if metrics_port > 0:
        start_http_server(metrics_port)
        logger.info("vault_reminder.metrics_server_started", extra={"port": metrics_port})

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    worker = VaultReminderWorker(
        session_factory=session_factory,
        reminder_window_days=window_days,
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
