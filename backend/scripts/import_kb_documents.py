"""Импорт юридических документов (Часть II мастер-документа) в раздел Документы.

Каждый блок `### Документ N. <title>` содержит метастроку (`doc_id`, `slug`,
`access_level`) и тело под пометкой `**Полный текст:**`. Документы создаются
через `DocumentRepository.create()` — это санкционированный bulk-import путь
(ADR-0023 Вариант B: storage-only, без webhook/audit, в отличие от
`documents.service.create_document` для internal workers).

Все документы юр-пакета — `confidentiality=PUBLIC`, `status=ACTIVE`. Тело
сохраняется как HTML-файл в MinIO (`compute_storage_key` + `upload_object`),
ссылка на файл добавляется в `documents.files` через `upsert_file`.

Запуск:

    python -m scripts.import_kb_documents scripts/seed/reHome_KB_master_v6.5.md [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html as html_lib
import re
import sys
from pathlib import Path
from typing import Any

# Категория хранилища документа (ТЗ §3.2): A=external, B=contracts,
# C=partners, D=internal, E=regulators, F=templates. Раскладка юр-пакета
# по типам — по стабильному `doc_id`.
CATEGORY_BY_DOC_ID: dict[str, str] = {
    "legal_offer": "A",  # публичная оферта — внешний документ
    "legal_user_agreement": "A",  # пользовательское соглашение — внешний
    "legal_confidentiality": "B",  # NDA — договорной
    "legal_rental_contract": "F",  # договор найма (шаблон)
    "legal_act_services": "F",  # акт об оказанных услугах (шаблон)
    "consent_pd_processing": "E",  # согласие на обработку ПДн — регуляторный
    "consent_pd_transfer": "E",  # согласие на передачу ПДн
    "consent_advertising": "E",  # согласие на рекламную рассылку
    "legal_privacy_policy": "E",  # политика обработки ПДн
}
# Категория для doc_id вне карты — нейтральные «шаблоны».
DEFAULT_CATEGORY = "F"

DEFAULT_CONFIDENTIALITY = "PUBLIC"
DEFAULT_STATUS = "ACTIVE"
DEFAULT_VERSION = "1.0"

# Блочная модель: заголовок документа отбивает границы блока, поэтому поля
# одного документа не могут «утечь» в соседний (защита от тихой потери при
# малформ-блоке — такой блок пропускается с предупреждением, а не сливается).
DOC_HEADER_RE = re.compile(r"^### Документ\s+\d+\.\s+(?P<title>.+?)\s*$", flags=re.MULTILINE)
DOC_ID_RE = re.compile(r"doc_id:\*\*\s*`(?P<doc_id>[^`]+)`")
DOC_SLUG_RE = re.compile(r"slug:\*\*\s*`(?P<slug>[^`]+)`")
BODY_MARKER = "**Полный текст:**"


def to_html(title: str, body: str) -> str:
    """Тело документа (plain-text абзацы) → самодостаточный HTML.

    Абзацы разделяются пустой строкой; одиночные переводы строк внутри
    абзаца сохраняются как `<br>`. Весь пользовательский текст
    HTML-экранируется.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body.strip()) if b.strip()]
    paragraphs = []
    for block in blocks:
        lines = [html_lib.escape(line.strip()) for line in block.splitlines()]
        paragraphs.append("<p>" + "<br>".join(lines) + "</p>")
    safe_title = html_lib.escape(title)
    return (
        '<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
        f'<meta charset="utf-8">\n<title>{safe_title}</title>\n'
        "</head>\n<body>\n"
        f"<h1>{safe_title}</h1>\n" + "\n".join(paragraphs) + "\n</body>\n</html>\n"
    )


def parse_documents(path: Path) -> list[dict[str, Any]]:
    """Распарсить Часть II в список документов с HTML-телом и категорией.

    Каждый блок ограничен следующим заголовком `### Документ`, поэтому
    `doc_id`/`slug`/тело извлекаются строго в его пределах. Малформ-блок
    (нет `doc_id`/`slug`/`**Полный текст:**` или пустое тело) пропускается
    с предупреждением в stderr — без тихой потери соседних документов.
    """
    text = path.read_text(encoding="utf-8")
    # Ограничиваемся Частью II, чтобы не зацепить статьи/оглавление.
    part_two = text.split("## Часть II", 1)
    scope = part_two[1] if len(part_two) > 1 else text

    headers = list(DOC_HEADER_RE.finditer(scope))
    documents: list[dict[str, Any]] = []
    for index, header in enumerate(headers):
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(scope)
        block = scope[start:end]
        title = header.group("title").strip()

        id_match = DOC_ID_RE.search(block)
        slug_match = DOC_SLUG_RE.search(block)
        if id_match is None or slug_match is None or BODY_MARKER not in block:
            print(
                f"WARN: пропущен малформ-блок «{title}» (нет doc_id/slug/текста)",
                file=sys.stderr,
            )
            continue
        body = block.split(BODY_MARKER, 1)[1].strip()
        if not body:
            print(f"WARN: пропущен документ «{title}» — пустое тело", file=sys.stderr)
            continue

        doc_id = id_match.group("doc_id").strip()
        documents.append(
            {
                "doc_id": doc_id,
                "slug": slug_match.group("slug").strip(),
                "title": title[:500],
                "category": CATEGORY_BY_DOC_ID.get(doc_id, DEFAULT_CATEGORY),
                "html": to_html(title, body),
            }
        )
    return documents


async def ingest_documents(
    path: Path,
    *,
    confidentiality: str = DEFAULT_CONFIDENTIALITY,
    status: str = DEFAULT_STATUS,
    version: str = DEFAULT_VERSION,
) -> int:
    """Создать строки документов + загрузить HTML-файлы в MinIO."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.api.config import get_settings
    from src.api.documents.models import Document
    from src.api.documents.repository import DocumentRepository
    from src.api.documents.storage import compute_storage_key, upload_object

    documents = parse_documents(path)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created = skipped = 0

    async with factory() as session:
        repo = DocumentRepository(session)
        existing = await session.execute(
            select(Document.title).where(Document.title.in_([d["title"] for d in documents]))
        )
        existing_titles = {row[0] for row in existing}

        for doc in documents:
            # Идемпотентность: повторный прогон не дублирует строки.
            if doc["title"] in existing_titles:
                skipped += 1
                continue
            row = await repo.create(
                title=doc["title"],
                category=doc["category"],
                status=status,
                confidentiality=confidentiality,
                version=version,
            )
            payload = doc["html"].encode("utf-8")
            storage_key = compute_storage_key(
                category=doc["category"],
                document_id=str(row.id),
                version=version,
                file_format="html",
            )
            upload_object(
                settings,
                storage_key,
                payload,
                content_type="text/html; charset=utf-8",
            )
            await repo.upsert_file(
                row,
                {
                    "format": "html",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "storage_key": storage_key,
                },
            )
            created += 1

        await session.commit()

    await engine.dispose()
    print(f"OK: documents_created={created}, skipped={skipped}, total={len(documents)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("path", type=Path, help="Путь к мастер-markdown (v6.5)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    documents = parse_documents(args.path)
    print(f"Распознано документов: {len(documents)}")
    for doc in documents:
        print(
            f"  {doc['doc_id']:<24} cat={doc['category']} " f"slug={doc['slug']:<18} {doc['title']}"
        )
    if args.dry_run:
        return 0
    if not documents:
        return 1
    return asyncio.run(ingest_documents(args.path))


if __name__ == "__main__":
    sys.exit(main())
