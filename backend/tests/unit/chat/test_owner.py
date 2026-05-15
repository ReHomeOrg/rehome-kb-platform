"""Unit tests для extract_chat_owner (#211).

Покрывает 4 ветки извлечения identifier'ов:
1. UUID sub → user_id parsed.
2. m2m sub (`service-account-...`) → user_id=None (graceful).
3. Valid X-Chat-Session-Token header → session_token parsed.
4. Invalid header → session_token=None (graceful, не 400).
5. Anon flow — нет claims нет header → (None, None).
6. Sub отсутствует / не строка → user_id=None.
"""

from uuid import uuid4

from src.api.chat.owner import extract_chat_owner


def test_uuid_sub_parsed_as_user_id() -> None:
    uid = uuid4()
    user_id, token = extract_chat_owner(
        claims={"sub": str(uid)},
        x_chat_session_token=None,
    )
    assert user_id == uid
    assert token is None


def test_m2m_service_account_sub_gracefully_none() -> None:
    """m2m JWT с non-UUID sub → anon flow."""
    user_id, token = extract_chat_owner(
        claims={"sub": "service-account-kb-api"},
        x_chat_session_token=None,
    )
    assert user_id is None
    assert token is None


def test_valid_session_token_header_parsed() -> None:
    tok = uuid4()
    user_id, token = extract_chat_owner(
        claims=None,
        x_chat_session_token=str(tok),
    )
    assert user_id is None
    assert token == tok


def test_invalid_header_gracefully_none() -> None:
    """Битый header → session_token=None, не 400 (клиент может иметь
    stale token из прошлой жизни)."""
    user_id, token = extract_chat_owner(
        claims=None,
        x_chat_session_token="not-a-uuid",
    )
    assert user_id is None
    assert token is None


def test_anon_flow_no_claims_no_header() -> None:
    user_id, token = extract_chat_owner(claims=None, x_chat_session_token=None)
    assert user_id is None
    assert token is None


def test_sub_missing_returns_none() -> None:
    user_id, _ = extract_chat_owner(claims={}, x_chat_session_token=None)
    assert user_id is None


def test_sub_not_string_returns_none() -> None:
    """Defensive: int sub → user_id=None, no crash."""
    user_id, _ = extract_chat_owner(claims={"sub": 42}, x_chat_session_token=None)
    assert user_id is None


def test_both_identifiers_extracted_together() -> None:
    """User-authed flow с stale anon token — оба identifier'а parsed."""
    uid = uuid4()
    tok = uuid4()
    user_id, token = extract_chat_owner(
        claims={"sub": str(uid)},
        x_chat_session_token=str(tok),
    )
    assert user_id == uid
    assert token == tok
