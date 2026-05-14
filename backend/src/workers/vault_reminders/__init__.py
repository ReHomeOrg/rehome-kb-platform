"""Vault rotation reminders worker (#167).

Periodically scans `vault_secrets.expires_at` для appropximaching rotation
deadline → emits structured log notification (real email integration —
отдельный backlog). Reuses worker patterns from indexer.

Run: `python -m src.workers.vault_reminders`
"""

from src.workers.vault_reminders.runner import (
    VaultReminderWorker,
    install_signal_handlers,
)

__all__ = ["VaultReminderWorker", "install_signal_handlers"]
