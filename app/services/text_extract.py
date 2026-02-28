"""Extract text from uploaded files for embedding and categorization."""
from __future__ import annotations

import io
from typing import BinaryIO


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
        return "\n".join(text_parts)[:50_000] if text_parts else ""
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
