"""Integration test fixtures — реальный Keycloak через docker compose.

Запуск ТОЛЬКО в CI job `Integration (Keycloak)` или локально через:
    cd infra && docker compose up -d keycloak postgres-keycloak
    cd ../backend && uvicorn src.api.main:app --port 8000 &
    pytest tests/integration -m integration

Все эти тесты делают РЕАЛЬНЫЕ HTTP-вызовы (никаких mock'ов).
"""

import json
import os
from base64 import urlsafe_b64decode
from typing import Any

import httpx
import pytest

KC_URL = os.environ.get("KC_URL", "http://localhost:8080")
KC_REALM = os.environ.get("KC_REALM", "rehome")
KC_M2M_CLIENT_ID = "rehome-platform-m2m"
KC_M2M_CLIENT_SECRET = os.environ.get(
    "KC_M2M_CLIENT_SECRET", "rehome-platform-m2m-local-dev-secret"
)
KB_API_URL = os.environ.get("KB_API_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def m2m_token() -> str:
    """Получить m2m access_token через Client Credentials Grant."""
    response = httpx.post(
        f"{KC_URL}/realms/{KC_REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": KC_M2M_CLIENT_ID,
            "client_secret": KC_M2M_CLIENT_SECRET,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


@pytest.fixture(scope="session")
def kb_client() -> httpx.Client:
    """HTTP-клиент к локальному backend uvicorn."""
    return httpx.Client(base_url=KB_API_URL, timeout=10.0)


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Декодировать payload JWT без верификации подписи (для inspect'а в тестах)."""
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    decoded = urlsafe_b64decode(payload_b64).decode("utf-8")
    return dict(json.loads(decoded))
