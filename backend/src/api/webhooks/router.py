"""FastAPI router для `/api/v1/webhooks/*` (E5.1 #87).

Endpoints:
- POST — создать (require auth, SSRF validate URL).
- GET — list (owner-scoped).
- DELETE — soft-delete.

POST /test (выполнить test delivery) — E5.2 (нужен delivery worker).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Response, status

from src.api.auth.dependency import require_authenticated
from src.api.webhooks.repository import WebhookRepository, get_webhook_repository
from src.api.webhooks.schemas import WebhookInput, WebhookResponse, WebhooksListResponse
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
    return WebhooksListResponse(data=[WebhookResponse.from_model(w) for w in webhooks])


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
