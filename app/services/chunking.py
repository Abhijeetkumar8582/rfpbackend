"""Text chunking for embedding and vector search — split documents into overlapping segments."""
from __future__ import annotations

import re


_HEADING_NUMERIC_RE = re.compile(r"^\d+(?:\.\d+){0,4}\s+.+$")
_HEADING_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9\s\-/()]{2,80}$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|(?:\d+|[a-zA-Z])[.)])\s+")
_NUMBERED_CLAUSE_RE = re.compile(r"^\s*\d+(?:\.\d+){1,6}\s+")
_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?\;\:])\s+")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{1,32}")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "were", "have",
    "has", "had", "into", "onto", "your", "our", "their", "its", "not", "but", "can",
    "will", "shall", "may", "must", "all", "any", "one", "two", "three", "per", "each",
}


def pages_for_char_span(
    start: int,
    end: int,
    page_starts: list[int],
    text_len: int,
) -> tuple[int | None, int | None]:
    """
    Map a character span in flattened PDF text to 1-based physical PDF page numbers.
    page_starts[i] is the char index where page i+1 begins.
    """
    if not page_starts or start < 0 or end <= start or not text_len:
        return None, None
    tl = max(0, text_len)

    def page_1based_for_char(c: int) -> int:
        c = max(0, min(c, tl - 1)) if tl else 0
        for i in range(len(page_starts) - 1, -1, -1):
            if c >= page_starts[i]:
                return i + 1
        return 1

    lo = page_1based_for_char(start)
    hi = page_1based_for_char(max(start, end - 1))
    return lo, hi


def _is_heading_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if s.startswith("#"):
        return True
    if _HEADING_NUMERIC_RE.match(s):
        return True
    if _HEADING_UPPER_RE.match(s) and not s.endswith("."):
        return True
    return False


def _heading_level(line: str) -> int:
    s = (line or "").strip()
    if s.startswith("#"):
        return min(6, max(1, len(s) - len(s.lstrip("#"))))
    if _HEADING_NUMERIC_RE.match(s):
        head = s.split(maxsplit=1)[0]
        return min(6, head.count(".") + 1)
    return 1


def _split_sections(text: str) -> list[tuple[str, str, str]]:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    sections: list[tuple[str, str, str]] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading = "Document"
    current_lines: list[str] = []

    def flush_section() -> None:
        body = "\n".join(current_lines).strip()
        if not body:
            return
        breadcrumb = " > ".join([h for _, h in heading_stack]) or current_heading
        sections.append((current_heading, breadcrumb, body))

    for ln in lines:
        stripped = ln.strip()
        if _is_heading_line(stripped):
            flush_section()
            current_lines = []
            level = _heading_level(stripped)
            heading = stripped.lstrip("#").strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading))
            current_heading = heading
            continue
        current_lines.append(ln)

    flush_section()
    if sections:
        return sections
    fallback = " ".join((text or "").split()).strip()
    return [("Document", "Document", fallback)] if fallback else []


def _line_kind(line: str) -> str:
    s = (line or "").strip()
    if not s:
        return "blank"
    if _TABLE_ROW_RE.match(s) or ("\t" in s and len([p for p in s.split("\t") if p.strip()]) >= 2):
        return "table"
    if _BULLET_RE.match(s):
        return "bullet"
    if _NUMBERED_CLAUSE_RE.match(s):
        return "clause"
    return "paragraph"


def _split_structural_units(section_body: str) -> list[str]:
    """
    Split by document structure before any size-based fallback:
    paragraph, bullet block, table block, numbered clause block.
    """
    lines = section_body.splitlines()
    units: list[str] = []
    current: list[str] = []
    current_kind = "paragraph"

    def flush() -> None:
        nonlocal current
        block = "\n".join(current).strip()
        if block:
            units.append(block)
        current = []

    for ln in lines:
        kind = _line_kind(ln)
        if kind == "blank":
            flush()
            current_kind = "paragraph"
            continue
        if not current:
            current = [ln]
            current_kind = kind
            continue
        if kind == current_kind and kind in ("bullet", "table", "clause"):
            current.append(ln)
            continue
        if kind in ("bullet", "table", "clause") or current_kind in ("bullet", "table", "clause"):
            flush()
            current = [ln]
            current_kind = kind
            continue
        # paragraph continuation
        current.append(ln)
    flush()
    return units


def _split_by_sentence_groups(text: str, max_chunk_chars: int) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if not sentences:
        return [text.strip()] if text.strip() else []
    groups: list[str] = []
    cur = ""
    for s in sentences:
        cand = f"{cur} {s}".strip() if cur else s
        if len(cand) <= max_chunk_chars:
            cur = cand
            continue
        if cur:
            groups.append(cur)
        cur = s
    if cur:
        groups.append(cur)
    return groups


def _recursive_split(text: str, max_chunk_chars: int) -> list[str]:
    """
    Recursive fallback hierarchy:
    paragraphs -> sentence groups -> hard boundary (final safety).
    """
    block = (text or "").strip()
    if not block:
        return []
    if len(block) <= max_chunk_chars:
        return [block]

    para_parts = [p.strip() for p in re.split(r"\n\s*\n+", block) if p.strip()]
    if len(para_parts) > 1:
        out: list[str] = []
        for p in para_parts:
            out.extend(_recursive_split(p, max_chunk_chars))
        return out

    sent_groups = _split_by_sentence_groups(block, max_chunk_chars)
    if len(sent_groups) > 1:
        return sent_groups

    # Final fallback: very long uninterrupted text.
    out = []
    i = 0
    step = max(128, max_chunk_chars - 64)
    while i < len(block):
        seg = block[i : i + max_chunk_chars].strip()
        if seg:
            out.append(seg)
        i += step
    return out


def _with_small_overlap(units: list[str], overlap_chars: int) -> list[str]:
    if not units:
        return []
    overlap_chars = max(0, int(overlap_chars))
    if overlap_chars <= 0:
        return units
    out: list[str] = []
    prev = ""
    for u in units:
        if prev:
            tail = prev[-overlap_chars:].strip()
            out.append((f"{tail}\n{u}".strip() if tail else u).strip())
        else:
            out.append(u)
        prev = u
    return out


def _content_tokens(text: str) -> set[str]:
    raw = _TOKEN_RE.findall((text or "").lower())
    return {t for t in raw if len(t) > 2 and t not in _STOPWORDS}


def _semantic_overlap(a: str, b: str) -> float:
    ta = _content_tokens(a)
    tb = _content_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return (inter / union) if union else 0.0


def _quality_refine_chunks(
    chunks: list[str],
    *,
    min_chunk_chars: int,
    max_chunk_chars: int,
    overlap_chars: int,
) -> list[str]:
    """
    Lightweight production validator:
    - remove near-duplicate adjacent chunks
    - merge very short chunks when possible
    - keep small overlap to preserve boundary context
    """
    refined: list[str] = []
    for ch in chunks:
        current = (ch or "").strip()
        if not current:
            continue
        if refined:
            prev = refined[-1]
            if _semantic_overlap(prev, current) >= 0.92:
                # Redundant retrieval candidates add cost with little recall gain.
                continue
            if len(current) < min_chunk_chars:
                merged = f"{prev}\n\n{current}".strip()
                if len(merged) <= max_chunk_chars:
                    refined[-1] = merged
                    continue
        refined.append(current)
    return _with_small_overlap(refined, overlap_chars)


def _pack_units(units: list[str], max_chunk_chars: int, overlap_chars: int) -> list[str]:
    min_chunk_chars = max(220, int(max_chunk_chars * 0.35))
    packed: list[str] = []
    cur = ""
    min_semantic_overlap = 0.06
    for u in units:
        unit = (u or "").strip()
        if not unit:
            continue
        # Quality gate: if next unit is semantically far and current is already meaningful,
        # start a new chunk so each chunk tends to answer one likely question.
        if cur and len(cur) >= min_chunk_chars:
            if _semantic_overlap(cur, unit) < min_semantic_overlap:
                packed.append(cur)
                cur = unit
                continue
        cand = f"{cur}\n\n{u}".strip() if cur else u
        if len(cand) <= max_chunk_chars:
            cur = cand
            continue
        if cur:
            packed.append(cur)
        cur = unit
    if cur:
        packed.append(cur)
    return _quality_refine_chunks(
        packed,
        min_chunk_chars=min_chunk_chars,
        max_chunk_chars=max_chunk_chars,
        overlap_chars=overlap_chars,
    )


def chunk_text_by_sections(
    text: str,
    *,
    max_chunk_chars: int = 1200,
    overlap_chars: int = 120,
    page_char_starts: list[int] | None = None,
) -> list[dict]:
    """
    Chunk text by section heading first, then recursively split large sections.
    Returns list of {"text", "section", "breadcrumb", "word_start", "word_end", optional page_start/page_end}.
    When page_char_starts is set (PDF physical page boundaries in text), each chunk gets 1-based page range.
    """
    if not text or not text.strip():
        return []
    out: list[dict] = []
    tl = len(text)
    search_pos = 0
    sections = _split_sections(text)
    for section, breadcrumb, section_body in sections:
        body_start = text.find(section_body, search_pos)
        if body_start < 0:
            body_start = text.find(section_body.strip(), search_pos)
        if body_start < 0:
            body_start = search_pos
        search_pos = body_start + max(len(section_body), 1)

        structural_units = _split_structural_units(section_body)
        recursive_units: list[str] = []
        for unit in structural_units:
            recursive_units.extend(_recursive_split(unit, max_chunk_chars))
        passage_units = _pack_units(recursive_units, max_chunk_chars, overlap_chars)
        word_cursor = 0
        passage_find = 0
        for passage in passage_units:
            w_count = len(passage.split())
            w_start = word_cursor
            w_end = word_cursor + w_count
            word_cursor = max(0, w_end - max(0, overlap_chars // 6))
            # Keep heading context in chunk text so references survive retrieval and rerank.
            chunk_with_context = f"{breadcrumb}\n\n{passage}".strip()
            pg_lo: int | None = None
            pg_hi: int | None = None
            if page_char_starts and len(page_char_starts) > 0:
                idx = section_body.find(passage, passage_find)
                if idx < 0:
                    idx = section_body.find(passage.strip(), passage_find)
                if idx < 0 and passage.strip():
                    head = passage.strip()[: min(120, len(passage.strip()))]
                    idx = section_body.find(head, passage_find)
                if idx >= 0:
                    abs_start = body_start + idx
                    abs_end = abs_start + len(passage)
                    passage_find = idx + max(1, len(passage) // 2)
                    pg_lo, pg_hi = pages_for_char_span(abs_start, abs_end, page_char_starts, tl)
                else:
                    passage_find = 0

            out.append(
                {
                    "text": chunk_with_context,
                    "section": section,
                    "breadcrumb": breadcrumb,
                    "word_start": w_start,
                    "word_end": w_end,
                    "page_start": pg_lo,
                    "page_end": pg_hi,
                }
            )
            if len(out) >= 200:
                return out
    return out


def chunk_text_by_words(
    text: str,
    *,
    words_per_chunk: int = 200,
    overlap_words: int = 30,
) -> list[str]:
    """
    Backward-compatible wrapper.
    Converts old word-based settings into structure-first chunking thresholds.
    """
    if not text or not text.strip():
        return []
    max_chunk_chars = max(600, int(words_per_chunk) * 6)
    overlap_chars = max(40, int(overlap_words) * 5)
    section_chunks = chunk_text_by_sections(
        text,
        max_chunk_chars=max_chunk_chars,
        overlap_chars=overlap_chars,
    )
    return [c["text"] for c in section_chunks[:200]]


def chunk_text(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    separator: str = "\n\n",
) -> list[str]:
    """
    Split text into overlapping chunks suitable for embedding.
    Uses separator-first splitting, then merges small chunks.
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    # Split by separator (paragraphs)
    parts = text.split(separator)
    chunks: list[str] = []
    current = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # If adding this part exceeds chunk_size, flush current and start new
        candidate = (separator.join(current) + separator + part) if current else part
        if len(candidate) > chunk_size and current:
            chunk = separator.join(current).strip()
            if chunk:
                chunks.append(chunk)
            # Keep overlap: last overlap chars from current
            overlap_text = separator.join(current)
            overlap_start = max(0, len(overlap_text) - chunk_overlap)
            overlap_part = overlap_text[overlap_start:].strip()
            current = [overlap_part, part] if overlap_part else [part]
        else:
            current.append(part)

    if current:
        chunk = separator.join(current).strip()
        if chunk:
            chunks.append(chunk)

    # Fallback: if no separator-based chunks, split by fixed size with overlap
    if not chunks and text:
        for i in range(0, len(text), chunk_size - chunk_overlap):
            seg = text[i : i + chunk_size]
            if seg.strip():
                chunks.append(seg.strip())

    return chunks[:100]  # Cap at 100 chunks per document
