"""Тесты парсинга и подготовки юр-документов в `import_kb_documents`.

Проверяют разбор Части II (doc_id/slug/title/тело), раскладку по категориям
A–F и генерацию HTML с экранированием. Ingest в БД/MinIO — интеграционный
путь, здесь не покрывается.
"""

from __future__ import annotations

from pathlib import Path

from scripts.import_kb_documents import (
    CATEGORY_BY_DOC_ID,
    DEFAULT_CATEGORY,
    parse_documents,
    to_html,
)

_DOC = """## Часть II. Документы (юридический пакет)

### Документ 1. Публичная оферта

- **doc_id:** `legal_offer` · **slug:** `public-offer` · **access_level:** PUBLIC

```
<!-- CLAUDE_CODE:INSERT_DOCUMENT doc_id=legal_offer -->
```

**Полный текст:**

ПУБЛИЧНАЯ ОФЕРТА

Текст с символами < & > "кавычки".

### Документ 2. Неизвестный тип

- **doc_id:** `legal_unknown_xyz` · **slug:** `unknown` · **access_level:** PUBLIC

**Полный текст:**

Тело второго документа.
"""


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "master.md"
    path.write_text(_DOC, encoding="utf-8")
    return path


def test_parse_documents_count_and_fields(tmp_path: Path) -> None:
    docs = parse_documents(_write(tmp_path))
    assert len(docs) == 2
    first = docs[0]
    assert first["doc_id"] == "legal_offer"
    assert first["slug"] == "public-offer"
    assert first["title"] == "Публичная оферта"
    assert "ПУБЛИЧНАЯ ОФЕРТА" in first["html"]


def test_category_mapping_known_id(tmp_path: Path) -> None:
    docs = {d["doc_id"]: d for d in parse_documents(_write(tmp_path))}
    assert docs["legal_offer"]["category"] == "A"
    assert docs["legal_offer"]["category"] == CATEGORY_BY_DOC_ID["legal_offer"]


def test_category_mapping_unknown_id_defaults(tmp_path: Path) -> None:
    docs = {d["doc_id"]: d for d in parse_documents(_write(tmp_path))}
    assert docs["legal_unknown_xyz"]["category"] == DEFAULT_CATEGORY


def test_to_html_escapes_special_chars() -> None:
    out = to_html("Заголовок", 'Текст с < & > "кавычки".')
    assert "&lt;" in out
    assert "&amp;" in out
    assert "&gt;" in out
    assert "&quot;" in out
    # Сырые угловые скобки пользовательского текста не попадают в разметку.
    assert "Текст с < &" not in out
    assert out.startswith("<!DOCTYPE html>")
    assert "<h1>Заголовок</h1>" in out


def test_to_html_paragraphs_and_linebreaks() -> None:
    out = to_html("T", "Абзац один\nстрока два\n\nАбзац два")
    assert "<p>Абзац один<br>строка два</p>" in out
    assert "<p>Абзац два</p>" in out


_DOC_MALFORMED = """## Часть II. Документы

### Документ 1. Хороший документ

- **doc_id:** `legal_offer` · **slug:** `public-offer` · **access_level:** PUBLIC

**Полный текст:**

Корректное тело.

### Документ 2. Сломанный блок без метаданных

Текст без doc_id, slug и пометки.

### Документ 3. Второй хороший

- **doc_id:** `legal_act_services` · **slug:** `act-of-services` · **access_level:** PUBLIC

**Полный текст:**

Тело третьего документа.
"""


def test_malformed_block_is_skipped_not_merged(tmp_path: Path) -> None:
    # M-1: сломанный блок №2 не должен «съесть» соседние — он пропускается,
    # а валидные документы 1 и 3 парсятся независимо и не сливаются.
    path = tmp_path / "master.md"
    path.write_text(_DOC_MALFORMED, encoding="utf-8")
    docs = parse_documents(path)
    assert [d["doc_id"] for d in docs] == ["legal_offer", "legal_act_services"]
    assert docs[0]["title"] == "Хороший документ"
    assert "Корректное тело" in docs[0]["html"]
    assert docs[1]["title"] == "Второй хороший"
    assert "Тело третьего документа" in docs[1]["html"]


def test_full_catalog_categories_are_valid() -> None:
    # Все девять doc_id юр-пакета разложены по валидным категориям A–F.
    assert set(CATEGORY_BY_DOC_ID.values()) <= {"A", "B", "C", "D", "E", "F"}
    assert len(CATEGORY_BY_DOC_ID) == 9
