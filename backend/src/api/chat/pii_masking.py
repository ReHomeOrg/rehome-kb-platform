"""PII masking pre-processor для LLM context (ФЗ-152, ADR-0010 §«Стадия 2»).

Goal: chunk text, retrieved из articles для RAG context, может содержать
ПДн (телефоны, email, паспорт, ИНН, СНИЛС, банковские карты) — например,
если статья базы знаний цитирует чью-то контактную информацию для
иллюстрации. Перед отправкой текста в external LLM API маскируем эти
patterns на placeholder strings.

Pattern priorities (precision over recall — false positives acceptable;
under-masking — реальный риск):
- Phone numbers (RU/intl) — high precision via +7/8 prefix anchor.
- Email — RFC 5322-lite pattern.
- СНИЛС — fixed format `NNN-NNN-NNN NN` или spaces.
- Passport (RU internal) — `NNNN NNNNNN` с word-boundary check.
- ИНН — 10/12 digits с word-boundary; lower confidence (many random
  10-digit sequences are not ИНН) — applied last after others.
- Bank card — 13-19 digits в groups of 4.

Не маскируем (out of scope):
- Personal names (no reliable pattern в RU без NER модели).
- Адреса (the LLM context often needs addresses for property questions).
- Date of birth (typically appears в structured fields, не raw text).

Возвращаем количество масок для observability (Prometheus counter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# Pattern library — ordered (specific → general).
# Each pattern: (regex, replacement, name).


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# Phone — RU formats: +7..., 8..., с separators.
_PHONE_RE: Final = _compile(r"(?:\+7|\b8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}")

# Email — pragmatic subset of RFC 5322.
_EMAIL_RE: Final = _compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")

# СНИЛС — `XXX-XXX-XXX XX` или `XXX XXX XXX XX`.
_SNILS_RE: Final = _compile(r"\b\d{3}[\-\s]\d{3}[\-\s]\d{3}[\-\s]\d{2}\b")

# Bank card — 13-19 digits в groups of 4 (Visa/MasterCard/Maestro range).
# Word-boundary anchored.
_CARD_RE: Final = _compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{1,4}(?:[\s\-]\d{3})?\b")

# Passport RU — `NNNN NNNNNN` (4 digits, separator, 6 digits).
_PASSPORT_RE: Final = _compile(r"\b\d{4}\s\d{6}\b")

# ИНН — 10 (legal entity) or 12 (individual) digits. Broad pattern;
# applied AFTER more specific masks to avoid double-masking phone parts
# (e.g. 10 digits внутри telephone). Word-boundary required.
_INN_RE: Final = _compile(r"\b\d{10}(?:\d{2})?\b")

# Order matters: specific (longer / fixed-format) patterns first.
_PATTERNS: Final[list[tuple[re.Pattern[str], str, str]]] = [
    (_PHONE_RE, "[PHONE]", "phone"),
    (_EMAIL_RE, "[EMAIL]", "email"),
    (_SNILS_RE, "[SNILS]", "snils"),
    (_CARD_RE, "[CARD]", "card"),
    (_PASSPORT_RE, "[PASSPORT]", "passport"),
    (_INN_RE, "[INN]", "inn"),
]


@dataclass(frozen=True)
class MaskingResult:
    """Output of `mask_pii`: text + counts per category для metrics."""

    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def mask_pii(text: str) -> MaskingResult:
    """Apply all PII patterns в order; return masked text + counts.

    Idempotent: повторный вызов на masked text returns same (placeholders
    `[PHONE]` etc. don't match patterns).
    """
    counts: dict[str, int] = {}
    masked = text
    for pattern, placeholder, name in _PATTERNS:
        matches = pattern.findall(masked)
        if matches:
            counts[name] = len(matches)
            masked = pattern.sub(placeholder, masked)
    return MaskingResult(text=masked, counts=counts)


__all__ = ["MaskingResult", "mask_pii"]
