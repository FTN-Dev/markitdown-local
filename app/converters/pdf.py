import os
from pathlib import Path

from ..config import DOCLING_URL

SCANNED_THRESHOLD_CHARS_PER_PAGE = 40


def is_scanned_pdf(in_path: str) -> bool:
    """Heuristic: if average chars per page < threshold, treat as scanned."""
    try:
        from pdfminer.high_level import extract_text
        from pdfminer.pdfpage import PDFPage
    except Exception:
        return False
    try:
        with open(in_path, "rb") as f:
            pages = list(PDFPage.get_pages(f))
        n_pages = len(pages) or 1
        text = extract_text(in_path) or ""
        chars = len(text.strip())
        return (chars / n_pages) < SCANNED_THRESHOLD_CHARS_PER_PAGE
    except Exception:
        return False


def convert_pdf(in_path: str, out_dir: str, original_name: str) -> dict:
    scanned = is_scanned_pdf(in_path)
    if scanned:
        if DOCLING_URL:
            from .docling_client import convert_via_docling
            return convert_via_docling(in_path, out_dir, original_name)
        return {"ok": False, "error": "PDF terdeteksi scan; OCR tidak aktif (set DOCLING_URL)"}
    # digital pdf -> markitdown
    from .markitdown_conv import convert_markitdown
    return convert_markitdown(in_path, out_dir, original_name)
