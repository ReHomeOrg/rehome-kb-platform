"""Unit tests для `resolve_system_prompt` + `build_rag_system_prompt`
base_prompt parameter (#348, ADR-0019 chat.system_prompt overlay).
"""

from __future__ import annotations

from uuid import UUID

from src.api.chat.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    GREETING_DIRECTIVE_FIRST,
    GREETING_DIRECTIVE_REPEAT,
    NO_CONTEXT_DIRECTIVE,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_MAX_LENGTH,
    SYSTEM_PROMPT_OVERLAY_KEY,
    apply_greeting_rule,
    apply_no_context_rule,
    build_greeting_directive,
    build_rag_system_prompt,
    has_usable_context,
    resolve_system_prompt,
    strip_citation_markers,
)
from src.api.search.repository import RetrievalHit


def _hit(text: str = "fragment", score: float = 0.5) -> RetrievalHit:
    return RetrievalHit(
        article_id=UUID("00000000-0000-0000-0000-000000000001"),
        slug="x",
        title="t",
        chunk_index=0,
        text=text,
        score=score,
        char_start=0,
        char_end=10,
    )


# ---------------------------------------------------------------------------
# Constants


def test_system_prompt_backward_compat_alias() -> None:
    """SYSTEM_PROMPT (legacy name) — alias на DEFAULT_SYSTEM_PROMPT."""
    assert SYSTEM_PROMPT == DEFAULT_SYSTEM_PROMPT


def test_overlay_key_constant_matches_repo_allowlist() -> None:
    """Overlay key — `chat.system_prompt` per ADR-0019."""
    assert SYSTEM_PROMPT_OVERLAY_KEY == "chat.system_prompt"


def test_max_length_reasonable() -> None:
    """16384 chars — защита от exhaust'а LLM context."""
    assert SYSTEM_PROMPT_MAX_LENGTH == 16384


# ---------------------------------------------------------------------------
# resolve_system_prompt


def test_resolve_none_overlay_returns_default() -> None:
    assert resolve_system_prompt(None) == DEFAULT_SYSTEM_PROMPT


def test_resolve_empty_overlay_returns_default() -> None:
    assert resolve_system_prompt({}) == DEFAULT_SYSTEM_PROMPT


def test_resolve_overlay_without_key_returns_default() -> None:
    assert resolve_system_prompt({"llm_provider": "mock"}) == DEFAULT_SYSTEM_PROMPT


def test_resolve_overlay_with_value_returns_override() -> None:
    overlay = {"chat.system_prompt": "Кастомный промпт от админа"}
    assert resolve_system_prompt(overlay) == "Кастомный промпт от админа"


def test_resolve_overlay_whitespace_only_returns_default() -> None:
    """Defensive: empty/whitespace overlay value → fallback."""
    assert resolve_system_prompt({"chat.system_prompt": "   "}) == DEFAULT_SYSTEM_PROMPT


def test_resolve_overlay_non_string_returns_default() -> None:
    """Defensive: non-string value (storage corruption) → fallback."""
    assert resolve_system_prompt({"chat.system_prompt": 12345}) == DEFAULT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# build_rag_system_prompt с base_prompt


def test_build_rag_no_chunks_no_base_returns_default() -> None:
    """Empty chunks + no base → DEFAULT_SYSTEM_PROMPT (backward-compat)."""
    assert build_rag_system_prompt([]) == DEFAULT_SYSTEM_PROMPT


def test_build_rag_no_chunks_with_base_returns_base() -> None:
    """Empty chunks + override base → возвращает override."""
    custom = "Custom override prompt"
    assert build_rag_system_prompt([], base_prompt=custom) == custom


def test_build_rag_with_chunks_uses_base_prompt() -> None:
    """Chunks present → base_prompt prepended (default), RAG block appended."""
    custom = "Кастомный admin prompt"
    prompt = build_rag_system_prompt([_hit(text="some text")], base_prompt=custom)
    assert prompt.startswith(custom)
    assert "## Контекст из базы знаний" in prompt


def test_build_rag_with_chunks_default_base_fallback() -> None:
    """No base_prompt arg → DEFAULT_SYSTEM_PROMPT используется."""
    prompt = build_rag_system_prompt([_hit()])
    assert prompt.startswith(DEFAULT_SYSTEM_PROMPT)


def test_build_rag_with_chunks_explicit_none_uses_default() -> None:
    """base_prompt=None (explicit) → DEFAULT (idempotent)."""
    prompt = build_rag_system_prompt([_hit()], base_prompt=None)
    assert prompt.startswith(DEFAULT_SYSTEM_PROMPT)


def test_greeting_directive_first_when_not_greeted() -> None:
    """greeted_today=False → директива поздороваться «Здравствуйте»."""
    directive = build_greeting_directive(greeted_today=False)
    assert directive == GREETING_DIRECTIVE_FIRST
    assert "Здравствуйте" in directive


def test_greeting_directive_repeat_when_greeted() -> None:
    """greeted_today=True → директива не здороваться повторно."""
    directive = build_greeting_directive(greeted_today=True)
    assert directive == GREETING_DIRECTIVE_REPEAT
    assert "НЕ пиши" in directive


def test_apply_greeting_rule_first_appends_greet_instruction() -> None:
    """Правило дописывается к prompt, base сохраняется, велит поздороваться."""
    out = apply_greeting_rule("BASE PROMPT", greeted_today=False)
    assert out.startswith("BASE PROMPT")
    assert GREETING_DIRECTIVE_FIRST in out
    assert "## Приветствие" in out


def test_apply_greeting_rule_repeat_says_no_greeting() -> None:
    """greeted_today=True → в prompt директива не здороваться."""
    out = apply_greeting_rule("BASE PROMPT", greeted_today=True)
    assert out.startswith("BASE PROMPT")
    assert GREETING_DIRECTIVE_REPEAT in out


# ---------------------------------------------------------------------------
# strip_citation_markers (#383): inline `[N]` сноски убираются из ответа


def test_strip_removes_single_marker_with_leading_space() -> None:
    """`текст [2].` → `текст.` (маркер и пробел перед ним срезаны)."""
    assert strip_citation_markers("Страховка покрывает ремонт [2].") == (
        "Страховка покрывает ремонт."
    )


def test_strip_removes_multiple_markers() -> None:
    assert strip_citation_markers("a [1] b [22] c [333]") == "a b c"


def test_strip_no_markers_unchanged() -> None:
    text = "Ответ без сносок, просто текст."
    assert strip_citation_markers(text) == text


def test_strip_ignores_markdown_links() -> None:
    """Markdown-ссылки `[текст](url)` не трогаются (не числовой маркер)."""
    text = "См. статью [Ремонт техники](/articles/remont)."
    assert strip_citation_markers(text) == text


def test_strip_ignores_non_numeric_brackets() -> None:
    """`[важно]` и прочие не-числовые скобки остаются."""
    text = "Это [важно] и [NB] помнить."
    assert strip_citation_markers(text) == text


def test_strip_marker_at_start_leaves_leading_space() -> None:
    """Маркер в самом начале строки убирается, но оставляет ведущий пробел —
    принятое ограничение (LLM не начинает ответ с `[N]`, см. коммент у regex)."""
    assert strip_citation_markers("[1] начало ответа") == " начало ответа"


def test_strip_marker_glued_between_words_documents_limitation() -> None:
    """Маркер вплотную без пробелов склеивает слова — принятое ограничение
    defensive-нетто (реальный LLM пишет `[N]` с пробелом)."""
    assert strip_citation_markers("ремонт[3]техники") == "ремонттехники"


def test_strip_multi_digit_marker() -> None:
    """Многозначные `[N]` тоже срезаются (как источники не встречаются)."""
    assert strip_citation_markers("текст [1000] дальше") == "текст дальше"


# ---------------------------------------------------------------------------
# build_rag_system_prompt: RAG-блок больше НЕ просит формат `[N]`


def test_build_rag_instruction_forbids_bracket_markers() -> None:
    """Инструкция RAG-блока велит НЕ вставлять `[N]`, а не цитировать ими."""
    prompt = build_rag_system_prompt([_hit(text="frag")], base_prompt="BASE")
    assert "НЕ вставляй" in prompt
    assert "в квадратных скобках" in prompt


# ---------------------------------------------------------------------------
# Confidence-gated escalation (#383, Tier 2): has_usable_context


def test_has_usable_context_empty_is_false() -> None:
    """Пустой retrieval → нет уверенного контекста."""
    assert has_usable_context([]) is False


def test_has_usable_context_nonempty_no_threshold_is_true() -> None:
    """Непустой retrieval при выключенном пороге (min_score=0) → есть контекст."""
    assert has_usable_context([_hit()]) is True


def test_has_usable_context_above_threshold_is_true() -> None:
    """Top-score выше порога → есть контекст."""
    assert has_usable_context([_hit(score=0.6)], min_score=0.5) is True


def test_has_usable_context_below_threshold_is_false() -> None:
    """Top-score ниже порога → контекста нет (data-driven эскалация)."""
    assert has_usable_context([_hit(score=0.1)], min_score=0.5) is False


def test_has_usable_context_uses_max_score() -> None:
    """Порог сверяется с ЛУЧШИМ (максимальным) score хита, не первым."""
    hits = [_hit(score=0.1), _hit(score=0.6)]
    assert has_usable_context(hits, min_score=0.5) is True


def test_has_usable_context_empty_ignores_threshold() -> None:
    """Пустой retrieval → False независимо от порога."""
    assert has_usable_context([], min_score=0.9) is False


# ---------------------------------------------------------------------------
# Confidence-gated escalation: apply_no_context_rule


def test_apply_no_context_rule_appends_when_no_context() -> None:
    """has_context=False → дописывается no-context директива, base сохраняется."""
    out = apply_no_context_rule("BASE PROMPT", has_context=False)
    assert out.startswith("BASE PROMPT")
    assert NO_CONTEXT_DIRECTIVE in out
    assert "поддержку" in out


def test_apply_no_context_rule_idempotent_when_has_context() -> None:
    """has_context=True → prompt без изменений (no-context не дописывается)."""
    out = apply_no_context_rule("BASE PROMPT", has_context=True)
    assert out == "BASE PROMPT"
    assert NO_CONTEXT_DIRECTIVE not in out
