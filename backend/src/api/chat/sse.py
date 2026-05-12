"""Server-Sent Events helpers для chat streaming (E3.4 #67).

SSE wire format (per RFC 6202 / EventSource spec):
```
event: <name>\\n
data: <JSON>\\n
\\n
```

Multi-line `data:` — каждая строка с префиксом `data:`. Мы используем
**compact JSON** (без newlines), поэтому одна строка `data:` всегда.
"""

import json
from typing import Any


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    """Возвращает SSE-formatted строку для одного event'а.

    JSON-encoded с `ensure_ascii=False` (Cyrillic в content без escape)
    и `separators=(',', ':')` (compact — single line).

    Output: `'event: <name>\\ndata: <json>\\n\\n'`
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
