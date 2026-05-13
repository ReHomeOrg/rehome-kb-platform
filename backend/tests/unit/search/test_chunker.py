"""Unit tests for paragraph chunker (#128)."""

import pytest

from src.api.search.chunker import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    TARGET_CHUNK_CHARS,
    Chunk,
    chunk_text,
)


def test_empty_returns_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_one_chunk() -> None:
    text = "Hello world."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(text)


def test_chunk_offsets_recover_source_text() -> None:
    # ≈ 8000 chars — reliably > TARGET_CHUNK_CHARS (2048), forces split.
    text = "First paragraph.\n\nSecond paragraph here." * 200
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    for c in chunks:
        # Recoverable: text == source[start:end]
        assert text[c.char_start : c.char_end] == c.text


def test_chunks_have_overlap_when_split() -> None:
    para = "Some sentence here. " * 100  # ≈ 2000+ chars
    text = (para + "\n\n") * 3
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    # Overlap: each subsequent chunk's start < prev's end.
    for i in range(1, len(chunks)):
        assert chunks[i].char_start < chunks[i - 1].char_end


def test_target_size_respected() -> None:
    """Большой text → chunks ≈ TARGET_CHUNK_CHARS, не huge dumps."""
    text = ("paragraph. " * 500 + "\n\n") * 5
    chunks = chunk_text(text)
    for c in chunks[:-1]:  # last chunk может быть short tail
        assert len(c.text) <= MAX_CHUNK_CHARS


def test_code_block_not_split() -> None:
    """``` ... ``` блоки остаются atomic chunk'ом, даже если > target."""
    huge_code = "\n".join(f"line_{i} = " + ("x" * 50) for i in range(200))
    text = f"intro paragraph\n\n```python\n{huge_code}\n```\n\noutro paragraph"
    chunks = chunk_text(text)
    # Один chunk должен содержать code block целиком.
    code_chunks = [c for c in chunks if "line_0" in c.text and "line_199" in c.text]
    assert len(code_chunks) == 1, "code block split across chunks"


def test_chunks_cover_full_source() -> None:
    """Union of chunks по char_start..char_end должен покрывать всё non-trivial
    содержимое (можем терять trailing newlines в paragraphs)."""
    text = "Para A.\n\nPara B.\n\nPara C."
    chunks = chunk_text(text)
    assert chunks[0].char_start == 0
    # last chunk должен заканчиваться near len(text). Allow small slack
    # for trailing whitespace lost в paragraph boundary detection.
    assert chunks[-1].char_end >= len(text) - 2


def test_overlap_chars_constant_sane() -> None:
    """Sanity check на constants — они в правильном порядке."""
    assert 0 < OVERLAP_CHARS < TARGET_CHUNK_CHARS < MAX_CHUNK_CHARS


def test_chunk_dataclass_frozen() -> None:
    """`Chunk` immutable — caller не сможет случайно mutate."""
    c = Chunk(text="x", char_start=0, char_end=1)
    # `pytest.raises` вместо try/except/pass — последний поймал бы
    # anti-crutches CI check (CLAUDE.md §5: "except: pass — кардинальный
    # костыль"). Здесь exception expected, но pytest.raises clearer.
    with pytest.raises((AttributeError, TypeError)):
        c.text = "y"  # type: ignore[misc]
