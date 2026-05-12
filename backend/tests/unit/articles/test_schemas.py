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


# ============================================================
# ArticlePatch (E4.5 #38)
# ============================================================


def test_article_patch_all_fields_optional() -> None:
    from src.api.articles.schemas import ArticlePatch

    # Empty `{}` — валидно.
    p = ArticlePatch()
    assert p.model_dump(exclude_unset=True) == {}


def test_article_patch_single_field_set() -> None:
    from src.api.articles.schemas import ArticlePatch

    p = ArticlePatch(title="New")
    assert p.title == "New"
    assert p.body_markdown is None
    assert p.tags is None
    assert p.status is None
    # exclude_unset: только явно переданное.
    assert p.model_dump(exclude_unset=True) == {"title": "New"}


def test_article_patch_extra_fields_rejected() -> None:
    """`extra='forbid'`: попытка передать access_level/slug/etc → 422."""
    from src.api.articles.schemas import ArticlePatch

    forbidden_fields = [
        {"access_level": "PUBLIC"},  # security-critical block
        {"slug": "new-slug"},
        {"category": "guide"},
        {"audience": "tenant"},
        {"language": "en"},
        {"short_answer": "..."},
        {"random": "junk"},
    ]
    for payload in forbidden_fields:
        with pytest.raises(ValidationError):
            ArticlePatch(**payload)  # type: ignore[arg-type]


def test_article_patch_title_too_long_rejected() -> None:
    from src.api.articles.schemas import ArticlePatch

    with pytest.raises(ValidationError):
        ArticlePatch(title="x" * 201)


def test_article_patch_empty_body_rejected() -> None:
    """Если body_markdown передан, не должен быть пустым."""
    from src.api.articles.schemas import ArticlePatch

    with pytest.raises(ValidationError):
        ArticlePatch(body_markdown="")


def test_article_patch_distinguishes_unset_from_null() -> None:
    """exclude_unset не путает «не передано» с «явно null»."""
    from src.api.articles.schemas import ArticlePatch

    # title не передан → отсутствует в dump.
    p1 = ArticlePatch(body_markdown="x")
    assert "title" not in p1.model_dump(exclude_unset=True)

    # title=None явно передан → присутствует в dump.
    # Но: ArticlePatch с min_length=1 на title не примет None.
    # Эту семантику оставляем future-proof для nullable полей.
    p2 = ArticlePatch(title="New")
    assert p2.model_dump(exclude_unset=True) == {"title": "New"}
