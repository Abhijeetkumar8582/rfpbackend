"""Extract text from uploaded files for embedding and categorization."""
from __future__ import annotations

import io
from typing import BinaryIO


def extract_pdf_with_page_map(data: bytes) -> tuple[str, list[int] | None]:
    """
    Extract PDF text with physical page boundaries (0-indexed page starts in flattened text).
    Returns (full_text, page_start_offsets). page_start_offsets[i] is the char index where
    PDF page i+1 begins. Used to map chunks to #page=N for deep links.
    If extraction fails, returns ("", None).
    """
    stream = io.BytesIO(data)
    try:
        from pypdf import PdfReader

        reader = PdfReader(stream)
        pages = reader.pages[:50]
    except Exception:
        pages = []

    if pages:
        parts: list[str] = []
        page_starts: list[int] = []
        pos = 0
        for i, page in enumerate(pages):
            t = page.extract_text() or ""
            page_starts.append(pos)
            if i > 0:
                parts.append("\n")
                pos += 1
            parts.append(t)
            pos += len(t)
        full = "".join(parts)
        if len(full) > 50_000:
            full = full[:50_000]
            while len(page_starts) > 1 and page_starts[-1] >= len(full):
                page_starts.pop()
        return full, page_starts

    return _extract_pdf_fitz_with_page_map(data)


def _extract_pdf_fitz_with_page_map(data: bytes) -> tuple[str, list[int] | None]:
    try:
        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        try:
            parts: list[str] = []
            page_starts: list[int] = []
            pos = 0
            for i in range(min(50, doc.page_count)):
                page = doc[i]
                t = page.get_text("text") or ""
                page_starts.append(pos)
                if i > 0:
                    parts.append("\n")
                    pos += 1
                parts.append(t)
                pos += len(t)
            full = "".join(parts)
            if len(full) > 50_000:
                full = full[:50_000]
                while len(page_starts) > 1 and page_starts[-1] >= len(full):
                    page_starts.pop()
            return full, page_starts
        finally:
            doc.close()
    except Exception:
        return "", None


def extract_text_from_file(content: bytes | BinaryIO, filename: str, content_type: str) -> str:
    """
    Extract plain text from PDF, XLSX, or fallback to filename.
    Used for embedding and GPT categorization.
    """
    if hasattr(content, "read"):
        data = content.read()
    else:
        data = content
    data = data if isinstance(data, bytes) else getattr(content, "read", lambda: b"")()
    stream = io.BytesIO(data)

    filename_str = str(filename).strip() if filename is not None else ""
    ext = (filename_str or "").rsplit(".", 1)[-1].lower()
    if "pdf" in content_type or ext == "pdf":
        return _extract_pdf(stream)
    if "spreadsheet" in content_type or "excel" in content_type or ext in ("xlsx", "xls"):
        return _extract_xlsx(stream)
    # Plain text
    if "text" in content_type or ext in ("txt", "md", "csv"):
        try:
            return data.decode("utf-8", errors="replace")[:50_000]
        except Exception:
            pass
    # Fallback: use filename as hint for categorization
    return _filename_to_text(filename_str if filename_str else filename)


def _extract_pdf(stream: io.BytesIO) -> str:
    from pypdf import PdfReader
    text_parts = []
    try:
        reader = PdfReader(stream)
        for page in reader.pages[:50]:  # limit pages
            t = page.extract_text()
            if t:
                text_parts.append(t)
        if text_parts:
            return "\n".join(text_parts)[:50_000]
    except Exception:
        pass
    # Fallback parser: some PDFs that fail in pypdf still yield text via PyMuPDF.
    try:
        import fitz

        stream.seek(0)
        doc = fitz.open(stream=stream.read(), filetype="pdf")
        try:
            fitz_parts = []
            for page in doc[:50]:
                t = page.get_text("text")
                if t:
                    fitz_parts.append(t)
            return "\n".join(fitz_parts)[:50_000] if fitz_parts else ""
        finally:
            doc.close()
    except Exception:
        return ""


def _extract_xlsx(stream: io.BytesIO) -> str:
    import openpyxl
    text_parts = []
    try:
        wb = openpyxl.load_workbook(stream, read_only=True, data_only=True)
        for sheet in wb.worksheets[:10]:
            for row in sheet.iter_rows(max_row=500, values_only=True):
                row_str = " ".join(str(c) for c in row if c is not None)
                if row_str.strip():
                    text_parts.append(row_str)
        wb.close()
        return "\n".join(text_parts)[:50_000] if text_parts else ""
    except Exception:
        return ""


def _filename_to_text(filename: str) -> str:
    """Use filename as minimal context for categorization (e.g. sso_security_policy.pdf -> Security)."""
    if filename is None:
        return "Document"
    s = str(filename).strip()
    if not s:
        return "Document"
    base = s.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    return base or "Document"
