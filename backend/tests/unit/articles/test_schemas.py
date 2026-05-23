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


# ============================================================
# Tags case normalization (#346)
# ============================================================


def test_article_input_tags_lowercased() -> None:
    """ArticleInput.tags: Mixed-case → lowercase на validate."""
    payload = ArticleInput(**_valid_payload(tags=["Договор", "ПАСПОРТ"]))  # type: ignore[arg-type]
    assert payload.tags == ["договор", "паспорт"]


def test_article_input_tags_dedup_case_insensitive() -> None:
    """Дубли с разным case → один lowercase entry."""
    payload = ArticleInput(  # type: ignore[arg-type]
        **_valid_payload(tags=["Договор", "договор", "ДОГОВОР"])
    )
    assert payload.tags == ["договор"]


def test_article_input_tags_strip_whitespace() -> None:
    """Trailing / leading whitespace стрипается до lowercase."""
    payload = ArticleInput(**_valid_payload(tags=["  Договор  ", "сервис"]))  # type: ignore[arg-type]
    assert payload.tags == ["договор", "сервис"]


def test_article_input_tags_drop_empty() -> None:
    """Whitespace-only теги отбрасываются."""
    payload = ArticleInput(**_valid_payload(tags=["", "  ", "договор"]))  # type: ignore[arg-type]
    assert payload.tags == ["договор"]


def test_article_input_tags_preserves_order_of_first_occurrence() -> None:
    """Dedup сохраняет order первого появления (важно для UI consistency)."""
    payload = ArticleInput(  # type: ignore[arg-type]
        **_valid_payload(tags=["Сервис", "Договор", "сервис"])
    )
    assert payload.tags == ["сервис", "договор"]


def test_article_patch_tags_lowercased() -> None:
    from src.api.articles.schemas import ArticlePatch

    p = ArticlePatch(tags=["Договор", "ПАСПОРТ"])
    assert p.tags == ["договор", "паспорт"]


def test_article_patch_tags_none_passes_through() -> None:
    """tags=None → None (не передано — `exclude_unset=True` skip'нет)."""
    from src.api.articles.schemas import ArticlePatch

    p = ArticlePatch()
    assert p.tags is None


def test_article_patch_tags_empty_list_normalized_to_empty() -> None:
    """Явный `tags=[]` → нормализованный `[]` (clears all tags на UPDATE)."""
    from src.api.articles.schemas import ArticlePatch

    p = ArticlePatch(tags=[])
    assert p.tags == []


# ============================================================
# Literal enums (#353) — audience / status / language
# ============================================================


def test_literal_enums_match_model_static_methods() -> None:
    """Drift guard: Literal aliases синхронны с `Article.allowed_*()` tuples.

    NB asymmetry: audience/status дополнительно sync'ятся с DB CHECK
    через `test_models_check_sync.py`. Language CHECK на DB нет —
    Pydantic Literal — единственный enforcement layer (см. docstring
    `Article.allowed_languages`).
    """
    from typing import get_args

    from src.api.articles.models import Article
    from src.api.articles.schemas import (
        ArticleAudience,
        ArticleLanguage,
        ArticleStatusLiteral,
    )

    assert set(get_args(ArticleAudience)) == set(Article.allowed_audiences())
    assert set(get_args(ArticleStatusLiteral)) == set(Article.allowed_statuses())
    assert set(get_args(ArticleLanguage)) == set(Article.allowed_languages())


def test_article_input_rejects_unknown_audience() -> None:
    """Pydantic Literal — invalid audience → 422 (не 500 от DB)."""
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(audience="alien"))  # type: ignore[arg-type]


def test_article_input_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(status="DELETED"))  # type: ignore[arg-type]


def test_article_input_rejects_unknown_language() -> None:
    with pytest.raises(ValidationError):
        ArticleInput(**_valid_payload(language="fr"))  # type: ignore[arg-type]


def test_article_input_accepts_all_valid_audiences() -> None:
    for value in ("all", "guest", "tenant", "landlord", "agent", "staff"):
        payload = ArticleInput(**_valid_payload(audience=value))  # type: ignore[arg-type]
        assert payload.audience == value


def test_article_input_accepts_all_valid_statuses() -> None:
    for value in ("DRAFT", "PUBLISHED", "ARCHIVED"):
        payload = ArticleInput(**_valid_payload(status=value))  # type: ignore[arg-type]
        assert payload.status == value


def test_article_input_accepts_all_valid_languages() -> None:
    for value in ("ru", "en"):
        payload = ArticleInput(**_valid_payload(language=value))  # type: ignore[arg-type]
        assert payload.language == value


def test_article_patch_rejects_unknown_status() -> None:
    """PATCH status — same Literal validation."""
    from src.api.articles.schemas import ArticlePatch

    with pytest.raises(ValidationError):
        ArticlePatch(status="DELETED")  # type: ignore[arg-type]


def test_article_patch_accepts_valid_status() -> None:
    from src.api.articles.schemas import ArticlePatch

    for value in ("DRAFT", "PUBLISHED", "ARCHIVED"):
        p = ArticlePatch(status=value)  # type: ignore[arg-type]
        assert p.status == value
