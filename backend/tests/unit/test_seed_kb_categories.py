"""Тесты парсинга категорий из секционных заголовков мастер-документа.

Сидинг в БД — интеграционный путь; здесь покрыт чистый парсер
`parse_section_categories`.
"""

from __future__ import annotations

from pathlib import Path

from scripts.seed_kb_categories import parse_section_categories

_DOC = """# Заголовок

## Оглавление

- **Начало работы** (`1_start`): статьи 1, 2

## Начало работы  (`1_start`)

### Статья 1. ...

## Агенты reHome  (`12_agents`)

### Статья 121. ...

## Споры, претензии и выплаты  (`13_claims`)

## Глоссарий  (`14_glossary`)

## Технические вопросы и поддержка  (`15_support`)

## Часть II. Документы (юридический пакет)

### Документ 1. ...
"""


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "master.md"
    path.write_text(_DOC, encoding="utf-8")
    return path


def test_parses_section_categories(tmp_path: Path) -> None:
    cats = {c["slug"]: c for c in parse_section_categories(_write(tmp_path))}
    assert set(cats) == {"1_start", "12_agents", "13_claims", "14_glossary", "15_support"}
    assert cats["12_agents"]["title"] == "Агенты reHome"
    assert cats["13_claims"]["title"] == "Споры, претензии и выплаты"


def test_excludes_toc_and_part_headers(tmp_path: Path) -> None:
    # `## Оглавление` (без слага) и `## Часть II ...` (скобки без backtick)
    # не должны попадать в категории.
    slugs = [c["slug"] for c in parse_section_categories(_write(tmp_path))]
    assert "Оглавление" not in slugs
    assert all("Часть" not in s for s in slugs)
    # Строка оглавления `- **...** (`1_start`)` не создаёт дубль 1_start.
    assert slugs.count("1_start") == 1


def test_description_generated(tmp_path: Path) -> None:
    cats = {c["slug"]: c for c in parse_section_categories(_write(tmp_path))}
    assert cats["14_glossary"]["description"] == "Статьи из категории «Глоссарий»"


def test_real_master_has_15_categories() -> None:
    master = Path(__file__).resolve().parents[2] / "scripts/seed/reHome_KB_master_v6.5.md"
    if not master.exists():  # pragma: no cover - seed присутствует в репо
        return
    cats = parse_section_categories(master)
    slugs = {c["slug"] for c in cats}
    assert len(cats) == 15
    assert {"12_agents", "13_claims", "14_glossary", "15_support"} <= slugs
