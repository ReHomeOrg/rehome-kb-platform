"""Unit tests для PII masking pre-processor (#338, ФЗ-152 Stage 2)."""

from __future__ import annotations

import pytest

from src.api.chat.pii_masking import mask_pii

# ---------------------------------------------------------------------------
# Per-pattern positive cases


@pytest.mark.parametrize(
    "raw",
    [
        "+7 916 123 45 67",
        "+79161234567",
        "8 (916) 123-45-67",
        "8-916-123-45-67",
        "+7-916-123-45-67",
    ],
)
def test_mask_phone_ru_formats(raw: str) -> None:
    result = mask_pii(f"Связаться: {raw}, ответят быстро.")
    assert "[PHONE]" in result.text
    assert raw not in result.text
    assert result.counts["phone"] == 1


def test_mask_email_standard() -> None:
    result = mask_pii("Email: support@rehome.one для вопросов.")
    assert "[EMAIL]" in result.text
    assert "support@rehome.one" not in result.text
    assert result.counts["email"] == 1


def test_mask_email_complex_local_part() -> None:
    result = mask_pii("ivan.petrov+test@example.co.uk")
    assert result.text == "[EMAIL]"


def test_mask_snils_with_dashes() -> None:
    result = mask_pii("СНИЛС 123-456-789 01")
    assert "[SNILS]" in result.text
    assert "123-456-789" not in result.text


def test_mask_snils_with_spaces() -> None:
    result = mask_pii("СНИЛС 123 456 789 01")
    assert "[SNILS]" in result.text


def test_mask_passport() -> None:
    result = mask_pii("Паспорт: 4523 123456 выдан ОВД.")
    assert "[PASSPORT]" in result.text
    assert "4523 123456" not in result.text


def test_mask_bank_card_with_spaces() -> None:
    result = mask_pii("Карта 4276 1234 5678 9012 принимается.")
    assert "[CARD]" in result.text
    assert "4276 1234 5678 9012" not in result.text


def test_mask_bank_card_with_dashes() -> None:
    result = mask_pii("4276-1234-5678-9012")
    assert "[CARD]" in result.text


def test_mask_inn_legal_10_digits() -> None:
    """ИНН юр.лица — 10 digits."""
    result = mask_pii("ИНН 7707083893")
    assert "[INN]" in result.text


def test_mask_inn_individual_12_digits() -> None:
    """ИНН физ.лица — 12 digits."""
    result = mask_pii("ИНН физ.лица 770708389312")
    assert "[INN]" in result.text


# ---------------------------------------------------------------------------
# Negative / non-PII text unchanged


def test_no_pii_text_unchanged() -> None:
    text = "Договор аренды квартиры включает оплату и страхование."
    result = mask_pii(text)
    assert result.text == text
    assert result.total == 0


def test_does_not_mask_short_number_sequences() -> None:
    """Random 5-9 digit numbers shouldn't match anything."""
    result = mask_pii("В договоре 5 пунктов, всего 12345 случаев.")
    assert result.total == 0


def test_does_not_mask_random_words() -> None:
    result = mask_pii("Москва, Санкт-Петербург, Казань — города реHome.")
    assert result.total == 0


def test_dates_not_masked() -> None:
    """Out-of-scope: dates are kept (LLM context often needs them)."""
    result = mask_pii("Договор от 15.05.2026 действует до 14.05.2027.")
    # Dates contain no patterns matching our masks.
    assert result.text == "Договор от 15.05.2026 действует до 14.05.2027."


# ---------------------------------------------------------------------------
# Multi-pattern + ordering


def test_multiple_patterns_in_single_text() -> None:
    text = "Email me@x.ru или +7 916 555 12 34, СНИЛС 111-222-333 44."
    result = mask_pii(text)
    assert "[EMAIL]" in result.text
    assert "[PHONE]" in result.text
    assert "[SNILS]" in result.text
    assert result.counts["email"] == 1
    assert result.counts["phone"] == 1
    assert result.counts["snils"] == 1
    assert result.total == 3


def test_phone_masked_before_inn_no_double_mask() -> None:
    """+79161234567 contains a 10-digit substring that could match
    ИНН pattern. Phone is applied first, leaving placeholder в тексте;
    ИНН pattern won't match placeholder."""
    text = "Phone +79161234567"
    result = mask_pii(text)
    assert "[PHONE]" in result.text
    assert "[INN]" not in result.text
    assert result.counts.get("inn", 0) == 0


def test_idempotency_double_mask_unchanged() -> None:
    """Повторный mask_pii на already-masked text → no additional changes."""
    once = mask_pii("phone +7 916 123 45 67 and email a@b.ru")
    twice = mask_pii(once.text)
    assert twice.text == once.text
    assert twice.total == 0


def test_counts_aggregate_multiple_same_category() -> None:
    """Multiple phones — count = 2."""
    text = "+7 916 111 22 33 и +7 916 444 55 66"
    result = mask_pii(text)
    assert result.counts["phone"] == 2


def test_empty_text() -> None:
    result = mask_pii("")
    assert result.text == ""
    assert result.total == 0


def test_masking_result_total_property() -> None:
    text = "+7 916 000 00 00 me@x.ru"
    result = mask_pii(text)
    assert result.total == result.counts["phone"] + result.counts["email"]


# ---------------------------------------------------------------------------
# Integration smoke с build_rag_system_prompt


def test_build_rag_system_prompt_masks_chunk_text() -> None:
    from uuid import UUID

    from src.api.chat.system_prompt import build_rag_system_prompt
    from src.api.search.repository import RetrievalHit

    hit = RetrievalHit(
        article_id=UUID("00000000-0000-0000-0000-000000000001"),
        slug="contacts",
        title="Контакты поддержки",
        chunk_index=0,
        text="Связаться: +7 916 555 12 34, support@rehome.one.",
        score=0.9,
        char_start=0,
        char_end=50,
    )
    prompt = build_rag_system_prompt([hit])
    assert "[PHONE]" in prompt
    assert "[EMAIL]" in prompt
    assert "+7 916 555 12 34" not in prompt
    assert "support@rehome.one" not in prompt
    # Title не masked — content stays для legit context.
    assert "Контакты поддержки" in prompt


def test_build_rag_system_prompt_empty_chunks_no_masking_log() -> None:
    """Empty chunks → returns base SYSTEM_PROMPT без RAG block."""
    from src.api.chat.system_prompt import SYSTEM_PROMPT, build_rag_system_prompt

    prompt = build_rag_system_prompt([])
    assert prompt == SYSTEM_PROMPT
