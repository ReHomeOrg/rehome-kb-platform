"""Тесты трансформации инлайн-ссылок на статьи в `import_kb_markdown`.

Проверяют, что номер статьи в теле («см. статью 151», «(статья 110)» и т.п.)
заменяется кликабельным названием целевой статьи (markdown-ссылка на
`/articles/<slug>`), а ссылки на неизвестные id и self-reference не трогаются.
"""

from __future__ import annotations

from pathlib import Path

from scripts.import_kb_markdown import (
    linkify_article_refs,
    parse_articles,
)

SLUGS = {"1": "chto-takoe-rehome", "151": "vhod-cherez-mts-id"}
TITLES = {"1": "Что такое reHome?", "151": "Вход через МТС ID"}


def test_inline_form_keeps_lead_word_and_links_title() -> None:
    body = "Вход через МТС ID (см. статью 151) доступен всем."
    out = linkify_article_refs(body, SLUGS, TITLES, current_id="6")
    assert out == (
        "Вход через МТС ID (см. статью "
        "[Вход через МТС ID](/articles/vhod-cherez-mts-id)) доступен всем."
    )


def test_paren_form_statya() -> None:
    out = linkify_article_refs("Подробнее (статья 1).", SLUGS, TITLES, current_id="9")
    assert out == "Подробнее (статья [Что такое reHome?](/articles/chto-takoe-rehome))."


def test_various_grammatical_forms() -> None:
    for form in ("статья 1", "статью 1", "статьёй 1", "статьях 1", "статье 1"):
        out = linkify_article_refs(form, SLUGS, TITLES, current_id="9")
        lead = form.split()[0]
        assert out == f"{lead} [Что такое reHome?](/articles/chto-takoe-rehome)"


def test_unknown_id_left_untouched() -> None:
    # 999 не существует среди статей (например, ссылка на документ) — не трогаем.
    body = "См. статью 999 и Договор 5.7."
    assert linkify_article_refs(body, SLUGS, TITLES, current_id="6") == body


def test_self_reference_left_untouched() -> None:
    body = "Эта же статья 1 описывает сервис."
    assert linkify_article_refs(body, SLUGS, TITLES, current_id="1") == body


def test_verb_stat_not_matched() -> None:
    # Глагол «стать» без падежного окончания + число — не ссылка.
    body = "Чтобы стать 1-м в очереди, подайте заявку."
    assert linkify_article_refs(body, SLUGS, TITLES, current_id="6") == body


def test_bracket_in_title_is_sanitized() -> None:
    titles = {"1": "Тариф [спец]"}
    slugs = {"1": "tarif-spec"}
    out = linkify_article_refs("См. статью 1.", slugs, titles, current_id="2")
    # Квадратные скобки в названии заменены, markdown-ссылка не сломана.
    assert out == "См. статью [Тариф (спец)](/articles/tarif-spec)."


_DOC = """## Раздел  (`r1`)

### Статья 1. Что такое reHome?
```yaml
id: 1
question: "Что такое reHome?"
category: r1
audience: [tenant]
access_level: PUBLIC
tags: [a]
related: [2]
```
Базовая статья.

### Статья 2. Как войти?
```yaml
id: 2
question: "Как войти?"
category: r1
audience: [tenant]
access_level: PUBLIC
tags: [b]
related: [1]
```
Войти можно как описано в статье 1, подробнее (см. статью 1).
"""


def test_parse_articles_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(_DOC, encoding="utf-8")
    arts = {a["_source_id"]: a for a in parse_articles(path)}
    assert set(arts) == {"1", "2"}

    body2 = arts["2"]["body_markdown"]
    slug1 = arts["1"]["slug"]
    # Обе инлайн-формы в теле статьи 2 указывают на статью 1 по названию.
    assert f"в статье [Что такое reHome?](/articles/{slug1})" in body2
    assert f"(см. статью [Что такое reHome?](/articles/{slug1}))" in body2
    # Футер related тоже по названию, не по номеру.
    assert "Связанные статьи: [Что такое reHome?]" in body2
    assert "Перейти к статье" not in body2


def test_footer_uses_titles_not_numbers(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(_DOC, encoding="utf-8")
    arts = {a["_source_id"]: a for a in parse_articles(path)}
    body1 = arts["1"]["body_markdown"]
    slug2 = arts["2"]["slug"]
    assert f"Связанные статьи: [Как войти?](/articles/{slug2})" in body1
