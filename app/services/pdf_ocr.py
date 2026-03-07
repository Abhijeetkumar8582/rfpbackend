"""PDF image detection and OCR — extract text from scanned PDFs and embedded images."""
from __future__ import annotations

import io
import logging
from typing import BinaryIO

from app.config import settings

logger = logging.getLogger(__name__)


def is_probably_scanned(pdf_path: str | bytes | BinaryIO, sample_pages: int = 3) -> bool:
    """
    Heuristic check: does the PDF appear to be image-heavy (e.g. scanned)?
    Pages with little text and large image blocks vote "scanned".
    Returns True if at least half of sampled pages look scanned.
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed; cannot detect scanned PDFs")
        return False

    if isinstance(pdf_path, bytes):
        doc = fitz.open(stream=io.BytesIO(pdf_path), filetype="pdf")
    elif hasattr(pdf_path, "read"):
        data = pdf_path.read() if callable(getattr(pdf_path, "read")) else getattr(pdf_path, "read")()
        doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    else:
        doc = fitz.open(pdf_path)

    try:
        pages = min(len(doc), sample_pages)
        scanned_votes = 0

        for i in range(pages):
            page = doc[i]
            text = page.get_text("text").strip()
            blocks = page.get_text("dict")["blocks"]

            # Compute largest image block area ratio
            rect = page.rect
            page_area = rect.width * rect.height
            max_img_area = 0.0

            for b in blocks:
                if b.get("type") == 1:  # type 1 = image block
                    x0, y0, x1, y1 = b["bbox"]
                    area = max(0, (x1 - x0)) * max(0, (y1 - y0))
                    max_img_area = max(max_img_area, area)

            img_ratio = (max_img_area / page_area) if page_area else 0.0

            # Heuristic: little text + large image block => probably scanned
            if len(text) < 50 and img_ratio > 0.6:
                scanned_votes += 1

        return scanned_votes >= max(1, pages // 2)
    finally:
        doc.close()


def pdf_has_images(pdf_path: str | bytes | BinaryIO) -> bool:
    """
    Check if the PDF contains any embedded images (quick scan of first few pages).
    """
    try:
        import fitz
    except ImportError:
        return False

    if isinstance(pdf_path, bytes):
        doc = fitz.open(stream=io.BytesIO(pdf_path), filetype="pdf")
    elif hasattr(pdf_path, "read"):
        data = pdf_path.read() if callable(getattr(pdf_path, "read")) else getattr(pdf_path, "read")()
        doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    else:
        doc = fitz.open(pdf_path)

    try:
        for i in range(min(len(doc), 5)):
            if doc[i].get_images():
                return True
        return False
    finally:
        doc.close()


def extract_images_and_ocr_text(
    pdf_content: bytes, max_pages: int = 100
) -> tuple[str, int]:
    """
    Scan the whole PDF, extract all images (and render page images for scanned pages),
    run OCR on each, return (concatenated text, pages_processed).
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed; cannot extract images from PDF")
        return "", 0

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("pytesseract or Pillow not installed; OCR disabled")
        return "", 0

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    text_parts: list[str] = []
    doc = fitz.open(stream=io.BytesIO(pdf_content), filetype="pdf")

    try:
        seen_xrefs: set[int] = set()
        pages_to_process = min(len(doc), max_pages)

        for page_idx in range(pages_to_process):
            page = doc[page_idx]

            # 1) Extract embedded images from page
            for img_info in page.get_images():
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    base_img = doc.extract_image(xref)
                    img_bytes = base_img["image"]
                    img_pil = Image.open(io.BytesIO(img_bytes))
                    if img_pil.mode not in ("RGB", "L"):
                        img_pil = img_pil.convert("RGB")
                    ocr_text = pytesseract.image_to_string(img_pil).strip()
                    if ocr_text:
                        text_parts.append(f"[Page {page_idx + 1}] {ocr_text}")
                except Exception as e:
                    logger.debug("OCR failed for image xref=%s: %s", xref, e)

            # 2) For pages with very little text, render whole page as image and OCR (scanned pages)
            page_text = page.get_text("text").strip()
            if len(page_text) < 50:
                try:
                    pix = page.get_pixmap(dpi=150, alpha=False)
                    img_bytes = pix.tobytes("png")
                    img_pil = Image.open(io.BytesIO(img_bytes))
                    if img_pil.mode not in ("RGB", "L"):
                        img_pil = img_pil.convert("RGB")
                    ocr_text = pytesseract.image_to_string(img_pil).strip()
                    if ocr_text:
                        text_parts.append(f"[Page {page_idx + 1}] {ocr_text}")
                except Exception as e:
                    logger.debug("Page render OCR failed for page %s: %s", page_idx + 1, e)

    finally:
        doc.close()

    result = "\n\n".join(text_parts)
    return (result[:100_000] if result else ""), pages_to_process
