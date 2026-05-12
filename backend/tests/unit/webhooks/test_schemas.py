"""Unit-тесты WebhookInput Pydantic validation (E5.1 #87)."""

import pytest
from pydantic import ValidationError

from src.api.webhooks.schemas import WebhookInput


def test_minimal_valid_input() -> None:
    inp = WebhookInput.model_validate(
        {"url": "https://example.com/hook", "events": ["article.published"]}
    )
    assert str(inp.url) == "https://example.com/hook"
    assert inp.events == ["article.published"]
    assert inp.secret is None


def test_all_fields() -> None:
    inp = WebhookInput.model_validate(
        {
            "url": "https://example.com/hook",
            "events": ["article.published", "chat.escalated"],
            "secret": "abcdefgh12345678",
            "description": "test webhook",
        }
    )
    assert inp.secret == "abcdefgh12345678"


def test_unknown_event_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown event"):
        WebhookInput.model_validate({"url": "https://example.com/", "events": ["article.bogus"]})


def test_empty_events_rejected() -> None:
    with pytest.raises(ValidationError):
        WebhookInput.model_validate({"url": "https://example.com/", "events": []})


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        WebhookInput.model_validate(
            {
                "url": "https://example.com/",
                "events": ["article.published"],
                "extra_field": "x",
            }
        )


def test_secret_too_short_rejected() -> None:
    with pytest.raises(ValidationError):
        WebhookInput.model_validate(
            {
                "url": "https://example.com/",
                "events": ["article.published"],
                "secret": "short",
            }
        )


def test_secret_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WebhookInput.model_validate(
            {
                "url": "https://example.com/",
                "events": ["article.published"],
                "secret": "x" * 65,
            }
        )


def test_invalid_url_scheme_rejected_by_pydantic() -> None:
    """Pydantic HttpUrl блокирует scheme'ы кроме http(s) per pydantic v2."""
    with pytest.raises(ValidationError):
        WebhookInput.model_validate({"url": "ftp://example.com/", "events": ["article.published"]})
