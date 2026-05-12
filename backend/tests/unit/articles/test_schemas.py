"""Тесты Pydantic-схем articles — `ArticleInput` validation.

Архитектурно-важно (deviation, approved #27): `access_level` обязателен,
`extra='forbid'`, slug pattern, length-ы.
"""

import pytest
from pydantic import ValidationError

from src.api.articles.schemas import ArticleInput
from src.api.auth.scope import AccessLevel


def _valid_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": "my-article",
        "title": "Заголовок",
        "body_markdown": "# Текст",
        "category": "guide",
        "audience": "tenant",
        "access_level": "PUBLIC",
    }
    base.update(overrides)
    return base


def test_article_input_valid_payload_parses() -> None:
    payload = ArticleInput(**_valid_payload())  # type: ignore[arg-type]
    assert payload.slug == "my-article"
    assert payload.access_level == AccessLevel.PUBLIC
    # Defaults
    assert payload.status == "DRAFT"
    assert payload.language == "ru"
    assert payload.tags == []


def test_article_input_access_level_required() -> None:
    """Approved deviation #27: access_level — обязательное поле."""
    bad = _valid_payload()
    del bad["access_level"]
    with pytest.raises(ValidationError) as exc:
        ArticleInput(**bad)  # type: ignore[arg-type]
    assert any("access_level" in str(e["loc"]) for e in exc.value.errors())


def test_article_input_invalid_access_level_value_rejected() -> None:
    """Pydantic StrEnum: невалидное значение → 422 (не 500 от ValueError)."""
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(access_level="FOOBAR"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_slug",
    [
        "UPPER",
        "слаг-кириллица",
        "with_underscore",
        "with space",
        "with.dot",
        "",
    ],
)
def test_article_input_slug_pattern_rejected(bad_slug: str) -> None:
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(slug=bad_slug))  # type: ignore[arg-type]


def test_article_input_slug_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(slug="a" * 201))  # type: ignore[arg-type]


def test_article_input_title_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(title="x" * 201))  # type: ignore[arg-type]


def test_article_input_empty_body_rejected() -> None:
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(body_markdown=""))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "missing_field", ["slug", "title", "body_markdown", "category", "audience"]
)
def test_article_input_missing_required_field_rejected(missing_field: str) -> None:
    bad = _valid_payload()
    del bad[missing_field]
    with pytest.raises(ValidationError) as exc:
        ArticleInput(**bad)  # type: ignore[arg-type]
    assert any(missing_field in str(e["loc"]) for e in exc.value.errors())


def test_article_input_extra_field_rejected() -> None:
    """`extra='forbid'`: неизвестные поля → 422 (защита от мусора и side-channel)."""
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(unknown_field="value"))  # type: ignore[arg-type]


def test_article_input_tags_default_empty_list() -> None:
    payload = ArticleInput(**_valid_payload())  # type: ignore[arg-type]
    assert payload.tags == []
    # Каждый вызов — свой список (не shared mutable default).
    payload.tags.append("x")
    payload2 = ArticleInput(**_valid_payload())  # type: ignore[arg-type]
    assert payload2.tags == []
