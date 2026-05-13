"""FastAPI router для `/api/v1/webhooks/*` (E5.1 #87).

Endpoints:
- POST — создать (require auth, SSRF validate URL).
- GET — list (owner-scoped).
- DELETE — soft-delete.

POST /test (выполнить test delivery) — E5.2 (нужен delivery worker).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Response, status

from src.api.auth.dependency import require_authenticated
from src.api.webhooks.delivery_repository import (
    WebhookDeliveryRepository,
    get_delivery_repository,
)
from src.api.webhooks.repository import WebhookRepository, get_webhook_repository
from src.api.webhooks.schemas import (
    WebhookInput,
    WebhookResponse,
    WebhooksListResponse,
    WebhookSummary,
)
from src.api.webhooks.ssrf import SSRFValidationError, validate_webhook_url

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _client_id_from_claims(claims: dict[str, Any]) -> str:
    """JWT `sub` — owner identifier. Гарантируем что str (Keycloak всегда)."""
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="Invalid JWT: sub claim missing")
    return sub


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=WebhookResponse,
    summary="Зарегистрировать webhook",
)
async def create_webhook(
    payload: WebhookInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: WebhookRepository = Depends(get_webhook_repository),
) -> WebhookResponse:
    """POST /webhooks — register subscription.

    SSRF: URL hostname резолвится в IP. Если RFC1918/loopback/etc —
    400. Default scheme `https://` уже отвергает не-http(s).
    """
    url_str = str(payload.url)
    try:
        validate_webhook_url(url_str)
    except SSRFValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook URL: {exc}") from exc

    client_id = _client_id_from_claims(claims)
    webhook = await repo.create(
        client_id=client_id,
        url=url_str,
        events=payload.events,
        secret=payload.secret,
        description=payload.description,
    )
    return WebhookResponse.from_model(webhook)


@router.get(
    "",
    response_model=WebhooksListResponse,
    summary="Список зарегистрированных webhook",
)
async def list_webhooks(
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: WebhookRepository = Depends(get_webhook_repository),
) -> WebhooksListResponse:
    client_id = _client_id_from_claims(claims)
    webhooks = await repo.list_by_owner(client_id)
    # #97: GET намеренно не возвращает secret — exposed only on POST 201.
    return WebhooksListResponse(data=[WebhookSummary.from_model(w) for w in webhooks])


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать webhook",
)
async def delete_webhook(
    webhook_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: WebhookRepository = Depends(get_webhook_repository),
) -> Response:
    client_id = _client_id_from_claims(claims)
    deleted = await repo.soft_delete(webhook_id, client_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{webhook_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Тестовая отправка события",
)
async def test_webhook(
    webhook_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: WebhookRepository = Depends(get_webhook_repository),
    delivery_repo: WebhookDeliveryRepository = Depends(get_delivery_repository),
) -> dict[str, Any]:
    """POST /webhooks/{id}/test — enqueue тестовое событие.

    Возвращает 202 Accepted с delivery_id. Реальный POST делает
    delivery worker async — sync wait на результат не делаем (требует
    polling enhancement, backlog).
    """
    client_id = _client_id_from_claims(claims)
    webhook = await repo.get_by_id_and_owner(webhook_id, client_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")

    delivery = await delivery_repo.enqueue(
        webhook_id=webhook.id,
        event_type="webhook.test",
        payload={"timestamp": datetime.now(UTC).isoformat()},
    )
    return {
        "delivery_id": str(delivery.id),
        "status": "enqueued",
    }
