"""Text chunking for embedding and vector search — split documents into overlapping segments."""
from __future__ import annotations


def chunk_text_by_words(
    text: str,
    *,
    words_per_chunk: int = 200,
    overlap_words: int = 30,
) -> list[str]:
    """
    Split text into chunks by word count (e.g. 100, 200 words per chunk).
    Paragraph-like chunks suitable for embedding and vector search.
    """
    if not text or not text.strip():
        return []
    words = text.strip().split()
    if not words:
        return []
    chunks: list[str] = []
    step = max(1, words_per_chunk - overlap_words)
    for i in range(0, len(words), step):
        chunk_words = words[i : i + words_per_chunk]
        if chunk_words:
            chunks.append(" ".join(chunk_words))
    return chunks[:200]  # Cap at 200 chunks per document


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
