"""FastAPI router для kb-vault (#147, ADR-0011).

Zero-knowledge endpoints. Все sensitive payload — base64-encoded
ciphertext'ы; сервер хранит as-is. Crypto operations — на клиенте.

Endpoints:
- `GET /vault/me` — текущее crypto state (для unlock prompt UI).
- `POST /vault/setup` — initial user setup.
- `POST /vault/unlock` — verify auth_hash (anti-bruteforce, audit log).
- `GET /vault/secrets` — list metadata доступных secrets.
- `POST /vault/secrets` — create encrypted secret + wraps.
- `GET /vault/secrets/{id}` — detail (с caller's wrapped_key).
- `PUT /vault/secrets/{id}` — update blob (optimistic version match).
- `DELETE /vault/secrets/{id}` — archive (soft-delete).
- `GET /vault/groups` — list user's groups.
- `POST /vault/groups` — create group.

Auth: `require_authenticated` через Keycloak JWT. Sub claim → user_id.
"""

import logging
from base64 import b64decode
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import (
    ACTION_VAULT_GROUP_CREATED,
    ACTION_VAULT_GROUP_MEMBER_ADDED,
    ACTION_VAULT_GROUP_MEMBER_REMOVED,
    ACTION_VAULT_SECRET_CREATED,
    ACTION_VAULT_SECRET_DELETED,
    ACTION_VAULT_SECRET_READ,
    ACTION_VAULT_SECRET_ROTATED,
    ACTION_VAULT_SECRET_UPDATED,
    ACTION_VAULT_SHARE_ADDED,
    ACTION_VAULT_SHARE_REVOKED,
    ACTION_VAULT_UNLOCK_FAILED,
    ACTION_VAULT_UNLOCK_SUCCESS,
    RESOURCE_VAULT_GROUP,
    RESOURCE_VAULT_SECRET,
    RESOURCE_VAULT_USER,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import require_authenticated
from src.api.db import get_session
from src.api.vault.metrics import SECRET_ACCESS_TOTAL, UNLOCK_TOTAL
from src.api.vault.models import VaultGroupMember, VaultSecret, VaultSecretWrap
from src.api.vault.repository import VaultRepository, get_vault_repository
from src.api.vault.schemas import (
    VaultGroupCreateInput,
    VaultGroupListResponse,
    VaultGroupMemberAddInput,
    VaultGroupMemberListResponse,
    VaultGroupMemberView,
    VaultGroupView,
    VaultMeView,
    VaultSecretAddWrapsInput,
    VaultSecretCreateInput,
    VaultSecretListResponse,
    VaultSecretRotateInput,
    VaultSecretUpdateInput,
    VaultSecretView,
    VaultSecretWrapListResponse,
    VaultSecretWrapView,
    VaultSetupInput,
    VaultTotpSetupInput,
    VaultUnlockInput,
    VaultUnlockResponse,
    VaultUserPubkeyView,
    group_view,
    me_view_from_user,
    secret_detail_view,
    secret_metadata_view,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["Vault"])


def _user_id_from_claims(claims: dict[str, Any]) -> UUID:
    """JWT sub → UUID. 401 если sub отсутствует или невалидный."""
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Missing sub claim")
    try:
        return UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid sub claim") from exc


# ---------------------------------------------------------------------------
# user setup / unlock


@router.get("/me", response_model=VaultMeView, summary="Current user vault state")
async def get_me(
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
) -> VaultMeView:
    """Client'у нужен salt + pubkey + encrypted_privkey ДО unlock'а.

    Если vault не setup'нут — `is_setup=False`, остальные поля None.
    Client покажет UI «Set up vault» с master password creation.
    """
    user_id = _user_id_from_claims(claims)
    user = await repo.get_user(user_id)
    return me_view_from_user(user)


@router.post(
    "/setup",
    response_model=VaultMeView,
    status_code=status.HTTP_201_CREATED,
    summary="Initial vault setup",
    responses={409: {"description": "Vault already set up"}},
)
async def setup(
    payload: VaultSetupInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultMeView:
    """First-time vault setup. Idempotent: 409 если уже setup'нут.

    Client отдельно подписывает обязательство о неразглашении (PZ §8.4)
    — это application-level workflow, не enforced серверной логикой.
    """
    user_id = _user_id_from_claims(claims)
    if await repo.get_user(user_id) is not None:
        raise HTTPException(status_code=409, detail="Vault already set up")
    user = await repo.create_user(
        user_id=user_id,
        argon_salt=b64decode(payload.argon_salt_b64),
        auth_hash=b64decode(payload.auth_hash_b64),
        encrypted_x25519_privkey=b64decode(payload.encrypted_x25519_privkey_b64),
        x25519_pubkey=b64decode(payload.x25519_pubkey_b64),
    )
    await session.commit()
    return me_view_from_user(user)


@router.post(
    "/unlock",
    response_model=VaultUnlockResponse,
    summary="Verify auth_hash (anti-bruteforce, audit)",
    responses={401: {"description": "Invalid auth_hash or vault not set up"}},
)
async def unlock(
    payload: VaultUnlockInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultUnlockResponse:
    """Verify auth_hash match. Success/failure both audited.

    Constant-time compare обязателен — bytes equality иначе timing
    leak'ит partial hash. Используем `secrets.compare_digest`.
    """
    import secrets as py_secrets
    from datetime import UTC, datetime

    user_id = _user_id_from_claims(claims)
    user = await repo.get_user(user_id)
    submitted = b64decode(payload.auth_hash_b64)

    success = user is not None and py_secrets.compare_digest(user.auth_hash, submitted)
    if success:
        # mypy guard — user truthy в этой branch.
        assert user is not None
        user.last_unlock_at = datetime.now(UTC)
        await audit.record(
            actor_sub=str(user_id),
            action=ACTION_VAULT_UNLOCK_SUCCESS,
            resource_type=RESOURCE_VAULT_USER,
            resource_id=str(user_id),
        )
        await session.commit()
        UNLOCK_TOTAL.labels(result="success").inc()
        return VaultUnlockResponse(success=True)
    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_UNLOCK_FAILED,
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(user_id),
    )
    await session.commit()
    UNLOCK_TOTAL.labels(result="failed").inc()
    raise HTTPException(status_code=401, detail="Invalid auth_hash")


# ---------------------------------------------------------------------------
# secrets


async def _user_group_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    """All group_ids в которых user — member."""
    result = await session.execute(
        select(VaultGroupMember.group_id).where(VaultGroupMember.user_id == user_id)
    )
    return list(result.scalars().all())


@router.post(
    "/secrets",
    response_model=VaultSecretView,
    status_code=status.HTTP_201_CREATED,
    summary="Create encrypted secret",
)
async def create_secret(
    payload: VaultSecretCreateInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultSecretView:
    """Create secret + initial wraps в одной транзакции.

    Validation:
    - Каждый wrap содержит user_id (обязательно) + опциональный group_id
      lineage (ADR-0017).
    - Creator должен быть среди wraps (иначе создатель сам не сможет
      открыть свой секрет — defensive нарушение invariant).
    """
    user_id = _user_id_from_claims(claims)
    # Verify creator has at least one wrap addressed к ним.
    has_self_wrap = any(w.user_id == user_id for w in payload.wraps)
    if not has_self_wrap:
        raise HTTPException(
            status_code=422,
            detail="At least one wrap must address creator's user_id",
        )
    # Group lineage — creator должен быть member группы, которой он
    # «помечает» wrap.
    wrap_models: list[VaultSecretWrap] = []
    for w in payload.wraps:
        if w.group_id is not None:
            is_member = await repo.is_group_member(w.group_id, user_id)
            if not is_member:
                raise HTTPException(
                    status_code=403,
                    detail=f"Not a member of group {w.group_id}",
                )
        wrap = VaultSecretWrap(
            user_id=w.user_id,
            group_id=w.group_id,
            wrapped_key=b64decode(w.wrapped_key_b64),
        )
        # secret_id заполнит repository.create_secret после flush'а
        # parent secret row (secret.id populated PK default).
        wrap_models.append(wrap)

    secret = await repo.create_secret(
        title_ciphertext=b64decode(payload.title_ciphertext_b64),
        category=payload.category,
        owner_id=user_id,
        blob_ciphertext=b64decode(payload.blob_ciphertext_b64),
        wraps=wrap_models,
    )
    if payload.expires_at is not None:
        secret.expires_at = payload.expires_at
        await session.flush()

    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_SECRET_CREATED,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret.id),
        metadata={"category": secret.category, "wrap_count": len(wrap_models)},
    )
    await session.commit()
    SECRET_ACCESS_TOTAL.labels(action="created", category=secret.category).inc()

    blob = await repo.get_secret_blob(secret.id)
    assert blob is not None
    # Caller's own wrap для response.
    own_wrap = next((w for w in wrap_models if w.user_id == user_id), None)
    assert own_wrap is not None
    return secret_detail_view(secret, blob, own_wrap.wrapped_key, via_group_id=None)


@router.get(
    "/secrets/{secret_id}",
    response_model=VaultSecretView,
    summary="Get encrypted secret + caller's wrapped_key",
    responses={404: {"description": "Not found or no access"}},
)
async def get_secret(
    secret_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultSecretView:
    user_id = _user_id_from_claims(claims)
    secret = await repo.get_secret(secret_id)
    if secret is None or secret.archived_at is not None:
        raise HTTPException(status_code=404, detail="Secret not found")

    group_ids = await _user_group_ids(session, user_id)
    wraps = await repo.get_wraps_for_recipient(
        secret_id=secret_id, user_id=user_id, user_group_ids=group_ids
    )
    if not wraps:
        # 404 не 403 — anti-enumeration (caller не должен distinguish
        # "exists but no access" от "not exists").
        raise HTTPException(status_code=404, detail="Secret not found")

    # Predilect personal wrap > group wrap (более direct ownership).
    chosen = next((w for w in wraps if w.user_id == user_id), wraps[0])

    blob = await repo.get_secret_blob(secret_id)
    if blob is None:
        # Defensive — schema гарантирует, но defensive 500 если invariant
        # нарушен (e.g., partial migration).
        raise HTTPException(status_code=500, detail="Blob missing")

    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_SECRET_READ,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret_id),
    )
    await session.commit()
    SECRET_ACCESS_TOTAL.labels(action="read", category=secret.category).inc()

    return secret_detail_view(secret, blob, chosen.wrapped_key, via_group_id=chosen.group_id)


@router.get(
    "/secrets",
    response_model=VaultSecretListResponse,
    summary="List accessible secrets (metadata only)",
)
async def list_secrets(
    claims: dict[str, Any] = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> VaultSecretListResponse:
    """Metadata-only list — secrets под которые caller имеет wrap (user
    или group member). Список НЕ аудитуется (PZ §8 — list не пишется
    в audit чтобы объём логов не взорвался).
    """
    user_id = _user_id_from_claims(claims)
    group_ids = await _user_group_ids(session, user_id)

    # WHERE secret_id IN (SELECT distinct secret_id FROM wraps WHERE
    # user_id=? OR group_id IN ?). Сделаем через join'и для clarity.
    wrap_filter = VaultSecretWrap.user_id == user_id
    if group_ids:
        wrap_filter = wrap_filter | VaultSecretWrap.group_id.in_(group_ids)

    stmt = (
        select(VaultSecret)
        .join(VaultSecretWrap, VaultSecretWrap.secret_id == VaultSecret.id)
        .where(wrap_filter, VaultSecret.archived_at.is_(None))
        .order_by(VaultSecret.updated_at.desc())
        .distinct()
    )
    result = await session.execute(stmt)
    secrets = list(result.scalars().all())
    return VaultSecretListResponse(data=[secret_metadata_view(s) for s in secrets])


@router.put(
    "/secrets/{secret_id}",
    response_model=VaultSecretView,
    summary="Update encrypted blob (optimistic concurrency)",
    responses={
        404: {"description": "Not found or no access"},
        409: {"description": "Version mismatch — fetch latest and retry"},
    },
)
async def update_secret(
    secret_id: UUID = Path(...),
    payload: VaultSecretUpdateInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultSecretView:
    user_id = _user_id_from_claims(claims)
    group_ids = await _user_group_ids(session, user_id)

    if not await repo.can_user_access_secret(
        secret_id=secret_id, user_id=user_id, user_group_ids=group_ids
    ):
        raise HTTPException(status_code=404, detail="Secret not found")

    new_blob = await repo.update_secret_blob(
        secret_id=secret_id,
        ciphertext=b64decode(payload.blob_ciphertext_b64),
        expected_version=payload.expected_version,
    )
    if new_blob is None:
        raise HTTPException(
            status_code=409,
            detail="Version mismatch — refresh and retry",
        )

    # touch updated_at на secret для list ordering.
    secret = await repo.get_secret(secret_id)
    assert secret is not None
    from datetime import UTC, datetime

    secret.updated_at = datetime.now(UTC)
    await session.flush()

    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_SECRET_UPDATED,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret_id),
        metadata={"new_version": new_blob.payload_version},
    )
    await session.commit()

    # Return updated detail view.
    wraps = await repo.get_wraps_for_recipient(
        secret_id=secret_id, user_id=user_id, user_group_ids=group_ids
    )
    chosen = next((w for w in wraps if w.user_id == user_id), wraps[0])
    return secret_detail_view(secret, new_blob, chosen.wrapped_key, via_group_id=chosen.group_id)


@router.post(
    "/secrets/{secret_id}/rotate",
    response_model=VaultSecretView,
    summary="Rotate secret_key (ADR-0017 §E true revoke)",
    description=(
        "Owner-only atomic rotation: client decrypts с old secret_key, "
        "генерирует новый, re-encrypt'ит blob, re-wrap'ит для surviving "
        "recipients. Server атомарно: DELETE all wraps + INSERT new wraps "
        "+ UPDATE blob.ciphertext + bump version. Прерывает «cached "
        "plaintext» exposure у revoked user'ов."
    ),
    responses={
        403: {"description": "Caller — не owner"},
        404: {"description": "Not found или archived"},
        409: {"description": "Version mismatch — refresh and retry"},
    },
)
async def rotate_secret(
    secret_id: UUID = Path(...),
    payload: VaultSecretRotateInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultSecretView:
    """ADR-0017 §E — true revoke через key rotation.

    Flow:
    1. RBAC: only owner может rotate (revoke других — owner-only action).
    2. Repository.rotate_secret_atomic — DELETE old wraps + INSERT new
       wraps + UPDATE blob в single transaction (SELECT FOR UPDATE).
    3. Audit: actor_sub + previous_version + new_version + new_recipients
       count. Metadata НЕ содержит revoked_user_ids (PII risk если log
       leak).
    4. ADR-0026 atomic: handler — single session.commit() в конце.
    """
    user_id = _user_id_from_claims(claims)
    secret = await repo.get_secret(secret_id)
    if secret is None or secret.archived_at is not None:
        raise HTTPException(status_code=404, detail="Secret not found")
    if secret.owner_id != user_id:
        # Owner-only — others get 403 (распознают что secret есть, но они не
        # owner). 404-mask не применяется, потому что rotate — explicit op
        # owner'а; 403 более honest.
        raise HTTPException(status_code=403, detail="Only owner may rotate secret_key")

    new_wraps = [
        VaultSecretWrap(
            secret_id=secret_id,
            user_id=w.user_id,
            group_id=w.group_id,
            wrapped_key=b64decode(w.wrapped_key_b64),
        )
        for w in payload.new_wraps
    ]

    new_blob = await repo.rotate_secret_atomic(
        secret_id=secret_id,
        new_title_ciphertext=b64decode(payload.new_title_ciphertext_b64),
        new_ciphertext=b64decode(payload.new_blob_ciphertext_b64),
        expected_version=payload.expected_version,
        new_wraps=new_wraps,
    )
    if new_blob is None:
        raise HTTPException(
            status_code=409,
            detail="Version mismatch — refresh and retry",
        )

    from datetime import UTC, datetime

    secret.updated_at = datetime.now(UTC)
    await session.flush()

    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_SECRET_ROTATED,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret_id),
        metadata={
            "previous_version": payload.expected_version,
            "new_version": new_blob.payload_version,
            "surviving_recipients_count": len(new_wraps),
        },
    )
    await session.commit()

    # Owner всегда должен быть в new_wraps (иначе он сам себя revoke'ает —
    # допустимо для archive flow). Если owner отсутствует — нет wrapped_key
    # для return view; используем placeholder с empty bytes (UI обработает
    # как «no access»).
    owner_wrap = next((w for w in new_wraps if w.user_id == user_id), None)
    if owner_wrap is None:
        # Edge case: owner revoke'нул сам себя. Return view без wrapped_key —
        # client должен archive secret следующим запросом.
        return secret_detail_view(secret, new_blob, b"", via_group_id=None)
    return secret_detail_view(secret, new_blob, owner_wrap.wrapped_key, via_group_id=None)


@router.delete(
    "/secrets/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive secret (soft-delete)",
    responses={404: {"description": "Not found or no access"}},
)
async def delete_secret(
    secret_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete: archived_at set. Только owner может архивировать."""
    user_id = _user_id_from_claims(claims)
    secret = await repo.get_secret(secret_id)
    if secret is None or secret.archived_at is not None:
        raise HTTPException(status_code=404, detail="Secret not found")
    if secret.owner_id != user_id:
        # 404 — анти-перечисление, не distinguish'им owned vs not-owned.
        raise HTTPException(status_code=404, detail="Secret not found")

    archived = await repo.archive_secret(secret_id)
    if not archived:
        raise HTTPException(status_code=404, detail="Secret not found")

    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_SECRET_DELETED,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret_id),
    )
    await session.commit()
    SECRET_ACCESS_TOTAL.labels(action="deleted", category=secret.category).inc()


# ---------------------------------------------------------------------------
# sharing (ADR-0017)


@router.get(
    "/users/{user_id}/pubkey",
    response_model=VaultUserPubkeyView,
    summary="X25519 pubkey lookup (ADR-0017)",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "User не setup'нул vault"},
    },
)
async def get_user_pubkey(
    user_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
) -> VaultUserPubkeyView:
    """Public pubkey по user_id.

    ADR-0011 §«Group keypair»: x25519_pubkey marked как «public по design»
    — server-visible, не secret. Возвращается любому authenticated user'у
    для wrap-for-user flow (ADR-0017 §C).
    """
    from base64 import b64encode

    pubkey = await repo.get_user_pubkey(user_id)
    if pubkey is None:
        raise HTTPException(status_code=404, detail="User vault not set up")
    return VaultUserPubkeyView(
        user_id=user_id,
        x25519_pubkey_b64=b64encode(pubkey).decode("ascii"),
    )


@router.post(
    "/secrets/{secret_id}/wraps",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Add wraps to existing secret (ADR-0017 sharing)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Caller не имеет access к secret'у"},
        404: {"description": "Secret не существует или archived"},
    },
)
async def add_secret_wraps(
    secret_id: UUID = Path(...),
    payload: VaultSecretAddWrapsInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Add wraps batch для existing secret (share with users / group).

    Caller должен иметь access к secret'у (own wrap exists). Каждый
    wrap addresses user_id; group_id optional lineage.
    """
    actor_id = _user_id_from_claims(claims)
    secret = await repo.get_secret(secret_id)
    if secret is None or secret.archived_at is not None:
        raise HTTPException(status_code=404, detail="Secret not found")

    # ADR-0017: access checked through user_id wraps only (group_id —
    # lineage metadata, не authorization). Avoid _user_group_ids session
    # call here — pass empty list (ignored downstream).
    if not await repo.can_user_access_secret(
        secret_id=secret_id, user_id=actor_id, user_group_ids=[]
    ):
        # 404 не 403 — anti-enumeration (см. delete_secret pattern).
        raise HTTPException(status_code=404, detail="Secret not found")

    new_wraps: list[VaultSecretWrap] = []
    for w in payload.wraps:
        new_wraps.append(
            VaultSecretWrap(
                user_id=w.user_id,
                group_id=w.group_id,
                wrapped_key=b64decode(w.wrapped_key_b64),
            )
        )
    added = await repo.add_secret_wraps(secret_id=secret_id, wraps=new_wraps)

    await audit.record(
        actor_sub=str(actor_id),
        action=ACTION_VAULT_SHARE_ADDED,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret_id),
        metadata={
            "added_user_ids": [str(w.user_id) for w in payload.wraps],
            "group_id": (
                str(payload.wraps[0].group_id)
                if payload.wraps and payload.wraps[0].group_id
                else None
            ),
            "added_count": added,
        },
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/secrets/{secret_id}/wraps",
    response_model=VaultSecretWrapListResponse,
    summary="List secret recipients (owner-only)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Caller — не owner secret'а"},
        404: {"description": "Secret не найден или archived"},
    },
)
async def list_secret_wraps(
    secret_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
) -> VaultSecretWrapListResponse:
    """Owner-only list текущих recipients (ADR-0017 §E rotation prep).

    Used UI rotation flow'ом для:
    1. Display списка кому сейчас расшарен secret.
    2. Compute «surviving recipients» list после revoke click'а.
    3. Re-wrap каждого survivor'а под новый secret_key — нужны их
       pubkey'и (отдельный per-user lookup через GET /vault/users/{id}/pubkey).

    Response НЕ содержит `wrapped_key` — per-recipient encrypted key
    нужен только самому recipient'у (zero-knowledge property).
    """
    user_id = _user_id_from_claims(claims)
    secret = await repo.get_secret(secret_id)
    if secret is None or secret.archived_at is not None:
        raise HTTPException(status_code=404, detail="Secret not found")
    if secret.owner_id != user_id:
        # Owner-only — 403, не 404-mask: caller знает что secret есть.
        raise HTTPException(status_code=403, detail="Only owner may list recipients")

    wraps = await repo.list_secret_wraps(secret_id)
    return VaultSecretWrapListResponse(
        data=[VaultSecretWrapView(user_id=w.user_id, group_id=w.group_id) for w in wraps]
    )


@router.delete(
    "/secrets/{secret_id}/wraps/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove wrap (unshare, ADR-0017 — owner-only)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Caller — не owner secret'а"},
        404: {"description": "Secret или wrap не найдены"},
    },
)
async def remove_secret_wrap(
    secret_id: UUID = Path(...),
    user_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove wrap. Только owner может unshare.

    Caveat (ADR-0017 §E): этот endpoint deletes wrap row, но НЕ делает
    cached plaintext forgotten — removed user мог cache'ить decrypted
    blob в browser memory. Для true revoke (rotation flow) используется
    `POST /vault/secrets/{id}/rotate` (ADR-0017 §E, реализован 2026-05-27).
    """
    actor_id = _user_id_from_claims(claims)
    secret = await repo.get_secret(secret_id)
    if secret is None or secret.archived_at is not None:
        raise HTTPException(status_code=404, detail="Secret not found")
    if secret.owner_id != actor_id:
        raise HTTPException(status_code=403, detail="Only owner can revoke wraps")

    removed = await repo.remove_secret_wrap(secret_id=secret_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Wrap not found")

    await audit.record(
        actor_sub=str(actor_id),
        action=ACTION_VAULT_SHARE_REVOKED,
        resource_type=RESOURCE_VAULT_SECRET,
        resource_id=str(secret_id),
        metadata={"removed_user_id": str(user_id)},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# groups


@router.post(
    "/groups",
    response_model=VaultGroupView,
    status_code=status.HTTP_201_CREATED,
    summary="Create vault group (sharing collection)",
)
async def create_group(
    payload: VaultGroupCreateInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultGroupView:
    user_id = _user_id_from_claims(claims)
    group = await repo.create_group(
        name=payload.name,
        description=payload.description,
        created_by=user_id,
    )
    await audit.record(
        actor_sub=str(user_id),
        action=ACTION_VAULT_GROUP_CREATED,
        resource_type=RESOURCE_VAULT_GROUP,
        resource_id=str(group.id),
        metadata={"name": group.name},
    )
    await session.commit()
    return group_view(group)


@router.get(
    "/groups",
    response_model=VaultGroupListResponse,
    summary="List groups user is member of",
)
async def list_groups(
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
) -> VaultGroupListResponse:
    user_id = _user_id_from_claims(claims)
    groups = await repo.list_groups_for_user(user_id)
    return VaultGroupListResponse(data=[group_view(g) for g in groups])


# ---------------------------------------------------------------------------
# Group members (#155) — owner-only management


async def _require_group_owner(
    repo: VaultRepository,
    group_id: UUID,
    user_id: UUID,
) -> None:
    """Helper: 403 если caller — НЕ owner данной группы.

    404 если group не существует или caller — не member вообще (anti-
    enumeration: чужие group_id не должны expose'иться через 403 vs 404).
    """
    group = await repo.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    member = await repo.get_group_member(group_id, user_id)
    if member is None:
        # 404, не 403 — anti-enumeration.
        raise HTTPException(status_code=404, detail="Group not found")
    if member.role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Only group owner can manage members",
        )


@router.get(
    "/groups/{group_id}/members",
    response_model=VaultGroupMemberListResponse,
    summary="List group members (must be member to see)",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Group не найдена или caller — не member"},
    },
)
async def list_group_members(
    group_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
) -> VaultGroupMemberListResponse:
    """Membership readable любому member группы. Non-member → 404."""
    user_id = _user_id_from_claims(claims)
    if not await repo.is_group_member(group_id, user_id):
        raise HTTPException(status_code=404, detail="Group not found")
    members = await repo.list_group_members(group_id)
    return VaultGroupMemberListResponse(
        data=[VaultGroupMemberView.model_validate(m) for m in members]
    )


@router.post(
    "/groups/{group_id}/members",
    response_model=VaultGroupMemberView,
    status_code=status.HTTP_201_CREATED,
    summary="Add member to group (owner-only)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Caller — не owner данной группы"},
        404: {"description": "Group не найдена или caller — не member"},
        409: {"description": "User уже member"},
    },
)
async def add_group_member(
    group_id: UUID = Path(...),
    payload: VaultGroupMemberAddInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultGroupMemberView:
    """Add member. Client должен сделать follow-up calls для re-wrap'а
    existing secrets под новый pubkey (см. POST /vault/secrets — wraps
    можно add при secret create; для existing — отдельный endpoint в
    follow-up PR'е).

    Это PR обеспечивает membership change; cryptographic re-wrap —
    отдельная операция (см. backlog Stage 1.4).
    """
    actor_id = _user_id_from_claims(claims)
    await _require_group_owner(repo, group_id, actor_id)

    # Idempotency: already-member → 409 (caller должен fetch existing).
    if await repo.is_group_member(group_id, payload.user_id):
        raise HTTPException(status_code=409, detail="User already member")

    member = await repo.add_group_member(
        group_id=group_id, user_id=payload.user_id, role=payload.role
    )
    await audit.record(
        actor_sub=str(actor_id),
        action=ACTION_VAULT_GROUP_MEMBER_ADDED,
        resource_type=RESOURCE_VAULT_GROUP,
        resource_id=str(group_id),
        metadata={"added_user_id": str(payload.user_id), "role": payload.role},
    )
    await session.commit()
    return VaultGroupMemberView.model_validate(member)


@router.delete(
    "/groups/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from group (owner-only, can't remove self)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Caller — не owner или попытка removed себя"},
        404: {"description": "Group или member не найдены"},
    },
)
async def remove_group_member(
    group_id: UUID = Path(...),
    user_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove member. Defensive: owner НЕ может удалить себя — иначе
    group остаётся без owner'а и becomes management-orphaned (force
    transfer ownership через explicit endpoint — backlog).
    """
    actor_id = _user_id_from_claims(claims)
    await _require_group_owner(repo, group_id, actor_id)

    if user_id == actor_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot remove yourself; transfer ownership first",
        )

    removed = await repo.remove_group_member(group_id=group_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")

    await audit.record(
        actor_sub=str(actor_id),
        action=ACTION_VAULT_GROUP_MEMBER_REMOVED,
        resource_type=RESOURCE_VAULT_GROUP,
        resource_id=str(group_id),
        metadata={"removed_user_id": str(user_id)},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# TOTP setup (#164) — 2FA enrollment


@router.post(
    "/totp/setup",
    response_model=VaultMeView,
    summary="Enable TOTP 2FA (store client-encrypted secret)",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Vault не setup'нут"},
    },
)
async def setup_totp(
    payload: VaultTotpSetupInput = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> VaultMeView:
    """Store client-encrypted TOTP secret.

    Zero-knowledge: client генерит TOTP secret (RFC 6238) + encrypts
    под vault_key + POSTs ciphertext. Server stores opaque blob,
    не может derive codes / verify.

    Replaces existing secret если already set (rotation). Idempotent
    same-value: client может re-POST one и тот же ciphertext.

    После setup'а `GET /vault/me` возвращает `has_totp: true`.
    """
    user_id = _user_id_from_claims(claims)
    updated = await repo.set_totp_secret(
        user_id,
        b64decode(payload.totp_secret_encrypted_b64),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Vault not set up")
    await audit.record(
        actor_sub=str(user_id),
        action="vault.totp.enabled",
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(user_id),
    )
    await session.commit()
    return me_view_from_user(updated)


@router.delete(
    "/totp",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable TOTP 2FA (clear encrypted secret)",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Vault не setup'нут или TOTP уже отключен"},
    },
)
async def disable_totp(
    claims: dict[str, Any] = Depends(require_authenticated),
    repo: VaultRepository = Depends(get_vault_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Clear `totp_secret_encrypted`. 404 если vault not set up или
    TOTP уже disabled (idempotency note: повторный DELETE на already-
    disabled → 404; caller должен check `has_totp` через /me)."""
    user_id = _user_id_from_claims(claims)
    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Vault not set up")
    if user.totp_secret_encrypted is None:
        raise HTTPException(status_code=404, detail="TOTP not enabled")
    await repo.set_totp_secret(user_id, None)
    await audit.record(
        actor_sub=str(user_id),
        action="vault.totp.disabled",
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(user_id),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
