"""Markdown-aware paragraph chunker (kb-search Stage 1, #128).

Стратегия (ADR-0010 §"Chunking"):
- Target chunk size: ~512 tokens (≈2000 chars для русского / mixed).
- Overlap: ~64 tokens (~250 chars) — 12% sliding window, стандартная heuristic.
- Markdown headings (`#`, `##`, ...) preserve'ятся как boundary hints —
  chunk кончается там где есть heading, если это в разумных размерах.
- Code blocks (тройные backtick) НЕ разбиваются — лучше один большой
  chunk чем syntactically broken fragments.

Token-counting через chars/4 heuristic (consistent с
chat/router.py:_CHARS_PER_TOKEN). Не добавляем tiktoken / transformers
tokenizer для chunker'а — он preserve'ит ~500 token target с разумной
точностью, а real input-truncation enforcement — на стороне embedding
model.
"""

from dataclasses import dataclass
from typing import Final

# Chars-per-token estimate matches `chat/router.py:_CHARS_PER_TOKEN`. Не
# universally accurate, но достаточно для chunk-sizing heuristic.
_CHARS_PER_TOKEN: Final = 4

TARGET_CHUNK_CHARS: Final = 512 * _CHARS_PER_TOKEN  # ≈ 2048 chars / 512 tokens
OVERLAP_CHARS: Final = 64 * _CHARS_PER_TOKEN  # ≈ 256 chars / 64 tokens

# Soft cap — chunk может перерасти TARGET если внутри code block. Hard cap
# защищает от gigantic single-block input (rare; обычно ≤10× target).
MAX_CHUNK_CHARS: Final = TARGET_CHUNK_CHARS * 4

# Markdown code block fence (тройной backtick, optional language hint).
_CODE_FENCE: Final = "```"


@dataclass(frozen=True)
class Chunk:
    """Один text chunk с char offsets в source text."""

    text: str
    char_start: int
    char_end: int


def chunk_text(source: str) -> list[Chunk]:
    """Split `source` на chunks по правилам выше.

    Returns пустой list для пустого / whitespace-only input.

    Invariants:
    - `chunks[i].char_start == chunks[i-1].char_end - OVERLAP_CHARS` (или
      ≥ если paragraph boundary дал natural split).
    - `chunks[-1].char_end == len(source)` если source non-empty.
    - text каждого chunk = `source[char_start:char_end]`.
    """
    if not source.strip():
        return []

    paragraphs = _split_paragraphs_respecting_code(source)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    cur_start: int = paragraphs[0][0]
    cur_text_parts: list[str] = []

    def _flush() -> None:
        nonlocal cur_start, cur_text_parts
        if not cur_text_parts:
            return
        text = "".join(cur_text_parts)
        # `cur_start + len(text)` отличается от `end_pos` на whitespace
        # между paragraph'ами; используем cur_start + length для точности.
        chunks.append(Chunk(text=text, char_start=cur_start, char_end=cur_start + len(text)))
        # Setup для next chunk: overlap из tail предыдущего.
        if len(text) > OVERLAP_CHARS:
            overlap_text = text[-OVERLAP_CHARS:]
            cur_start = cur_start + len(text) - OVERLAP_CHARS
            cur_text_parts = [overlap_text]
        else:
            cur_start = cur_start + len(text)
            cur_text_parts = []

    for para_start, para_end, para_text in paragraphs:
        accumulated = "".join(cur_text_parts) + para_text
        if len(accumulated) > MAX_CHUNK_CHARS:
            # Paragraph сам по себе огромный (code block) — emit as-is
            # без overlap'а (single-block integrity > overlap).
            if cur_text_parts:
                _flush()
            chunks.append(Chunk(text=para_text, char_start=para_start, char_end=para_end))
            cur_start = para_end
            cur_text_parts = []
            continue

        if accumulated and len(accumulated) >= TARGET_CHUNK_CHARS:
            # Дозреем до target — flush с overlap.
            cur_text_parts.append(para_text)
            _flush()
            continue

        # Накапливаем дальше.
        if not cur_text_parts:
            cur_start = para_start
        cur_text_parts.append(para_text)

    # Tail.
    if cur_text_parts:
        text = "".join(cur_text_parts)
        chunks.append(Chunk(text=text, char_start=cur_start, char_end=cur_start + len(text)))

    return chunks


def _split_paragraphs_respecting_code(source: str) -> list[tuple[int, int, str]]:
    """Split на paragraphs (separated by blank line), keeping code blocks
    atomic. Returns list of (char_start, char_end, text).
    """
    paragraphs: list[tuple[int, int, str]] = []
    pos = 0
    in_code = False
    cur_start = 0
    cur_lines: list[str] = []

    def _emit() -> None:
        nonlocal cur_lines, cur_start
        if not cur_lines:
            return
        text = "".join(cur_lines)
        if text.strip():
            paragraphs.append((cur_start, cur_start + len(text), text))
        cur_lines = []

    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(_CODE_FENCE):
            # Toggle code block. Fence line — часть текущего paragraph'а.
            if not cur_lines:
                cur_start = pos
            cur_lines.append(line)
            in_code = not in_code
        elif in_code:
            cur_lines.append(line)
        elif stripped == "":
            # Blank line вне code — paragraph boundary.
            cur_lines.append(line)
            _emit()
            cur_start = pos + len(line)
        else:
            if not cur_lines:
                cur_start = pos
            cur_lines.append(line)
        pos += len(line)
    _emit()
    return paragraphs
