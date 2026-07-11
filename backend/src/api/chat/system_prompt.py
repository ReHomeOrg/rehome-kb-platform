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
import re
from typing import Any

from src.api.chat.pii_masking import mask_pii
from src.api.search.repository import RetrievalHit

logger = logging.getLogger(__name__)

# #383: источники показываются пользователю отдельным блоком citations (карточки
# со ссылками), поэтому inline-сноски вида `[2]` в тексте ответа — визуальный
# шум. Паттерн ловит только числовые маркеры `[N]` (не трогает `[важно]` и
# markdown-ссылки `[текст](url)`), опционально съедая пробел перед ними.
# Принятые ограничения (defensive-нетто поверх prompt-инструкции «не вставляй
# [N]», реальный LLM-вывод им не подвержен): маркер без ведущего пробела вплотную
# между словами склеит их (`ремонт[3]техники`→`ремонттехники`), а маркер в самом
# начале строки оставит ведущий пробел. LLM пишет `[N]` после слова с пробелом —
# именно его паттерн и съедает, сохраняя разделение. Многозначные `[1000]` тоже
# срезаются — как источники такие не встречаются.
_CITATION_MARKER_RE = re.compile(r" ?\[\d+\]")

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


# Правило приветствия: «Здравствуйте» — только один раз в течение одного
# календарного дня (по таймзоне Москвы). Первый ответ ассистента за день
# несёт приветствие, последующие — нет. Условие (`greeted_today`)
# вычисляется в router'е из истории диалога; директива дописывается к
# system prompt, т.к. сам LLM не знает, здоровался ли он сегодня.
GREETING_DIRECTIVE_FIRST = (
    "Это твой первый ответ пользователю за сегодняшний календарный день — "
    "начни ответ с приветствия «Здравствуйте»."
)
GREETING_DIRECTIVE_REPEAT = (
    "Сегодня ты уже здоровался с пользователем — НЕ пиши «Здравствуйте» и не "
    "используй других приветствий, сразу переходи к сути ответа."
)


def build_greeting_directive(*, greeted_today: bool) -> str:
    """Директива приветствия в зависимости от того, был ли уже greeting сегодня."""
    return GREETING_DIRECTIVE_REPEAT if greeted_today else GREETING_DIRECTIVE_FIRST


def apply_greeting_rule(prompt: str, *, greeted_today: bool) -> str:
    """Дописать к system prompt правило «Здравствуйте раз в календарный день»."""
    directive = build_greeting_directive(greeted_today=greeted_today)
    return f"{prompt}\n\n## Приветствие\n{directive}"


# Confidence-gated escalation (#382, Tier 2). Директива дописывается к system
# prompt ТОЛЬКО когда retrieval не дал уверенного контекста (пусто или top-score
# ниже порога). Делает эскалацию data-driven — «нет ответа в базе» → предложить
# поддержку, — вместо дежурной приписки про оператора в каждом ответе (это
# отдельно вычищено в chat.system_prompt overlay, Tier 1).
NO_CONTEXT_DIRECTIVE = (
    "## Нет данных в базе знаний\n"
    "По этому вопросу в базе знаний reHome не нашлось релевантной информации. "
    "Не выдумывай ответ и не приводи вымышленные факты. Честно сообщи, что не "
    "нашёл информации по этому вопросу в базе знаний, и предложи обратиться в "
    "поддержку за помощью."
)


def has_usable_context(
    chunks: list[RetrievalHit],
    *,
    min_score: float = 0.0,
) -> bool:
    """Есть ли у retrieval уверенный контекст для ответа.

    `False` когда chunks пусты. При `min_score > 0` дополнительно требует,
    чтобы лучший (максимальный) score хита был не ниже порога — RRF fused
    score для hybrid retrieval: higher = better. `min_score <= 0` (default)
    отключает score-гейт: сигнал строится только на непустом retrieval
    (robust — абсолютный порог по RRF хрупок, калибруется под корпус).
    """
    if not chunks:
        return False
    if min_score <= 0.0:
        return True
    return max(hit.score for hit in chunks) >= min_score


def apply_no_context_rule(prompt: str, *, has_context: bool) -> str:
    """Дописать no-context директиву к system prompt, если контекста нет.

    Idempotent при `has_context=True` — возвращает prompt без изменений.
    Так эскалация к оператору становится крайней мерой, привязанной к
    реальному отсутствию ответа в базе, а не к каждому ответу.
    """
    if has_context:
        return prompt
    return f"{prompt}\n\n{NO_CONTEXT_DIRECTIVE}"


def build_rag_system_prompt(
    chunks: list[RetrievalHit],
    *,
    base_prompt: str | None = None,
) -> str:
    """Аugment base prompt retrieved chunks как numbered context block.

    Empty chunks → возвращает unchanged base_prompt (idempotent).
    Иначе добавляет block с фрагментами и инструкцией НЕ вставлять номера
    источников `[N]` в текст ответа (#383): источники показываются
    пользователю отдельным `citations`-блоком, inline-маркеры — визуальный шум
    (см. `strip_citation_markers` — defensive-нетто на остаточные маркеры).

    `base_prompt` — optional override (обычно из `resolve_system_prompt`);
    None → `DEFAULT_SYSTEM_PROMPT`.

    Фрагменты нумеруются 1-indexed для читаемости контекста и стабильного
    порядка; эта нумерация внутренняя и в ответ пользователю не просачивается.
    """
    prompt = base_prompt if base_prompt is not None else DEFAULT_SYSTEM_PROMPT
    if not chunks:
        return prompt

    lines = [
        prompt,
        "",
        "## Контекст из базы знаний",
        "",
        "Используй приведённые фрагменты для ответа. НЕ вставляй в текст ответа "
        "номера источников в квадратных скобках (вида [1], [2]) — источники "
        "показываются пользователю отдельно. Если фрагменты не содержат ответа — "
        "скажи об этом и не выдумывай.",
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


def strip_citation_markers(text: str) -> str:
    """Удалить inline-сноски `[N]` из текста ответа ассистента (#383).

    Defensive-нетто поверх prompt-инструкции «не используй [N]»: LLM —
    вероятностная модель и изредка всё же вставляет маркер. Источники
    отдаются клиенту отдельным `citations`-блоком, поэтому `[2]` в тексте —
    только визуальный шум. Трогает лишь числовые маркеры; markdown-ссылки
    `[текст](url)` и `[слово]` не затрагиваются.
    """
    return _CITATION_MARKER_RE.sub("", text)


def hits_to_citations(chunks: list[RetrievalHit]) -> list[dict[str, Any]]:
    """Convert RetrievalHit-ы в JSONB-serializable citations.

    Структура соответствует existing `chat_messages.citations` JSONB
    field (`{type, id, title, url, ...}`) с дополнительными полями
    chunk_index / score для richer frontend display.

    `type` различает article body chunks ("article") vs Q&A ответы
    ("article_question"). Q&A citations включают `question_id` и
    URL с anchor'ом `#question-{id}` для deep-link'а на правильный
    блок article page (2026-05-29, ТЗ Чат-поиск §«корпуса»).
    """
    citations: list[dict[str, Any]] = []
    for hit in chunks:
        if hit.source_type == "article_question" and hit.question_id is not None:
            citations.append(
                {
                    "type": "article_question",
                    "id": str(hit.article_id),
                    "question_id": str(hit.question_id),
                    "title": hit.title,
                    "slug": hit.slug,
                    "chunk_index": hit.chunk_index,
                    "score": hit.score,
                    "url": f"/articles/{hit.slug}#question-{hit.question_id}",
                }
            )
        else:
            citations.append(
                {
                    "type": "article",
                    "id": str(hit.article_id),
                    "title": hit.title,
                    "slug": hit.slug,
                    "chunk_index": hit.chunk_index,
                    "score": hit.score,
                    "url": f"/articles/{hit.slug}",
                }
            )
    return citations
