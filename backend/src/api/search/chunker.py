"""Paragraph chunker (kb-search Stage 1, #128).

Стратегия (ADR-0010 §"Chunking"):
- Target chunk size: ~512 tokens (≈2000 chars для русского / mixed).
- Overlap: ~64 tokens (~250 chars) — 12% sliding window, стандартная heuristic.
- Code blocks (тройные backtick) НЕ разбиваются — лучше один большой
  chunk чем syntactically broken fragments (если в пределах MAX).
- Code blocks > MAX_CHUNK_CHARS И обычные параграфы > MAX_CHUNK_CHARS
  разбиваются на character boundaries без overlap'а — anti-data-loss
  safety для embedding model'и (e5-large input limit ~512 токенов).

Token-counting через chars/4 heuristic (consistent с
chat/router.py:_CHARS_PER_TOKEN). Не добавляем tiktoken / transformers
tokenizer для chunker'а — он preserve'ит ~500 token target с разумной
точностью, real truncation enforcement — на стороне embedding model.

NB: markdown heading-aware splitting (`#`, `##`) — backlog (ADR-0010
mentions это как possible refinement, не Stage 1 must-have). Сейчас
headings обрабатываются как regular text.
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

    Char offset semantics:
    - `char_start`/`char_end` указывают на source span соответствующий
      chunk'у (полезно для citation rendering + highlight).
    - `chunk.text` — это actual indexed content. Может быть СОКРАЩЕНО
      относительно `source[char_start:char_end]` потому что
      inter-paragraph whitespace gaps НЕ попадают в text (они "съедены"
      paragraph splitter'ом). Slice source — для highlight rendering;
      использовать chunk.text для display'ev / embeddings.
    - Overlap regions duplicate'ятся между соседними chunks (это by
      design — context preservation).
    - Никакая chunk.text НЕ превышает MAX_CHUNK_CHARS — even single
      huge paragraph hard-split'ится на character boundaries.
    """
    if not source.strip():
        return []

    paragraphs = _split_paragraphs_respecting_code(source)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    # Accumulator state: span — последний paragraph_end, который попал в
    # cur_text_parts. char_end правильный для slice'а из source даже при
    # gaps между paragraphs.
    cur_start: int = paragraphs[0][0]
    cur_end: int = paragraphs[0][0]
    cur_text_parts: list[str] = []

    def _flush() -> None:
        """Emit chunk + setup overlap context для следующего."""
        nonlocal cur_start, cur_end, cur_text_parts
        if not cur_text_parts:
            return
        text = "".join(cur_text_parts)
        chunks.append(Chunk(text=text, char_start=cur_start, char_end=cur_end))
        if len(text) > OVERLAP_CHARS:
            overlap_text = text[-OVERLAP_CHARS:]
            # Next chunk's "start" — последние OVERLAP_CHARS bytes этого
            # chunk'а. cur_end остаётся прежним (overlap не consume'ит
            # source — он duplicate'ит).
            cur_start = cur_end - OVERLAP_CHARS
            cur_text_parts = [overlap_text]
        else:
            cur_start = cur_end
            cur_text_parts = []

    for para_start, para_end, para_text in paragraphs:
        # Special case 1: huge single paragraph (e.g., runaway pasted text
        # без blank lines или code block > MAX). Hard-split на character
        # boundaries без overlap. Anti-data-loss: иначе embedding model
        # silently truncate'нет.
        if len(para_text) > MAX_CHUNK_CHARS:
            if cur_text_parts:
                _flush()
            for sub_start_off in range(0, len(para_text), MAX_CHUNK_CHARS):
                sub_text = para_text[sub_start_off : sub_start_off + MAX_CHUNK_CHARS]
                abs_start = para_start + sub_start_off
                chunks.append(
                    Chunk(
                        text=sub_text,
                        char_start=abs_start,
                        char_end=abs_start + len(sub_text),
                    )
                )
            cur_start = para_end
            cur_end = para_end
            cur_text_parts = []
            continue

        accumulated_len = sum(len(p) for p in cur_text_parts) + len(para_text)

        # Special case 2: добавление paragraph'а превысит MAX — flush
        # текущее (с overlap), оставить paragraph для следующего.
        if accumulated_len > MAX_CHUNK_CHARS and cur_text_parts:
            _flush()

        # Init start если cur_text_parts только что cleared'ились.
        if not cur_text_parts:
            cur_start = para_start
        cur_text_parts.append(para_text)
        cur_end = para_end

        # Достигли target — flush с overlap.
        if sum(len(p) for p in cur_text_parts) >= TARGET_CHUNK_CHARS:
            _flush()

    # Tail.
    if cur_text_parts:
        text = "".join(cur_text_parts)
        chunks.append(Chunk(text=text, char_start=cur_start, char_end=cur_end))

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
