"""System prompt для AI-ассистента reHome (E3 Chat MVP).

Default prompt — `DEFAULT_SYSTEM_PROMPT`. Configurable через `system_config`
overlay (ADR-0019) — admin PATCH `/admin/system-config` с key
`chat.system_prompt` overrides. `resolve_system_prompt(overlay)`
возвращает overlay value или default.

#136: добавлен `build_rag_system_prompt` для chat RAG integration —
augment'ит base prompt retrieved chunks как numbered context block.

#338 (ФЗ-152 Stage 2): retrieved chunks pass'ятся через
`mask_pii` перед включением в system prompt — защита от leak ПДн в
external LLM API (phones / emails / СНИЛС / passport / ИНН / cards).
"""

import logging
from typing import Any

from src.api.chat.pii_masking import mask_pii
from src.api.search.repository import RetrievalHit

logger = logging.getLogger(__name__)

# `system_config` overlay key для системного prompt'а. Соответствует
# `MUTABLE_KEYS` в `admin/system_config_repository.py`.
SYSTEM_PROMPT_OVERLAY_KEY = "chat.system_prompt"

# Hard cap на длину overlay value. ~4K tokens worst case — admin не должен
# случайно exhaust'ить context window LLM'а через сверхдлинный prompt.
SYSTEM_PROMPT_MAX_LENGTH = 16384

DEFAULT_SYSTEM_PROMPT = """Ты — AI-ассистент платформы reHome, помогающий
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

# Backward-compat alias до полного callsite-rollout'а на DEFAULT.
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT


def resolve_system_prompt(overlay: dict[str, Any] | None) -> str:
    """Возвращает overlay's `chat.system_prompt` если non-empty string,
    иначе DEFAULT_SYSTEM_PROMPT.

    Defensive против битого overlay (non-string value, empty string,
    None) — fallback на default. Length cap enforced на boundary
    (admin PATCH validation); этот helper не валидирует — assumes
    storage уже отсеяла невалидное.
    """
    if overlay is None:
        return DEFAULT_SYSTEM_PROMPT
    value = overlay.get(SYSTEM_PROMPT_OVERLAY_KEY)
    if isinstance(value, str) and value.strip():
        return value
    return DEFAULT_SYSTEM_PROMPT


def build_rag_system_prompt(
    chunks: list[RetrievalHit],
    *,
    base_prompt: str | None = None,
) -> str:
    """Аugment base prompt retrieved chunks как numbered context block.

    Empty chunks → возвращает unchanged base_prompt (idempotent).
    Иначе добавляет block с инструкцией о citation формате `[N]`.

    `base_prompt` — optional override (обычно из `resolve_system_prompt`);
    None → `DEFAULT_SYSTEM_PROMPT`.

    Chunks нумеруются 1-indexed для соответствия типичному citation
    convention (LLM'ы лучше следуют `[1]` чем `[0]`).
    """
    prompt = base_prompt if base_prompt is not None else DEFAULT_SYSTEM_PROMPT
    if not chunks:
        return prompt

    lines = [
        prompt,
        "",
        "## Контекст из базы знаний",
        "",
        "Используй приведённые фрагменты для ответа. Цитируй источники в формате `[N]` "
        "где N — номер фрагмента ниже. Если фрагменты не содержат ответа — скажи "
        "об этом и не выдумывай.",
        "",
    ]
    # #338 ФЗ-152 Stage 2: mask ПДн в chunk text перед отправкой в LLM.
    # Titles tend to be safe (article titles, не ПДн), но text может
    # содержать example phones / emails / etc. Mask aggressively —
    # false positives acceptable (over-masking безопаснее под-маски).
    total_masks: dict[str, int] = {}
    for idx, hit in enumerate(chunks, start=1):
        result = mask_pii(hit.text)
        for category, count in result.counts.items():
            total_masks[category] = total_masks.get(category, 0) + count
        lines.append(f"[{idx}] **{hit.title}** (slug: {hit.slug}, chunk {hit.chunk_index}):")
        lines.append(result.text)
        lines.append("")
    if total_masks:
        logger.info(
            "chat.rag_pii_masked",
            extra={"counts": total_masks, "chunks": len(chunks)},
        )
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
