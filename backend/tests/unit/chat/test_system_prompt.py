"""Unit tests для `resolve_system_prompt` + `build_rag_system_prompt`
base_prompt parameter (#348, ADR-0019 chat.system_prompt overlay).
"""

from __future__ import annotations

from uuid import UUID

from src.api.chat.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    GREETING_DIRECTIVE_FIRST,
    GREETING_DIRECTIVE_REPEAT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_MAX_LENGTH,
    SYSTEM_PROMPT_OVERLAY_KEY,
    apply_greeting_rule,
    build_greeting_directive,
    build_rag_system_prompt,
    resolve_system_prompt,
)
from src.api.search.repository import RetrievalHit


def _hit(text: str = "fragment") -> RetrievalHit:
    return RetrievalHit(
        article_id=UUID("00000000-0000-0000-0000-000000000001"),
        slug="x",
        title="t",
        chunk_index=0,
        text=text,
        score=0.5,
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
