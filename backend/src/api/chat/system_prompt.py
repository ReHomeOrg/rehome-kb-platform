"""System prompt для AI-ассистента reHome (E3 Chat MVP).

Hardcoded в этом эпике. Configurable через config DB / admin — backlog
(E6 admin). При изменении требуется перезапуск.

#136: добавлен `build_rag_system_prompt` для chat RAG integration —
augment'ит base prompt retrieved chunks как numbered context block.
"""

from typing import Any

from src.api.search.repository import RetrievalHit

SYSTEM_PROMPT = """Ты — AI-ассистент платформы reHome, помогающий
нанимателям, собственникам и сотрудникам поддержки разобраться в
вопросах аренды жилья и работы платформы.

Правила:
- Отвечай только на вопросы, связанные с reHome: договоры аренды,
  оплата, сервисный платёж, кадастр, ремонт, заселение, страхование.
- Если вопрос не касается reHome — вежливо откажись и переориентируй
  на профильные ресурсы.
- Будь точным и кратким. Если не знаешь точного ответа — скажи об
  этом, а не выдумывай.
- Никогда не запрашивай у пользователя пароли, номера карт, паспортные
  данные. Передай в поддержку.
- Не давай юридических консультаций — переадресуй на профильного юриста.

Тональность: дружелюбная, но деловая. Без избыточной формальности и
без сленга.

Если тема выходит за рамки твоих знаний или требует ручного вмешательства
(жалоба, конфликт, юридический спор) — предложи эскалацию на оператора
поддержки.
"""


def build_rag_system_prompt(chunks: list[RetrievalHit]) -> str:
    """Аugment base prompt retrieved chunks как numbered context block.

    Empty chunks → возвращает unchanged SYSTEM_PROMPT (idempotent).
    Иначе добавляет block с инструкцией о citation формате `[N]`.

    Chunks нумеруются 1-indexed для соответствия типичному citation
    convention (LLM'ы лучше следуют `[1]` чем `[0]`).
    """
    if not chunks:
        return SYSTEM_PROMPT

    lines = [
        SYSTEM_PROMPT,
        "",
        "## Контекст из базы знаний",
        "",
        "Используй приведённые фрагменты для ответа. Цитируй источники в формате `[N]` "
        "где N — номер фрагмента ниже. Если фрагменты не содержат ответа — скажи "
        "об этом и не выдумывай.",
        "",
    ]
    for idx, hit in enumerate(chunks, start=1):
        lines.append(f"[{idx}] **{hit.title}** (slug: {hit.slug}, chunk {hit.chunk_index}):")
        lines.append(hit.text)
        lines.append("")
    return "\n".join(lines)


def hits_to_citations(chunks: list[RetrievalHit]) -> list[dict[str, Any]]:
    """Convert RetrievalHit-ы в JSONB-serializable citations.

    Структура соответствует existing `chat_messages.citations` JSONB
    field (`{type, id, title, url, ...}`) с дополнительными полями
    chunk_index / score для richer frontend display.
    """
    return [
        {
            "type": "article",
            "id": str(hit.article_id),
            "title": hit.title,
            "slug": hit.slug,
            "chunk_index": hit.chunk_index,
            "score": hit.score,
            "url": f"/articles/{hit.slug}",
        }
        for hit in chunks
    ]
