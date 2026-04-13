"""PDF image detection and OCR — extract text from scanned PDFs and embedded images."""
from __future__ import annotations

import base64
import io
import logging
import uuid
from typing import BinaryIO

from app.config import settings
from app.services.openai_client import get_chat_client
from app.services.s3 import s3_upload, s3_download, s3_delete

logger = logging.getLogger(__name__)
TEMP_OCR_FOLDER = "Temporyfiles"


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
    Scan the PDF and OCR page images.
    Primary path: GPT-4o-mini vision OCR on rendered page images.
    Optional fallback: local Tesseract OCR if GPT OCR fails.
    Returns (concatenated text, pages_processed).
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed; cannot extract images from PDF")
        return "", 0

    # Optional local OCR fallback.
    pytesseract = None
    Image = None
    try:
        import pytesseract as _pytesseract
        from PIL import Image as _Image

        pytesseract = _pytesseract
        Image = _Image
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    except ImportError:
        pass

    text_parts: list[str] = []
    client = None
    model = None
    try:
        client, model = get_chat_client()
    except Exception as e:
        logger.warning("GPT OCR unavailable, will rely on local OCR fallback: %s", e)

    doc = fitz.open(stream=io.BytesIO(pdf_content), filetype="pdf")

    try:
        pages_to_process = min(len(doc), max_pages)

        for page_idx in range(pages_to_process):
            page = doc[page_idx]
            page_text = page.get_text("text").strip()
            has_images = bool(page.get_images())
            should_ocr_page = has_images or len(page_text) < 50
            if not should_ocr_page:
                continue

            # Render full page image and OCR with GPT.
            ocr_text = ""
            img_bytes = b""
            try:
                pix = page.get_pixmap(dpi=130, alpha=False)
                img_bytes = pix.tobytes("png")
                if client and model:
                    ocr_text = _ocr_page_with_gpt(client, model, img_bytes, page_idx + 1)
            except Exception as e:
                logger.debug("GPT OCR render/call failed for page %s: %s", page_idx + 1, e)

            # Optional local fallback if GPT OCR produced nothing.
            if (not ocr_text) and img_bytes and pytesseract and Image:
                try:
                    img_pil = Image.open(io.BytesIO(img_bytes))
                    if img_pil.mode not in ("RGB", "L"):
                        img_pil = img_pil.convert("RGB")
                    ocr_text = (pytesseract.image_to_string(img_pil) or "").strip()
                except Exception as e:
                    logger.debug("Local OCR fallback failed for page %s: %s", page_idx + 1, e)

            if ocr_text:
                text_parts.append(f"[Page {page_idx + 1}] {ocr_text}")

    finally:
        doc.close()

    result = "\n\n".join(text_parts)
    return (result[:100_000] if result else ""), pages_to_process


def _ocr_page_with_gpt(client, model: str, image_bytes: bytes, page_number: int) -> str:
    """Extract text from one rendered PDF page image using GPT vision."""
    temp_key = None
    image_url = None
    if settings.s3_bucket:
        temp_key = f"{TEMP_OCR_FOLDER}/ocr-page-{page_number}-{uuid.uuid4().hex}.png"
        try:
            s3_upload(image_bytes, temp_key, "image/png")
            image_url = s3_download(temp_key, "image/png", expires_in=600)
        except Exception as e:
            logger.warning("Temporary OCR image upload failed for page %s: %s", page_number, e)
            temp_key = None
            image_url = None

    if not image_url:
        # Fallback when S3 is unavailable: inline data URI (higher token footprint).
        data_b64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:image/png;base64,{data_b64}"

    messages = [
        {
            "role": "system",
            "content": (
                "You are an OCR engine. Extract all visible text from the given document page image. "
                "Return plain text only. Preserve reading order and line breaks. "
                "Do not summarize, explain, or add markdown."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Extract all text from this PDF page image (page {page_number})."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4000,
            timeout=120.0,
        )
        out = ((resp.choices[0].message.content or "") if resp and resp.choices else "").strip()
        return out
    finally:
        if temp_key:
            try:
                s3_delete(temp_key)
            except Exception as e:
                logger.warning("Failed to delete temporary OCR image %s: %s", temp_key, e)
